"""A local read-only window onto the store, for the Obsidian plugin.

The plugin runs in Electron and the store is embedded Kuzu behind Python, so
something has to sit between them. This is the smallest thing that can: a
stdlib HTTP server, bound to the loopback interface, that answers GET requests
and holds no write path at all.

Three decisions worth stating.

It binds 127.0.0.1 and nothing else. The store holds a browsing history --
the reason `Workspace.mirror_path` names its files by digest -- and a server
that answered on 0.0.0.0 would publish it to the local network.

It is read-only BY DEFAULT, and the exception is a door with a lock. No GET
route mutates anything, so a page rendered in a vault cannot alter the store
or touch the web no matter what it contains. `POST /enact` drives the live
browser and exists only when the process was started with `enact=True` --
otherwise it answers 403 and says so. The flag lives on the SERVER because a
plugin setting is a client asserting something about itself, and the client is
a page renderer in an app the user installs plugins into.

It sends the line's ADDRESS, not just its text. The address key is the
`url:xpath:taxonomy:content` identity everything downstream is keyed on, and
it is what lets a click in Obsidian name an element in the real page. Sending
rendered text alone would make the surface a picture of the page rather than
a handle on it.
"""

from __future__ import annotations

import json
import os
import sys
import re
import threading
from pathlib import Path
from collections import deque
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from .. import tokens
from .export import _reflow, link_targets
from .htmlform import render_lines
from .layout import (build_layout, build_page_layout, place_into,
                     remember_page_positions, unfold as unfold_path)


#: Capture sessions, keyed by url: the stateful decoder and the trie spine
#: for a page the browser cell is scanning. Held for the life of the server
#: rather than evicted -- a drain's dictionary is append-only, so a session
#: dropped mid-page could not resolve the next drain's interned segments and
#: would fail in a way that looks like a page suddenly going empty.
_capture_sessions: Dict[str, Dict] = {}


_MEDIA_LINE = re.compile(r"^\s*(?:- )?\([^)]*\)\[[^\]]+\]", re.M)
_JSON_LINE = re.compile(r"^\s*(?:- )?`?[\[{]\s*\"", re.M)
_LINKISH = re.compile(r"!?\[[^\]]*\]\([^)]*\)")


def _content_kinds(mds) -> Dict[str, int]:
    """Counts of content kinds across a page's chunk markdown: pictures,
    other media (video/audio, drawn ``(alt)[url]``), JSON-looking lines, and
    chunks with any words. Read from the projection, so it names what the
    reader's panels and the index were given."""
    out = {"images": 0, "media": 0, "json": 0, "text_chunks": 0}
    for md in mds:
        md = md or ""
        out["images"] += md.count("![")
        out["media"] += len(_MEDIA_LINE.findall(md))
        out["json"] += len(_JSON_LINE.findall(md))
        if re.search(r"[A-Za-z]{3,}", _LINKISH.sub("", md)):
            out["text_chunks"] += 1
    return out


def sensor_restarted(session: Dict, body: Dict) -> bool:
    """Did the page's sensor start over since this capture session began?

    A reload of the same url injects a new sensor whose tag dictionary begins
    again at 0; decoded against the session's old dictionary, ids read as "?"
    and garbage addresses reach the store. Each payload reports its sensor's
    dictionary size (`stats.dictSize`, after this payload's additions): it
    must equal what the session holds plus what the payload adds.
    """
    if body.get("settle"):
        return False
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return False
    size = (payload.get("stats") or {}).get("dictSize")
    if not isinstance(size, int):
        return False
    held = len(getattr(session.get("sensor"), "_dict", []) or [])
    return size != held + len(payload.get("dict") or [])

#: Serialises everything that WRITES the workspace.
#:
#: The server is already threaded -- a vault opens many chunks at once -- and
#: adding a background embedder makes a writer concurrent with those readers
#: for the first time. A kuzu connection is not built to be used from several
#: threads at once, so every mutation goes through here. It is an `RLock`
#: because `ingest` reaches `flush_vectors`, which would otherwise deadlock
#: against itself.
_WORK_LOCK = threading.RLock()

#: The encoder (one GPU model), shared by the embed worker and `/project`.
#: Neither holds the store's lock while encoding, so a projection waits at
#: most one embed batch -- never a capture's write.
_ENCODER_LOCK = threading.Lock()

#: Serialises LAYOUT FITTING, which `_WORK_LOCK` does not cover.
#:
#: `_WORK_LOCK` guards writes. A fit is a read, so it was taking nothing --
#: and this is a `ThreadingHTTPServer`, so two `/layout` requests arriving
#: together each ran UMAP on its own thread. The process segfaulted three
#: times under a full confirmation suite: native, no Python traceback,
#: always while layouts were being fitted and always with the pane and a
#: probe both asking. UMAP's numba kernels are not built to be entered
#: concurrently from one process.
#:
#: A separate lock rather than `_WORK_LOCK`, deliberately. A cold
#: chunk-level fit is 95 seconds, and holding the write lock for it would
#: stall every live capture behind it: fits wait for fits, captures do not
#: wait for fits.
_FIT_LOCK = threading.Lock()

#: Foreground captures waiting for `_WORK_LOCK` right now. Background work
#: (the embed worker, aggregation) steps aside while this is non-zero: the
#: lock is not fair, and a reader who just navigated waited 8.8 s (Radix
#: tree) and 22.8 s (DuckDuckGo) for the capture of the page they are LOOKING
#: at, behind work for the page they left (D-35, 2026-09-27).
_FOREGROUND = [0]
_FOREGROUND_GUARD = threading.Lock()


class _foreground:
    """Mark a foreground wait for `_WORK_LOCK` for the length of a block."""

    def __enter__(self):
        with _FOREGROUND_GUARD:
            _FOREGROUND[0] += 1

    def __exit__(self, *exc):
        with _FOREGROUND_GUARD:
            _FOREGROUND[0] -= 1


def _yield_to_foreground(limit_s: float = 5.0) -> float:
    """Background work calls this before taking `_WORK_LOCK`. Returns the
    seconds it stood aside (bounded, so background work is never starved)."""
    started = time.perf_counter()
    while _FOREGROUND[0] > 0 and time.perf_counter() - started < limit_s:
        time.sleep(0.02)
    return time.perf_counter() - started

#: Raised when there are chunks waiting for vectors.
_EMBED_WANTED = threading.Event()

#: When the store was last written (a capture or a settle). The checkpoint
#: thread waits for a pause in writing before folding the WAL in (D-48).
_LAST_WRITE = [0.0]
#: When ANY request last arrived. A checkpoint holds the store for 10-21 s on
#: the 32 GB store, and every read -- `/health` included -- waits behind it:
#: run after a write pause alone, it froze panels and made `confirm.mjs`
#: declare the sidecar dead (2026-10-07). So it waits for the whole sidecar
#: to go quiet, and for a WAL worth folding.
_LAST_REQUEST = [0.0]
#: The last full `/health` answer and when it was computed.
_HEALTH_CACHE: Dict[str, object] = {}


def _cache_health(body: Dict, key: object = None) -> Dict:
    # Keyed by the SERVER that computed it: two sidecars in one process (the
    # tests start several) must never answer with each other's flags.
    _HEALTH_CACHE["body"] = dict(body)
    _HEALTH_CACHE["at"] = time.time()
    _HEALTH_CACHE["key"] = key
    return body
_CHECKPOINT_QUIET_S = 120.0
_CHECKPOINT_MIN_WAL = 8 << 20
#: Folded in past this whatever the reader is doing. 256 MB was too much:
#: on 2026-10-18 continuous activity kept the WAL from quiet folds for 49
#: minutes, it reached 201.5 MB, and replaying THAT at the next start
#: overflowed the 2 GiB pool -- CHECKPOINT segfaulted twice and the store
#: was poisoned until the supervisor compacted it. A fold of 64 MB is a few
#: seconds of paused reads.
_CHECKPOINT_CEILING = 64 << 20
#: Writes stopped this long: the reader is not browsing, so the fold runs
#: whatever is polling (`_checkpoint_due`). A two-second lull between polls
#: was asked for at first and never came -- the open pane polls about once a
#: second -- so the WAL grew on (2026-10-11). Reads wait out the fold.
_CHECKPOINT_IDLE_WRITE_S = 600.0
_CHECKPOINT_POLL_GAP_S = 0.0
#: Planted: the old rule -- quiet only with no REQUEST of any kind for 120 s.
_PLANT_REQUEST_QUIET = [False]


#: True while a CHECKPOINT runs. A restart that kills the process then
#: kills the fold mid-way: it happened twice on 2026-10-17 (14:35, 17:27),
#: because the WAL file reads ~0 bytes DURING a checkpoint and "WAL under
#: 8 MB" was taken to mean "safe". `/checkpointing` answers without touching
#: the store, and the restart tools refuse while this is set.
_CHECKPOINTING = [False]
#: Set by POST /shutdown: writes are refused (retry) while the work lock is
#: taken, then the process exits for its supervisor to restart. A killed
#: process interrupted a capture's transaction (2026-10-17 19:35: an anchor
#: DELETE, rolled back on replay) -- the restart now waits for the work.
_SHUTTING = [False]


def _checkpoint_due(size: int, now: float, last_write: float, last_request: float) -> bool:
    """Fold the WAL in now?

    Past the ceiling, always. Otherwise only with something to fold, and only
    when quiet -- and "quiet" used to mean no request of any kind for 120 s,
    which the plugin's own background polls never allow: through 2.8 hours of
    an idle reader on 2026-10-11 the WAL grew to 249 MB unfolded, every byte
    of it at risk to a native crash (the `.unreplayable` logs). So a second
    quiet: no WRITE for ten minutes -- nobody is browsing -- polls or not.
    Reads pause for the fold (10-19 s on a 32 GB store), which an idle reader
    does not see.
    """
    if size >= _CHECKPOINT_CEILING:
        return True
    if size < _CHECKPOINT_MIN_WAL:
        return False
    since_write, since_request = now - last_write, now - last_request
    if since_write >= _CHECKPOINT_QUIET_S and since_request >= _CHECKPOINT_QUIET_S:
        return True
    if _PLANT_REQUEST_QUIET[0]:
        return False
    return since_write >= _CHECKPOINT_IDLE_WRITE_S and since_request >= _CHECKPOINT_POLL_GAP_S


def _checkpoint_forever(workspace, stop) -> None:
    """Fold the WAL into the store during PAUSES (D-48, 2026-10-07).

    A native Kuzu crash sets the WAL aside unreplayable, losing every write
    since the last checkpoint (~17 MB once). Kuzu checkpoints on its own only
    past a size threshold. A checkpoint here took 10-19 s on a 32 GB store, so
    it runs only after 60 s with no write and once the WAL holds 1 MB or more:
    a crash costs at most what was written since the reader last paused, and
    browsing never waits on it."""
    wal = Path(str(workspace.store.path) + ".wal")
    while not stop.wait(1.0):
        try:
            size = wal.stat().st_size if wal.exists() else 0
            # Kuzu no longer checkpoints on its own (the store turns it off so
            # its readers can run beside a write), so past a ceiling the WAL is
            # folded in even mid-session: reads pause for it, nothing fails.
            # Checked every second, so a two-second lull between polls is seen.
            if not _checkpoint_due(size, time.time(), _LAST_WRITE[0], _LAST_REQUEST[0]):
                continue
            _CHECKPOINTING[0] = True
            db = Path(str(workspace.store.path))
            before = db.stat().st_size if db.exists() else 0
            try:
                with _WORK_LOCK:
                    ms = workspace.store.checkpoint()
            finally:
                _CHECKPOINTING[0] = False
            after = db.stat().st_size if db.exists() else 0
            _profile("checkpoint", {"ms": ms, "wal_before": size, "store_before": before, "store_after": after})
            # Where the store GROWS (G-218): each checkpoint is when the WAL's
            # writes land in the file, so its size before and after, with the
            # WAL it folded in, dates and sizes every growth step on disk.
            try:
                with open(Path(workspace.path) / "store_growth.log", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "wal_mb": round(size / 1e6, 2),
                                         "store_mb_before": round(before / 1e6, 1), "store_mb_after": round(after / 1e6, 1),
                                         "grew_mb": round((after - before) / 1e6, 1), "ms": ms}) + chr(10))
            except OSError:
                pass
            # Outgrown its last compaction, and the reader away: ask the
            # supervisor to rebuild it (G-218). Taken under the work lock, so
            # nothing is mid-write when the process leaves.
            _maybe_compact(workspace, after / 1e6)
        except Exception as exc:                    # noqa: BLE001
            _profile("checkpoint", {"error": str(exc)[:160]})

#: Compaction asked for when the store is this many times its last compacted
#: size (G-218), and only after this long with no request: the supervisor
#: rebuilds it with the sidecar down (~40 s for the working store).
_COMPACT_RATIO = 2.0
_COMPACT_FLOOR_MB = 1500.0
_COMPACT_QUIET_S = 600.0
_PLANT_NO_AUTOCOMPACT = [os.environ.get("VERTISCOPE_PLANT_NO_AUTOCOMPACT") == "1"]
_COMPACT_BASE_MB: List[float] = []


#: Model jobs by id: state, result (the role's typed value), error.
_MODEL_JOBS: Dict[str, Dict] = {}


def _model_job(workspace, jid: str, body: Dict) -> None:
    from .. import models
    job = _MODEL_JOBS[jid]
    t0 = time.time()
    try:
        if job["role"] == "triplex":
            cid = str(body.get("cid") or "")
            rows = workspace.store._rows("MATCH (c:Chunk {cid: $c}) RETURN c.md, c.url", {"c": cid}) if cid else []
            text = models.plain(rows[0][0]) if rows else str(body.get("text") or "")
            if not text:
                raise ValueError("no text for chunk %r" % cid)
            res = models.run_triplex(text[:4000], list(body.get("entity_types") or ["PERSON", "ORGANIZATION", "LOCATION", "DATE", "CONCEPT", "PRODUCT"]),
                                     list(body.get("predicates") or ["IS_A", "PART_OF", "LOCATED_IN", "CREATED_BY", "USED_FOR", "RELATED_TO"]))
            job["source"] = {"cid": cid, "url": rows[0][1] if rows else ""}
        else:
            res = models.run_chat(str(body.get("prompt") or ""))
        job.update(state="done" if res.ok else "error", result=res.to_json(), error=res.error,
                   s=round(time.time() - t0, 1))
    except Exception as exc:                        # noqa: BLE001
        job.update(state="error", error="%s: %s" % (type(exc).__name__, str(exc)[:200]), s=round(time.time() - t0, 1))
    _profile("model_run", {k: job.get(k) for k in ("role", "cid", "state", "s")})


#: Confirmed downloads by href: state, bytes, total, path, error.
_DOWNLOADS: Dict[str, Dict] = {}
#: Where an installed model goes: the directory the GPT4All runtime loads from.
MODEL_DIR = Path(os.environ.get("VERTISCOPE_MODEL_DIR") or (Path.home() / ".cache" / "gpt4all"))


def _file_head(href: str) -> Dict:
    """A file's size and type, asked of its server WITHOUT fetching it (HEAD,
    redirects followed) -- what the panel shows before asking to download."""
    import urllib.request
    if not href.startswith(("http://", "https://")):
        return {"error": "not an http(s) url"}
    try:
        req = urllib.request.Request(href, method="HEAD", headers={"User-Agent": "vertiscope"})
        with urllib.request.urlopen(req, timeout=20) as res:
            size = res.headers.get("Content-Length")
            # Hugging Face answers a HEAD on `resolve/` with the LFS size here.
            size = res.headers.get("X-Linked-Size") or size
            return {"size": int(size) if size and str(size).isdigit() else None,
                    "type": res.headers.get("Content-Type")}
    except Exception as exc:                        # noqa: BLE001
        return {"error": "%s: %s" % (type(exc).__name__, str(exc)[:160])}


def _download_target(workspace, href: str, kind: str, name: str) -> Path:
    from urllib.parse import unquote, urlsplit
    name = name or unquote(urlsplit(href).path).rsplit("/", 1)[-1] or "download"
    name = "".join(ch for ch in name if ch not in '<>:"/\\|?*') or "download"
    if kind == "model" or name.lower().endswith(".gguf"):
        return MODEL_DIR / name
    return Path(workspace.path) / "downloads" / name


def _download(workspace, href: str, kind: str, name: str) -> None:
    """Fetch `href` to its destination, resumable, with progress in
    `_DOWNLOADS`. A PDF is then chunked like a page (`index_pdf`)."""
    import urllib.request
    st = _DOWNLOADS[href]
    try:
        dest = _download_target(workspace, href, kind, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "vertiscope"}
        if have:
            headers["Range"] = "bytes=%d-" % have
        req = urllib.request.Request(href, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as res:
            if have and res.status != 206:
                have = 0                            # the server ignored the range: start over
            total = res.headers.get("Content-Length")
            st["total"] = (int(total) + have) if total and total.isdigit() else None
            st["bytes"] = have
            with open(part, "ab" if have else "wb") as fh:
                while True:
                    buf = res.read(1 << 20)
                    if not buf:
                        break
                    fh.write(buf)
                    st["bytes"] += len(buf)
        part.replace(dest)
        st.update(state="done", path=str(dest))
        if kind == "pdf" or dest.suffix.lower() == ".pdf":
            data = dest.read_bytes()
            if data.startswith(b"%PDF"):
                with _foreground(), _WORK_LOCK:
                    got = workspace.index_pdf(data, href)
                st["indexed"] = {k: got.get(k) for k in ("url", "pages", "chunks")}
                _LAST_WRITE[0] = time.time()
        _profile("download", {k: st.get(k) for k in ("href", "bytes", "path", "state")})
    except Exception as exc:                        # noqa: BLE001
        st.update(state="error", error="%s: %s" % (type(exc).__name__, str(exc)[:200]))


def _compact_due(store_mb: float, base_mb: float, now: float, last_request: float,
                 supervised: bool, reader_idle_s: float = 0.0, last_write: float = 0.0) -> bool:
    """Is the store big enough, against what it was after its last compaction,
    and the reader away long enough, to rebuild it now?

    "Away" is either no request at all for `_COMPACT_QUIET_S`, or -- the one
    that actually happens -- the PLUGIN reporting the reader idle in Obsidian
    for that long (`POST /maintenance`) with no capture for
    `_COMPACT_WRITE_QUIET_S`. The app's own polling never left the sidecar
    quiet: the store grew 1.6 -> 8.8 GB in four hours and captures slowed
    from 3-10 s to 15-26 s with compaction due the whole time (2026-10-18).
    Planted `_PLANT_REQUEST_QUIET_ONLY`: the request clock alone, as before."""
    away = now - last_request >= _COMPACT_QUIET_S
    if not away and not _PLANT_REQUEST_QUIET_ONLY[0]:
        away = reader_idle_s >= _COMPACT_QUIET_S and now - last_write >= _COMPACT_WRITE_QUIET_S
    return (supervised and not _PLANT_NO_AUTOCOMPACT[0] and store_mb >= _COMPACT_FLOOR_MB
            and base_mb > 0 and store_mb >= _COMPACT_RATIO * base_mb and away)


#: No capture or settle for this long, with the reader reported idle.
_COMPACT_WRITE_QUIET_S = 120.0
#: Planted: compaction waits for request silence only (never, in practice).
_PLANT_REQUEST_QUIET_ONLY = [False]
#: The reader's idle seconds as the plugin last reported them, and when.
_READER_IDLE = [0.0, 0.0]


#: The native stacks the sidecar loads lazily, in the order they load each
#: other: torch (the encoder), then UMAP's numba / sklearn / scipy.
_PRELOAD = ("torch", "numba", "scipy.stats", "scipy.integrate", "scipy.sparse.csgraph",
            "sklearn.utils", "sklearn.neighbors", "pynndescent", "umap")


def preload_native() -> Dict[str, float]:
    """Load the native libraries on the MAIN thread, before any worker runs.

    2026-10-19: the sidecar wedged a minute after every start. The stack
    dump showed a worker importing UMAP's sklearn -> scipy, stuck inside
    `create_module` loading `scipy.integrate._odepack` (OpenBLAS / Fortran
    DLLs) while another worker deep-copied torch tensors: a DLL loaded on a
    worker thread, beside threads running other native runtimes, holds the
    Windows loader lock through its initialisation -- and every new thread
    (one per HTTP request), `ExitProcess`, and that load all waited on each
    other at 0% CPU. Loaded here first, the DLLs initialise before there is
    another thread to race. Returns ms per module. Planted
    `VERTISCOPE_PLANT_LAZY_IMPORTS=1`: nothing loaded here, as before.
    """
    out: Dict[str, float] = {}
    if os.environ.get("VERTISCOPE_PLANT_LAZY_IMPORTS") == "1":
        return out
    import importlib
    for name in _PRELOAD:
        t0 = time.perf_counter()
        try:
            importlib.import_module(name)
            out[name] = round((time.perf_counter() - t0) * 1000, 1)
        except Exception:                           # noqa: BLE001
            out[name] = -1.0
    return out


def _exit_for_supervisor(code: int, workspace=None, checkpoint: bool = True) -> None:
    """Leave with `code` for the supervisor -- without Windows' DLL teardown.

    `os._exit` is `ExitProcess`: it ends the other threads and then runs
    every loaded DLL's detach routine, and with the CUDA libraries loaded one
    of those never returned (2026-10-19). The process sat with its socket
    open, accepting connections it would never answer, at 0% CPU -- the
    faulthandler timer found only "<freed thread state>" -- and the
    supervisor, waiting for exit 76, never compacted. It wedged a minute
    after every start, as soon as the plugin reported the reader idle and
    the 5.8 GB store came due. `TerminateProcess` ends the process with the
    code and runs no detach routine. The WAL is checkpointed first where the
    store can take it, so what the supervisor opens next has nothing to
    replay. Planted `VERTISCOPE_PLANT_EXIT_PROCESS=1`: `os._exit`, as before.
    """
    if checkpoint and workspace is not None:
        try:
            workspace.store.checkpoint()
        except Exception:                           # noqa: BLE001
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:                           # noqa: BLE001
            pass
    if os.name == "nt" and os.environ.get("VERTISCOPE_PLANT_EXIT_PROCESS") != "1":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.TerminateProcess(k32.GetCurrentProcess(), int(code))
        except Exception:                           # noqa: BLE001
            pass
    os._exit(code)


def _maybe_compact(workspace, store_mb: Optional[float] = None) -> None:
    """After a checkpoint and on every quiet integrity record: if due, exit
    76 under the work lock (nothing mid-write) for the supervisor."""
    if store_mb is None:
        try:
            store_mb = (Path(workspace.path) / "graph.kuzu").stat().st_size / 1e6
        except OSError:
            return
    # A report older than two minutes says nothing about now.
    idle_s = _READER_IDLE[0] if time.time() - _READER_IDLE[1] < 120 else 0.0
    if _compact_due(store_mb, _compact_base(workspace, store_mb), time.time(), _LAST_REQUEST[0],
                    os.environ.get("VERTISCOPE_SUPERVISED") == "1", idle_s, _LAST_WRITE[0]):
        with _WORK_LOCK:
            _profile("compact_asked", {"store_mb": round(store_mb, 1), "base_mb": _compact_base(workspace, store_mb)})
            _exit_for_supervisor(76, workspace)


def _compact_base(workspace, store_mb: float) -> float:
    """The size the last compaction left (`compacted.json`), else this
    process's first sight of the store."""
    if not _COMPACT_BASE_MB:
        base = store_mb
        try:
            base = float(json.loads((Path(workspace.path) / "compacted.json").read_text(encoding="utf-8"))["after_mb"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        _COMPACT_BASE_MB.append(base)
    return _COMPACT_BASE_MB[0]

#: Seconds between integrity records while the sidecar is quiet.
_INTEGRITY_EVERY_S = 600.0
_INTEGRITY_LAST: Dict[str, int] = {}


def _integrity_counts(store) -> Dict[str, int]:
    """The two string columns the store has been seen to LOSE: chunk markdown
    (80.6% empty on 2026-09-23, 78.2% on 2026-10-07) and address keys
    (145,618 blank on 2026-10-07), each with its integers intact beside it."""
    def one(q):
        rows = store._rows(q)
        return int(rows[0][0] or 0) if rows else 0
    return {
        "chunks": one("MATCH (c:Chunk) RETURN count(c)"),
        "empty_md": one("MATCH (c:Chunk) WHERE c.md IS NULL OR size(c.md) = 0 RETURN count(c)"),
        "addresses": one("MATCH (a:Address) RETURN count(a)"),
        "blank_akey": one("MATCH (a:Address) WHERE a.akey IS NULL OR a.akey = '' RETURN count(a)"),
    }


def _integrity_record(workspace, why: str) -> Optional[Dict]:
    """Append one dated integrity record to `integrity.log` (D-48).

    Twice the store has lost most of its markdown with no error anywhere, and
    neither time could the loss be dated: a crash, a WAL set aside, a SET on
    other columns -- each was tested on a scratch store on 2026-10-07 and none
    reproduced it. So the store dates it itself: a record at every start (a
    crash and its replay are bracketed by the record before and the one
    after) and every ten quiet minutes, on disk beside `crashes.log` because
    the in-memory profile dies with the process. A count that ROSE says so,
    with the statement the store last ran."""
    try:
        # The previous PROCESS's last record, so a loss that happened across
        # a restart is flagged too. Every loss so far did (2026-09-23,
        # 10-07, and 10-18: 180 -> 67,040 empty between the 22:36 start and
        # the 00:44 one) and the in-memory baseline started empty each time,
        # so ROSE never fired.
        if not _INTEGRITY_LAST:
            _INTEGRITY_LAST.update(_integrity_last_on_disk(workspace))
        with _WORK_LOCK:
            t0 = time.perf_counter()
            got = _integrity_counts(workspace.store)
            ms = round((time.perf_counter() - t0) * 1000, 1)
        rose = {k: got[k] - _INTEGRITY_LAST[k] for k in ("empty_md", "blank_akey")
                if k in _INTEGRITY_LAST and got[k] > _INTEGRITY_LAST[k]}
        record = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "why": why, **got, "ms": ms}
        # The store's size on disk beside its counts (G-218: 1.44 -> 5.14 GB
        # in 40 minutes after a rebuild, with no record of WHEN or by what).
        try:
            db = Path(workspace.path) / "graph.kuzu"
            record["store_mb"] = round(db.stat().st_size / 1e6, 1)
            wal = db.with_name("graph.kuzu.wal")
            record["wal_mb"] = round(wal.stat().st_size / 1e6, 1) if wal.exists() else 0.0
        except OSError:
            pass
        if rose:
            record["ROSE"] = rose
            try:
                record["last_statement"] = (Path(workspace.path) / "last_statement.txt").read_text(
                    encoding="utf-8", errors="replace").strip()[:300]
            except OSError:
                pass
        _INTEGRITY_LAST.update(got)
        with open(Path(workspace.path) / "integrity.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + chr(10))
        _profile("integrity", record)
        return record
    except Exception as exc:                        # noqa: BLE001
        _profile("integrity", {"error": str(exc)[:160]})
        return None


def _warm_containment(workspace, stop) -> None:
    """Each page's trie nodes read once, in the background, after a start
    (PLUGIN_GOAL 110): kept per page until the page is written, they make a
    chunk-view layout cost its rows and not every anchor in the store -- but
    the FIRST layout after a restart would still read them all (42-66 s,
    2026-10-11). Page by page, standing aside for the reader's requests."""
    if stop.wait(20.0):
        return
    t0 = time.time()
    done = 0
    try:
        urls = [r[0] for r in workspace.store._rows("MATCH (p:Page) RETURN p.url") if r and r[0]]
    except Exception:                               # noqa: BLE001
        return
    for url in urls:
        if stop.is_set():
            return
        _yield_to_foreground()
        try:
            workspace.store.contains_within(url)
            done += 1
        except Exception:                           # noqa: BLE001
            continue
    _profile("warm_containment", {"pages": done, "of": len(urls), "s": round(time.time() - t0, 1)})
    # And each chunk's title, tokens and picture (`layout._CHUNK_FACTS`), so the
    # first chunk-view switch after a start is not the one that reads them.
    try:
        from .layout import projected_chunk_layout
        from .projector import projector as _get
        proj = _get()
        for _ in range(60):
            if stop.is_set() or (proj is not None and proj.projection is not None):
                break
            stop.wait(5.0)
        if proj is not None and proj.projection is not None and not stop.is_set():
            _yield_to_foreground()
            t1 = time.time()
            got = projected_chunk_layout(workspace, proj)
            _profile("warm_facts", {"n": (got or {}).get("n"), "s": round(time.time() - t1, 1),
                                    "timing": (got or {}).get("timing")})
    except Exception as exc:                        # noqa: BLE001
        _profile("warm_facts", {"error": str(exc)[:160]})


def _poison_watch(workspace, stop) -> None:
    """A store whose connection is poisoned (`GraphStore.poisoned`: the
    buffer pool refused a statement) restarts the process with the
    supervisor's restart code BEFORE anything else runs on it: the next
    statement after such a refusal segfaulted, ~50 times in an hour
    (2026-10-18). The WAL holds only committed work; the plugin retries the
    capture that was refused."""
    while not stop.wait(0.5):
        why = getattr(getattr(workspace, "store", None), "poisoned", "")
        if why:
            try:
                with open(Path(workspace.path) / "crashes.log", "a", encoding="utf-8") as fh:
                    fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + " poisoned, compacting (76): " + why + chr(10))
            except OSError:
                pass
            _profile("poisoned", {"why": why})
            # 76, not 75: a plain restart replays the same WAL into the same
            # pool and was refused again -- twice at 13:39 and 13:42 on
            # 2026-10-18, with segfaults at CHECKPOINT between. The supervisor
            # compacts with a larger pool (which folded that 50.9 MB WAL and
            # took the store 5,143 -> 1,543 MB), then restarts.
            # No checkpoint: the pool already refused this store.
            _exit_for_supervisor(76, workspace, checkpoint=False)


def _integrity_last_on_disk(workspace) -> Dict[str, int]:
    """The counts of the last record in `integrity.log`, or {}."""
    try:
        with open(Path(workspace.path) / "integrity.log", "rb") as fh:
            fh.seek(0, 2); fh.seek(max(0, fh.tell() - 4096))
            tail = fh.read().decode("utf-8", "replace").splitlines()
        for line in reversed(tail):
            line = line.strip()
            if line.startswith("{"):
                rec = json.loads(line)
                return {k: int(rec[k]) for k in ("chunks", "empty_md", "addresses", "blank_akey") if k in rec}
    except (OSError, ValueError):
        pass
    return {}


#: Markdown lost by this many chunks or more is refilled from the checkpoint
#: at once (`Workspace.restore_markdown`: it fills only what is EMPTY, from
#: the recorded value of the same cid). Planted `VERTISCOPE_PLANT_NO_MD_HEAL=1`:
#: recorded only, as before.
_MD_HEAL_AT = 500
_PLANT_NO_MD_HEAL = [os.environ.get("VERTISCOPE_PLANT_NO_MD_HEAL") == "1"]

#: Module flags a live check may plant through `POST /plant` -- the planted
#: arm of a rule that runs in the sidecar's projection, not in the plugin.
_PLANTABLE = {
    "placeholder-target": ("vertiscope.markdown", "PLANT_PLACEHOLDER_TARGET"),   # G-197
}


def _heal_markdown(workspace, record: Optional[Dict]) -> Optional[Dict]:
    rose = ((record or {}).get("ROSE") or {}).get("empty_md", 0)
    if rose < _MD_HEAL_AT or _PLANT_NO_MD_HEAL[0]:
        return None
    try:
        with _WORK_LOCK:
            t0 = time.time()
            got = workspace.restore_markdown()
            # A chunk indexed while its markdown was empty has a lexical row
            # with no terms; re-derived from the markdown now held.
            if got.get("restored") and hasattr(workspace, "rebuild_lexical"):
                got["lexical"] = workspace.rebuild_lexical()
        got["s"] = round(time.time() - t0, 1)
        _profile("md_heal", got)
        return _integrity_record(workspace, "healed %d" % int(got.get("restored", 0)))
    except Exception as exc:                        # noqa: BLE001
        _profile("md_heal", {"error": str(exc)[:160]})
        return None


def _integrity_forever(workspace, stop) -> None:
    _heal_markdown(workspace, _integrity_record(workspace, "start"))
    last = time.time()
    while not stop.wait(30.0):
        if time.time() - last < _INTEGRITY_EVERY_S:
            continue
        if time.time() - max(_LAST_WRITE[0], _LAST_REQUEST[0]) < _CHECKPOINT_QUIET_S:
            continue
        _heal_markdown(workspace, _integrity_record(workspace, "quiet"))
        _maybe_compact(workspace)
        last = time.time()


#: Token counts for the page the overlay is watching, keyed on its chunk set.
_TOKEN_MEMO: Dict = {}

#: The page-level fit made in this process, per (dims, spherical), kept
#: until the chunk corpus doubles. See the `layout` route.
_PAGE_FIT: Dict = {}
#: The last reconciliation of each kept fit, keyed on the page table it was
#: reconciled against, so an unchanged corpus is answered without redoing it.
_PAGE_REFRESH: Dict = {}

#: Pipeline profile, sidecar side. Bounded so a long session cannot grow it.
#:
#: Rings rather than aggregates, because a percentile has to be taken over
#: the samples and an average hides exactly the tail the profiler is for.
_PROFILE_CAP = 400
_PROFILE: Dict[str, "deque"] = {}


def _profile(kind: str, record: Dict) -> None:
    """Append one timed record. Never raises: a profiler that can fail a
    capture has made the thing it measures less reliable."""
    try:
        ring = _PROFILE.get(kind)
        if ring is None:
            ring = _PROFILE[kind] = deque(maxlen=_PROFILE_CAP)
        record = dict(record)
        record["at"] = round(time.time(), 3)
        ring.append(record)
    except Exception:                               # noqa: BLE001
        pass

#: The background embedder, started by `serve()` when a workspace has an
#: embedder to run. One thread, not a pool: the encoder is the bottleneck and
#: two of them would contend for the same GPU.
_EMBED_THREAD = None


#: `/health`'s lexical coverage, memoised on what it is a function of: the
#: chunk count and the frequency matrix's mutation counter.
_LEXICAL_MEMO: Dict = {}


def _lexical_coverage(workspace) -> Dict[str, int]:
    """How many chunks retrieval can reach on the lexical factor (`G-3`).

    Two ways to be unreachable, counted apart because they have different
    causes: no row at all (the matrix lost it, or never had it), and a row
    with no terms while the chunk's markdown has words (indexed while empty).
    """
    from ..vectors import tokens as _tokens
    freq = workspace.freq
    key = (workspace.store.chunk_count(), getattr(freq, "version", 0))
    if _LEXICAL_MEMO.get("key") == key:
        return _LEXICAL_MEMO["value"]
    no_row = empty_row = 0
    for cid, md in workspace.store._rows("MATCH (c:Chunk) RETURN c.cid, c.md"):
        row = freq.row_of(cid)
        if row is None:
            no_row += 1
        elif not freq._counts[row] and any(True for _ in _tokens(md or "")):
            empty_row += 1
    value = {"chunks_without_lexical_row": no_row,
             "chunks_with_empty_lexical_row": empty_row}
    _LEXICAL_MEMO.update(key=key, value=value)
    return value


# ---- the central diff (2026-10-04) --------------------------------------------
#
# "centralize deduplication etc on diffs throughout the pipeline in a
# centralized place on the backend that then can facilitate mappings ... a
# singular diff update on the scan side compatible with the same set of 3D and
# 2D representations". One record per capture, computed here from the render
# the trie already produced (`ScanUpdate.all_chunks`), keyed on the cid -- the
# key every consumer already shares (store, projector, chunk map, 3D nodes,
# pins). It names what the store must retire and what was only renamed, so no
# view has to infer it, and every view applies the same list.
#
#   added    cids in this render, not in the session's previous one
#   dirty    cids this capture rewrote
#   retired  cids in the previous render, not in this one (the store drops
#            them; the projector reports them gone; the views remove them)
#   renamed  retired cid -> added cid whose markdown is identical: a shift
#            moved a chunk's address, not its content
#
# Retirement is judged within ONE page session (what this visit rendered).
# Chunks stored by earlier visits are untouched until the page settles, as
# before -- whether the store keeps a page's history is Q.002, and with the
# diff central that is one policy here, `RETIRE`.
import collections as _collections
import hashlib as _hashlib

_DIFFS: "collections.deque" = _collections.deque(maxlen=5000)
_DIFF_SEQ = [0]
_DIFF_LOCK = threading.Lock()
#: What a retired cid does to the store: "delete" (today's semantics, the
#: same thing a settle does) -- Q.002 may make it "mark".
RETIRE = "delete"
#: **Within one visit the page is every unique chunk it showed** (Q.002 for
#: a visit, ruled 2026-10-17 by the reader's "track the full set of unique
#: chunks" / "persist chunk streams no matter how fast"). A chunk that drops
#: out of the render -- archive.org's list recycles as it scrolls -- is KEPT
#: (`session["kept"]`), not deleted; only a RENAMED chunk (the same markdown
#: at a new address, one content) retires. The settle then writes its trie
#: without retiring what the visit kept. Planted: the old in-session delete.
_PLANT_RETIRE_IN_SESSION = [False]


def _digest(markdown: str) -> str:
    return _hashlib.sha1((markdown or "").encode("utf-8")).hexdigest()[:16]


def _record_diff(diff: dict) -> dict:
    with _DIFF_LOCK:
        _DIFF_SEQ[0] += 1
        diff = dict(diff, seq=_DIFF_SEQ[0], at=round(time.time(), 3))
        _DIFFS.append(diff)
    return diff


def _page_diff(session: dict, url: str, passno: int, all_chunks, dirty) -> Optional[dict]:
    """The capture's diff against the session's previous render. None when
    this capture rendered nothing (no address changed: no render ran)."""
    if not all_chunks:
        return None
    now = {c.cid: _digest(c.markdown) for c in all_chunks}
    prev = session.get("render")
    session["render"] = now
    # What the store's trie already held for this page when the session
    # began: a revisit renders chunks the store has, and they are not ADDED
    # (2026-10-04: "Re-navigating back to a previous page re-spawns existing
    # nodes. This is where the patricia trie on the DB is the central spine").
    stored = session.get("stored") or set()
    known = set(prev or ()) | stored
    added = [c for c in now if c not in known]
    retired = [c for c in prev if c not in now] if prev is not None else []
    by_digest = {}
    for c in added:
        by_digest.setdefault(now[c], []).append(c)
    renamed = {}
    for old in retired:
        cands = by_digest.get(prev[old]) if prev else None
        if cands:
            renamed[old] = cands.pop(0)
    # **Across visits** (2026-10-04, measured live): a page re-rendered on a
    # revisit draws the same content at shifted xpaths -- 26 stored chunks
    # became 50 after one revisit of a gamerevolution guide, every one of the
    # 24 new cids a byte-identical copy of an old one. A stored cid that is
    # NOT in this render, whose markdown this render draws under a new cid, is
    # that chunk renamed: the old row retires, the new cid takes its place,
    # and the views carry the node instead of spawning another. Each stored
    # cid is matched at most once per session (`stored_md` is consumed).
    pool = session.get("stored_md") or {}
    if pool:
        free = {}
        for old, dg in pool.items():
            if old not in now:
                free.setdefault(dg, []).append(old)
        for c in list(added):
            olds = free.get(now[c])
            if olds and by_digest.get(now[c]) and c in by_digest[now[c]]:
                old = olds.pop(0)
                renamed[old] = c
                retired.append(old)
                pool.pop(old, None)
                stored.discard(old)
                by_digest[now[c]].remove(c)
    return {"kind": "capture", "url": url, "passno": passno, "added": added,
            "dirty": [c.cid for c in dirty], "retired": retired, "renamed": renamed,
            # Rendered now AND already in the store before this visit: drawn
            # from the store, never re-spawned as new.
            "known": [c for c in now if c in stored and c not in set(prev or ())],
            "chunks": len(now)}


def _document_url(url: str) -> str:
    """The DOCUMENT a url names: a plain fragment (`#chat`, `#section-2`) is a
    place in one document, not another page -- ddg's `/` and `/#chat` were
    stored as two pages and drew two page nodes for one document (the tree
    verdict's one second root, 2026-10-07). A hash ROUTE (`#/...`, `#!...`)
    selects content in a single-page app and is kept."""
    head, sep, frag = url.partition("#")
    if not sep or frag.startswith("/") or frag.startswith("!"):
        return url
    return head


def _settle_truncated(session: dict, stored: int, now: Optional[float] = None) -> bool:
    """Would settling this session write a TRUNCATED page as the complete one?

    A young session (under 15 s) that rendered under half of what the store
    holds for the page (6 or more chunks) has seen a page still loading -- a
    reload ends a session holding only the fresh load's first fold. Such a
    settle writes nothing and retires nothing (2026-10-06: 30 of johnwick's 31
    stored chunks retired by a settle of 1 rendered chunk).
    """
    now = time.time() if now is None else now
    rendered = len(session.get("render") or ())
    young = now - float(session.get("born") or 0) < 15.0
    return young and stored >= 6 and rendered < 0.5 * stored


def _project(cids) -> None:
    """Hand chunks to the chunk projector's queue. Never raises."""
    try:
        from .projector import projector as _get
        got = _get()
        if got is not None and cids:
            got.enqueue(list(cids))
    except Exception:                               # noqa: BLE001
        pass


def _project_page(workspace, url: str) -> None:
    """Queue every chunk a page holds now, plus any the projector still
    holds for it that the page has lost."""
    try:
        from .projector import projector as _get
        got = _get()
        if got is None or not url:
            return
        cids = [r[0] for r in workspace.store._rows(
            "MATCH (c:Chunk {url: $u}) RETURN c.cid", {"u": url})]
        got.enqueue_page(url, cids)
    except Exception:                               # noqa: BLE001
        pass


_LEXICAL_SAVED_AT = [0.0]


def _save_lexical_due(workspace, every: float = 30.0) -> None:
    """Persist the frequency matrix at most every `every` seconds, if it
    changed. Never raises."""
    now = time.monotonic()
    if now - _LEXICAL_SAVED_AT[0] < every:
        return
    _LEXICAL_SAVED_AT[0] = now
    try:
        started = time.perf_counter()
        with _WORK_LOCK:
            wrote = workspace.save_lexical()
        if wrote:
            _profile("lexical_save", {
                "ms": round((time.perf_counter() - started) * 1000, 1)})
    except Exception:                               # noqa: BLE001
        pass


def _aggregate_due(workspace) -> None:
    """Re-cluster the pages that have gone quiet (`G-65`).

    Runs on the embedding worker, after a flush, because the two are ordered:
    a page clustered before its new chunks have vectors would cluster the
    chunks it had a moment ago. Off the request path either way -- a capture
    returns without waiting for this, and the groups appear on the next one.
    """
    now = time.monotonic()
    due = [url for url, when in list(_AGGREGATE_AFTER.items()) if when <= now]
    for url in due:
        _AGGREGATE_AFTER.pop(url, None)
        try:
            _yield_to_foreground()
            asked = time.perf_counter()
            with _WORK_LOCK:
                got_lock = time.perf_counter()
                workspace.aggregate(url)
            # Merge groups changed, so which chunk leads and which vector it
            # speaks with changed too: the projector re-places the page.
            _project_page(workspace, url)
            _profile("aggregate", {
                "lock_wait_ms": round((got_lock - asked) * 1000, 1),
                "ms": round((time.perf_counter() - got_lock) * 1000, 1),
            })
        except Exception:                           # noqa: BLE001
            # A page that failed to cluster is a page with the groups it had.
            # It must not stop the worker, or nothing would ever be embedded
            # again either -- they share this thread.
            pass


def _embed_forever(workspace, stop: threading.Event) -> None:
    """Embed what is queued, off the request path.

    In batches with the lock RELEASED between them. Holding it for a whole
    page would make the background worker exactly as blocking as the
    synchronous flush it replaces, just further from the caller -- a request
    arriving mid-flush would wait the same 13.9 seconds and have no way to
    know why.
    """
    while not stop.is_set():
        if not _EMBED_WANTED.wait(timeout=0.5):
            # Nothing to embed, but a page may still be due to re-cluster --
            # the last drain of a visit queues one and then no more arrive.
            _aggregate_due(workspace)
            # And the lexical rows go to disk once things are quiet, so a
            # hard kill costs seconds of them, not the whole session's.
            _save_lexical_due(workspace)
            continue
        _EMBED_WANTED.clear()
        while not stop.is_set():
            try:
                stood = _yield_to_foreground()
                asked = time.perf_counter()
                # Take, ENCODE OUTSIDE THE LOCK, store (D-35). The encoder is
                # the slow part of a batch, and holding the store's lock
                # through it made every capture on the page being read wait
                # for the page left behind to be embedded.
                with _WORK_LOCK:
                    before = len(workspace.vectors)
                    taken = workspace.take_vectors(limit=_EMBED_BATCH)
                enc_start = time.perf_counter()
                with _ENCODER_LOCK:
                    produced = workspace.encode_taken(taken)
                enc_ms = (time.perf_counter() - enc_start) * 1000
                stood += _yield_to_foreground()
                with _WORK_LOCK:
                    got_lock = time.perf_counter()
                    workspace.store_vectors(produced)
                    # The stream: what just got a vector is transformed into
                    # the fit next, in the projector's own batches.
                    _project(getattr(workspace, "last_embedded", None) or ())
                    # The QUEUE's length, not the flush's return value.
                    # `flush_vectors` answers with `vectors.report()`, which
                    # is a set of cumulative counters -- pushed, queued,
                    # skipped, embedded -- and they are non-zero forever after
                    # the first flush. Reading them as "work done this call"
                    # gives a loop that never exits: a thread spinning on the
                    # encoder, taking and dropping the lock, starving every
                    # request behind it.
                    remaining = len(workspace.vectors)
                done = time.perf_counter()
                _profile("embed", {
                    "lock_wait_ms": round((got_lock - asked) * 1000 - enc_ms, 1),
                    "yielded_ms": round(stood * 1000, 1),
                    "encode_ms": round(enc_ms, 1),
                    "ms": round((done - got_lock) * 1000, 1),
                    "embedded": max(0, before - remaining),
                    "queue_after": remaining,
                })
            except Exception:                       # noqa: BLE001
                # A failed batch leaves its chunks queued and unembedded,
                # which the pane already reports as awaiting a vector. It must
                # not kill the worker: the next capture would queue into a
                # thread that is gone, and nothing would ever be embedded
                # again with no error anywhere to say so.
                break
            if not remaining:
                break
        _aggregate_due(workspace)


#: How many chunks one background batch embeds before yielding the lock.
#:
#: Small enough that a request arriving mid-flush waits for a batch and not a
#: page. 64 chunks is well under a second on this machine's GPU.
_EMBED_BATCH = 64

#: Pages whose chunks changed, and the earliest moment to re-cluster each.
#:
#: `G-65`: stage two ran only at the settle, so while a reader browsed, the
#: merge groups on screen described a page that had moved on.
_AGGREGATE_AFTER: Dict[str, float] = {}

#: How long a page must be quiet before it is re-clustered.
#:
#: Every drain pushes the deadline out, so this runs when the reader pauses
#: rather than while they scroll -- which is the behaviour wanted, because a
#: page mid-scroll is not a page anyone has finished looking at. A full page
#: aggregation is about 110ms now (33ms to read the vectors in one query,
#: ~80ms to cluster), so the debounce exists to avoid pointless work rather
#: than to hide an expensive one.
#:
#: NOT incremental, and deliberately not. An incremental DBSCAN -- union-find
#: over the eps-graph with component splits on change -- was designed and then
#: not built, because measuring first showed the clustering was never the
#: cost: an 835-chunk page spent 330ms reading its vectors one query at a time
#: and 78ms clustering them. Fixing the read made the whole thing cheap enough
#: that the machinery would have been bought to speed up the wrong half.
_AGGREGATE_DEBOUNCE = 1.5


#: Each page's CONTROLS (element xpath -> its first control address), read
#: once per page per capture. The lookup was a scan of the whole Address
#: table -- a flat ~50 ms per panel whatever the chunk's size, the bulk of
#: every panel's payload (2026-10-11, `/chunk` `_ms`: controls 46-104 of
#: 51-110 ms). A capture that writes the page drops its entry.
_CONTROLS: Dict[str, Dict[str, object]] = {}
_CONTROLS_LOCK = threading.Lock()
#: Planted: every panel scans the Address table for its controls, as before.
_PLANT_CONTROL_SCAN = [False]
#: Planted: a capture re-writes chunks the store already holds identically.
_PLANT_REWRITE_SAME = [False]
#: Planted: a payload decoded against a dictionary it does not complete.
_PLANT_NO_RESYNC = [False]


def _forget_controls(url: str) -> None:
    with _CONTROLS_LOCK:
        _CONTROLS.pop(url, None)


def _page_controls(workspace, url: str) -> Dict[str, object]:
    with _CONTROLS_LOCK:
        got = _CONTROLS.get(url)
    if got is not None:
        return got
    from ..address import ContentAddress
    out: Dict[str, object] = {}
    for xpath, key in workspace.store._rows(
            "MATCH (a:Address) WHERE a.url = $url RETURN a.xpath, a.akey ORDER BY a.akey", {"url": url}):
        if not key or xpath in out:
            continue
        try:
            a = ContentAddress.parse(key)
        except Exception:                           # noqa: BLE001
            continue
        if a.is_control:
            out[xpath] = a
    with _CONTROLS_LOCK:
        _CONTROLS[url] = out
        while len(_CONTROLS) > 64:
            _CONTROLS.pop(next(iter(_CONTROLS)))
    return out


#: Planted (2026-10-12): lines zipped with the anchors by position.
_PLANT_POSITIONAL_ANCHORS = [False]
#: Planted (2026-10-12): a capture skips a chunk whose MARKDOWN is unchanged,
#: whatever its addresses did.
_PLANT_SKIP_BY_MD = [False]


def chunk_payload(workspace, cid: str) -> Optional[Dict]:
    """One chunk as the plugin's `ChunkPayload`.

    The markdown's lines and `addresses_of` are aligned by the positional
    `anchors` contract -- one address per line, in line order -- so they are
    zipped rather than matched. That contract is asserted in the store's own
    tests; if it ever breaks, this silently mislabels every line, which is why
    the zip is strict about length rather than truncating.
    """
    _t0 = time.perf_counter()
    _ms: Dict[str, float] = {}
    stored = workspace.store.chunk(cid)
    if stored is None:
        return None
    _ms["chunk"] = round((time.perf_counter() - _t0) * 1000, 1)
    self_window = getattr(workspace, "context_window", 0)

    _t = time.perf_counter()
    # By line index, never by position in the list: a line with no anchor
    # left no slot, and zipping shifted every later line onto its neighbour's
    # address (2026-10-12, arXiv). Planted: the positional zip.
    store = workspace.store
    if _PLANT_POSITIONAL_ANCHORS[0] or not hasattr(store, "anchors_by_line"):
        addresses = list(workspace.addresses_for(cid))
        by_line = {i: a for i, a in enumerate(addresses)}
    else:
        by_line = store.anchors_by_line(cid)
        addresses = [by_line[i] for i in sorted(by_line)]
        _ms["duplicate_ords"] = getattr(store, "last_duplicate_ords", 0)
        dups = getattr(store, "last_duplicates", {}) or {}
        if dups:
            _ms["duplicates_sample"] = {str(o): [k.split("|")[1][-48:] for k in ks][:4]
                                        for o, ks in list(sorted(dups.items()))[:4]}
    _ms["addresses"] = round((time.perf_counter() - _t) * 1000, 1)
    # Re-indented by nesting LEVEL before anyone sees it.
    #
    # The renderer indents by depth in the DOM, so a chunk rooted a few
    # elements down opens at column 10 -- and both consumers of this payload
    # put the lines into a markdown note, where four or more leading spaces is
    # an indented CODE BLOCK. The export learned this the hard way: 82 of 98
    # notes parsed as code and every wikilink in them was unreachable.
    #
    # Done here rather than in each caller so the `/` retrieval gesture, which
    # inserts these lines into a note directly, cannot reintroduce it.
    # `_reflow` maps one line to one line, so the positional `anchors`
    # alignment below is untouched.
    texts = _reflow(stored.md).splitlines()

    # An affordance is usually not the address the line is stored under.
    #
    # `interactive.links` is suppressed by the render, so the line an anchor
    # draws is stored under its `urls.*` or `text.visible` address instead --
    # and the store keeps ONE address per line, so the control is simply not
    # in `addresses_for`. Asking only that list reported 105 controls on a
    # six-page workspace, every one a button or a form, and not a single link
    # on a site that is almost entirely anchors.
    #
    # `addresses_at` is the lookup that answers this: every address at one
    # element, which is where the anchor's affordance actually sits. Cached
    # per element because a chunk draws the same element on several lines.
    control_cache: Dict[str, Optional[object]] = {}
    # Every element the chunk draws, asked in ONE query (`addresses_at_many`):
    # one query per element cost a panel 0.36-2.0 s on the working store.
    elements = [a.xpath.split("/text()")[0] for a, _v in addresses]
    many = getattr(workspace.store, "addresses_at_many", None)
    _t = time.perf_counter()
    if _PLANT_CONTROL_SCAN[0]:
        # The old path: a scan for the chunk's elements, or one per element
        # (`control_at`, lazily, below) when the batched scan is off.
        if many is not None and elements:
            for element, found_at in many(elements, stored.url).items():
                control_cache[element] = next((a for a, _v in found_at if a.is_control), None)
    elif elements:
        page = _page_controls(workspace, stored.url)
        for element in elements:
            control_cache[element] = page.get(element)
    _ms["controls"] = round((time.perf_counter() - _t) * 1000, 1)

    def control_at(element: str):
        if element not in control_cache:
            found = None
            for address, _value in workspace.store.addresses_at(
                    element, stored.url):
                if address.is_control:
                    found = address
                    break
            control_cache[element] = found
        return control_cache[element]

    lines: List[Dict] = []
    for i, text in enumerate(texts):
        entry: Dict[str, object] = {"text": text, "key": "", "cls": "text",
                                    "control": False}
        if i in by_line:
            address, value = by_line[i]
            entry["key"] = address.key()
            # The template this line belongs to, beside the address that
            # identifies it. Two result rows share a shape and never share an
            # address, which is the whole point of carrying both.
            entry["shape"] = address.shape
            entry["cls"] = address.render_class
            entry["control"] = bool(address.is_control)
            if address.is_url:
                entry["target"] = value
            if not entry["control"]:
                found = control_at(address.xpath.split("/text()")[0])
                if found is not None:
                    entry["control"] = True
                    # The address that names the affordance, reported beside
                    # the line's own so a caller can still say where the line
                    # is stored. Enacting needs the control; navigating needs
                    # the line.
                    entry["control_key"] = found.key()
                    entry["cls"] = found.render_class
        lines.append(entry)

    # The merge layer (`G-27`). A chunk that belongs to a group is still
    # served as itself -- it is what a retrieval hit resolves to, and its
    # addresses are its own -- with the group named beside it so the surface
    # can offer the merged reading without pretending the parts are gone.
    group: Optional[Dict] = None
    _t = time.perf_counter()
    if stored.group_of:
        members = workspace.store.group_members(stored.group_of)
        if len(members) > 1:
            group = {
                "lead": stored.group_of,
                "members": [m.cid for m in members],
                "position": [m.cid for m in members].index(stored.cid) + 1,
                # Assembled, never stored: a member rewritten by the next
                # drain would otherwise leave a stale copy of itself inside
                # the merged text.
                "markdown": _reflow(workspace.merged_markdown(stored.group_of)),
                "tokens": tokens.budget(
                    workspace.merged_markdown(stored.group_of)),
            }

    _ms["group"] = round((time.perf_counter() - _t) * 1000, 1)
    _ms["total"] = round((time.perf_counter() - _t0) * 1000, 1)
    return {
        "_ms": _ms,
        "cid": stored.cid,
        "url": stored.url,
        "xpath": stored.xpath,
        "lines": lines,
        #: Null unless stage two put this chunk with others (`G-26`).
        "group": group,
        # Reported so a caller can tell a genuinely short chunk from a
        # misaligned one instead of guessing from the render.
        "addresses": len(addresses),
        # The chunk's size in the unit its window was measured in, and the
        # window it was cut against, so a surface can show fill rather than
        # leaving "are these chunks the right size" a question nobody can
        # answer from the vault.
        # What the chunk spends of the WINDOW, which is what the badge
        # beside it is a fraction of. `count` here would report a number the
        # window was never compared against.
        "tokens": tokens.budget(stored.md or ""),
        "window": int(self_window),
    }


def search_payload(workspace, query: str, k: int = 8, *,
                   offset: int = 0, url: str = "",
                   coarse: bool = True, budget: int = 0) -> Dict:
    """Ranked chunks for the overlay (`G-63`, `G-64`, `G-69`, `G-70`).

    Ranking is the store's own three-form retrieval; this adds nothing to it
    and reshapes what comes back.

    **A window over a ranked list, not a top-k.** `G-69`: rank is a total
    order over the corpus and the cutoff is a decision the reader makes by
    stopping. So the caller asks for a slice and keeps asking as it scrolls.
    The rank is recomputed for `offset + k` and sliced, because the index
    ranks rather than paginates -- which is honest but means a deep scroll
    costs more than a shallow one, and the cap is what keeps that bounded.

    **Scoped, or not** (`G-70`). `url` restricts to one shadow DOM, which is
    what clicking a page node means; without it the ranking is the corpus's.

    **Coarse first** (`G-63`). A merge group is represented by its LEAD and
    its members are suppressed, because the group is what the merge layer
    indexes and a reader scrolling results does not want the same passage
    eight times. `coarse=False` drops that and ranks the members themselves,
    which is what a click expansion inside one page wants.

    **Inside a budget** (`G-64`). `budget` in link-free tokens: results are
    taken until the next one would not fit, so a list handed to a model is a
    list that can be handed to a model.
    """
    want = max(1, offset + k)
    # Scoped means ranked WITHIN the page, and the index does that itself now
    # (`scope_url`). It used to be a post-filter over a widened global top-k,
    # bounded so that scoping a large page did not rank the corpus end to
    # end -- and that bound was the defect: RFC 9110's 1,173 chunks rank
    # below the bound globally, so scoping to the largest page in the store
    # returned 0 hits for every query.
    # `n` for "showing {k}/{n} results" (PLUGIN_GOAL 86): the chunks the
    # ranking gives a positive score at all -- before duplicate content and
    # merge groups collapse, so it bounds what scrolling can reach from above.
    from ..search import SearchDiagnostics
    diag = SearchDiagnostics()
    try:
        hits = workspace.search(query, k=want, scope_url=url or "", diagnostics=diag)
    except TypeError:                       # an index without diagnostics
        hits = workspace.search(query, k=want, scope_url=url or "")
    import time as _time
    _t_shape = _time.perf_counter()
    out = []
    spent = 0
    seen_groups = set()
    # One read for every hit (it was one query per hit, after the ranking had
    # already read them all once: 9-10 s cold, 2026-10-17).
    many = getattr(workspace.store, "chunks_many", None)
    # The ranking already read these to collapse duplicates: reused, not read
    # again (shape was 1.2-2.2 s of every search on 65k chunks, 2026-10-17).
    got = dict(getattr(diag, "read_chunks", None) or {})
    need = [c for c in (getattr(h, "cid", None) or getattr(h, "chunk", "") for h in hits) if c and c not in got]
    if need and many:
        got.update(many(need))
    elif need:
        got = None
    for hit in hits:
        cid = getattr(hit, "cid", None) or getattr(hit, "chunk", "")
        stored = (got.get(cid) if got is not None else workspace.store.chunk(cid)) if cid else None
        if stored is None:
            continue
        if url and stored.url != url:
            continue
        if stored.redundant:
            # `G-24` settled this one: it draws what another chunk draws.
            continue
        if coarse:
            if stored.group_of and stored.group_of != stored.cid:
                # A member speaks through its lead, which ranks on its own.
                continue
            if stored.group_of in seen_groups:
                continue
            if stored.group_of:
                seen_groups.add(stored.group_of)
        out.append({
            "cid": stored.cid,
            "url": stored.url,
            "xpath": stored.xpath,
            "score": float(getattr(hit, "score", 0.0) or 0.0),
            # The three factors, not just their product. The product is a
            # multiplication of three small numbers and lands around 1e-5,
            # which reads as zero at any sane precision and tells a reader
            # nothing about WHY a result ranked -- whether the words matched,
            # the meaning did, or the page is simply well linked.
            "lexical": float(getattr(hit, "lexical", 0.0) or 0.0),
            "semantic": float(getattr(hit, "semantic", 0.0) or 0.0),
            "pagerank": float(getattr(hit, "rank", 0.0) or 0.0),
            "members": stored.group_n,
            "tokens": tokens.budget(stored.md or ""),
            # The first lines, LINK-FREE. The stored markdown is 52.5%
            # machine addressing by token (M.7), and a preview of it
            # reads as the same long path twice inside one `[](...)`,
            # filling the row and pushing the words that would say what
            # the result IS off the end. `for_model` is the string the
            # encoder ranked on, so a preview of it previews what
            # actually matched.
            "preview": "\n".join(
                tokens.for_model(stored.md or "").splitlines()[:6]),
        })

    out = out[offset:offset + k]
    if budget:
        kept = []
        for row in out:
            if spent + row["tokens"] > budget and kept:
                break
            kept.append(row)
            spent += row["tokens"]
        out = kept
    return {"query": query, "hits": out, "offset": offset,
            "scope": url or "", "coarse": bool(coarse),
            "tokens": spent if budget else sum(r["tokens"] for r in out),
            #: True while the ranking still had more to give at this depth,
            #: so a scrolling overlay knows whether to keep asking.
            "more": len(hits) >= want,
            "n": int(getattr(diag, "survivors", 0) or 0),
            "code_partitions": getattr(diag, "code_partitions", None),
            # Where the time went: the ranking's phases, its store reads, and
            # this reshaping's own (one more read per hit).
            "timing": dict(getattr(diag, "ms", None) or {}, select_reads=getattr(diag, "select_reads", 0),
                           shape=round((_time.perf_counter() - _t_shape) * 1000, 1))}


#: Requests in flight: thread id -> (started, request line). Read by the
#: stall watchdog (`_stall_watchdog`), nothing else.
_INFLIGHT: Dict[int, tuple] = {}
_STALL_DUMPED = [0.0]
#: Where `_reqlog` writes (set by `serve()`); None leaves it off.
_REQLOG = [None]


def _reqlog(what: str, tid: int, line: str) -> None:
    """One line per request start and end, flushed at once (`requests.log`).

    A stall the interpreter cannot report (2026-10-19: the C-level dump said
    only "freed thread state") is found by what STARTED and never ended just
    before it. Kept to ~2 MB: the file is cut to its last half when it grows.
    """
    path = _REQLOG[0]
    if path is None:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s %s %x %s\n" % (time.strftime("%H:%M:%S"), what, tid, line[:160]))
        if path.stat().st_size > 2_000_000:
            tail = path.read_text(encoding="utf-8", errors="replace")[-1_000_000:]
            path.write_text(tail, encoding="utf-8")
    except Exception:                               # noqa: BLE001
        pass


def _stall_watchdog(workspace_path: str, stall_s: float = 90.0, every_s: float = 600.0) -> None:
    """Dump every thread's stack when a request has been in flight too long.

    2026-10-19: the sidecar twice stopped answering a minute after it
    started -- no CPU, connections piling up in CLOSE_WAIT, and even
    `/sensor`, which reads a file, never returned. Nothing was logged, and a
    stall without a stack can only be guessed at. When any request has been
    in flight for `stall_s`, every thread's Python stack goes to
    `stacks.log` in the workspace, at most once per `every_s`.
    """
    import faulthandler
    # And a stall Python cannot see: a native call holding the GIL stops
    # every Python thread, this one included (the second stall: no dump).
    # `dump_traceback_later` runs its timer in C, without the GIL; this
    # thread re-arms it every 15 s, so it fires only when Python has not run
    # for 75 s -- and then names every thread's frame.
    try:
        gil_fh = open(Path(workspace_path) / "stacks.log", "a", encoding="utf-8")
    except OSError:
        gil_fh = None
    while True:
        if gil_fh is not None:
            try:
                faulthandler.dump_traceback_later(75, repeat=False, file=gil_fh, exit=False)
            except Exception:                       # noqa: BLE001
                pass
        time.sleep(15)
        try:
            now = time.time()
            old = [(t, line) for t, line in list(_INFLIGHT.values()) if now - t > stall_s]
            if not old or now - _STALL_DUMPED[0] < every_s:
                continue
            _STALL_DUMPED[0] = now
            with open(Path(workspace_path) / "stacks.log", "a", encoding="utf-8") as fh:
                fh.write("\n==== %s: %d request(s) in flight > %ds, oldest %ds: %s\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), len(old), stall_s,
                    max(now - t for t, _ in old), "; ".join(line[:120] for _, line in old[:8])))
                fh.flush()
                faulthandler.dump_traceback(file=fh, all_threads=True)
        except Exception:                           # noqa: BLE001
            pass


class _Handler(BaseHTTPRequestHandler):
    workspace = None            # set by serve()

    def handle_one_request(self) -> None:
        # In flight, for the stall watchdog: the request line once it is read.
        me = threading.get_ident()
        _INFLIGHT[me] = (time.time(), "(reading)")
        try:
            super().handle_one_request()
        finally:
            got = _INFLIGHT.pop(me, None)
            if got and got[1] != "(reading)":
                _reqlog("end %dms" % int((time.time() - got[0]) * 1000), me, got[1])

    def parse_request(self) -> bool:
        ok = super().parse_request()
        me = threading.get_ident()
        if me in _INFLIGHT:
            _INFLIGHT[me] = (_INFLIGHT[me][0], str(getattr(self, "requestline", "")))
            _reqlog("start", me, str(getattr(self, "requestline", "")))
        return ok
    enact_allowed = False       # set by serve(); the write path's gate
    #: Set by `serve()`. Separate from `enact_allowed` because they are
    #: different permissions: enact presses controls on live pages, capture
    #: only writes down what the browser cell read.
    capture_allowed = False
    #: `D-39`: refuse captures that do not come from the plugin.
    plugin_captures_only = False
    kernel_pool = None          # set by serve(); None means --kernel was off
    shell_pool = None           # set by serve(); shares --kernel's gate

    # Silence the default stderr access log: it prints the requested path, and
    # the path carries the cid of whatever the reader is looking at.
    def log_message(self, *args) -> None:
        return

    def _send(self, code: int, body: Dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        # Obsidian renders from app://obsidian.md, so the fetch is
        # cross-origin. Loopback-only binding is what limits reach here; the
        # header just makes the plugin's own fetch legal.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def _send_bytes(self, code: int, data: bytes, content_type: str, cache: bool = True) -> None:
        """`cache` only for bytes that cannot change under their address -- a
        media blob is keyed by its url's hash. An offline form is rebuilt from
        a store that moves: cached a day, the cell opened Axolotl's traced
        page as it was before the picture count was added (2026-10-11)."""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:                   # noqa: N802 (stdlib name)
        """Answer the CORS preflight, or every POST fails before it is sent.

        Obsidian renders from `app://obsidian.md`, so a fetch to loopback is
        cross-origin. A GET with no custom headers is "simple" and goes
        straight through -- which is why reading chunks worked from the first
        day -- but a POST with `Content-Type: application/json` is not, and
        the browser sends an OPTIONS preflight first. `BaseHTTPRequestHandler`
        answers 501 to a verb it has no handler for, the preflight fails, and
        `fetch` REJECTS: the plugin saw a thrown error and reported "no answer
        from the sidecar" while the server was healthy and the 403 it had
        written was never read.

        Invisible to the Node harness, which has no origin and no preflight.
        Only the real app could show it.
        """
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Vertiscope-Client")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:                      # noqa: N802 (stdlib name)
        """The acting routes, each only when the server was asked for one.

        Two now, and they are gated separately on purpose. `enact` presses a
        control in a real browser; `kernel` runs arbitrary Python with this
        process's privileges. Those are different sizes of permission and a
        reader who wanted a notebook did not thereby ask for a vault that can
        drive the web, nor the reverse.
        """
        _LAST_REQUEST[0] = time.time()
        parts = urlsplit(self.path)
        route = parts.path.strip("/")
        if route == "shutdown":
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self._send(403, {"error": "loopback only"})
                return
            _SHUTTING[0] = True
            asked = time.time()

            def _exit_when_idle():
                # Every capture, embed batch, settle and checkpoint in flight
                # holds the work lock: taking it means none is mid-write.
                with _WORK_LOCK:
                    _profile("shutdown", {"waited_s": round(time.time() - asked, 1)})
                    # The reply first: with nothing in flight the lock was free
                    # at once and the process left before answering (the
                    # restart script read that as "did not answer").
                    time.sleep(0.5)
                    # 75: "restart me" to the supervisor (exit 0 is a stop,
                    # and the first graceful restart left the sidecar down).
                    _exit_for_supervisor(75, self.workspace)
            threading.Thread(target=_exit_when_idle, daemon=True).start()
            self._send(200, {"shutting_down": True, "waits_for": "the work lock"})
            return
        if _SHUTTING[0]:
            self._send(503, {"error": "shutting down", "retry": True})
            return
        if route == "chunk_preview":
            self._post_chunk_preview()
            return

        # The browser cell handing over what it captured (`G-47`).
        #
        # Ungated for the same reason `chunk_preview` is: it writes only the
        # workspace, runs no process, and presses nothing on any page. It is
        # the scan the reader is watching, arriving from the pane they are
        # watching it in.
        # Where the chunks a live capture produced belong in the picture
        # already on screen (`G-34`). Read-only: it fits nothing and stores
        # nothing, it asks the existing fit where a point lands.
        # One step of unravelling a page's path (`G-54`). Read-only: it
        # fits nothing and stores nothing.
        # Hover-first (`G-80`): the chunks under the reader's pointer jump the
        # encoder's queue and the projector's, so what they point at is what
        # is embedded and drawn next. Nothing is written; only order changes.
        # Chunk view's drawn places, kept on the chunks (PLUGIN_GOAL 108): the
        # pane relaxed them; the next switch reads them instead of relaxing
        # again. Writes the workspace only, like a capture.
        if route == "drawn":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            rows = [(r[0], r[1:8]) for r in (body.get("rows") or [])
                    if isinstance(r, list) and len(r) >= 7][:50000]
            t0 = time.perf_counter()
            with _foreground(), _WORK_LOCK:
                n = self.workspace.store.save_drawn(rows)
            _LAST_WRITE[0] = time.time()
            _profile("drawn", {"n": n, "ms": round((time.perf_counter() - t0) * 1000, 1)})
            self._send(200, {"saved": n})
            return

        if route == "focus":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            cids = [str(c) for c in (body.get("cids") or []) if c][:64]
            from .projector import projector as _get_projector
            proj = _get_projector()
            with _WORK_LOCK:
                embed_first = self.workspace.vectors.prioritize(cids)
            projected = proj.prioritize(cids) if proj is not None else 0
            if embed_first:
                _EMBED_WANTED.set()
            _profile("focus", {"cids": len(cids), "embed_first": embed_first,
                               "project_first": projected})
            self._send(200, {"cids": len(cids), "embed_first": embed_first,
                             "project_first": projected})
            return

        if route == "unfold":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                # `space` so the anchors come from the fit the reader is
                # actually looking at. Without it an unfolding taken while
                # the pane showed S3 hung its chunks off euclidean page
                # positions, 378 units from the node they belong to.
                self._send(200, unfold_path(
                    self.workspace,
                    body.get("url") or "",
                    body.get("path") or "",
                    space=str(body.get("space") or ""),
                    #: The territory a recursive step inherits from the
                    #: branch that revealed it. Absent for a first step,
                    #: where the page's own room is the right answer.
                    anchor_at=body.get("anchor"),
                    room=float(body.get("room") or 0.0)))
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        # Rebuild `akey` for every address that lost it (`D-26`).
        #
        # A write, so it is a POST, but not a capture: it invents nothing and
        # reaches no page. The key is DERIVED from four columns already on
        # the row, so this is recomputation rather than repair in the sense
        # of guessing. A row missing its url or xpath is left alone and
        # counted, because a handle that points nowhere is worse than none.
        #
        # It is a route rather than a maintenance script because the store is
        # held open by this process: repairing it otherwise means stopping
        # the sidecar, which means the plugin loses its backend, which is how
        # a five-second fix became a restart every time.
        if route == "repair_keys":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                self._send(200, self.workspace.store.repair_blank_keys())
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        # Recompute the page link graph over the whole corpus (`D-32`).
        # Same justification as `/repair_keys`: the store is held open by
        # this process, so doing it any other way means taking the plugin's
        # backend away to fix the plugin.
        # Containment among an arbitrary set of drawn chunks (`G-6`).
        #
        # Read-only. The pane sends what it is drawing and gets back the
        # edges the trie holds between those nodes -- including pairs that
        # arrived from different routes at different times, which is exactly
        # what every per-call edge computation misses.
        if route == "edges":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            cids = [c for c in (body.get("cids") or []) if c]
            if not cids:
                self._send(200, {"edges": [], "n": 0})
                return
            try:
                drawn = set(cids)
                urls = {c.url for c in self.workspace.store.chunks_by_cids(cids)} \
                    if hasattr(self.workspace.store, "chunks_by_cids") \
                    else {u for u in (body.get("urls") or [])}
                if not urls:
                    urls = set(self.workspace.pages())
                out, seen = [], set()
                for page in urls:
                    for a, b in self.workspace.store.contains_within(page, among=drawn):
                        if a in drawn and b in drawn and a != b \
                                and (a, b) not in seen:
                            seen.add((a, b))
                            out.append({"source": a, "target": b})
                self._send(200, {"edges": out, "n": len(out),
                                 "asked": len(cids), "pages": len(urls)})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        # A picture a saved page form draws, its bytes as the page loaded them
        # (`snapshots.save_media`). Body: the raw bytes; ?url= the picture's url.
        # A page as the cell PRESENTED it (`G-60`): MHTML from
        # `webContents.savePage`, with its visible text for the infill test.
        if route == "offline":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            from . import offline as _off
            import base64 as _b64
            url = (parse_qs(urlsplit(self.path).query).get("url") or [""])[0]
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 2 * _off.PAGE_MAX:
                    self._send(413, {"saved": False, "why": "too large"})
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                data = _b64.b64decode(body.get("mhtml_b64") or "")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            got = _off.save_page(self.workspace, url, data, str(body.get("text") or ""))
            _profile("offline_saved", {"url": url, **{k: v for k, v in got.items() if k != "key"}})
            self._send(200, got)
            return

        if route == "media":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            from . import snapshots as _snaps
            url = (parse_qs(parts.query).get("url") or [""])[0]
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > _snaps.MEDIA_MAX:
                    self._send(413, {"saved": False, "why": "too large"})
                    return
                data = self.rfile.read(length)
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            got = _snaps.save_media(self.workspace, url, data, self.headers.get("Content-Type") or "")
            _profile("media", {"bytes": len(data), **{k: v for k, v in got.items() if k != "key"}})
            self._send(200, got)
            return

        # Streamed chunks placed BEFORE the store holds them (PLUGIN_GOAL 48):
        # encoded and placed through the fit at once, no store read or write.
        if route == "project":
            if self.workspace is None or getattr(self.workspace, "embedder", None) is None:
                self._send(503, {"error": "no encoder"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            url = str(body.get("url") or "")
            items = [it for it in (body.get("items") or []) if it.get("id") and str(it.get("text") or "").strip()][:400]
            if not url or not items:
                self._send(200, {"pos": {}, "hsv": {}})
                return
            try:
                t0 = time.perf_counter()
                with _ENCODER_LOCK:
                    t1 = time.perf_counter()
                    M = self.workspace.embedder.embed_texts([str(it["text"])[:4000] for it in items])
                t2 = time.perf_counter()
                import numpy as np
                from .projector import projector as _get_projector
                proj = _get_projector()
                if proj is None or not hasattr(proj, "project_transient"):
                    self._send(200, {"pos": {}, "hsv": {}, "why": "no page projector"})
                    return
                vec = {it["id"]: np.asarray(M[i], dtype=np.float32) for i, it in enumerate(items)}
                got = proj.project_transient(url, vec)
                got["ms"] = {"lock": round((t1 - t0) * 1000, 1), "encode": round((t2 - t1) * 1000, 1),
                             "place": round((time.perf_counter() - t2) * 1000, 1)}
                got["n"] = len(items)
                _profile("project", {"url": url, "n": len(items), **got["ms"], "placed": len(got.get("pos") or {})})
                self._send(200, got)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        # A PDF the browser cell reached (G-248): its bytes, read by the page
        # context from its own document, kept and chunked like a page.
        if route == "model_run":
            # A model role run on a CHUNK (G-264: Triplex over a web text
            # panel; `chat` over a prompt): in a thread, as its answer takes
            # 20-40 s on CPU; `GET /model_job?id=` follows it. The answer is
            # the role's TYPE or the reason it is not (`vertiscope/models.py`).
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            role = str(body.get("role") or "")
            if role not in ("triplex", "chat") or self.workspace is None:
                self._send(400, {"error": "role triplex or chat, with a workspace"})
                return
            jid = "%s:%s:%d" % (role, body.get("cid") or "prompt", int(time.time() * 1000))
            _MODEL_JOBS[jid] = {"state": "running", "id": jid, "role": role, "cid": body.get("cid")}
            threading.Thread(target=_model_job, args=(self.workspace, jid, body), daemon=True).start()
            self._send(202, dict(_MODEL_JOBS[jid]))
            return

        if route == "download":
            # A special file fetched -- ONLY when the body says the reader
            # confirmed it (2026-10-18: "prompt the user before applying a
            # download on-click"; the panel asks, with the name, size and
            # destination, before it sends this). A model goes to the model
            # directory, a PDF through the PDF pipeline, anything else to the
            # workspace's `downloads/`. Runs in a thread; `GET
            # /download_status?href=` follows it.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            href = str(body.get("href") or "")
            if body.get("confirmed") is not True:
                self._send(400, {"error": "a download needs the reader's confirmation (confirmed: true)"})
                return
            if not href.startswith(("http://", "https://")) or self.workspace is None:
                self._send(400, {"error": "an http(s) file, with a workspace"})
                return
            cur = _DOWNLOADS.get(href)
            if cur and cur.get("state") == "running":
                self._send(200, dict(cur))
                return
            _DOWNLOADS[href] = {"state": "running", "bytes": 0, "total": None, "href": href}
            threading.Thread(target=_download, args=(self.workspace, href, str(body.get("kind") or ""),
                                                     str(body.get("name") or "")), daemon=True).start()
            self._send(202, dict(_DOWNLOADS[href]))
            return

        if route == "pdf":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 120 * 1024 * 1024:
                    self._send(413, {"error": "a PDF over 80 MB is not taken"})
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                import base64
                data = base64.b64decode(body.get("b64") or "")
                url = str(body.get("url") or "")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            if not data.startswith(b"%PDF") or not url:
                self._send(400, {"error": "not a PDF"})
                return
            try:
                t0 = time.time()
                with _foreground(), _WORK_LOCK:
                    got = self.workspace.index_pdf(data, url)
                    got["cids"] = [r[0] for r in self.workspace.store._rows(
                        "MATCH (c:Chunk {url: $u}) RETURN c.cid", {"u": got["url"]})]
                got["ms"] = round((time.time() - t0) * 1000)
                _LAST_WRITE[0] = time.time()
                _profile("pdf", {k: got.get(k) for k in ("url", "pages", "blocks", "chunks", "ms", "pages_without_text")})
                self._send(200, got)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        # A chunk's page form, saved while its elements are on the page
        # (`snapshots.py`, PLUGIN_GOAL 51). Off the capture path: the cell
        # sends them in small batches after the page is stored.
        if route == "snapshots":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            from . import snapshots as _snaps
            try:
                _yield_to_foreground()
                with _WORK_LOCK:
                    got = _snaps.save(self.workspace, body.get("items") or [])
                _profile("snapshots", got)
                self._send(200, got)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        # Refill chunk markdown the graph lost, from the checkpoint (`D-33`).
        # A route for the same reason `/repair_keys` is one: the store is
        # held open by this process.
        if route == "restore_markdown":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                self._send(200, self.workspace.restore_markdown())
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "plant":
            # A live check's planted arm for a rule that runs HERE, in the
            # sidecar's own projection: the check flips the module flag, runs
            # its arm in the plugin, and flips it back. Only the flags named
            # in `_PLANTABLE`; anything else is refused.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            name = str(body.get("name") or "")
            if name not in _PLANTABLE:
                self._send(400, {"error": "not plantable: %s" % name, "plantable": sorted(_PLANTABLE)})
                return
            mod, attr = _PLANTABLE[name]
            module = __import__(mod, fromlist=[attr])
            setattr(module, attr, bool(body.get("on")))
            self._send(200, {"name": name, "on": getattr(module, attr)})
            return

        if route == "maintenance":
            # The plugin, once a minute while the reader is idle in Obsidian:
            # the one signal that says nobody is using the app (see
            # `_compact_due`). Answers what it decided; a due compaction exits
            # 76 for the supervisor after the reply is sent.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            _READER_IDLE[0] = float(body.get("reader_idle_ms") or 0) / 1000.0
            _READER_IDLE[1] = time.time()
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                store_mb = (Path(self.workspace.path) / "graph.kuzu").stat().st_size / 1e6
            except OSError:
                store_mb = 0.0
            base = _compact_base(self.workspace, store_mb) if store_mb else 0.0
            due = _compact_due(store_mb, base, time.time(), 0.0, os.environ.get("VERTISCOPE_SUPERVISED") == "1",
                               _READER_IDLE[0], _LAST_WRITE[0]) if store_mb else False
            self._send(200, {"store_mb": round(store_mb, 1), "base_mb": round(base, 1), "compact": due,
                             "supervised": os.environ.get("VERTISCOPE_SUPERVISED") == "1"})
            if due:
                threading.Thread(target=_maybe_compact, args=(self.workspace, store_mb), daemon=True).start()
            return

        if route == "relink":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                self._send(200, self.workspace.store.relink_pages())
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "place":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                started = time.perf_counter()
                placed = place_into(self.workspace, body.get("cids") or [])
                # **Profiled, because this is now where most placement
                # happens.** The pane's placement queue asks here for chunks
                # a capture could not place yet; before this was recorded,
                # the profile showed zero placements while the queue was
                # placing everything -- and the warmup's own test skipped,
                # unable to see the path doing the work.
                rec = {("place_" + k): v
                       for k, v in (placed.get("timing") or {}).items()}
                rec.update(total=round((time.perf_counter() - started) * 1000, 1),
                           placed=len(placed.get("nodes") or []),
                           unplaced=len(placed.get("unplaced") or []))
                _profile("place", rec)
                self._send(200, placed)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        # An installed package, or this codebase, into the trie as module
        # pages (G-104): `{"name": "<package>"}` or `{"repo": true}`. Gated
        # with `capture`: it writes the workspace and presses nothing.
        # Stale anchors deleted, a batch of chunks a call (G-186; the reader
        # asked for it: "Clean them now"). Gated with `capture`.
        if route == "heal_anchors":
            if not self.capture_allowed or self.workspace is None:
                self._send(403, {"error": "healing is off: start the sidecar with --capture"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:                       # noqa: BLE001
                body = {}
            t0 = time.perf_counter()
            with _WORK_LOCK:
                got = self.workspace.store.heal_anchors(int(body.get("limit") or 200),
                                                        step=lambda _c: _yield_to_foreground())
            _LAST_WRITE[0] = time.time()
            got["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            _profile("heal_anchors", got)
            self._send(200, got)
            return

        # `G-236`: a change as a mutation of the code graph -> a unified diff,
        # compile-checked. Previewed unless `apply`; applied only to this
        # repository's own files (`code://repo/`), never an installed
        # package, and then re-ingested: chunks, CPG and projector follow.
        if route == "cpg_mutate":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            from ..cpg_mutate import MutationError, mutate
            from ..source import source_path_of
            url = str(body.get("url") or "")
            got_path = source_path_of(url)
            if not got_path or not got_path[1].endswith(".py"):
                self._send(400, {"error": "not a code:// python file"})
                return
            root, rel = got_path
            base = Path(__file__).resolve().parents[1]
            path = (base / rel).resolve() if root == "repo" else None
            if path is None or base not in path.parents or not path.exists():
                self._send(400, {"error": "only this repository's files (code://repo/...) are mutated"})
                return
            text = path.read_text(encoding="utf-8")
            try:
                out = mutate(text, list(body.get("mutations") or []), rel)
            except (MutationError, KeyError, SyntaxError) as exc:
                self._send(422, {"error": "%s: %s" % (type(exc).__name__, exc)})
                return
            res = {"url": url, "diff": out["diff"], "changed": out["changed"], "applied_ops": out["applied"], "written": False}
            if body.get("apply") and out["changed"]:
                if not self.capture_allowed or self.workspace is None:
                    self._send(403, {"error": "writing is off (start with --capture)", **res})
                    return
                with _WORK_LOCK:
                    path.write_text(out["text"], encoding="utf-8")
                    self.workspace.index_source(out["text"], rel, root=root)
                    res["cpg"] = getattr(self.workspace, "last_cpg", None)
                _LAST_WRITE[0] = time.time()
                _project_page(self.workspace, url)
                res["written"] = True
            _profile("cpg_mutate", {"url": url, "ops": out["applied"], "written": res["written"]})
            self._send(200, res)
            return

        if route == "package":
            if not self.capture_allowed or self.workspace is None:
                self._send(403, {"error": "package indexing is off",
                                 "why": "start the sidecar with --capture to let it write the workspace"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            from .. import packages as _pk

            def _step(_rel):
                _yield_to_foreground()

            t0 = time.perf_counter()
            if body.get("project"):
                # Queue code pages already indexed (by `root` prefix) into the
                # projector, without indexing again.
                prefix = "code://" + str(body.get("project")).strip("/") + "/"
                urls = [u for u in self.workspace.store.page_urls() if u.startswith(prefix)]
                for u in urls:
                    _project_page(self.workspace, u)
                self._send(200, {"queued_pages": len(urls), "prefix": prefix})
                return
            with _WORK_LOCK:
                if body.get("repo"):
                    base = Path(__file__).resolve().parents[1]
                    got = _pk.index_tree(self.workspace, base, "repo", step=_step,
                                         limit=int(body.get("limit") or 0))
                else:
                    got = _pk.index_package(self.workspace, str(body.get("name") or ""), step=_step,
                                            limit=int(body.get("limit") or 0))
            _LAST_WRITE[0] = time.time()
            # Into the projector, page by page, as a capture's pages go: the
            # module pages reach the 3D view by the stream's own placement.
            prefix = "code://%s/" % got.get("root", "")
            queued = 0
            for u in self.workspace.store.page_urls():
                if u.startswith(prefix):
                    _project_page(self.workspace, u)
                    queued += 1
            got["queued_pages"] = queued
            got["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            _profile("package", {k: v for k, v in got.items() if k != "failed"})
            self._send(200, got)
            return

        if route == "purge":
            # Drop one page, its chunks and its addresses (`store.purge_page`).
            #
            # **This exists so that a live check can clean up after itself.**
            # `S-7` serves a fixture, drives a real interaction in the browser
            # cell and reads the result back out of the trie -- which means it
            # captures a page into the reader's own corpus every time it runs,
            # on a fresh ephemeral port each time. A confirmation harness that
            # grows the corpus it is measuring is an instrument that changes
            # its own denominator, and this file already carries four separate
            # cases of a denominator being the thing that was wrong.
            #
            # Gated with `capture`, not with `enact`: it writes the workspace
            # and presses nothing on any page, which is the same size of
            # permission `capture` is.
            if not self.capture_allowed:
                self._send(403, {
                    "error": "purge is off",
                    "why": "the sidecar holds this workspace read-only. "
                           "Start it with --capture to let it be written.",
                })
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            url = (body or {}).get("url") or ""
            if not url:
                self._send(400, {"error": "no url"})
                return
            try:
                removed = self.workspace.store.purge_page(url)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
                return
            self._send(200, {"url": url, "chunks_removed": removed})
            return

        if route == "capture":
            if not self.capture_allowed:
                # Named, because the alternative is what actually happened:
                # a raw "Cannot execute write operations in a read-only
                # database" from kuzu, which tells a reader about a lock and
                # nothing about a permission they can grant.
                self._send(403, {
                    "error": "capture is off",
                    "why": "the sidecar holds this workspace read-only. "
                           "Start it with --capture to let the browser cell "
                           "scan into it; that takes the store's writer lock "
                           "and excludes other readers.",
                })
                return
            # Only the plugin's browser cell writes the reader's store (`D-39`:
            # two DuckDuckGo queries a terminal probe ran were stored as pages
            # and drawn among the reader's). A probe uses a test store.
            if (self.plugin_captures_only
                    and self.headers.get("X-Vertiscope-Client") != "obsidian-plugin"):
                self._send(403, {
                    "error": "captures come from the plugin's browser cell",
                    "why": "this sidecar writes the reader's store; a probe "
                           "runs against a test store (a sidecar started with "
                           "--allow-probe-captures, or the Verifier's) (D-39)",
                })
                return
            self._post_capture()
            return

        if route not in ("enact", "kernel", "shell"):
            self._send(404, {"error": "no such route", "path": parts.path})
            return

        if route == "kernel":
            self._post_kernel()
            return

        if route == "shell":
            self._post_shell()
            return

        if not self.enact_allowed:
            # Named rather than a bare 403: a caller that cannot tell "off" from
            # "failed" will retry forever, and a reader of the surface deserves
            # to know the difference between refused and unavailable.
            self._send(403, {
                "error": "enact is off",
                "detail": "start the sidecar with --enact to let the vault "
                          "drive the live page"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        from .enact import EnactError, enact, plan
        if body.get("mode") == "plan":
            # A panel gesture on the page in the browser CELL: adjudicated
            # here, carried out by the plugin in the cell. Same flag (above),
            # same 409 for a refusal, and NOTHING is driven by this process.
            try:
                self._send(200, plan(self.workspace,
                                     body.get("address") or "",
                                     body.get("action") or "press",
                                     body.get("text")))
            except EnactError as exc:
                self._send(409, {"error": str(exc), "refused": True})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__,
                                                      exc)})
            return
        try:
            self._send(200, enact(self.workspace,
                                  body.get("address") or "",
                                  body.get("action") or "press",
                                  body.get("text")))
        except EnactError as exc:
            # A refusal is a 409, not a 500: the request was understood and
            # deliberately not carried out, and the surface should say which.
            self._send(409, {"error": str(exc), "refused": True})
        except Exception as exc:                    # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _post_kernel(self) -> None:
        """Run one cell in its note's kernel.

        Body: ``{"note": "<vault path>", "code": "...", "op": "restart"?}``.

        `note` is required and is not defaulted. It is the isolation boundary —
        `NOTEBOOK_PANEL_DESIGN` §4, variables shared within a note and isolated
        across notes — so a missing one would silently put every cell in the
        vault into one shared namespace, which is the failure this design exists
        to avoid and would look like a mysterious name collision rather than a
        missing field.
        """
        if self.kernel_pool is None:
            # Named, not a bare 403: a caller that cannot tell "off" from
            # "failed" retries forever, and the panel should be able to draw the
            # button as unavailable rather than broken.
            self._send(403, {
                "error": "kernel is off",
                "detail": "start the sidecar with --kernel to run cells from "
                          "the vault. It executes arbitrary Python with this "
                          "process's privileges, so it is off by default."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        note = (body.get("note") or "").strip()
        if not note:
            self._send(400, {"error": "missing note",
                             "detail": "the note path is the isolation "
                                       "boundary; without it every cell would "
                                       "share one namespace"})
            return

        if body.get("op") == "restart":
            self._send(200, {"restarted": self.kernel_pool.restart(note),
                             "note": note})
            return

        code = body.get("code")
        if not isinstance(code, str) or not code.strip():
            self._send(400, {"error": "missing code"})
            return

        lang = (body.get("lang") or "python").lower()
        if lang not in ("python", "py", "python3"):
            # Step 3 is python only, and says so rather than running python and
            # pretending it ran bash.
            self._send(400, {
                "error": f"unsupported language {lang!r}",
                "detail": "this kernel runs python; a shell is P-N2's separate "
                          "pane and is not built yet"})
            return

        try:
            self._send(200, self.kernel_pool.run(note, code))
        except Exception as exc:                    # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _post_chunk_preview(self) -> None:
        """Where the chunker would cut this text (`P-N8`).

        A POST because the BODY is the note, and a note is not a query string;
        it carries newlines, and on a long one it is tens of kilobytes.

        **Ungated, and that is not an oversight.** Every other POST here acts on
        the world -- `enact` presses a control in a real browser, `kernel` and
        `shell` run code. This one is a pure function of the text it was handed:
        it writes nothing, reads no workspace, and touches no process. Gating it
        behind `--kernel` would mean a reader could not see why their note
        splits unless they had first enabled code execution, which is a
        permission that has nothing to do with the question.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        text = body.get("text")
        if not isinstance(text, str):
            self._send(400, {"error": "missing text"})
            return
        try:
            from ..vault import chunk_preview
            window = body.get("window")
            self._send(200, {
                "path": body.get("path") or "",
                "chunks": chunk_preview(
                    text, body.get("path") or "untitled.md",
                    vault=(body.get("vault") or "vault"),
                    # The WORKSPACE's window when the caller did not name one,
                    # so a preview cannot disagree with the store about how big
                    # a chunk is -- which is the one way this could mislead.
                    context_window=int(window) if window else getattr(
                        self.workspace, "context_window", None)),
            })
        except Exception as exc:                    # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _post_shell(self) -> None:
        """Run one command in a pane's shell.

        Body: ``{"pane": "<id>", "command": "...", "shell": "pwsh"?, "cwd": ""?,
        "op": "restart"?}``.

        Gated on the KERNEL's flag, deliberately and not by oversight. A second
        flag would imply a distinction that does not exist: a Python kernel can
        already call `subprocess.run`, so a reader who turned that on has shell
        access whether or not a terminal pane exists. A permission that looks
        meaningful and is not is worse than no permission.
        """
        if self.shell_pool is None:
            self._send(403, {
                "error": "shell is off",
                "detail": "start the sidecar with --kernel; the terminal shares "
                          "that gate because a python kernel already grants "
                          "shell access."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        pane = (body.get("pane") or "").strip()
        if not pane:
            # As with the kernel's note: the pane IS the session boundary, and
            # defaulting it would put every terminal in the vault into one
            # shell -- one reader's `cd` moving another reader's prompt.
            self._send(400, {"error": "missing pane",
                             "detail": "the pane id is the session boundary"})
            return

        if body.get("op") == "restart":
            self._send(200, {"restarted": self.shell_pool.restart(pane),
                             "pane": pane})
            return

        command = body.get("command")
        if not isinstance(command, str) or not command.strip():
            self._send(400, {"error": "missing command"})
            return
        try:
            self._send(200, self.shell_pool.run(
                pane, command, shell=(body.get("shell") or ""),
                cwd=(body.get("cwd") or "")))
        except Exception as exc:                    # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _post_capture(self) -> None:
        """Take one drain from the browser cell into the trie (`G-47`).

        The scan migrates from Selenium to the Electron browser the reader is
        watching, and what crosses this boundary is what crossed the Selenium
        one: **a drain payload**, not a serialisation. The sensor maintains
        the fold in the page and emits, per drain, only what changed -- which
        is the O(delta) contract, and the reason this is a SESSION rather than
        a one-shot post.

        The decoder is stateful and has to be. The payload's dictionary and
        shape table are append-only: a drain carries only the entries added
        since the last one, so a decoder that forgot between calls would fail
        to resolve every interned segment from the first drain onward. That
        state lives in `Sensor`, so `Sensor(None, url)` is constructed here as
        a decoder -- it stores the driver and never touches it unless asked to
        boot, and booting is the browser cell's job now.

        `settle` asks for the one complete write from the finished trie. The
        per-drain writes keep the store current while the reader is still on
        the page, but they are deltas and never retire a chunk that
        re-partitioning replaced -- the Selenium path settles at the same
        point, for the same reason.

        Ungated, like `chunk_preview`: it writes the workspace, runs no
        process, and presses nothing on any page.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        url = _document_url((body.get("url") or "").strip())
        if not url:
            self._send(400, {"error": "capture needs a url"})
            return
        if self.workspace is None:
            self._send(503, {"error": "no workspace"})
            return

        from ..sensing import Sensor
        from ..stream import StreamingScan

        sessions = _capture_sessions
        session = sessions.get(url)
        # **The page's sensor started over** -- a reload of the same url
        # injects a new sensor, whose tag dictionary begins again at 0 -- and
        # this session still holds the old one. Decoded against it, every id
        # past the old dictionary read as "?", and addresses like
        # /html/*[name()='?'][1]/... went into the store; one such chunk then
        # claimed the whole page in the overlay's map (G-79, 2026-09-27).
        # The payload says how big its dictionary is; if that is not what this
        # session holds plus what the payload adds, it is a new sensor.
        if session is not None and sensor_restarted(session, body):
            session = None
        if session is None or body.get("restart"):
            session = {
                "sensor": Sensor(None, url),
                "spine": StreamingScan(
                    url, context_window=self.workspace.context_window),
                "passno": 0,
                # Chunks captured but not yet vectorised. Retried on every
                # later drain, so a chunk whose vector arrives while the
                # reader keeps browsing lands in the picture on its own --
                # the pane does not have to remember to ask again, and a
                # chunk cannot be lost between "captured" and "placed".
                "pending": [],
                "born": time.time(),
            }
            # The store's cids for this page as the visit begins (the trie on
            # the DB is the spine): the diff judges ADDED against it.
            try:
                _rows = list(self.workspace.store.chunks(url))
                session["stored"] = {c.cid for c in _rows}
                # Their content, for the cross-visit rename (`_page_diff`).
                session["stored_md"] = {c.cid: _digest(c.md) for c in _rows}
            except Exception:                       # noqa: BLE001
                session["stored"] = set()
                session["stored_md"] = {}
            sessions[url] = session

        # **The SIDECAR started over** -- the other direction. A restart under
        # a page left open meets a sensor that has already sent its dictionary
        # to the process that died, and now sends only additions; decoded
        # against an empty one, the ids land on the wrong segments and
        # plausible garbage reaches the store (/header/tr[2]/b/small/i[88] for
        # a Wikipedia table row, 2026-10-11). The same arithmetic tells: the
        # sensor's dictionary is larger than this session plus this payload.
        # Refused, and the plugin asks its sensor to resend everything
        # (`resync`). Planted: decoded anyway, as before.
        if (not body.get("settle") and not _PLANT_NO_RESYNC[0]
                and sensor_restarted(session, body)):
            sessions.pop(url, None)
            _profile("capture_refused", {"url": url, "why": "dictionary incomplete"})
            self._send(409, {"error": "sensor dictionary incomplete", "resync": True, "url": url})
            return

        started = time.perf_counter()
        try:
            if body.get("settle"):
                spine = session["spine"]
                before = {c.cid for c in self.workspace.store.chunks(url)}
                # **A young, nearly empty trie is not the page** (2026-10-06,
                # measured: a page reloaded in the cell ended its session
                # holding the first fold of the fresh load -- 1 chunk -- and
                # the settle wrote that as the complete page, retiring 30 of
                # johnwick's 31 stored chunks; the next capture re-added 24
                # as new rows, and the view's nodes for the 30 became
                # phantoms). Under 15 s old and rendering under half of what
                # the store holds, the settle writes nothing and retires
                # nothing; a page that truly shrank settles on a later visit.
                truncated = _settle_truncated(session, len(before))
                if truncated:
                    rendered = len(session.get("render") or ())
                    sessions.pop(url, None)
                    sdiff = _record_diff({"kind": "settle", "url": url, "passno": None,
                                          "added": [], "dirty": [], "retired": [], "renamed": {},
                                          "chunks": len(before), "skipped": "young trie: %d rendered of %d stored"
                                          % (rendered, len(before))})
                    self._send(200, {"settled": False, "url": url, "diff": sdiff,
                                     "skipped": sdiff["skipped"]})
                    return
                if spine.trie is not None and len(spine.trie):
                    # The visit kept chunks its last DOM no longer holds: the
                    # settle adds the trie and retires none of them (G-216).
                    union = bool(session.get("kept")) and not _PLANT_RETIRE_IN_SESSION[0]
                    with _WORK_LOCK:
                        self.workspace.ingest(
                            url, spine.trie, title=(body.get("title") or ""), complete=not union)
                    _forget_controls(url)
                # Durability is the checkpoint thread's (`_checkpoint_forever`):
                # on this 32 GB store a checkpoint took 10-19 s, and run here
                # it held the write lock through every settle (2026-10-07).
                _LAST_WRITE[0] = time.time()
                # A settled page is complete: whatever the projector holds
                # for it that the page no longer has is gone.
                _project_page(self.workspace, url)
                stored = list(self.workspace.store.chunks(url))
                sessions.pop(url, None)
                after = {c.cid for c in stored}
                sdiff = _record_diff({"kind": "settle", "url": url, "passno": None,
                                      "added": sorted(after - before), "dirty": [],
                                      "retired": sorted(before - after), "renamed": {},
                                      "chunks": len(after)})
                self._send(200, {
                    "settled": True, "url": url, "diff": sdiff,
                    "addresses": len(spine.trie) if spine.trie else 0,
                    "chunks": len(stored),
                    "ms": round((time.perf_counter() - started) * 1000, 1),
                })
                return

            payload = body.get("payload") or {}
            if not payload:
                self._send(400, {"error": "capture needs a drain payload"})
                return
            passno = int(session["passno"])
            session["passno"] = passno + 1

            # Every phase timed separately (`G-66`, and constraint 4 of
            # CLAUDE.md, which has said so all along for the fold and the
            # projections and was never extended to this path).
            #
            # A capture was one number -- 2.16 seconds -- covering decode,
            # absorb, render and store, and a single number cannot say which
            # of them to fix. Guessing which phase dominates is the mistake
            # this project keeps making; these four fields are what stops it
            # being guessed again.
            phases = {}
            mark = time.perf_counter()

            sense = session["sensor"]._as_pass(payload, 0.0, 0.0, passno)
            phases["decode"] = round((time.perf_counter() - mark) * 1000, 1)
            mark = time.perf_counter()

            spine = session["spine"]
            update = spine.absorb(sense.units, sense.passno,
                                  removed=sense.removed_addresses,
                                  moved=sense.moved_addresses)
            phases["absorb"] = round((time.perf_counter() - mark) * 1000, 1)
            mark = time.perf_counter()

            # `dirty_chunks` is where `render_trie` runs, so this is the
            # markdown projection's cost on the delta -- named as `render`
            # because that is what it is, whatever the method is called.
            dirty = spine.dirty_chunks(update)
            phases["render"] = round((time.perf_counter() - mark) * 1000, 1)
            # What KIND of change dirtied them: a page that inserts above the
            # reader shifts every address below, and a pure move rewrites the
            # chunk (2026-10-11: ScienceDirect re-dirtied 195-213 of 212 chunks
            # on every capture, 7-60 s of store writes each).
            try:
                dl = update.delta
                phases["delta"] = {"added": len(dl.added), "changed": len(dl.changed),
                                   "removed": len(dl.removed), "moved": len(dl.moved)}
            except Exception:                       # noqa: BLE001
                pass
            mark = time.perf_counter()
            diff = _page_diff(session, url, passno, update.all_chunks, dirty)
            retired = list(diff["retired"]) if diff and RETIRE == "delete" else []
            if diff and not _PLANT_RETIRE_IN_SESSION[0]:
                renamed_old = set((diff.get("renamed") or {}).keys())
                kept = [c for c in retired if c not in renamed_old]
                if kept:
                    session.setdefault("kept", set()).update(kept)
                retired = [c for c in retired if c in renamed_old]
                diff["retired"] = list(retired)
                diff["kept"] = kept
            phases["diff"] = round((time.perf_counter() - mark) * 1000, 1)
            mark = time.perf_counter()

            # Only what the store does not already hold, written. A new capture
            # session (a reload, a sensor restart) re-sends every chunk of a page
            # as "added", and the store re-wrote identical chunks -- every anchor
            # deleted and recreated: 52 chunks, 2.5 s on GitHub; 212 of 212 on a
            # ScienceDirect article, 7-60 s a capture (2026-10-11). Same cid
            # (the hash of its address span) and same markdown is the same chunk.
            # They stay in `dirty` for the reply: panels and graph still hear.
            write = dirty
            if dirty and not _PLANT_REWRITE_SAME[0]:
                try:
                    if _PLANT_SKIP_BY_MD[0] or not hasattr(self.workspace.store, "chunk_sigs"):
                        held = self.workspace.store.chunk_mds([c.cid for c in dirty])
                        write = [c for c in dirty if held.get(c.cid) != c.markdown]
                    else:
                        # The same markdown is not the same chunk when its
                        # ADDRESSES moved (2026-10-12): skipped, its anchors
                        # stayed one sibling off on arXiv for every capture.
                        from vertiscope.graphstore import anchor_sig
                        sigs = self.workspace.store.chunk_sigs([c.cid for c in dirty])
                        lines_of = lambda c: sum(1 for ln in c.lines if ln.address is not None)
                        write = [c for c in dirty
                                 if sigs.get(c.cid) != (c.markdown, anchor_sig(c), lines_of(c))]
                    phases["unchanged_skipped"] = len(dirty) - len(write)
                except Exception:                   # noqa: BLE001
                    write = dirty
            if write or retired:
                # **The wait is not the work.** `_WORK_LOCK` is shared with
                # the embed worker (per 64-chunk batch) and aggregation (per
                # page), so a drain arriving mid-batch waits for someone
                # else's job -- and that wait was inside `store`, which then
                # read as a slow database.
                asked = time.perf_counter()
                with _foreground(), _WORK_LOCK:
                    phases["lock_wait"] = round(
                        (time.perf_counter() - asked) * 1000, 1)
                    # A code block's text as the page holds it -- the
                    # trie's value, newlines kept -- for the code graph
                    # (G-233); the markdown line has it on one line.
                    def _held(addr, _t=getattr(spine, "trie", None)):
                        n = _t.find(addr) if _t is not None else None
                        return n.value if n is not None else None
                    _written, counts = self.workspace.ingest_chunks(
                        url, write, complete=False, removed=retired,
                        title=(body.get("title") or ""), raw_values=_held)
                # The store's own breakdown, carried up. `store` was 96% of a
                # capture and one number cannot say which statement it is.
                if isinstance(counts, dict):
                    phases.update({k: v for k, v in counts.items()
                                   if str(k).startswith("ms_") or str(k).startswith("anchors_")})
                    # A size, not a time, but it is what makes `ms_mirror`
                    # readable: the cost of the checkpoint is proportional
                    # to how much of the page it rewrote.
                    if "mirror_rows_written" in counts:
                        phases["mirror_rows"] = counts["mirror_rows_written"]
                # There are chunks without vectors now. The worker embeds
                # them; this request does not wait for it -- but the page the
                # reader is ON goes to the front of the queue (2026-10-07: a
                # captured chunk waited p50 1.0 s / p90 12 s for its vector
                # behind other pages' backlog, end to end p90 4.5 s, while the
                # fold itself took 1.7 ms). Newest first: what is on screen now.
                try:
                    self.workspace.vectors.prioritize([c.cid for c in dirty])
                except Exception:                   # noqa: BLE001
                    pass
                _EMBED_WANTED.set()
                _LAST_WRITE[0] = time.time()
                _forget_controls(url)
                # And the page's merge groups are now out of date (`G-65`).
                # Each drain pushes the deadline out, so this lands when the
                # reader pauses rather than while they are still scrolling.
                _AGGREGATE_AFTER[url] = time.monotonic() + _AGGREGATE_DEBOUNCE
            phases["store"] = round((time.perf_counter() - mark) * 1000, 1)
            # Named, not counted. The pane asks `place` about exactly these,
            # and a count would leave it re-fetching the whole layout to find
            # out which three nodes moved.
            dirty_cids = [c.cid for c in dirty]
            # And the elements each one draws, for the browser's overlay map
            # (DESIGN_VII §3): the delta that keeps it current, already in
            # memory, so the overlay never has to ask the store.
            map_delta = {c.cid: [line.address.xpath for line in c.lines]
                         for c in dirty}
            # Rewritten chunks keep their cid only if their span did; either
            # way the projector must look again. One without a vector yet is
            # dropped from its queue and comes back through the embedder.
            # Retired ones too: the projector finds them gone from the store
            # and logs them `gone`, which is how the pane removes their nodes.
            _project(dirty_cids + retired)
            if diff is not None:
                diff = _record_diff(diff)
        except Exception as exc:                    # noqa: BLE001
            # Named rather than swallowed. A capture that fails quietly is
            # indistinguishable from a page with nothing in it, and that
            # confusion has cost this project whole measurement runs.
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        reply = {
            "url": url,
            "passno": passno,
            "addresses": sense.addresses,
            "lines": sense.lines,
            "changed": sense.changed,
            "dirty": len(dirty),
            "dirty_cids": dirty_cids,
            "map_delta": map_delta,
            # The central diff: every view applies these lists, none infers them.
            "diff": diff,
            "wire_bytes": sense.wire_bytes,
            "phases": phases,
        }

        # Placed HERE, in the same reply, when the caller asks.
        #
        # The browser cell wants three things per drain and they are one
        # question: fold the page, store what changed, and say where the
        # changed chunks go. Asking them separately cost a round trip whose
        # only content was a list of cids the server had just computed and
        # was about to be handed back -- and each trip is a fetch from a
        # renderer, a thread from the pool, and a kuzu read that has to
        # re-find the same chunks.
        #
        # `POST /place` stays, because "where would these go" is a real
        # question on its own -- a pane that already has cids from somewhere
        # else has no drain to attach them to.
        place_mark = time.perf_counter()
        if body.get("place"):
            # Everything this drain touched, PLUS everything an earlier drain
            # could not place yet. A chunk embedded in the background while
            # the reader scrolled belongs on screen now, and this is the only
            # moment anyone asks.
            wanted = list(dict.fromkeys(
                list(session.get("pending") or []) + dirty_cids))
            try:
                placed = place_into(self.workspace, wanted) if wanted else {}
                reply.update(placed)
                # Placement's own parts, into the profile. `place` was one
                # number and read 532 ms for ONE chunk after the warmup had
                # removed the transform's cold cost -- so something else was
                # in there, and a single figure could not say what.
                for k, v in (placed.get("timing") or {}).items():
                    phases["place_" + k] = v
                session["pending"] = list(placed.get("unplaced") or [])
            except Exception as exc:                # noqa: BLE001
                # Named and non-fatal. The capture succeeded and is stored;
                # failing to say where the chunks go must not read to the
                # caller as failing to capture them.
                reply["place_error"] = "%s: %s" % (type(exc).__name__, exc)

        # What stage two currently makes of this page. It moves on its own,
        # after the reader pauses, so a pane watching this number is watching
        # live aggregation happen (`G-65`).
        try:
            reply["groups"] = self.workspace.store.group_count(url)
        except Exception:                           # noqa: BLE001
            pass
        phases["place"] = round((time.perf_counter() - place_mark) * 1000, 1)
        reply["ms"] = round((time.perf_counter() - started) * 1000, 1)
        # Carried back so the pane can correlate this reply with the drain
        # that produced it; the sidecar has no other way to know which one.
        if body.get("trace"):
            reply["trace"] = body.get("trace")
        _profile("capture", dict(phases, total=reply["ms"],
                                 dirty=len(dirty), url=url,
                                 placed=len(reply.get("nodes") or []),
                                 unplaced=len(reply.get("unplaced") or []),
                                 trace=body.get("trace") or ""))
        self._send(200, reply)

    def _layout_count(self) -> int:
        """Stored fits, or 0 if the store cannot answer."""
        try:
            rows = self.workspace.store._rows(
                "MATCH (l:Layout) RETURN count(l)")
            return int(rows[0][0]) if rows and rows[0] else 0
        except Exception:                           # noqa: BLE001
            return 0

    def do_GET(self) -> None:                       # noqa: N802 (stdlib name)
        _LAST_REQUEST[0] = time.time()
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.strip("/").split("/") if s]

        if not segments or segments[0] == "health":
            # **Liveness must not wait on the store** (2026-10-07). These are
            # ~10 full-table counts on a 32 GB store, behind the same lock a
            # capture's write holds for up to 8 s: `confirm.mjs` waited 10 s,
            # got nothing, and stopped its run calling the sidecar dead while
            # it was storing a page. A fresh answer is cached for 30 s; while
            # the store is busy the last one is served, marked `busy`.
            now = time.time()
            # A token of the server's own: `id()` is reused once a server is
            # collected, and two test servers shared a cache that way.
            hkey = getattr(self.server, "_vertiscope_health_key", None)
            if hkey is None:
                hkey = self.server._vertiscope_health_key = object()
            cached = _HEALTH_CACHE.get("body") if _HEALTH_CACHE.get("key") is hkey else None
            if cached is not None and now - _HEALTH_CACHE.get("at", 0) < 30.0:
                self._send(200, dict(cached, cached_s=round(now - _HEALTH_CACHE["at"], 1)))
                return
            lock = getattr(self.workspace.store, "_db_lock", None)
            if lock is not None and not lock.acquire(timeout=0.5):
                self._send(200, dict(cached or {"ok": True}, busy=True,
                                     cached_s=round(now - _HEALTH_CACHE.get("at", now), 1)))
                return
            if lock is not None:
                lock.release()
            # `enact` is advertised so the plugin can draw a read-only
            # surface as read-only rather than offering a button that 403s.
            # **Is the trie actually ANCHORED?**
            #
            # Addresses and anchors are different things and only one of them
            # was ever counted. A capture reported 320 addresses written for
            # a page while every line of every chunk on it came back with
            # `key: ""`, because the Anchors edges that bind a LINE to an
            # ADDRESS were not there. The address key is the identity
            # everything downstream is keyed on -- the retrieval gesture, the
            # affordance list, the click that names an element in the real
            # page -- so a store full of addresses and empty of anchors is a
            # store whose chunks cannot be acted on at all. Counting both,
            # cheaply, is what makes that visible instead of silent.
            def _one(q):
                try:
                    return self.workspace.store._rows(q)[0][0]
                except Exception:               # noqa: BLE001
                    return None
            self._send(200, _cache_health(key=hkey, body={"ok": True,
                             "pages": len(self.workspace.pages()),
                             "addresses": _one(
                                 "MATCH (a:Address) RETURN count(a)"),
                             "anchors": _one(
                                 "MATCH ()-[r:Anchors]->() RETURN count(r)"),
                             # **An anchor whose address will not parse is
                             # worse than a missing one**, because the line
                             # still draws and simply has no handle on the
                             # page -- silently, since `addresses_of` skips
                             # it. Reported so the two causes of a keyless
                             # line can be told apart without guessing.
                             "anchors_blank_key": _one(
                                 "MATCH ()-[r:Anchors]->(a:Address) "
                                 "WHERE a.akey IS NULL OR a.akey = '' "
                                 "RETURN count(r)"),
                             "addresses_blank_key": _one(
                                 "MATCH (a:Address) "
                                 "WHERE a.akey IS NULL OR a.akey = '' "
                                 "RETURN count(a)"),
                             # The edge sets, because "the trie is drawn"
                             # is a claim about these and nothing else was
                             # counting them. A projector showing 89 of 144
                             # nodes isolated is either a layout that does
                             # not ask or a store that does not hold them,
                             # and only these two numbers tell them apart.
                             # How much of the corpus can show a picture at
                             # all. A branch or page node carries an image only
                             # if its markdown contains one, so this is the
                             # ceiling on what the projector can billboard --
                             # and it was never counted, so "a lot of missing
                             # images" could not be told apart from "there are
                             # not many images".
                             "chunks_with_image": _one(
                                 "MATCH (c:Chunk) WHERE c.md CONTAINS '![' "
                                 "RETURN count(c)"),
                             "chunks_total": _one(
                                 "MATCH (c:Chunk) RETURN count(c)"),
                             "pages_with_image": _one(
                                 "MATCH (c:Chunk) WHERE c.md CONTAINS '![' "
                                 "RETURN count(DISTINCT c.url)"),
                             # A chunk with text and no vector cannot be
                             # placed, and a page none of whose chunks has one
                             # is missing from the fit. Counted because the
                             # layout dropped from 112 page nodes to 95 with
                             # no other sign anything was wrong.
                             # The defect that emptied 80.6% of the corpus's
                             # markdown with no error anywhere. Counted so the
                             # app can show it -- a store that silently lost
                             # its content is the one state every other
                             # number on the profile pane depends on.
                             "chunks_empty_md": _one(
                                 "MATCH (c:Chunk) WHERE c.md IS NULL OR "
                                 "size(c.md) = 0 RETURN count(c)"),
                             "chunks_without_vector": _one(
                                 "MATCH (c:Chunk) WHERE size(c.md) > 0 AND "
                                 "c.embedding IS NULL RETURN count(c)"),
                             "pages_without_any_vector": _one(
                                 "MATCH (p:Page) WHERE NOT EXISTS { "
                                 "MATCH (p)-[:HasChunk]->(c:Chunk) "
                                 "WHERE c.embedding IS NOT NULL } "
                                 "RETURN count(p)"),
                             "image_addresses": _one(
                                 "MATCH (a:Address) WHERE a.tag = 'image' "
                                 "RETURN count(a)"),
                             "contains_edges": _one(
                                 "MATCH (:Chunk)-[r:Contains]->(:Chunk) "
                                 "RETURN count(r)"),
                             "linksto_edges": _one(
                                 "MATCH (:Chunk)-[r:LinksTo]->(:Page) "
                                 "RETURN count(r)"),
                             "linksto_between_stored_pages": _one(
                                 "MATCH (c:Chunk)-[r:LinksTo]->(p:Page) "
                                 "WHERE c.url <> p.url RETURN count(r)"),
                             **_lexical_coverage(self.workspace),
                             "unreadable_addresses":
                                 __import__("vertiscope.graphstore",
                                            fromlist=["GraphStore"])
                                 .GraphStore.unreadable_addresses,
                             "enact": bool(self.enact_allowed),
                             "capture": bool(self.capture_allowed),
                             # Advertised so the panel can draw a run button as
                             # disabled rather than offering one that 403s --
                             # the same reason `enact` is advertised.
                             "kernel": self.kernel_pool is not None,
                             # `G-12`: how many fits the store is holding.
                             # Advertised for the same reason `enact` and
                             # `kernel` are -- a feature nothing can observe
                             # is a feature nobody can confirm, and this one
                             # is invisible by design when it works.
                             "layouts": self._layout_count()}))
            return

        if segments[0] == "snapshot" and len(segments) == 2:
            from . import snapshots as _snaps
            doc = _snaps.load(self.workspace, segments[1]) if self.workspace is not None else None
            if doc is None:
                self._send(404, {"error": "no saved page form", "cid": segments[1]})
            else:
                # Pictures the sidecar holds are drawn from its copy: the form
                # renders with the connection down ("Even media", 2026-10-10).
                base = "http://%s" % (self.headers.get("Host") or "127.0.0.1")
                self._send(200, _snaps.localize(self.workspace, doc, base))
            return

        # The page for when there is no connection (`G-59`..`G-62`): what
        # there is for a url, the page as the cell presented it, and the page
        # rebuilt from the scan trace alone.
        if segments[0] == "offline" and len(segments) <= 2:
            from . import offline as _off
            url = (parse_qs(urlsplit(self.path).query).get("url") or [""])[0]
            if self.workspace is None or not url:
                self._send(400, {"error": "offline needs ?url="})
                return
            which = segments[1] if len(segments) == 2 else ""
            if which == "saved":
                data = _off.load_page(self.workspace, url)
                if data is None:
                    self._send(404, {"error": "no saved page", "url": url})
                else:
                    self._send_bytes(200, data, "multipart/related", cache=False)
                return
            if which == "infilled":
                got = _off.infill(self.workspace, url)
                if got is None:
                    self._send(404, {"error": "no saved page", "url": url})
                else:
                    _profile("offline_infilled", {k: v for k, v in got.items() if k != "mhtml"})
                    self._send_bytes(200, got["mhtml"], "multipart/related", cache=False)
                return
            if which == "traced":
                got = _off.reconstruct(self.workspace, url)
                _profile("offline_traced", {k: v for k, v in got.items() if k != "html"})
                self._send_bytes(200, got["html"].encode("utf-8"), "text/html; charset=utf-8", cache=False)
                return
            self._send(200, _off.page_info(self.workspace, url))
            return

        if segments[0] == "media" and len(segments) == 2:
            from . import snapshots as _snaps
            got = _snaps.load_media(self.workspace, segments[1]) if self.workspace is not None else None
            if got is None:
                self._send(404, {"error": "no saved media"})
            else:
                self._send_bytes(200, got[0], got[1])
            return

        if segments[0] == "local_quality":
            from .projector import projector as _get_projector
            proj = _get_projector()
            url = (parse_qs(parts.query).get("url") or [""])[0]
            if proj is None or not hasattr(proj, "local_quality"):
                self._send(503, {"error": "no page projector"})
            elif url:
                self._send(200, proj.local_quality(url))
            else:
                with proj.lock:
                    urls = sorted(proj.local, key=lambda u: -len(proj.local[u]["cids"]))[:12]
                self._send(200, {"pages": [proj.local_quality(u) for u in urls]})
            return

        if segments[0] == "snapshot_coverage":
            from . import snapshots as _snaps
            url = (parse_qs(parts.query).get("url") or [""])[0]
            self._send(200, _snaps.coverage(self.workspace, url) if url and self.workspace is not None
                       else {"error": "no url"})
            return

        if segments[0] == "chunk" and len(segments) == 2:
            payload = chunk_payload(self.workspace, segments[1])
            if payload is None:
                self._send(404, {"error": "no such chunk", "cid": segments[1]})
            else:
                # Both forms, from one payload, in one response.
                #
                # Two round trips would let the surface hold a markdown form
                # and an HTML form fetched at different moments, which is two
                # renderings of possibly two states. They are one
                # distillation; they travel together.
                _t = time.perf_counter()
                payload["html"] = render_lines(payload["lines"],
                                               base=payload.get("url", ""))
                ms = dict(payload.get("_ms") or {})
                ms["html"] = round((time.perf_counter() - _t) * 1000, 1)
                payload["_ms"] = ms
                _profile("chunk_route", ms)
                self._send(200, payload)
            return

        if segments[0] == "resolve":
            # An address on a live page -> the chunk that draws it (`G-39`).
            #
            # **Walking UP, and that is the whole difficulty.** The element
            # under a reader's cursor is almost never a chunk root -- it is a
            # span inside a paragraph inside a section, and only one of those
            # ancestors is a thing the trie holds. So the exact xpath is
            # tried, then each ancestor in turn, and the FIRST hit wins:
            # the nearest chunk containing what was pointed at, which is what
            # "this thing here" means to the person pointing.
            query = parse_qs(parts.query)
            xpath = (query.get("xpath") or [""])[0]
            url = (query.get("url") or [""])[0]
            if not xpath:
                self._send(400, {"error": "no xpath"})
                return
            #: A PREFIX match, not an equality one, and that is not an
            #: optimisation -- it is what the data requires. Chunks anchor to
            #: TEXT nodes: the element `.../ul/li/a` has no anchor and
            #: `.../ul/li/a/text()[1]` does. An equality test on what the
            #: cursor is over therefore finds nothing on almost every page.
            #:
            #: (`addresses_at` is the wrong instrument here for a second
            #: reason: it returns `(address, VALUE)`, not `(address, aid)`,
            #: so feeding its second element to `chunk_for_address` hands it
            #: an href and gets None every time.)
            steps = [s for s in xpath.split("/") if s]
            found = None
            walked = 0
            tried = []
            while steps and found is None:
                candidate = "/" + "/".join(steps)
                tried.append(candidate)
                rows = self.workspace.store._rows(
                    "MATCH (c:Chunk)-[:Anchors]->(a:Address) "
                    "WHERE c.url = $u AND (a.xpath = $x "
                    "OR starts_with(a.xpath, $p)) "
                    "RETURN c.cid LIMIT 1",
                    {"u": url, "x": candidate, "p": candidate + "/"})
                if rows and rows[0] and rows[0][0]:
                    chunk = self.workspace.store.chunk(rows[0][0])
                    if chunk is not None:
                        found = (candidate, chunk)
                if found is None:
                    steps.pop()
                    walked += 1
            if found is None:
                # Say what was tried. A bare "not found" over a walk of
                # seven candidates is not a diagnosis.
                self._send(404, {"error": "no chunk draws that address",
                                 "xpath": xpath, "url": url,
                                 "tried": tried})
                return
            at, chunk = found
            payload = chunk_payload(self.workspace, chunk.cid) or {}
            payload["matched_xpath"] = at
            #: How far up the document the answer was found. 0 means the
            #: reader pointed straight at a chunk root; a large number means
            #: they pointed at something deep inside one, and both are
            #: ordinary.
            payload["ancestors_walked"] = walked
            payload["asked_xpath"] = xpath
            self._send(200, payload)
            return

        if segments[0] == "sensor":
            # The browser cell runs the SAME sensor the Selenium path runs,
            # read from the same file at request time. Bundling a copy into
            # the plugin would create a second sensor that drifts from the
            # first, and every capture comparison after that would be
            # measuring the drift instead of the page.
            from .. import sensing
            try:
                source = sensing._JS.read_text(encoding="utf-8")
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "sensor unreadable: %s" % exc})
                return
            self._send(200, {"source": source})
            return

        if segments[0] == "pages":
            # Every page url the store holds, straight from the Page table.
            #
            # **Not the same question as /layout.** That one is a cached FIT,
            # keyed on chunk count and shared across requests so the 3D view
            # does not refit on every open -- it answered 98 nodes while the
            # store held 119 pages, which is correct for a fit and useless
            # for "what is in here". Cleanup after a live check needs the
            # second question, and asking the first was how 20 fixture pages
            # went unnoticed.
            #
            # Read-only, like every other GET here. `?contains=` filters by
            # substring, which is what a caller tidying up after itself has.
            query = parse_qs(parts.query)
            needle = (query.get("contains") or [""])[0]
            rows = self.workspace.store._rows(
                "MATCH (p:Page) RETURN p.url ORDER BY p.url")
            urls = [r[0] for r in rows if r and r[0]]
            if needle:
                urls = [u for u in urls if needle in u]
            self._send(200, {"urls": urls, "n": len(urls)})
            return

        # The state of one page's chunks, straight from the store.
        #
        # Every other way of asking went through `/search`, which only
        # returns chunks with text to match -- so a page whose chunks had
        # EMPTY markdown was invisible to the very sampler used to look for
        # empty markdown. 11,542 of 14,313 chunks were in that state and the
        # search-based probes reported nothing wrong.
        # The sidecar's half of the pipeline profile, from its own clock.
        # `?reset=1` empties the rings so a run measures only itself.
        if segments[0] == "search_pages":
            # Tier 1 of a tiered search (G-210): the url nodes nearest the
            # query; tier 2 is `/search?url=` per page, asked by the plugin.
            params = parse_qs(parts.query)
            query = (params.get("q") or [""])[0]
            try:
                k = max(1, min(int((params.get("k") or ["12"])[0]), 200))
            except ValueError:
                k = 12
            t0 = time.perf_counter()
            index = getattr(self.workspace, "index", None)
            # Pages ranked by what they HOLD for the query (their best fused
            # chunk score, the ranking tier 2 runs) and the corpus-wide match
            # count -- the k/n fields' bound (PLUGIN_GOAL 154) -- in one pass,
            # no chunk read. `centroid=1` (planted): the semantic centroids,
            # which chose pages with nothing tier 2 lets through.
            matching = None
            pages = []
            counts = {}
            with _foreground():
                pages, matching, counts = _search_pages(index, query, k, params)
            self._send(200, {"query": query, "pages": [{"url": u, "score": round(sc, 5), "n": counts.get(u)} for u, sc in pages],
                             "matching": matching,
                             "ms": round((time.perf_counter() - t0) * 1000, 1)})
            return

        if segments[0] == "checkpointing":
            # Never the store, never the work lock: answerable mid-checkpoint.
            self._send(200, {"checkpointing": bool(_CHECKPOINTING[0]),
                             "since_write_s": round(time.time() - _LAST_WRITE[0], 1)})
            return

        if segments[0] == "profile":
            query = parse_qs(parts.query)
            if (query.get("reset") or [""])[0]:
                # **Not the warmup.** It happens once per process, at startup,
                # and a run reset is about the run. Clearing it made the
                # warmup look as though it had never run -- which is what the
                # test for it reported, about a warmup that had.
                kept = {k: v for k, v in _PROFILE.items()
                        if k in ("warmup", "projector_fit")}
                _PROFILE.clear()
                _PROFILE.update(kept)
                self._send(200, {"reset": True, "kept": sorted(kept)})
                return
            got = {k: list(v) for k, v in _PROFILE.items()}
            # The query index's rebuilds, timed where they happen.
            got["index_build"] = list(getattr(self.workspace, "index_builds", []) or [])
            self._send(200, got)
            return

        # Where ONE page is in the pipeline, for the browser cell's overlay.
        #
        # The chain a reader cares about for the page in front of them:
        # captured -> embedded -> placed, how each chunk sits against the
        # context window, and how close the fit is to its next refit. Asked
        # about every second while the overlay is open, so the token count --
        # the only part that costs anything -- is memoised on the page's
        # chunk set.
        # The chunk projector: the fit every position in the graph comes
        # from, and the stream of what it has placed since a given point.
        if segments[0] == "projector":
            from .projector import projector as _get
            proj = _get()
            if proj is None:
                self._send(503, {"error": "no projector in this process"})
                return
            query = parse_qs(parts.query)
            if len(segments) > 1 and segments[1] == "delta":
                since = int((query.get("since") or ["0"])[0] or 0)
                epoch = int((query.get("epoch") or ["-1"])[0] or -1)
                self._send(200, proj.delta(since, epoch))
                return
            url = (query.get("url") or [""])[0]
            out = proj.status(self.workspace, url)
            if (query.get("quality") or [""])[0]:
                out["neighbourhoods"] = proj.neighbourhoods_kept()
            if (query.get("drawable") or [""])[0]:
                # The denominator for "every drawable chunk is projected",
                # NOW -- not at the fit, which a merge or a retirement since
                # has already made stale. The same read the fit uses.
                with _WORK_LOCK:
                    now = {c for c, _u, _v in self.workspace.store.lead_vectors()}
                with proj.lock:
                    held = set(proj.pos)
                # One snapshot for both sides: `projected` above was read
                # before the store, and a drain in flight between them made
                # 14,382 vs 14,374 out of two equal sets.
                out["projected"] = len(held)
                out["drawable_now"] = len(now)
                out["drawable_unprojected"] = len(now - held)
                out["projected_not_drawable"] = len(held - now)
            self._send(200, out)
            return

        # A page's whole patricia TREE (Addendum VII): every drawable chunk
        # on the tree of its DOM, branches only where the DOM branches.
        # The page's element -> chunk map, for the browser cell's overlay
        # (DESIGN_VII §3): each markdown line's own address and the 256-token
        # chunk that draws it, in one query. The overlay then resolves hovers
        # in memory instead of asking the store per element.
        if segments[0] == "live_render":
            # The chunks the LIVE capture currently renders for a page -- the
            # session's own last full render, read-only -- so what a capture
            # makes of a page can be compared with what the same HTML makes
            # offline. The Suffix tree definition rendered as one chunk from
            # the page's HTML and as three from the live capture, and nothing
            # showed the live side's partition.
            query = parse_qs(parts.query)
            url = (query.get("url") or [""])[0]
            needle = (query.get("contains") or [""])[0]
            session = _capture_sessions.get(url)
            spine = session and session.get("spine")
            last = spine.updates[-1] if spine is not None and getattr(spine, "updates", None) else None
            chunks = getattr(last, "all_chunks", None) or []
            from .. import tokens as _tokens
            # `keys=1`: each line with its address and the value the LIVE trie
            # holds there (2026-10-12, G-186) -- whether a wrong pairing is
            # the trie's (values entered under the wrong address) or the
            # render's (right trie, lines paired wrongly). Read-only.
            want_keys = (query.get("keys") or [""])[0] == "1"
            held = {}
            if want_keys and spine is not None and getattr(spine, "trie", None) is not None:
                try:
                    for leaf in spine.trie.leaves():
                        if leaf.address is not None:
                            held[leaf.address.key()] = str(leaf.value)
                except Exception:                   # noqa: BLE001
                    held = {}
            out = []
            for c in chunks:
                md_text = c.markdown
                if needle and needle not in md_text:
                    continue
                row = {"xpath": c.xpath, "part": getattr(c, "part", 0),
                       "tokens": _tokens.budget(md_text), "lines": len(c.lines),
                       "head": md_text[:240]}
                if want_keys:
                    row["pairs"] = [[(ln.text or "")[:80],
                                     ln.address.key() if ln.address is not None else "",
                                     held.get(ln.address.key(), None) if ln.address is not None else None]
                                    for ln in c.lines]
                out.append(row)
            self._send(200, {"url": url, "session": session is not None,
                             "chunks_total": len(chunks), "chunks": out[:200]})
            return

        if segments[0] == "diffs":
            # Every diff since `since`, oldest first: the one list every view
            # applies (2026-10-04, the central diff).
            q = parse_qs(parts.query)
            since = int((q.get("since") or ["0"])[0] or 0)
            want = (q.get("url") or [""])[0]
            with _DIFF_LOCK:
                rows = [d for d in _DIFFS if d["seq"] > since and (not want or d["url"] == want)]
                last = _DIFF_SEQ[0]
            self._send(200, {"seq": last, "diffs": rows[-500:], "retire": RETIRE})
            return

        if segments[0] == "page_map":
            url = (parse_qs(parts.query).get("url") or [""])[0]
            if not url:
                self._send(400, {"error": "no url"})
                return
            # The reader just landed: warm this page's controls now, off the
            # request, so the first panel does not pay the read (119-382 ms).
            ws = self.workspace
            def _warm():
                try:
                    _page_controls(ws, url)
                except Exception:                   # noqa: BLE001
                    pass
            threading.Thread(target=_warm, name="vertiscope-warm-controls", daemon=True).start()
            _t0 = time.perf_counter()
            rows = self.workspace.store._rows(
                "MATCH (c:Chunk)-[:Anchors]->(a:Address) WHERE c.url = $u "
                "RETURN c.cid, a.xpath", {"u": url})
            chunks: Dict[str, List[str]] = {}
            for cid, xpath in rows:
                if cid and xpath:
                    chunks.setdefault(cid, []).append(xpath)
            # **And where the projector already has them** (S-1). Landing on
            # a stored page used to draw nothing for 3-4 s: its chunks came
            # through the placement queue, behind the page's first capture
            # and the store lock, though the projector held every position
            # in memory. Served here, in the same call as the map, so the
            # pane draws the page's projected chunks -- and its page node,
            # which the page view could lack (S-8) -- the moment it lands.
            nodes, page_node = [], None
            from .projector import projector as _get_projector
            proj = _get_projector()
            if proj is not None and getattr(proj, "projection", None) is not None and chunks:
                from .layout import _first_image, _title
                meta = self.workspace.store._rows(
                    "MATCH (c:Chunk) WHERE c.url = $u RETURN c.cid, c.md, c.chars, "
                    "c.dup_of, c.dup_n, c.group_of, c.group_n", {"u": url})
                with proj.lock:
                    pos = {m[0]: proj.pos.get(m[0]) for m in meta}
                    hsv = {m[0]: proj.hsv.get(m[0]) for m in meta}
                    page_at = proj.page_pos.get(url)
                    page_hsv = proj.page_hsv.get(url)
                for cid, md_text, chars, dup_of, dup_n, group_of, group_n in meta:
                    if dup_of or (group_of and group_of != cid):
                        continue
                    at = pos.get(cid)
                    if at is None:
                        continue
                    node = {"cid": cid, "url": url, "title": _title(md_text or ""),
                            "rank": 0.0, "chars": chars or 0,
                            "tokens": 0, "copies": dup_n or 1, "members": group_n or 1,
                            "val": float(max(1.0, max(group_n or 1, 1) ** 0.5)),
                            "level": "chunk", "pos": [float(v) for v in at[:3]],
                            "placed": True, "source": "projector"}
                    if hsv.get(cid):
                        node["hsv"] = hsv[cid]
                    pic = _first_image(md_text or "", url)
                    if pic is not None:
                        node["image"] = pic
                    nodes.append(node)
                if page_at is not None:
                    page_node = {"cid": "page:" + url, "url": url, "title": url,
                                 "level": "page", "rank": 0.0, "chars": 0, "tokens": 0,
                                 "copies": 1, "members": len(meta),
                                 "val": float(max(1.0, max(len(meta), 1) ** 0.5)),
                                 "pos": [float(v) for v in page_at[:3]],
                                 "source": "projector"}
                    if page_hsv:
                        page_node["hsv"] = page_hsv
            ms = round((time.perf_counter() - _t0) * 1000, 1)
            _profile("page_map", {"url": url[-60:], "chunks": len(chunks),
                                  "addresses": len(rows), "nodes": len(nodes), "ms": ms})
            self._send(200, {"url": url, "chunks": chunks, "ms": ms,
                             "nodes": nodes + ([page_node] if page_node else [])})
            return

        if segments[0] == "page_tree":
            from .layout import page_tree
            from .projector import projector as _get_projector
            url = (parse_qs(parts.query).get("url") or [""])[0]
            if not url:
                self._send(400, {"error": "no url"})
                return
            _t0 = time.perf_counter()
            got = page_tree(self.workspace, url, _get_projector())
            got["ms"] = round((time.perf_counter() - _t0) * 1000, 1)
            _profile("tree", {"url": url[-60:], "nodes": len(got.get("nodes") or []),
                              "ms": got["ms"]})
            self._send(200, got)
            return

        # `G-235`: a code file's property graph (AST, CFG, DFG, CALLS,
        # INHERITS), by the same addresses as its chunks; or the totals.
        if segments[0] in ("models", "model_job"):
            # The installed model roles and their types (G-262), and a model
            # job's state (`POST /model_run`).
            if segments[0] == "models":
                from ..models import installed
                self._send(200, {"dir": str(MODEL_DIR), "roles": installed()})
                return
            jid = (parse_qs(parts.query).get("id") or [""])[0]
            self._send(200, dict(_MODEL_JOBS.get(jid) or {"state": "none"}))
            return

        if segments[0] in ("files", "file_head", "download_status"):
            # Special files (PLUGIN_GOAL 186k): what a page links to, a file's
            # size BEFORE anything is fetched, and a confirmed download's
            # progress. Nothing here downloads.
            q = parse_qs(parts.query)
            if segments[0] == "files":
                if self.workspace is None:
                    self._send(503, {"error": "no workspace"})
                    return
                url = (q.get("url") or [""])[0]
                self._send(200, {"url": url, "files": self.workspace.store.files_of(url)})
                return
            href = (q.get("href") or [""])[0]
            if segments[0] == "file_head":
                self._send(200, _file_head(href))
                return
            self._send(200, dict(_DOWNLOADS.get(href) or {"state": "none"}))
            return

        if segments[0] == "code_kg":
            # The compact code knowledge graph of one `code://` module (PLUGIN_GOAL
            # 186g, `vertiscope/code_kg.py`): read from the source it describes --
            # this repository's (`code://repo/...`) or an installed package's.
            from ..code_kg import compact
            from ..source import source_path_of
            url = (parse_qs(parts.query).get("url") or [""])[0]
            got_path = source_path_of(url)
            if not got_path or not got_path[1].endswith(".py"):
                self._send(400, {"error": "not a code:// python file"})
                return
            root, rel = got_path
            try:
                if root == "repo":
                    base = Path(__file__).resolve().parents[1]
                else:
                    import importlib.util
                    spec = importlib.util.find_spec(root)
                    base = Path(spec.origin).resolve().parent if spec and spec.origin else None
                path = (base / rel).resolve() if base is not None else None
                if path is None or base not in path.parents or not path.exists():
                    self._send(404, {"error": "no source for %s" % url})
                    return
                self._send(200, compact(path.read_text(encoding="utf-8"), url, rel))
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if segments[0] in ("cpg", "cpg_stats", "cpg_vectors", "cpg_edges"):
            query = parse_qs(parts.query)
            store = self.workspace.store
            try:
                if segments[0] == "cpg_edges":
                    # The edges the 3D view DRAWS (G-241): CALLS and INHERITS
                    # touching this file, each end mapped to the node that
                    # draws it -- the chunk at that address, or the nearest
                    # chunk above it, else the file's page node. Drawn, never
                    # forces: the layout measurement says UMAP keeps meaning.
                    url = (query.get("url") or [""])[0]
                    rows = store._rows(
                        "MATCH (a:CodeNode)-[e:Cpg]->(b:CodeNode) WHERE (a.url = $u OR b.url = $u) "
                        "AND e.kind IN ['CALLS', 'INHERITS'] RETURN a.url, a.xpath, b.url, b.xpath, e.kind, e.line", {"u": url})
                    urls = sorted({r[0] for r in rows} | {r[2] for r in rows} | {url})
                    by_url: Dict[str, list] = {}
                    for cu, cx, cid in store._rows("MATCH (c:Chunk) WHERE list_contains($us, c.url) RETURN c.url, c.xpath, c.cid", {"us": urls}):
                        by_url.setdefault(cu, []).append((cx or "", cid))

                    def drawn(u, xp):
                        best = None
                        for cx, cid in by_url.get(u, []):
                            if xp == cx or xp.startswith(cx + "/"):
                                if best is None or len(cx) > len(best[0]):
                                    best = (cx, cid)
                        return best[1] if best else "page:" + u
                    edges, seen = [], set()
                    for au, ax, bu, bx, kind, line in rows:
                        s, t = drawn(au, ax), drawn(bu, bx)
                        if s == t or (s, t, kind) in seen:
                            continue
                        seen.add((s, t, kind))
                        edges.append({"source": s, "target": t, "kind": kind, "line": line,
                                      "from": "%s|%s" % (au, ax), "to": "%s|%s" % (bu, bx)})
                    self._send(200, {"url": url, "edges": edges, "rows": len(rows)})
                elif segments[0] == "cpg_vectors":
                    # `G-241`'s measurement: each class/function of the code
                    # pages under `prefix`, with the vector of the chunk that
                    # holds its docstring (`G-52`: only prose is embedded) --
                    # the chunk whose root xpath is the symbol's own, or the
                    # nearest one inside it.
                    prefix = (query.get("prefix") or ["code://repo/"])[0]
                    syms = store._rows("MATCH (n:CodeNode) WHERE n.url STARTS WITH $p AND n.kind IN ['class', 'function'] "
                                       "RETURN n.key, n.url, n.xpath, n.kind, n.qname", {"p": prefix})
                    chunks: Dict[str, list] = {}
                    for u, xp, emb in store._rows("MATCH (c:Chunk) WHERE c.url STARTS WITH $p AND c.embedding IS NOT NULL "
                                                  "RETURN c.url, c.xpath, c.embedding", {"p": prefix}):
                        chunks.setdefault(u, []).append((xp or "", emb))
                    out = []
                    for key, u, xp, kind, q in syms:
                        best = None
                        for cxp, emb in chunks.get(u, []):
                            if cxp == xp or cxp.startswith(xp + "/"):
                                if best is None or len(cxp) < len(best[0]):
                                    best = (cxp, emb)
                        out.append({"key": key, "url": u, "xpath": xp, "kind": kind, "qname": q,
                                    "vector": [round(float(x), 5) for x in best[1]] if best and best[1] is not None and any(best[1]) else None})
                    self._send(200, {"prefix": prefix, "symbols": out, "with_vector": sum(1 for o in out if o["vector"])})
                elif segments[0] == "cpg_stats":
                    kinds = dict(store._rows("MATCH ()-[e:Cpg]->() RETURN e.kind, count(*)"))
                    nodes = dict(store._rows("MATCH (n:CodeNode) RETURN n.kind, count(*)"))
                    files = store._rows("MATCH (n:CodeNode {kind: 'module'}) RETURN count(*)")
                    cross = store._rows("MATCH (a:CodeNode)-[e:Cpg]->(b:CodeNode) WHERE a.url <> b.url RETURN e.kind, count(*)")
                    self._send(200, {"edges": kinds, "nodes": nodes, "files": int(files[0][0]) if files else 0,
                                     "cross_file": dict(cross)})
                else:
                    url = (query.get("url") or [""])[0]
                    if not url:
                        self._send(400, {"error": "no url"})
                        return
                    self._send(200, store.cpg_of(url))
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if segments[0] == "page_status":
            from .. import tokens as _tokens
            from .layout import (_ESTIMATED_PAGES, _PAGE_POS, live_projection)
            query = parse_qs(parts.query)
            url = (query.get("url") or [""])[0]
            if not url:
                self._send(400, {"error": "no url"})
                return
            store = self.workspace.store
            rows = store._rows(
                "MATCH (c:Chunk {url: $u}) RETURN c.cid, c.md, "
                "c.embedding IS NOT NULL", {"u": url})
            # The DRAWABLE chunks, which is the denominator "in the graph" is
            # answerable for. A duplicate is drawn once as the copy it is
            # (`G-25`) and a merge-group member through its lead (`G-27`), so
            # neither ever gets a node of its own. Dividing by every stored
            # chunk read a correct projector as missing 89 of 688.
            drawable = store._rows(
                "MATCH (c:Chunk {url: $u}) WHERE (c.dup_of IS NULL OR "
                "c.dup_of = '') AND (c.group_of IS NULL OR c.group_of = '' "
                "OR c.group_of = c.cid) RETURN count(c)", {"u": url})[0][0]
            window = int(getattr(self.workspace, "context_window", 0) or 256)
            key = (url, len(rows), sum(len(md or "") for _c, md, _e in rows))
            toks = _TOKEN_MEMO.get(key)
            if toks is None:
                toks = sorted(_tokens.budget_for(md or "", url)
                              for _c, md, _e in rows if (md or "").strip())
                _TOKEN_MEMO.clear()
                _TOKEN_MEMO[key] = toks
            # The chunk projector is what the graph is drawn from, so it is
            # what this page's "fit" is. The old page-mean fit is consulted
            # only if the projector is not running in this process.
            from .projector import projector as _get_projector
            cp = _get_projector()
            projection = (cp.projection if cp is not None and cp.projection
                          is not None else live_projection())
            total = store.chunk_count()
            fitted = projection.fitted_chunks if projection else None
            fits = [e for e in (_PROFILE.get("projector_fit") or _PROFILE.get("layout") or [])
                    if e.get("kind", "fit") == "fit"]
            anchored = any(url in (t or {}) for t in _PAGE_POS.values()) or bool(
                cp is not None and url in cp.page_pos)
            self._send(200, {
                "url": url,
                "chunks": len(rows),
                "drawable": int(drawable),
                "empty_md": sum(1 for _c, md, _e in rows if not (md or "").strip()),
                # What KINDS of content the page's chunks carry (G-99): a
                # page that shows pictures and stores none has lost them.
                "kinds": _content_kinds(md for _c, md, _e in rows),
                "embedded": sum(1 for _c, _m, e in rows if e),
                "window": window,
                "tokens_max": toks[-1] if toks else 0,
                "tokens_p50": toks[len(toks) // 2] if toks else 0,
                "over_window": sum(1 for t in toks if t > window),
                "fitted_chunks": fitted,
                "chunks_now": total,
                "growth": round(total / fitted, 3) if fitted else None,
                "refit_at": 2 * fitted if fitted else None,
                "stale": bool(projection and projection.stale(total)),
                "last_fit_at": fits[-1].get("at") if fits else None,
                "anchor": ("projector" if cp is not None and url in cp.page_pos
                           else "estimated" if url in _ESTIMATED_PAGES
                           else "fitted" if anchored else "none"),
                "embed_queue": len(self.workspace.vectors),
                #: This page's chunks with a position in the projector, and
                #: the projector's own stream state.
                "projected": (len(cp.by_url.get(url) or ()) if cp is not None else None),
                "projector": (cp.brief() if cp is not None else None),
                # Asked for when the browser lands on a page, so every chunk
                # can be queued for the projector and not only the ones a
                # drain happens to re-dirty.
                **({"cids": [c for c, _m, _e in rows]}
                   if (query.get("cids") or [""])[0] else {}),
            })
            return

        if segments[0] == "chunk_stats":
            query = parse_qs(parts.query)
            url = (query.get("url") or [""])[0]
            if not url:
                self._send(400, {"error": "no url"})
                return
            if url == "*":
                # Store-wide anchor health (G-186): chunks holding more anchors
                # than lines carry stale ones, which heal on the page's next
                # capture. Read-only, one pass.
                # Aggregated PER CHUNK (`WITH c, ...`): returning url and
                # line_count beside count(e) grouped by THOSE -- every chunk
                # of a page with the same line count pooled into one row --
                # and reported 167,203 "stale" anchors that were not there
                # (2026-10-12; per chunk there was 1).
                rows = self.workspace.store._rows(
                    "MATCH (c:Chunk) OPTIONAL MATCH (c)-[e:Anchors]->(:Address) "
                    "WITH c, count(e) AS k RETURN c.url, c.line_count, k")
                over = [(u, int(n or 0), int(k or 0)) for u, n, k in rows if int(k or 0) > int(n or 0)]
                pages = {}
                for u, n, k in over:
                    pages[u] = pages.get(u, 0) + 1
                self._send(200, {"chunks": len(rows), "chunks_with_excess_anchors": len(over),
                                 "excess_anchors": sum(k - n for _u, n, k in over),
                                 "pages_affected": len(pages),
                                 "worst_pages": sorted(pages.items(), key=lambda kv: -kv[1])[:8]})
                return
            rows = self.workspace.store._rows(
                "MATCH (c:Chunk {url: $u}) RETURN c.cid, c.md, c.line_count",
                {"u": url})
            empty = [cid for cid, md, _n in rows if not (md or "").strip()]
            self._send(200, {
                "url": url, "chunks": len(rows), "empty_md": len(empty),
                "with_image": sum(1 for _c, md, _n in rows if "![" in (md or "")),
                "line_count_but_empty_md": sum(
                    1 for _c, md, n in rows if not (md or "").strip() and (n or 0) > 0),
                "sample_empty": empty[:3],
            })
            return

        if segments[0] == "addresses":
            # The xpaths one page holds, for a claim about STRUCTURE.
            #
            # `/resolve` answers "which chunk draws this point", which is the
            # reader's question and the wrong one here: a structural claim --
            # that a node inside a shadow root sits under its host in the
            # trie -- is about the set of addresses and their prefixes, not
            # about any one of them. `/pages` is its sibling for the same
            # reason.
            #
            # Read-only, like every other GET. `?contains=` filters by
            # substring, which is how a caller asks only for the shadow ones.
            query = parse_qs(parts.query)
            url = (query.get("url") or [""])[0]
            if not url:
                self._send(400, {"error": "no url"})
                return
            needle = (query.get("contains") or [""])[0]
            limit = int((query.get("limit") or ["4000"])[0])
            rows = self.workspace.store._rows(
                "MATCH (a:Address {url: $u}) RETURN a.xpath, a.tag, a.akey "
                "ORDER BY a.xpath", {"u": url})
            out = []
            blank_keys = 0
            for xpath, tag, akey in rows:
                if not akey:
                    blank_keys += 1
                if not xpath:
                    continue
                if needle and needle not in xpath:
                    continue
                # The KEY is the identity everything downstream is anchored
                # on. A row with a blank one cannot be parsed back, so the
                # line that points at it loses its handle on the page.
                out.append({"xpath": xpath, "tag": tag or "",
                            "akey": akey or ""})
                if len(out) >= limit:
                    break
            self._send(200, {"url": url, "n": len(out),
                             "rows_total": len(rows),
                             "blank_akeys": blank_keys, "addresses": out})
            return

        if segments[0] == "links":
            # Where a link to each page should land. The gesture needs the
            # SAME cid the export uses, or the two would write different
            # edges for one link and the graph would show both.
            self._send(200, {"targets": link_targets(self.workspace)})
            return

        if segments[0] == "layout":
            # Cached on the handler CLASS, so every request in this process
            # shares one fit. UMAP over a real workspace is seconds, and the
            # 3D view asks on every open; refitting per request would make
            # opening the pane feel broken. Keyed on the chunk count so an
            # ingest invalidates it without anyone having to remember to.
            query = parse_qs(parts.query)
            want = int((query.get("dims") or ["3"])[0])
            want = 3 if want not in (2, 3) else want
            # `?space=S3` asks for the quaternion embedding (`G-18`). A query
            # parameter rather than a startup flag, because the two fits are
            # a thing to COMPARE -- the pane can ask for either without
            # restarting the server, and the reply says which it got.
            spherical = (query.get("space") or [""])[0].lower() in (
                "s3", "spherical", "quaternion")
            # PAGES by default (`G-53`). 12,820 chunk nodes hold 3.3 fps
            # because each node and each link is its own draw call; 96 pages
            # is 96. `?level=chunk` still asks for every chunk, because the
            # two are a thing to compare and a small workspace has no reason
            # to collapse.
            level = (query.get("level") or ["page"])[0].lower()
            level = "chunk" if level == "chunk" else "page"
            # **Which corpus, not how big it is (`D-22`).**
            #
            # This was keyed on `chunk_count()` alone, and a count is not an
            # identity: purge twenty pages, capture twenty chunks elsewhere,
            # and the key is unchanged while the corpus is not. A stored fit
            # then comes back for documents it never saw -- measured, a
            # served page layout still held nodes for purged fixtures, and
            # unfolding anchored 643 units from the page against a ball of
            # radius 90.
            #
            # `corpus_fingerprint` is one ordered scan of the Page table,
            # hashed, on the same path that already pays for the count.
            # **The page level is fitted at 2x growth and refreshed between.**
            # Keyed on the page table, capturing ONE page refit the corpus
            # (14 -> 1,189 ms) and moved every existing page -- the median by
            # 54% of the cloud. So a page fit made IN THIS PROCESS is kept,
            # and reconciled against the corpus on each request instead:
            # purged pages dropped, new pages placed into it, refit only once
            # the chunk corpus has doubled. In-process only, because the
            # transform has to come from the same fit that drew the pages it
            # is placing beside; a stored layout cannot provide that.
            refit_asked = bool((parse_qs(parts.query).get("refit") or [""])[0])
            # **The chunk projector answers, when it has a fit.** Positions
            # for pages and chunks alike come from the one fit the stream
            # places into, so the default view, an unfolding and a live
            # capture are the same picture. `?source=legacy` keeps the old
            # separate fits reachable for comparison; S3 still uses them,
            # because the projector fits Euclidean space only.
            source = (parse_qs(parts.query).get("source") or [""])[0]
            if source != "legacy" and not spherical and want == 3:
                from .layout import projected_chunk_layout, projected_page_layout
                from .projector import projector as _get
                proj = _get()
                if proj is not None and refit_asked and not proj.fitting:
                    threading.Thread(target=proj.fit, args=(self.workspace,),
                                     name="vertiscope-refit", daemon=True).start()
                if proj is not None and proj.projection is not None:
                    _t0 = time.perf_counter()
                    got = (projected_page_layout(self.workspace, proj)
                           if level == "page"
                           else projected_chunk_layout(self.workspace, proj))
                    if got is not None:
                        _profile("layout", {"kind": "projector", "level": level,
                                            "n": got.get("n"),
                                            "epoch": got.get("epoch"),
                                            "phases": got.get("timing"),
                                            "ms": round((time.perf_counter() - _t0) * 1000, 1)})
                        self._send(200, got)
                        return
                if proj is not None and proj.projection is None:
                    # Not fitted yet: say so rather than fall back to a
                    # different model the stream will never place into.
                    # (A REFIT is not this: the old fit keeps answering until
                    # the new one is swapped in, `G-74`. Refusing on
                    # `proj.fitting` blanked the picture -- and every unfold --
                    # for the length of each refit, 2026-09-27.)
                    self._send(200, {"nodes": [], "edges": [], "n": 0,
                                     "level": level, "source": "projector",
                                     "fitting": True,
                                     "projector": proj.status(self.workspace),
                                     "note": "the chunk projector is fitting"})
                    return
            if level == "page" and not refit_asked:
                live_fit = _PAGE_FIT.get((want, spherical))
                if live_fit is not None:
                    from .layout import refresh_page_layout
                    # **Memoised on the page table.** Reconciling costs 300-470
                    # ms -- it reads every page and the chunk count -- and it
                    # ran on EVERY request, including the many where nothing
                    # had changed. The fingerprint is exactly "has the set of
                    # pages changed", which is exactly when the answer can.
                    mark = self.workspace.store.corpus_fingerprint()
                    memo = _PAGE_REFRESH.get((want, spherical))
                    if memo is not None and memo[0] == mark and memo[1] is live_fit:
                        _profile("layout", {"kind": "refresh-memo"})
                        self._send(200, memo[2])
                        return
                    got = refresh_page_layout(self.workspace, live_fit, spherical)
                    if not got.get("stale"):
                        got["from_store"] = False
                        got["incremental"] = True
                        _PAGE_REFRESH[(want, spherical)] = (mark, live_fit, got)
                        _profile("layout", {"kind": "refresh",
                                            "fresh": got.get("fresh_pages"),
                                            "dropped": got.get("dropped_pages")})
                        self._send(200, got)
                        return
                    _profile("layout", {"kind": "stale", "chunks": got.get("chunks_now"),
                                        "fitted_chunks": got.get("fitted_chunks")})
            fresh = (self.workspace.store.corpus_fingerprint(), want,
                     spherical, level)
            if refit_asked or (level == "page" and (want, spherical) in _PAGE_FIT):
                # A refit was asked for, or the kept fit went stale: the cache
                # must not answer with the fit being replaced.
                getattr(type(self), "_layouts", {}).pop(fresh, None)
            # A few slots, not one.
            #
            # A single slot is right when there is one question; there are
            # four here (page/chunk x euclidean/S3) and the pane has a button
            # for each axis. With one slot, toggling the space refit the
            # WHOLE corpus, then toggling back refit it again -- and the S3
            # fit is two UMAP runs since the warm start was wired, so a
            # reader pressing a button twice paid for four fits to see two
            # pictures it had already computed. Keyed identically; only the
            # number of remembered answers changes.
            cache = getattr(type(self), "_layouts", None)
            if cache is None:
                cache = type(self)._layouts = {}
            # A refit that is answered from the store is not a refit: it would
            # hand back a layout this process did not fit, whose transform it
            # does not hold, and keep nothing. Measured: `?refit=1` returned in
            # 36 ms and the next page still refit the corpus.
            if fresh not in cache and not refit_asked:
                # `G-12`: the store may already hold this exact fit. Keyed
                # on everything the fit is a function of, so a stored answer
                # comes back only to the question it answered. The
                # chunk-level fit is 95 seconds over this corpus and the
                # page-level one under a second, so what this buys is the
                # expensive picture surviving a restart.
                stored_key = "|".join(str(v) for v in fresh)
                kept = None
                try:
                    kept = self.workspace.store.load_layout(stored_key)
                except Exception:                   # noqa: BLE001
                    kept = None
                if kept:
                    try:
                        got = json.loads(kept)
                        got["from_store"] = True
                        cache[fresh] = got
                        # A stored layout skips `build_page_layout`, and with
                        # it the side effect that records where each page was
                        # drawn. Restore it, or an unfolding anchors on
                        # nothing (`D-21`).
                        if level == "page":
                            remember_page_positions(got, spherical)
                    except Exception:               # noqa: BLE001
                        pass
            if fresh not in cache:
              # Checked again INSIDE the lock: two threads can both miss,
              # and the point is that only one of them fits.
              with _FIT_LOCK:
                if fresh not in cache:
                    _fit_started = time.perf_counter()
                    cache[fresh] = (
                        build_page_layout(self.workspace, dims=want,
                                          spherical_space=spherical)
                        if level == "page"
                        else build_layout(self.workspace, dims=want,
                                          spherical_space=spherical))
                    _profile("layout", {"kind": "fit", "level": level,
                                        "ms": round((time.perf_counter() - _fit_started) * 1000, 1)})
                    if level == "page":
                        # This process made this fit, so its transform
                        # agrees with its positions: it can be kept.
                        _PAGE_FIT[(want, spherical)] = cache[fresh]
                    # Always present, true or false. It was set only when
                    # the answer CAME from the store, so a freshly built one
                    # had no such key -- and a caller asking "which did I
                    # get?" could not tell "built" from "not reported".
                    cache[fresh]["from_store"] = False
                    try:
                        self.workspace.store.save_layout(
                            stored_key, json.dumps(cache[fresh]),
                            n=int(cache[fresh].get("n") or 0))
                    except Exception:               # noqa: BLE001
                        # A fit that cannot be saved is still a fit: this
                        # store is opened read-only by most callers.
                        pass
                # Bounded, and evicting the OLDEST rather than the largest:
                # the chunk-level fits are the expensive ones and are exactly
                # what a reader toggling `pages` wants back.
                while len(cache) > 4:
                    cache.pop(next(iter(cache)))
            self._send(200, cache[fresh])
            return

        if segments[0] == "kernel":
            # What is running, so a reader can tell a lost namespace from a
            # kernel that never started.
            if self.kernel_pool is None:
                self._send(200, {"enabled": False, "kernels": []})
            else:
                self._send(200, dict(self.kernel_pool.status(), enabled=True))
            return

        if segments[0] == "shell":
            if self.shell_pool is None:
                self._send(200, {"enabled": False, "shells": []})
            else:
                self._send(200, dict(self.shell_pool.status(), enabled=True))
            return

        if segments[0] == "interpreters":
            # Discovery, not a fixed list: what can be run is a property of the
            # machine, and a hardcoded list is wrong on every machine but the
            # author\'s. Answered whether or not the kernel is on, because a
            # panel should be able to say what WOULD be available.
            from .shell import interpreters
            self._send(200, interpreters())
            return

        if segments[0] == "search":
            params = parse_qs(parts.query)
            query = (params.get("q") or [""])[0]
            # `k` is clamped rather than trusted: the caller is a plugin in
            # another process and an absent or absurd value must not turn a
            # keystroke into a full-workspace scan.
            try:
                k = int((params.get("k") or ["8"])[0])
            except ValueError:
                k = 8
            # 2000, the field's own maximum: at 50 the reader's n could never
            # reach the retrieved set (2026-10-17: "don't exceed a 50 result
            # limit to cover the full set of retrieved results"). A keystroke
            # still asks the field's default depth, not this.
            # The bound is what MATCHES, not a fixed 2000 (2026-10-17,
            # PLUGIN_GOAL 154: "maxed out at 2000 rather than the proper upper
            # limit"); this ceiling only stops a runaway request.
            k = max(1, min(k, 20000))
            try:
                offset = int((params.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            # Bounded, for the reason `k` is: a scroll that never stops must
            # not become a request that ranks the whole corpus twice.
            offset = max(0, min(offset, 2000))
            scope = (params.get("url") or [""])[0]
            coarse = (params.get("coarse") or ["1"])[0] != "0"
            try:
                budget = int((params.get("budget") or ["0"])[0])
            except ValueError:
                budget = 0
            if not query:
                self._send(400, {"error": "missing q"})
            else:
                # Foreground: background training and embedding stand aside
                # while the reader waits on a search (PLUGIN_GOAL 152).
                with _foreground():
                    got = search_payload(
                        self.workspace, query, k, offset=offset,
                        url=scope, coarse=coarse, budget=budget)
                self._send(200, got)
            return

        self._send(404, {"error": "no such route", "path": parts.path})


def _search_pages(index, query: str, k: int, params) -> tuple:
    """Tier 1: (pages, corpus match count, each page's count). `centroid=1`
    (planted): the semantic centroids, which chose pages holding nothing
    tier 2 lets through."""
    if not query or index is None:
        return [], None, {}
    centroid = (params.get("centroid") or ["0"])[0] == "1"
    if not centroid and hasattr(index, "search_pages_matching"):
        from ..search import SearchDiagnostics
        diag = SearchDiagnostics()
        pages = index.search_pages_matching(query, k, diagnostics=diag)
        return pages, int(diag.survivors), dict(getattr(index, "last_page_counts", {}) or {})
    if hasattr(index, "search_pages"):
        return index.search_pages(query, k), None, {}
    return [], None, {}


def serve(workspace, port: int = 8787, *, block: bool = True,
          enact: bool = False, capture: bool = False, kernel: bool = False,
          kernel_timeout: Optional[float] = None,
          plugin_captures_only: bool = False):
    """Answer on loopback until stopped.

    Returns the server so a caller that passed ``block=False`` can shut it
    down; a test that leaks one wedges the port for the next run.

    ``kernel`` starts a pool of per-note Python subprocesses and opens
    ``POST /kernel``. It is off by default because it runs arbitrary code with
    this process's privileges, which is a larger permission than anything else
    here, and it is a SEPARATE flag from ``enact`` because a reader who wanted a
    notebook did not thereby ask for a vault that can drive the web.
    """
    # Background training steps aside for searches (PLUGIN_GOAL 152).
    # Planted: VERTISCOPE_PLANT_NO_TRAIN_YIELD=1.
    if os.environ.get("VERTISCOPE_PLANT_NO_TRAIN_YIELD") != "1":
        try:
            from . import pumap as _pumap
            _pumap.TRAIN_YIELD[0] = lambda: _yield_to_foreground(limit_s=2.0)
        except Exception:                           # noqa: BLE001
            pass
    pool = None
    shells = None
    if kernel:
        from .kernel import DEFAULT_TIMEOUT, KernelPool
        from .shell import ShellPool
        pool = KernelPool(timeout=kernel_timeout or DEFAULT_TIMEOUT)
        # One flag for both: see `_post_shell` for why a second would be a
        # permission that looks meaningful and is not.
        shells = ShellPool()

    # The background embedder. Started only when there is an embedder to
    # run, so a read-only workspace does not carry a thread that can never
    # have anything to do.
    global _EMBED_THREAD
    stop = threading.Event()
    if getattr(workspace, "embedder", None) is not None:
        _EMBED_THREAD = threading.Thread(
            target=_embed_forever, args=(workspace, stop),
            name="vertiscope-embed", daemon=True)
        _EMBED_THREAD.start()
    if workspace is not None and not getattr(workspace, "read_only", False)             and hasattr(workspace.store, "checkpoint"):
        threading.Thread(target=_checkpoint_forever, args=(workspace, stop),
                         name="vertiscope-checkpoint", daemon=True).start()
        threading.Thread(target=_integrity_forever, args=(workspace, stop),
                         name="vertiscope-integrity", daemon=True).start()
        threading.Thread(target=_poison_watch, args=(workspace, stop),
                         name="vertiscope-poison-watch", daemon=True).start()
        threading.Thread(target=_warm_containment, args=(workspace, stop),
                         name="vertiscope-warm-containment", daemon=True).start()

    # **The chunk projector.** One fit over every drawable chunk, made off
    # the request path; then a worker that drains the stream the embedder and
    # the capture path feed it, and refits in the background at 2x growth.
    # The statement kuzu is running, recorded before it runs (`D-23`): the
    # sidecar segfaults natively in kuzu under load, and a crash leaves no
    # Python frame that names the statement. `supervise` reads this back.
    if workspace is not None and hasattr(workspace.store, "enable_breadcrumb"):
        workspace.store.enable_breadcrumb(Path(workspace.path) / "last_statement.txt")

    if workspace is not None:
        from . import projector as _projector
        if _projector.PROJECTOR is None:
            # Addendum VII: UMAP over one centroid per page; a page's chunks
            # are its patricia tree, laid out by force in the pane. The
            # centroid is the triple mechanism's unless told otherwise.
            # THE DEFAULT since 2026-09-27 ("make the page-centroid UMAP the
            # default projector"): fitted on page centroids, every chunk
            # transformed through that fit. The semantic centroid by default,
            # because it is the space a chunk vector lives in; the triple one
            # stays selectable. VERTISCOPE_PROJECTOR=chunk brings back the fit on
            # a sample of chunks.
            import os as _os
            if _os.environ.get("VERTISCOPE_PROJECTOR", "page") == "page":
                _projector.PROJECTOR = _projector.PageProjector(
                    dims=3, centroid=_os.environ.get("VERTISCOPE_PAGE_CENTROID", "semantic"))
            else:
                _projector.PROJECTOR = _projector.ChunkProjector(dims=3)
            _projector.PROJECTOR.on_batch = lambda r: _profile("project", r)
            _projector.PROJECTOR.on_fit = lambda r: _profile("projector_fit", r)
            _projector.PROJECTOR.start(workspace, work_lock=_WORK_LOCK,
                                       fit_lock=_FIT_LOCK)

    # **The query index, built before anyone asks.** Its first build hydrated
    # every embedding (146 s measured before the growth fix) and landed on
    # the first reader's search. The embed worker owns the encoder here, so
    # a search never runs it inline (`Workspace.embed_inline`).
    if workspace is not None and hasattr(workspace, "embed_inline"):
        workspace.embed_inline = False

        def _warm_index():
            try:
                started = time.perf_counter()
                workspace.index
                _profile("index_warm", {"ms": round((time.perf_counter() - started) * 1000, 1)})
            except Exception as exc:                # noqa: BLE001
                _profile("index_warm", {"error": "%s: %s" % (type(exc).__name__, exc)})
        threading.Thread(target=_warm_index, name="vertiscope-index", daemon=True).start()

    # **Lexical rows for every chunk, at start.** Rows lost to a hard kill
    # (the matrix used to be written only on a clean close) or indexed while
    # a chunk's markdown was empty are re-derived from the store's markdown,
    # off the request path. See `Workspace.rebuild_lexical`.
    if workspace is not None and hasattr(workspace, "rebuild_lexical"):
        def _lexical():
            try:
                started = time.perf_counter()
                with _WORK_LOCK:
                    got = workspace.rebuild_lexical()
                got["ms"] = round((time.perf_counter() - started) * 1000, 1)
                _profile("lexical_repair", got)
            except Exception as exc:                # noqa: BLE001
                _profile("lexical_repair", {"error": "%s: %s" % (type(exc).__name__, exc)})
        threading.Thread(target=_lexical, name="vertiscope-lexical", daemon=True).start()

    # (The page-fit warmup that stood here is gone: it built the old
    # page-mean fit so its transform would be warm. The projector's fit
    # transforms every chunk on its way in, which warms the same thing, and
    # the page-mean fit is no longer what the graph is drawn from.)

    handler = type("_Bound", (_Handler,),
                   {"workspace": workspace, "enact_allowed": bool(enact),
                    "capture_allowed": bool(capture),
                    "plugin_captures_only": bool(plugin_captures_only),
                    "kernel_pool": pool, "shell_pool": shells})

    class _Server(ThreadingHTTPServer):
        # A vault opens many chunks at once -- a note with several `vertiscope`
        # blocks, or the graph view beside a handful of surfaces -- and every
        # one is its own connection, arriving together.
        #
        # `socketserver` defaults `request_queue_size` to 5, so the sixth
        # connection of a burst is REFUSED rather than queued. Measured with
        # nine simultaneous requests: exactly one came back ECONNREFUSED and
        # the rest were fine, which is the worst possible shape -- the plugin
        # answers null on a failed fetch, the surface then says "sidecar
        # unreachable", and it stays saying that until the note is edited. One
        # surface in nine looked broken while the sidecar was healthy.
        request_queue_size = 128
        daemon_threads = True

    server = _Server(("127.0.0.1", port), handler)
    _REQLOG[0] = Path(workspace.path) / "requests.log"
    try:
        threading.Thread(target=_stall_watchdog, args=(str(workspace.path),),
                         name="vertiscope-stall-watchdog", daemon=True).start()
    except Exception:                               # noqa: BLE001
        pass
    # The pool hangs off the server so a `block=False` caller can reach it, and
    # so nothing else has to remember it exists.
    server.kernel_pool = pool
    server.shell_pool = shells
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            # Kernels are child PROCESSES, and they go before the socket does.
            # A Ctrl-C that left them running would leak an interpreter per
            # note, and the next run would find the machine slower for reasons
            # nothing on screen explains.
            if pool is not None:
                pool.shutdown()
            if shells is not None:
                shells.shutdown()
            server.server_close()
        return server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
