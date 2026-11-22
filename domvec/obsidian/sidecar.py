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
from contextlib import nullcontext
from pathlib import Path
from collections import deque
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Sequence
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



def md_title(md: str, limit: int = 60) -> str:
    """A chunk's title as a reader would name it: its first line with words
    in it -- a heading's text, a link's text (not its url), no image -- with
    the markdown taken off. "" when no line has a word."""
    for line in (md or "").splitlines():
        t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", line)                 # images
        t = re.sub(r"\[+\(?\s*([^\[\]]*?)\s*\)?\]+\(+[^)]*\)+", r"\1", t)   # links -> their text
        t = re.sub(r"https?://\S+", " ", t)                                   # bare urls
        t = re.sub(r"\b[0-9a-fA-F]{8,}\b", " ", t)                            # cids, hashes
        t = re.sub(r"<[^>]+>|`|\*\*|__|[\[\]]|^\s*(#+|[-*+>]|\d+\.)\s*", " ", t)
        t = re.sub(r"\s+", " ", t).strip(" |-")
        if re.search(r"[^\W\d_]{2,}", t):
            return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"
    return ""

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
class _HeldLock:
    """`_WORK_LOCK`, saying who holds it and for how long (2026-10-29).

    Captures waited 3-12 s for this lock (`lock_wait`) while their own work
    took ~1 s, and hover and the panel stream queued behind them; 32 places
    take it and nothing said which one was holding it. A re-entrant lock that
    records, per OUTERMOST hold, the thread, the code that took it, how long
    it waited and how long it held -- read at `GET /locks`. Holds over 0.2 s
    are kept, the newest 200.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._depth = 0
        self.holder = None
        self.since = 0.0
        self.slow: "deque" = deque(maxlen=200)
        self.totals: Dict[str, List[float]] = {}

    @staticmethod
    def _site() -> str:
        f = sys._getframe(2)
        while f is not None and f.f_code.co_filename == __file__ and f.f_code.co_name in (
                "__enter__", "acquire", "_site"):
            f = f.f_back
        if f is None:
            return "?"
        return "%s:%d %s" % (os.path.basename(f.f_code.co_filename), f.f_lineno, f.f_code.co_name)

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        t0 = time.perf_counter()
        ok = self._lock.acquire(blocking, timeout)
        if ok:
            self._depth += 1
            if self._depth == 1:
                self.since = time.perf_counter()
                self.holder = (threading.current_thread().name, self._site(),
                               round((self.since - t0) * 1000, 1))
        return ok

    def release(self) -> None:
        if self._depth == 1 and self.holder is not None:
            held = (time.perf_counter() - self.since) * 1000
            thread, site, waited = self.holder
            tot = self.totals.setdefault(site, [0, 0.0, 0.0])
            tot[0] += 1
            tot[1] += held
            tot[2] = max(tot[2], held)
            if held > 200:
                self.slow.append({"site": site, "thread": thread, "held_ms": round(held, 1),
                                  "waited_ms": waited, "at": round(time.time(), 3)})
            self.holder = None
        self._depth -= 1
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def report(self) -> Dict:
        holder = None
        if self.holder is not None:
            holder = {"thread": self.holder[0], "site": self.holder[1],
                      "held_ms": round((time.perf_counter() - self.since) * 1000, 1)}
        top = sorted(self.totals.items(), key=lambda kv: -kv[1][1])[:15]
        return {"holder": holder,
                "by_site": [{"site": k, "n": int(v[0]), "held_ms": round(v[1], 1), "max_ms": round(v[2], 1)}
                            for k, v in top],
                "slow": list(self.slow)[-25:]}


_WORK_LOCK = _HeldLock()

#: Planted (G-279): a cell's `{ref}` inputs are not bound before it runs.
PLANT_NO_REF_BINDING = [False]
#: Planted (G-279): no base objects in a cell's kernel.
PLANT_NO_BASE_OBJECTS = [False]
#: Planted (P-N4): no vault facade -- a cell sees neither `Vault` nor its note's folder.
PLANT_NO_VAULT = [False]
#: Planted (PLUGIN_GOAL 62): a note's markdown trees are not compiled into its kernel.
PLANT_NO_TREES = [False]
#: Planted (PLUGIN_GOAL 62): the slate check finds nothing.
PLANT_NO_SLATE_CHECK = [False]
#: Names that exist outside any note: the kernel's base objects, the cockpit's key stream.
_SLATE_KNOWN = ("Database", "WebBrowser", "Agent", "search", "Vault", "keys")
#: Planted (item 59): a filtered search page is truncated, not refilled.
PLANT_NO_REFILL = [False]
#: Planted (G-288): a cell's asks of the app are dropped.
PLANT_NO_ASKS = [False]
#: Planted (G-13, 2026-10-30): a re-cluster re-queues EVERY chunk of the page
#: for re-projection, as before, instead of the ones whose group changed.
PLANT_PROJECT_WHOLE_PAGE = [False]
#: Planted (G-105): a prototype comes back without its code -- the name alone.
PLANT_PROTOTYPE_NO_CODE = [False]
#: Planted (P-C1): a saved artifact is re-indexed but its file is not written.
PLANT_SOURCE_NOT_WRITTEN = [False]
#: Planted (P-C5): a saved artifact is stored but reaches the 3D view by
#: neither path -- not queued for projection, dropped from the encoder.
PLANT_SOURCE_NOT_PROJECTED = [False]

#: The encoder (one GPU model), shared by the embed worker and `/project`.
#: Neither holds the store's lock while encoding, so a projection waits at
#: most one embed batch -- never a capture's write.
_ENCODER_LOCK = threading.Lock()
#: Interactive encodes waiting for `_ENCODER_LOCK` (`/project`). The
#: background embedder gives way to them between slices (D-40).
_ENCODER_FG = [0]
_ENCODER_FG_LOCK = threading.Lock()
#: Texts the background embedder encodes per hold of the encoder lock.
_EMBED_SLICE = 16
#: The browser's `/project` gives up after this; an encode started later
#: serves no one.
_PROJECT_CLIENT_S = 8.0
#: Planted: the whole batch encoded under one hold, as before.
PLANT_ENCODER_BATCH_HOLD = [False]
_ENCODER_STATS = {"slices": 0, "gave_way": 0, "gave_way_s": 0.0, "project_stale": 0}


class _foreground_encoder:
    """Hold `_ENCODER_LOCK` for an interactive encode, announced first so the
    background embedder stops taking slices until it is through."""

    def __enter__(self):
        with _ENCODER_FG_LOCK:
            _ENCODER_FG[0] += 1
        try:
            _ENCODER_LOCK.acquire()
        except BaseException:
            with _ENCODER_FG_LOCK:
                _ENCODER_FG[0] -= 1
            raise
        return self

    def __exit__(self, *exc):
        _ENCODER_LOCK.release()
        with _ENCODER_FG_LOCK:
            _ENCODER_FG[0] -= 1
        return False


def _encode_sliced(workspace, taken, slice_n=None, max_give_way_s: float = 10.0):
    """The background batch encoded `slice_n` texts per hold of the encoder
    lock, giving way while an interactive encode waits (D-40: a `/project`
    for the chunks streaming into the 3D view waited 682 s behind batch
    encodes, 2026-11-22, the GPU under a game; on a quiet GPU one 64-text
    batch is about a second, D-40's 1.7 s to_3d). On failure the slices not
    yet encoded go back to the queue before it raises."""
    taken = list(taken or ())
    if PLANT_ENCODER_BATCH_HOLD[0]:
        with _ENCODER_LOCK:
            return workspace.encode_taken(taken)
    n = max(1, int(slice_n or _EMBED_SLICE))
    produced = {}
    for i in range(0, len(taken), n):
        part = taken[i:i + n]
        t0 = time.monotonic()
        while _ENCODER_FG[0] > 0 and time.monotonic() - t0 < max_give_way_s:
            time.sleep(0.005)
        waited = time.monotonic() - t0
        if waited > 0.004:
            _ENCODER_STATS["gave_way"] += 1
            _ENCODER_STATS["gave_way_s"] = round(_ENCODER_STATS["gave_way_s"] + waited, 3)
        try:
            with _ENCODER_LOCK:
                got = workspace.encode_taken(part)
        except Exception:
            rest = taken[i + n:]
            if rest:
                try:
                    workspace.vectors.requeue(rest)
                except Exception:                   # noqa: BLE001
                    pass
            raise
        _ENCODER_STATS["slices"] += 1
        produced.update(got or {})
    return produced

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
#: Planted (G-270): a purged page's projected chunks stay held until the
#: idle reconcile finds them.
PLANT_PURGE_KEEPS_PROJECTED = [False]
PLANT_OUTPUTS_EVERYWHERE = [False]
#: Planted (2026-11-15): a results page's echo of the query is kept.
PLANT_NO_ECHO_RULE = [False]
#: The share of a chunk's words that are its page's own query words, at or
#: above which it is the page saying the query back. Live: DuckDuckGo's "No
#: more results found for ..." box (with its "Check spelling", "Ask Duck.ai"
#: suggestions) is 18 of 46 words, 0.39; a result snippet quoting the
#: phrase is ~0.01.
ECHO_SHARE = 0.3
_WORD = re.compile(r"[a-z0-9]+")


def _echoes(stored, query: str) -> bool:
    """Is this chunk a results page repeating the query back?

    Live 2026-11-15: DuckDuckGo's "No more results found for <query>" ranked
    first for the query it repeats -- nearest in words AND meaning (lexical
    0.47, semantic 0.78), and its page's content share (0.64) too high for
    the content factor to sink it. Three conditions, all read from the trie's
    own address and the chunk's text, none from a site list:
    the page was MADE from the query (each query word begins a word of its
    url's query string -- the field searches as the reader types, so the last
    word is often a prefix: "unionRect xpa" against q=unionRect+xpaths+...);
    the chunk says the query as a phrase (the same prefix rule); and it is
    mostly the query -- at least `ECHO_SHARE` of its words are the url's own
    query words. A result snippet quoting the phrase is not, and stays."""
    from urllib.parse import urlsplit, parse_qsl
    q = _WORD.findall(query.lower())
    if not q:
        return False
    try:
        params = " ".join(v for _k, v in parse_qsl(urlsplit(str(stored.url)).query))
    except ValueError:
        return False
    made = set(_WORD.findall(params.lower()))
    if not all(any(m.startswith(w) for m in made) for w in q):
        return False
    words = _WORD.findall(tokens.for_model(stored.md or "").lower())
    if not words or sum(1 for x in words if x in made) < ECHO_SHARE * len(words):
        return False
    n = len(q)
    return any(all(words[i + j].startswith(q[j]) for j in range(n)) for i in range(len(words) - n + 1))
#: Set while a thread recomputes the health counts (one at a time).
_HEALTH_REFRESHING = threading.Event()


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
_PLANT_NO_AUTOCOMPACT = [os.environ.get("DOMVEC_PLANT_NO_AUTOCOMPACT") == "1"]
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
            res = models.run_chat(str(body.get("prompt") or ""), role=job["role"])
        job.update(state="done" if res.ok else "error", result=res.to_json(), error=res.error,
                   s=round(time.time() - t0, 1))
    except Exception as exc:                        # noqa: BLE001
        job.update(state="error", error="%s: %s" % (type(exc).__name__, str(exc)[:200]), s=round(time.time() - t0, 1))
    # The job as a run of `model://<role>` over the chunk it read (THROUGH_STACK_SYNTHESIS 1c).
    record_call(workspace, "model://%s" % job.get("role"),
                _call_text("run_role", {"role": job.get("role"), "cid": job.get("cid")}),
                [("text", job.get("cid"))] if job.get("cid") else [], job.get("state") == "done",
                str(job.get("error") or job.get("state")))
    _profile("model_run", {k: job.get(k) for k in ("role", "cid", "state", "s")})


#: Confirmed downloads by href: state, bytes, total, path, error.
_DOWNLOADS: Dict[str, Dict] = {}
#: Where an installed model goes: the directory the GPT4All runtime loads from.
MODEL_DIR = Path(os.environ.get("DOMVEC_MODEL_DIR") or (Path.home() / ".cache" / "gpt4all"))


def _file_head(href: str) -> Dict:
    """A file's size and type, asked of its server WITHOUT fetching it (HEAD,
    redirects followed) -- what the panel shows before asking to download."""
    import urllib.request
    if not href.startswith(("http://", "https://")):
        return {"error": "not an http(s) url"}
    try:
        req = urllib.request.Request(href, method="HEAD", headers={"User-Agent": "domvec"})
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
        headers = {"User-Agent": "domvec"}
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
    `DOMVEC_PLANT_LAZY_IMPORTS=1`: nothing loaded here, as before.
    """
    out: Dict[str, float] = {}
    if os.environ.get("DOMVEC_PLANT_LAZY_IMPORTS") == "1":
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
    replay. Planted `DOMVEC_PLANT_EXIT_PROCESS=1`: `os._exit`, as before.
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
    if os.name == "nt" and os.environ.get("DOMVEC_PLANT_EXIT_PROCESS") != "1":
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
                    os.environ.get("DOMVEC_SUPERVISED") == "1", idle_s, _LAST_WRITE[0]):
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
        # Reads, on the store's read connection: no work lock. Under it the
        # start-up count held every capture and hover for 25.7 s (2026-10-29).
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
    # Last process's memos first (`layout.load_view_memo`): every page still
    # stamped as it was saved needs no reading at all.
    try:
        from .layout import load_view_memo
        _profile("view_memo_loaded", load_view_memo(workspace) or {})
    except Exception as exc:                        # noqa: BLE001
        _profile("view_memo_loaded", {"error": str(exc)[:160]})
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
            # ...and kept for the next process, then every ten minutes.
            from .layout import save_view_memo
            _profile("view_memo_saved", save_view_memo(workspace) or {})
            while not stop.wait(600.0):
                _yield_to_foreground()
                _profile("view_memo_saved", save_view_memo(workspace) or {})
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
#: the recorded value of the same cid). Planted `DOMVEC_PLANT_NO_MD_HEAL=1`:
#: recorded only, as before.
_MD_HEAL_AT = 500
_PLANT_NO_MD_HEAL = [os.environ.get("DOMVEC_PLANT_NO_MD_HEAL") == "1"]

#: Module flags a live check may plant through `POST /plant` -- the planted
#: arm of a rule that runs in the sidecar's projection, not in the plugin.
#: A LOAD, not a defect (D-42): each capture holds the write lock 400 ms
#: longer, as it does when a settle or an embed batch is in its way. D-42
#: turns it on for BOTH arms -- on an idle sidecar a capture (~200 ms) keeps
#: up with a 120 ms drain, so one-capture-per-drain had nothing to lose and
#: the planted arm could not fail (run 36: serial p95 442 ms, merged 889).
PLANT_CAPTURE_LOAD = [False]

_PLANTABLE = {
    "capture-load": ("domvec.obsidian.sidecar", "PLANT_CAPTURE_LOAD"),      # D-42 load
    "no-shape": ("domvec.typegen", "PLANT_NO_SHAPE"),                         # G-388: every repeat is a type
    "browse-host-only": ("domvec.browse", "PLANT_DOMAIN_HOST_ONLY"),          # G-205: the domain scope one level only
    "no-call-runs": ("domvec.obsidian.sidecar", "PLANT_NO_CALL_RUNS"),       # synthesis 1c: tool calls leave no run
    "placeholder-target": ("domvec.markdown", "PLANT_PLACEHOLDER_TARGET"),   # G-197
    "no-edge-memo": ("domvec.obsidian.layout", "PLANT_NO_EDGE_MEMO"),
    "no-declump": ("domvec.obsidian.layout", "PLANT_NO_DECLUMP"),            # 137(6)
    "lead-in-python": ("domvec.graphstore", "PLANT_LEAD_IN_PYTHON"),         # 143 fit read
    "zero-group-dropped": ("domvec.graphstore", "PLANT_ZERO_GROUP_DROPPED"),  # G-270 drawable set
    "no-reconcile": ("domvec.obsidian.projector", "PLANT_NO_RECONCILE"),     # G-270
    "incremental-refit": ("domvec.obsidian.projector", "PLANT_INCREMENTAL_REFIT"),  # 173 b
    "no-gpu-gate": ("domvec.gpu_gate", "PLANT_NO_GATE"),                  # G-385
    "replace-unchanged": ("domvec.obsidian.projector", "PLANT_REPLACE_UNCHANGED"),  # hover jump
    "purge-keeps-projected": ("domvec.obsidian.sidecar", "PLANT_PURGE_KEEPS_PROJECTED"),  # G-270
    "outputs-everywhere": ("domvec.obsidian.sidecar", "PLANT_OUTPUTS_EVERYWHERE"),  # T-13
    "no-output-boundary": ("domvec.markdown", "PLANT_NO_OUTPUT_BOUNDARY"),       # T-13, short notes
    "aggregate-mid-stream": ("domvec.obsidian.sidecar", "PLANT_AGGREGATE_MID_STREAM"),  # 137(20)
    "furniture-is-content": ("domvec.markdown", "PLANT_FURNITURE_IS_CONTENT"),  # 137(3)       # chunk view, 2026-10-24
    "fixed-batch": ("domvec.obsidian.projector", "PLANT_FIXED_BATCH"),      # G-13, 2026-10-24
    "adaptive-window": ("domvec.obsidian.projector", "ADAPTIVE_WINDOW"),    # G-13, on: opens for a trickle only
    "window-always": ("domvec.obsidian.projector", "PLANT_WINDOW_ALWAYS"),  # G-13, the window regardless of arrivals
    "no-scope-switch": ("domvec.obsidian.projector", "PLANT_NO_SCOPE_SWITCH"),  # G-2, 2026-10-25
    "page-scoped-dedup": ("domvec.graphstore", "PLANT_PAGE_SCOPED_DEDUP"),     # 2026-10-29
    "no-ref-binding": ("domvec.obsidian.sidecar", "PLANT_NO_REF_BINDING"),     # G-279
    "no-base-objects": ("domvec.obsidian.sidecar", "PLANT_NO_BASE_OBJECTS"),   # G-279
    "no-asks": ("domvec.obsidian.sidecar", "PLANT_NO_ASKS"),                   # G-288
    "project-whole-page": ("domvec.obsidian.sidecar", "PLANT_PROJECT_WHOLE_PAGE"),  # G-13
    "chat-resend": ("domvec.chat", "PLANT_RESEND"),                               # G-43
    "prototype-no-code": ("domvec.obsidian.sidecar", "PLANT_PROTOTYPE_NO_CODE"),  # G-105
    "reembed-all": ("domvec.vectors", "PLANT_REEMBED_ALL"),                    # P-N6
    "no-seed": ("domvec.workspace", "PLANT_NO_SEED"),                          # P-N6
    "no-vault": ("domvec.obsidian.sidecar", "PLANT_NO_VAULT"),                 # P-N4
    "no-trees": ("domvec.obsidian.sidecar", "PLANT_NO_TREES"),                 # item 62
    "no-slate-check": ("domvec.obsidian.sidecar", "PLANT_NO_SLATE_CHECK"),     # item 62
    "no-content-factor": ("domvec.search", "PLANT_NO_CONTENT_FACTOR"),         # item 59
    "product-fuse": ("domvec.search", "PLANT_PRODUCT_FUSE"),                   # item 85
    "no-where": ("domvec.obsidian.sidecar", "PLANT_NO_WHERE"),                # item 78
    "no-maps": ("domvec.obsidian.sidecar", "PLANT_NO_MAPS"),                  # item 79
    "flat-box": ("domvec.obsidian.blackbox", "PLANT_FLAT"),                   # item 80
    "no-imports": ("domvec.obsidian.blackbox", "PLANT_NO_IMPORTS"),           # item 112
    "slate-space-split": ("domvec.slate", "PLANT_SPACE_SPLIT"),               # G-277
    "stored-note": ("domvec.obsidian.refs", "PLANT_STORED_NOTE"),             # G-277
    "uniform-types": ("domvec.codegraph", "PLANT_UNIFORM_TYPES"),             # G-317
    "no-versions": ("domvec.graphstore", "PLANT_NO_VERSIONS"),                # G-253
    "no-requeue": ("domvec.workspace", "PLANT_NO_REQUEUE"),                   # stuck unembedded rows
    "no-debias": ("domvec.obsidian.projector", "PLANT_NO_DEBIAS"),            # 175 c: debias off for the next fit
    "encoder-batch-hold": ("domvec.obsidian.sidecar", "PLANT_ENCODER_BATCH_HOLD"),  # D-40
    "retire-in-session": ("domvec.obsidian.sidecar", "_PLANT_RETIRE_IN_SESSION"),  # Q.002 / G-120
    "edge-two-match": ("domvec.graphstore", "PLANT_EDGE_TWO_MATCH"),  # 137 (20)
    "record-split-at-window": ("domvec.markdown", "PLANT_RECORD_SPLIT_AT_WINDOW"),  # G-246
    "untyped-box": ("domvec.obsidian.blackbox", "PLANT_UNTYPED"),             # item 100
    "no-codegraph": ("domvec.search", "PLANT_NO_CODEGRAPH"),                  # item 93
    "no-instant": ("domvec.obsidian.sidecar", "PLANT_NO_INSTANT"),            # item 100
    "world-projection": ("domvec.obsidian.sidecar", "PLANT_WORLD_PROJECTION"),  # item 76
    "no-refill": ("domvec.obsidian.sidecar", "PLANT_NO_REFILL"),               # item 59
    "subprocess-kernel": ("domvec.obsidian.kernel", "PLANT_SUBPROCESS_KERNEL"),  # P-N1
    "source-not-written": ("domvec.obsidian.sidecar", "PLANT_SOURCE_NOT_WRITTEN"),     # P-C1
    "source-not-projected": ("domvec.obsidian.sidecar", "PLANT_SOURCE_NOT_PROJECTED"),  # P-C5
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

def _vram(release: bool = False) -> Dict:
    """This process's view of the GPU, for the chat profile (PLUGIN_GOAL 159:
    "the latency is honestly several minutes"). The chat model, the embedder
    and torch's parametric UMAP share one 8 GB card in this one process; the
    model and its 8,192-token KV cache took 5.4 GB and left 1,052 MB free
    (2026-11-14). A fresh worker answered at 45 tokens/s, 0.25 s to the first
    token; a long-running one at 0.6-1.3 tokens/s and 39-43 s to the first,
    at 100% GPU. The slow state is NOT yet explained: VRAM spill was the
    first guess and torch held 2 MB when measured. `release` returns torch's
    CACHED blocks to the driver before a turn; its arm
    (`keep_torch_cache`) has not yet discriminated anything.
    Never imports torch: absent, there is nothing of torch's to report."""
    t = sys.modules.get("torch")
    try:
        if t is None or not t.cuda.is_available():
            return {}
        mb = lambda b: round(b / 1048576)
        out = {"torch_reserved_mb": mb(t.cuda.memory_reserved()), "torch_alloc_mb": mb(t.cuda.memory_allocated())}
        if release:
            t.cuda.empty_cache()
            out["released_mb"] = out["torch_reserved_mb"] - mb(t.cuda.memory_reserved())
        free, total = t.cuda.mem_get_info()
        out["free_mb"] = mb(free); out["total_mb"] = mb(total)
        return out
    except Exception as exc:                        # noqa: BLE001
        return {"error": str(exc)[:120]}


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


def _write_source(path: Path, text: str) -> None:
    """A repository file written with its OWN line endings: Python's text mode
    turns every \\n into \\r\\n on Windows, so a one-line edit from the app
    rewrote a whole LF file (G-236, run 67)."""
    crlf = path.exists() and b"\r\n" in path.read_bytes()
    data = text.replace("\r\n", "\n")
    path.write_text(data.replace("\n", "\r\n") if crlf else data, encoding="utf-8", newline="")


def _source_file(url: str):
    """(path, module, editable) for a ``code://`` python module (P-C1), or
    None. ``code://repo/`` is this package and is editable; ``code://pypi/``
    an installed one, found where Python imports it from, read-only."""
    from ..source import source_path_of
    got = source_path_of(url)
    if not got or not got[1].endswith(".py"):
        return None
    root, rel = got
    mod = re.sub(r"(/__init__)?\.py$", "", rel).replace("/", ".")
    if root == "repo":
        base = Path(__file__).resolve().parents[1]
        path = (base / rel).resolve()
        if base not in path.parents:
            return None
        return path, "domvec." + mod, True
    if root == "pypi":
        import importlib.util
        # A single-file module is its own top (`typing.py`), as `blackbox.module_url` writes it.
        top = re.sub(r"\.py$", "", rel.split("/", 1)[0])
        try:
            spec = importlib.util.find_spec(top)
        except (ImportError, ValueError):
            spec = None
        if spec is None or not spec.origin:
            return None
        base = Path(spec.origin).resolve().parent
        path = (base.parent / rel).resolve() if spec.submodule_search_locations else (base / rel).resolve()
        return (path, mod, False) if path.exists() else None
    return None


#: Planted: no codebase sync -- a module reaches the store only when saved
#: through the plugin (`POST /source`), as before.
PLANT_NO_CODE_SYNC = [False]
_CODE_SYNC_LOCK = threading.Lock()
#: The pass in progress, for `GET /code/sources` (the harness polls it: the
#: first pass over 145 modules took ~17 min behind live capture).
_CODE_SYNC_STATE = {"running": False, "done": 0, "total": 0, "current": "", "started": 0.0, "last": None}


#: Planted (2026-11-15): a module's parse and code graph built while holding
#: the work lock, as before.
PLANT_CODE_SYNC_PREPARE_LOCKED = [False]

#: Planted: the plugin's TypeScript is not walked (`code://repo/` only), as
#: before 2026-11-15.
PLANT_NO_PLUGIN_SOURCE = [False]
#: Planted: the repository's code-sync thread runs again (G-375 retired it).
PLANT_CODE_SYNC = [False]
#: Planted: the `/package` route indexes this repository and installed packages again (G-375 closed it).
PLANT_PACKAGE_ROUTE = [False]
#: Planted: the chat cell streams through GPT4All again, ungated (G-385 moved it to llama.cpp on CUDA).
PLANT_CHAT_GPT4ALL = [False]


def _sync_code(workspace, *, limit: Optional[int] = None, forget=()) -> Dict:
    """The codebase into the trie, as it is on disk NOW (PLUGIN_GOAL 159: "the
    completeness of results to be for all code artifacts in our db").

    A module reached the store only when saved through the plugin
    (`POST /source`); written or edited any other way -- git, an editor, a
    session like this one -- it was never indexed. Measured 2026-11-14: 18 of
    145 `domvec/` modules had no chunk at all (`chat.py`, `models.py`,
    `front.py`, `slate.py`, `blackbox.py` ...), so a search for the chat
    backend could not return the chat backend, and every module edited since
    its last save was searched as it USED to read.

    O(files) to hash, O(delta) to write: each module's text is hashed and
    compared with the ledger of what was last indexed (`code_index.json`);
    a missing or changed one goes through `index_source` -> `_project_page`,
    the path a save takes. One file per `_WORK_LOCK` hold, standing aside for
    foreground work between files. A module deleted from disk is REPORTED
    (`gone`), never purged: removing pages is not this loop's call."""
    import hashlib
    from ..source import PLUGIN_SUFFIXES, iter_sources, source_url
    out = {"files": 0, "indexed": 0, "unchanged": 0, "failed": 0, "gone": 0, "ms": 0, "planted": bool(PLANT_NO_CODE_SYNC[0])}
    if PLANT_NO_CODE_SYNC[0] or workspace is None or getattr(workspace, "read_only", False):
        return out
    if not _CODE_SYNC_LOCK.acquire(blocking=False):
        out["busy"] = True
        return out
    t0 = time.time()
    try:
        base = Path(__file__).resolve().parents[1]
        ledger_path = Path(workspace.path) / "code_index.json"
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        except Exception:                           # noqa: BLE001
            ledger = {}
        # `forget`: these modules' LEDGER entries only (never their chunks), so
        # the pass treats them as changed -- the check's way to ask for a
        # known delta on a store that is already in sync.
        for u in forget or ():
            ledger.pop(str(u), None)
        seen = set()
        done_now: List[str] = []
        file_ms: List[float] = []
        # Two roots: this package (`code://repo/`) and the plugin's own
        # TypeScript (`code://plugin/`), which draws the panels the reader is
        # looking at. Planted `PLANT_NO_PLUGIN_SOURCE`: the package only.
        todo = [("repo", p, r) for p, r in iter_sources(base)]
        plugin_src = base.parent / "obsidian-plugin" / "src"
        if plugin_src.is_dir() and not PLANT_NO_PLUGIN_SOURCE[0]:
            todo += [("plugin", p, r) for p, r in iter_sources(plugin_src, PLUGIN_SUFFIXES)]
        _CODE_SYNC_STATE.update(running=True, done=0, total=len(todo), current="", started=time.time())
        for root, path, rel in todo:
            url = source_url(root, rel)
            seen.add(url)
            out["files"] += 1
            _CODE_SYNC_STATE["done"] = out["files"]
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                out["failed"] += 1
                continue
            h = hashlib.sha1(text.encode("utf-8")).hexdigest()
            if ledger.get(url) == h:
                out["unchanged"] += 1
                continue
            if limit is not None and out["indexed"] >= limit:
                continue
            _yield_to_foreground()
            _CODE_SYNC_STATE["current"] = url
            tf = time.time()
            try:
                # The parse, trie and code graph are built BEFORE the lock --
                # they touch no store -- and only the store write holds it.
                # Planted PLANT_CODE_SYNC_PREPARE_LOCKED: all of it held.
                if PLANT_CODE_SYNC_PREPARE_LOCKED[0]:
                    with _WORK_LOCK:
                        workspace.index_source(text, rel, root=root)
                else:
                    prep = workspace.prepare_source(text, rel, root=root)
                    with _WORK_LOCK:
                        workspace.index_source(text, rel, root=root, prepared=prep)
                out.setdefault("file_phases", {})[url] = dict(getattr(workspace, "last_source_ms", {}) or {})
                _project_page(workspace, url)
                ledger[url] = h
                out["indexed"] += 1
                done_now.append(url)
                file_ms.append((time.time() - tf) * 1000)
                # Saved per file: a pass cut short by a restart keeps what it
                # did (the first one wrote only at its end, after ~17 min).
                try:
                    ledger_path.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
                except OSError:
                    pass
            except Exception:                       # noqa: BLE001
                out["failed"] += 1
        out["gone"] = sum(1 for u in ledger if u.startswith(("code://repo/", "code://plugin/")) and u not in seen)
        try:
            ledger_path.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
        if done_now:
            _LAST_WRITE[0] = time.time()
        out["sample"] = done_now[:20]
        if file_ms:
            fm = sorted(file_ms)
            out["file_ms_p50"] = round(fm[len(fm) // 2]); out["file_ms_max"] = round(fm[-1])
    finally:
        out["ms"] = round((time.time() - t0) * 1000)
        _CODE_SYNC_STATE.update(running=False, current="", last={k: v for k, v in out.items() if k != "sample"})
        _CODE_SYNC_LOCK.release()
    _profile("code_sync", {k: v for k, v in out.items() if k != "sample"})
    return out


def _code_sync_forever(workspace, stop) -> None:
    """`_sync_code` two minutes after start (the store and the projector warm
    first), then every five: a module written outside the plugin is
    searchable within five minutes of being saved."""
    if stop.wait(120.0):
        return
    while True:
        try:
            _sync_code(workspace)
        except Exception as exc:                    # noqa: BLE001
            _profile("code_sync", {"error": str(exc)[:160]})
        if stop.wait(300.0):
            return


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
    _project_dedup(workspace)


def _groups_of(workspace, url: str) -> dict:
    """cid -> the chunk that leads its merge group ("" when it leads none)."""
    return {r[0]: (r[1] or "") for r in workspace.store._rows(
        "MATCH (c:Chunk {url: $u}) RETURN c.cid, c.group_of", {"u": url})}


def _project_regrouped(workspace, url: str, before: dict) -> int:
    """After a re-cluster, queue only what it CHANGED for re-projection
    (G-13, 2026-10-30): a chunk whose group changed, the leads on both sides
    of that change (their vectors are recomputed), a chunk the projector does
    not place yet, and one it places that the page has lost.

    `_project_page` here re-queued the whole page on every re-cluster, and a
    re-cluster follows every quiet gap of a live page: drains of 60-129 chunks
    for a feed adding two, measured on the busy feed -- O(page) per mutation
    where the trie's fold is O(delta). Planted `PLANT_PROJECT_WHOLE_PAGE`."""
    if PLANT_PROJECT_WHOLE_PAGE[0]:
        _project_page(workspace, url)
        return -1
    try:
        from .projector import projector as _get
        got = _get()
        if got is None or not url:
            return 0
        now = _groups_of(workspace, url)
        with got.lock:
            held = set(got.by_url.get(url) or ())
            placed = set(c for c in now if c in got.pos)
        changed = set()
        for cid, lead in now.items():
            if before.get(cid) != lead:
                changed.add(cid)
                changed.update(x for x in (lead, before.get(cid)) if x)
        fresh = set(now) - placed
        gone = held - set(now)
        want = (changed | fresh | gone)
        if want:
            got.enqueue(sorted(want))
        ws = got.window_stats
        ws["regroups"] = ws.get("regroups", 0) + 1
        ws["regroup_queued"] = ws.get("regroup_queued", 0) + len(want)
        ws["regroup_page_chunks"] = ws.get("regroup_page_chunks", 0) + len(now)
        _project_dedup(workspace)
        return len(want)
    except Exception:                               # noqa: BLE001
        return 0



def _project_dedup(workspace) -> int:
    """Chunks on OTHER pages whose drawing a write changed (2026-10-29: one
    content, one drawn chunk, store-wide) -- a copy promoted when its lead
    went, a lead demoted -- to the projector, which adds or removes them."""
    store = getattr(workspace, "store", None)
    changed = getattr(store, "dedup_changed", None)
    if not changed:
        return 0
    cids = list(changed)
    changed.clear()
    _project(cids)
    return len(cids)


_LEXICAL_SAVED_AT = [0.0]

#: The lexical version last seen by `_warm_lexical`, and when it was first
#: seen at that version.
_LEX_WARM = {"version": None, "since": 0.0, "warmed": 0}
#: Planted (2026-11-15): tf-idf rebuilt by the first SEARCH after a write, as
#: before -- tier 1's lexical phase read 0.78-0.94 s after a capture, 20 ms
#: at rest.
PLANT_NO_LEXICAL_WARM = [False]


def _warm_lexical(workspace, quiet_s: float = 0.75) -> bool:
    """Rebuild the tf-idf weights in the background once the matrix has
    stopped changing, so the next search finds them built. Takes only the
    matrix's own lock -- what the search would have taken to build them
    itself -- never `_WORK_LOCK`. Never raises; True when it warmed."""
    if PLANT_NO_LEXICAL_WARM[0]:
        return False
    try:
        freq = getattr(workspace, "freq", None)
        if freq is None:
            return False
        version = getattr(freq, "version", 0)
        now = time.monotonic()
        if version != _LEX_WARM["version"]:
            _LEX_WARM.update(version=version, since=now)
            return False
        if getattr(freq, "_tfidf", None) is not None or now - _LEX_WARM["since"] < quiet_s:
            return False
        started = time.perf_counter()
        freq.tfidf()
        _LEX_WARM["warmed"] += 1
        _profile("lexical_warm", {"ms": round((time.perf_counter() - started) * 1000, 1),
                                  "version": version})
        return True
    except Exception:                               # noqa: BLE001
        return False


def _save_lexical_due(workspace, every: float = 30.0) -> None:
    """Persist the frequency matrix at most every `every` seconds, if it
    changed. Never raises."""
    now = time.monotonic()
    if now - _LEXICAL_SAVED_AT[0] < every:
        return
    _LEXICAL_SAVED_AT[0] = now
    # Only the SNAPSHOT holds a lock; the 25.7 MB npz and 53.9 MB of JSON are
    # written outside both `_WORK_LOCK` and the matrix's own lock, which every
    # search's `similarities` takes. Held across the write, a save stalled
    # concurrent search-field calls for 7-16 s (2026-11-15: `lexical_save`
    # 16.3, 11.2 and 10.0 s in exactly the window of the stalls). Planted
    # `vectors.PLANT_LEXICAL_SAVE_LOCKED`: the write under both, as before.
    from domvec import vectors as _vectors
    try:
        started = time.perf_counter()
        planted = _vectors.PLANT_LEXICAL_SAVE_LOCKED[0]
        wrote = False
        # `ms` used to start BEFORE the lock was taken, so it mixed the wait
        # with the work: one read 151.5 s (2026-11-15), most of it queued
        # behind other holders. Wait, hold and write are now three numbers.
        with _WORK_LOCK:
            got = time.perf_counter()
            snap = workspace.lexical_snapshot()
            if planted and snap is not None:
                with workspace.freq._lock:
                    wrote = workspace.write_lexical(snap)
            held = time.perf_counter() - got
        w0 = time.perf_counter()
        if not planted and snap is not None:
            wrote = workspace.write_lexical(snap)
        if wrote:
            _profile("lexical_save", {
                "ms": round((time.perf_counter() - started) * 1000, 1),
                "ms_wait": round((got - started) * 1000, 1),
                "ms_locked": round(held * 1000, 1),
                "ms_write_unlocked": round((time.perf_counter() - w0) * 1000, 1),
                "planted": planted})
    except Exception:                               # noqa: BLE001
        pass


_EMBED_SAVED_AT = [0.0]


_REQUEUED_AT = [0.0]


def _requeue_unembedded_due(workspace, every: float = 60.0) -> None:
    """Every `every` seconds of an idle embedder: stored chunks with text
    and no vector that nothing would embed go back in the queue
    (`Workspace.requeue_unembedded`). Under the work lock for the one read.
    Never raises."""
    now = time.monotonic()
    if now - _REQUEUED_AT[0] < every or not hasattr(workspace, "requeue_unembedded"):
        return
    _REQUEUED_AT[0] = now
    try:
        started = time.perf_counter()
        with _WORK_LOCK:
            got = workspace.requeue_unembedded()
        if got.get("found"):
            _profile("embed_requeue", dict(got, ms=round((time.perf_counter() - started) * 1000, 1)))
        if got.get("requeued"):
            _EMBED_WANTED.set()
    except Exception as exc:                        # noqa: BLE001
        _profile("embed_requeue", {"error": str(exc)[:160]})


def _save_embeddings_due(workspace, every: float = 120.0) -> None:
    """Persist the query-side embedding matrix (`EmbeddingMatrix.load`'s
    cache) at most every `every` seconds, if it changed. The copy is taken
    under the matrix lock, the ~264 MB write outside every lock. Never raises."""
    now = time.monotonic()
    if now - _EMBED_SAVED_AT[0] < every:
        return
    _EMBED_SAVED_AT[0] = now
    try:
        started = time.perf_counter()
        if workspace.save_embeddings():
            _profile("embed_save", {"ms": round((time.perf_counter() - started) * 1000, 1),
                                    "rows": len(workspace.embeddings.rows)})
    except Exception as exc:                        # noqa: BLE001
        _profile("embed_save", {"error": str(exc)[:160]})


#: Seconds without a store write before a page is re-clustered (137(20)).
_AGGREGATE_QUIET_S = 8.0
#: Planted (137(20)): re-cluster as soon as due, mid-stream.
PLANT_AGGREGATE_MID_STREAM = [False]
_AGGREGATE_STATS = {"deferred": 0}


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
        # Not while captures are landing (137(20), bandcamp 2026-11-08): the
        # aggregate holds `_WORK_LOCK` for ~6 s, and on a page that streams the
        # next capture queued behind it -- lock wait p50 3.7 s of a 7.7 s
        # capture. Deferred until the store has been quiet a few seconds.
        # Planted `aggregate-mid-stream`: it runs as soon as due, as before.
        if (not PLANT_AGGREGATE_MID_STREAM[0]
                and time.time() - _LAST_WRITE[0] < _AGGREGATE_QUIET_S):
            _AGGREGATE_AFTER[url] = now + _AGGREGATE_QUIET_S
            _AGGREGATE_STATS["deferred"] += 1
            continue
        _AGGREGATE_AFTER.pop(url, None)
        try:
            _yield_to_foreground()
            asked = time.perf_counter()
            with _WORK_LOCK:
                got_lock = time.perf_counter()
                grouped = _groups_of(workspace, url)
                workspace.aggregate(url)
            # Merge groups changed, so which chunk leads and which vector it
            # speaks with changed too: the projector re-places what changed.
            _project_regrouped(workspace, url, grouped)
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
            _save_embeddings_due(workspace)
            _requeue_unembedded_due(workspace)
            _warm_lexical(workspace)
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
                produced = _encode_sliced(workspace, taken)
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
                    # What this batch stored, not queue-before minus
                    # queue-after: chunks arriving during a slow encode
                    # cancelled the batch out (2026-11-22: a 619 s encode
                    # under a game read "embedded 0" with the queue at 56).
                    "embedded": len(produced or ()),
                    "taken": len(taken or ()),
                    "net_drain": before - remaining,
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


#: The EGO SET (PLUGIN_GOAL 74, 78; RESERVOIR_DESIGN 10.4-10.7): the
#: computation graph's artifacts as the plugin's craft holds them (`urls`,
#: posted on each rebuild) and the web chunks the reader TAGGED into the ego
#: (`cids`, persisted in the workspace as `ego.json`).
EGO = {"urls": set(), "cids": set(), "loaded": ""}
#: Planted (item 78): `where` ignored -- ego and web retrieve alike.
PLANT_NO_WHERE = [False]
#: Planted (item 79): a note's `maps` toggle ignored -- its refs resolve anywhere.
PLANT_NO_MAPS = [False]
#: Planted (item 100): unnesting a box shows no search results.
PLANT_NO_INSTANT = [False]


def _ego_file(workspace):
    return Path(getattr(workspace, "path", ".")) / "ego.json"


def ego_load(workspace) -> None:
    f = _ego_file(workspace)
    if EGO["loaded"] == str(f):
        return
    EGO["loaded"] = str(f)
    try:
        EGO["cids"] = set(json.loads(f.read_text(encoding="utf-8")).get("cids") or [])
    except Exception:                               # noqa: BLE001 -- none yet
        EGO["cids"] = set()


def ego_save(workspace) -> None:
    try:
        _ego_file(workspace).write_text(json.dumps({"cids": sorted(EGO["cids"])}), encoding="utf-8")
    except Exception:                               # noqa: BLE001
        pass


#: Planted (item 76): the ego projected by the WORLD's fit, as before -- the
#: craft's places taken from the world bearings, no projection of its own.
PLANT_WORLD_PROJECTION = [False]


def ego_projection(workspace) -> Dict:
    """The ego's OWN projection (PLUGIN_GOAL 76, binding; RESERVOIR_DESIGN
    10.4): each ego artifact's KNOWLEDGE KEY -- its trie address, a note's
    `vault://` url or a tagged chunk's cid -- placed by its embedding alone,
    projected among the ego set only, never by the world's fit. A note's
    embedding is the mean of its chunks'. UMAP once the set holds 15 or more
    (it needs neighbours); below that, PCA of the same vectors. Places are
    centred and scaled into the unit ball."""
    import numpy as np
    ego_load(workspace)
    if PLANT_WORLD_PROJECTION[0]:
        return {"method": "world", "n": 0, "places": {}, "missing": []}
    idx = getattr(workspace, "index", None)
    emb = getattr(idx, "embeddings", None)
    if idx is None or emb is None or emb.matrix is None:
        return {"method": "none", "n": 0, "places": {}, "missing": sorted(EGO["urls"]) + sorted(EGO["cids"])}
    keys, vecs, missing = [], [], []
    rows = len(idx.freq.rows)
    def vec_of_cid(cid):
        r = emb.row_of(cid)
        return None if r is None else np.asarray(emb.matrix[r], dtype=np.float64)
    for url in sorted(EGO["urls"]):
        got = [vec_of_cid(idx.freq.rows[int(r)]) for r in idx._rows_of_url(url, rows)]
        got = [v for v in got if v is not None and np.any(v)]
        if got:
            keys.append(url); vecs.append(np.mean(got, axis=0))
        else:
            missing.append(url)
    for cid in sorted(EGO["cids"]):
        v = vec_of_cid(cid)
        if v is not None and np.any(v):
            keys.append(cid); vecs.append(v)
        else:
            missing.append(cid)
    n = len(keys)
    if n == 0:
        return {"method": "none", "n": 0, "places": {}, "missing": missing}
    X = np.stack(vecs)
    X = X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-9)
    if n >= 15:
        import umap as _umap
        Y = _umap.UMAP(n_components=3, metric="cosine", n_neighbors=min(15, n - 1), random_state=0).fit_transform(X)
        method = "umap"
    elif n >= 2:
        Xc = X - X.mean(axis=0)
        _, _, vt = np.linalg.svd(Xc, full_matrices=False)
        Y = Xc @ vt[:3].T
        if Y.shape[1] < 3:
            Y = np.pad(Y, ((0, 0), (0, 3 - Y.shape[1])))
        method = "pca"
    else:
        Y = np.zeros((1, 3)); method = "single"
    Y = Y - Y.mean(axis=0)
    scale = float(np.max(np.linalg.norm(Y, axis=1))) or 1.0
    Y = Y / scale
    return {"method": method, "n": n, "missing": missing,
            "places": {k: [round(float(a), 4) for a in y] for k, y in zip(keys, Y)}}


def key_vectors(workspace, keys) -> Dict:
    """An embedding per knowledge key: a cid's own vector, a url's mean over
    its chunks (as `ego_projection` takes them). Keys with none are left out."""
    import numpy as np
    idx = getattr(workspace, "index", None)
    emb = getattr(idx, "embeddings", None)
    if idx is None or emb is None or emb.matrix is None:
        return {}
    rows = len(idx.freq.rows)
    out = {}
    for key in keys:
        key = str(key)
        if "://" in key:
            vs = []
            for r in idx._rows_of_url(key, rows):
                er = emb.row_of(idx.freq.rows[int(r)])
                if er is not None:
                    vs.append(np.asarray(emb.matrix[er], dtype=np.float64))
            if vs:
                out[key] = np.mean(vs, axis=0)
        else:
            er = emb.row_of(key)
            if er is not None:
                out[key] = np.asarray(emb.matrix[er], dtype=np.float64)
    return {k: v / max(float(np.linalg.norm(v)), 1e-9) for k, v in out.items() if np.any(v)}


def pairwise(workspace, keys) -> Dict:
    """The halo's lateral geometry (PLUGIN_GOAL 81): cosine similarity between
    every two of the retrieved results, mapped to 0..1."""
    import numpy as np
    vecs = key_vectors(workspace, keys)
    have = [str(k) for k in keys if str(k) in vecs]
    if not have:
        return {"keys": [], "sim": []}
    X = np.stack([vecs[k] for k in have])
    S = np.clip((X @ X.T + 1.0) / 2.0, 0.0, 1.0)
    return {"keys": have, "sim": [[round(float(x), 4) for x in row] for row in S]}


#: The code graph web (PLUGIN_GOAL 93-95): built off the request path at start,
#: its module PageRank handed to the index as a retrieval term for code chunks.
CODEGRAPH = {"graph": None, "ms": 0, "error": ""}

#: What the browser cell in use shows, as the plugin last told it (G-279).
BROWSER_STATE: dict = {"url": "", "title": "", "at": 0.0}

#: Planted: tool calls leave no run -- only cell runs reach the dependency graph,
#: as before THROUGH_STACK_SYNTHESIS item 1.
PLANT_NO_CALL_RUNS = [False]


def record_call(workspace, caller: str, call: str, inputs, ok: bool, output: str):
    """A TOOL call as a run of the dependency graph (THROUGH_STACK_SYNTHESIS
    1c, item 1): the same `Run` / `RunInput` a cell run writes (G-279), keyed
    by its CALLER where a cell run is keyed by its note -- the cell's note when
    a cell called, `mcp://<tool>` for an agent, `plane://<tool>` for a card,
    `model://<role>` for a model job. Line -1 marks a call. Its inputs are the
    chunks it read or acted on, so `/signal` draws it and `/inverse_map` finds
    it from any of them. Returns the run id, or None when not recorded."""
    if PLANT_NO_CALL_RUNS[0] or workspace is None or getattr(workspace, "read_only", False) or not caller:
        return None
    try:
        with _WORK_LOCK:
            return workspace.store.record_run(str(caller), -1, str(call), [(n, c) for n, c in inputs if c],
                                              bool(ok), str(output or "")[:2000])
    except Exception:                               # noqa: BLE001 -- a record never fails the call
        return None


def _call_text(name: str, args: dict) -> str:
    return "%s(%s)" % (name, ", ".join("%s=%r" % (k, v) for k, v in args.items() if v not in (None, "", False)))


#: G-205: the one retrieval artifact per sidecar -- session-only (177 d).
BROWSE: dict = {"session": None}


def browse_session(workspace):
    """The sidecar's `browse.Session`, made on first use: its search is
    `search_payload` (the same ranking, collapse and previews the overlay
    uses) and its forms are the index's page urls with their dual-similarity
    edges -- the two embeddings, never a layout."""
    if BROWSE["session"] is None:
        from .. import browse as _browse, hierank as _hierank

        def _search(query, k, urls):
            got = search_payload(workspace, query, k, urls=list(urls or ()))
            return [{"cid": h.get("cid"), "url": h.get("url"), "xpath": h.get("xpath"),
                     "preview": h.get("preview") or "", "score": h.get("score")}
                    for h in (got.get("hits") or [])]

        def _forms():
            urls, lex, sem = workspace.index.page_forms()
            keep = [i for i, u in enumerate(urls) if _hierank.page_of(u) == u]
            urls, lex, sem = [urls[i] for i in keep], lex[keep], sem[keep]
            return urls, (_hierank.dual_similar(urls, lex, sem) if urls else [])

        BROWSE["session"] = _browse.Session(_search, _forms)
    return BROWSE["session"]


def _build_codegraph(workspace) -> None:
    import time as _t
    t0 = _t.perf_counter()
    try:
        from ..codegraph import CodeGraph
        root = Path(__file__).resolve().parents[1]
        g = CodeGraph(root, Path(getattr(workspace, "path", ".")) / "codegraph.json").build()
        CODEGRAPH["graph"] = g
        # url -> its module's percentile, for every code:// page the store
        # holds -- computed whether or not an index exists yet: a fresh
        # sidecar builds its index lazily, and the ranks gated on it were never
        # computed at all (G-318: 0 pages ranked). `_ensure_code_rank` hands
        # them to whichever index is current.
        ranks = {}
        for url in workspace.store.page_urls():
            if url.startswith("code://repo/"):
                m = g.module_of_url(url)
                if m in g.rank:
                    ranks[url] = g.rank[m]
        CODEGRAPH["ranks"] = ranks
        _ensure_code_rank(workspace)
    except Exception as exc:                        # noqa: BLE001 -- retrieval goes on without it
        CODEGRAPH["error"] = "%s: %s" % (type(exc).__name__, exc)
    CODEGRAPH["ms"] = round((_t.perf_counter() - t0) * 1000)


def _ensure_code_rank(workspace) -> int:
    """The code graph's ranks on whichever index is CURRENT: the sidecar
    replaces its index as the store grows, and the ranks were set on the one
    that existed when the graph was built (G-318 read 0 pages ranked)."""
    ranks = CODEGRAPH.get("ranks")
    idx = getattr(workspace, "index", None)
    if ranks and idx is not None and getattr(idx, "code_rank", None) is not ranks:
        idx.code_rank = ranks
    return len(getattr(idx, "code_rank", None) or {})


def _ego_hits(workspace, query: str, want: int) -> list:
    """The ego's ranking: each ego page ranked WITHIN itself (the index's
    `scope_url`), a tagged chunk through its own page, merged by score --
    only ego artifacts, never the corpus ranked end to end."""
    ego_load(workspace)
    urls = set(EGO["urls"])
    for cid in EGO["cids"]:
        c = workspace.store.chunk(cid)
        if c is not None:
            urls.add(c.url)
    hits = []
    for u in urls:
        try:
            got = workspace.search(query, k=max(8, want), scope_url=u)
        except Exception:                           # noqa: BLE001 -- one page's failure is not the ego's
            continue
        for h in got or []:
            cid = getattr(h, "cid", None) or getattr(h, "chunk", "")
            if u in EGO["urls"] or cid in EGO["cids"]:
                hits.append(h)
    hits.sort(key=lambda h: -float(getattr(h, "score", 0.0) or 0.0))
    return hits[:want]


#: A slate's search state (`vault._tag_slate`): `/state`, `/state[2]`, at any depth.
_STATE_STEP = re.compile(r"/state(\[\d+\])?(/|$)")


def _in_ego(stored) -> bool:
    return stored.cid in EGO["cids"] or stored.url in EGO["urls"]


def search_payload(workspace, query: str, k: int = 8, *,
                   offset: int = 0, url: str = "",
                   coarse: bool = True, budget: int = 0, where: str = "", trace: int = 0,
                   ref: str = "", rank: str = "", urls: Sequence[str] = ()) -> Dict:
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

    **Keyed by a chunk** (`ref`, G-372 step 2): "similar" on a result -- the
    same ranking, its lexical and semantic factors read from that chunk's
    stored rows, no encoder call. `query` is then only the label echoed back.
    """
    want = max(1, offset + k)
    _ensure_code_rank(workspace)
    # Scoped means ranked WITHIN the page, and the index does that itself now
    # (`scope_url`). It used to be a post-filter over a widened global top-k,
    # bounded so that scoping a large page did not rank the corpus end to
    # end -- and that bound was the defect: RFC 9110's 1,173 chunks rank
    # below the bound globally, so scoping to the largest page in the store
    # returned 0 hits for every query.
    # `n` for "showing {k}/{n} results" (PLUGIN_GOAL 86): the chunks the
    # ranking gives a positive score at all -- before duplicate content and
    # merge groups collapse, so it bounds what scrolling can reach from above.
    # Refilled, not truncated: the coarse and redundant filters below drop
    # members and copies, and a page of k asked for exactly k came back
    # EMPTY once content ranked first ("okapi": 220 matches, 0 hits,
    # 2026-11-01). Asked again four times as deep while the page is short
    # and the ranking had more. Planted `PLANT_NO_REFILL`.
    while True:
        from ..search import SearchDiagnostics
        diag = SearchDiagnostics()
        # The search's own computation graph, per stage (G-372): asked by
        # `?trace=k`, recorded by the ranking, never by a second search.
        diag.want_trace = max(0, min(int(trace or 0), 200))
        if where == "ego" and not url and not ref and not PLANT_NO_WHERE[0]:
            # The EGO ranked over its own pages only (item 78): a scoped
            # ranking per ego page, merged by score -- a filter over the whole
            # corpus's ranking refilled to k=4096 on every call, a few ego
            # chunks among 60k, and an ego search took seconds (G-309).
            hits = _ego_hits(workspace, query, want)
        else:
            try:
                hits = workspace.search(query, k=want, scope_url=url or "", diagnostics=diag,
                                        **({"ref": ref} if ref else {}),
                                        **({"rank": rank} if rank else {}),
                                        **({"scope_urls": list(urls)} if urls else {}))
            except TypeError:                   # an index without diagnostics
                hits = workspace.search(query, k=want, scope_url=url or "")
        import time as _time
        _t_shape = _time.perf_counter()
        out = []
        spent = 0
        echoes = 0
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
            # Ego or web (item 78): `ego` keeps only the ego set; `web` keeps
            # the world -- everything but the computation graph's own notes
            # (a tagged web chunk is in both). Unset: everything, as before.
            # T-13 (PLUGIN_GOAL 145): a notebook cell's OUTPUT is retrievable
            # in the ego scope only, unless asked for -- the vault reader roots
            # it at an `output` step, so the rule reads the trie, not the text.
            # Planted PLANT_OUTPUTS_EVERYWHERE: outputs in every scope.
            if (where != "ego" and not PLANT_OUTPUTS_EVERYWHERE[0] and str(stored.url).startswith("vault://")
                    and ("/output" in str(stored.xpath or "") or _STATE_STEP.search(str(stored.xpath or "")))):
                continue
            # A results page saying the query back (`_echoes`): it was made
            # from the query, so matching it says nothing about the corpus.
            if query and not ref and not PLANT_NO_ECHO_RULE[0] and _echoes(stored, query):
                echoes += 1
                continue
            if where and not PLANT_NO_WHERE[0]:
                ego_load(workspace)
                if where == "ego" and not _in_ego(stored):
                    continue
                if where == "web" and stored.url in EGO["urls"]:
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
                "content": float(getattr(hit, "content", 1.0)),
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

        if len(out) >= offset + k or len(hits) < want or want >= 4096 or PLANT_NO_REFILL[0]:
            break
        want = min(4096, want * 4)

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
            "scope": url or "", "coarse": bool(coarse), "where": where or "",
            #: Which fuse ranked them (PLUGIN_GOAL 85: "additive" by default).
            "fuse": getattr(diag, "fuse", ""),
            "tokens": spent if budget else sum(r["tokens"] for r in out),
            #: True while the ranking still had more to give at this depth,
            #: so a scrolling overlay knows whether to keep asking.
            "more": len(hits) >= want,
            "n": int(getattr(diag, "survivors", 0) or 0),
            "code_partitions": getattr(diag, "code_partitions", None),
            "echoes": echoes,
            **({"ref": ref, "encoder_calls": int(getattr(diag, "encoder_calls", 0) or 0)} if ref else {}),
            **({"trace": dict(diag.trace, shape=[r["cid"] for r in out], survivors=int(getattr(diag, "survivors", 0) or 0),
                              laps=dict(getattr(diag, "ms", None) or {}))}
               if getattr(diag, "trace", None) else {}),
            # Where the time went: the ranking's phases, its store reads, and
            # this reshaping's own (one more read per hit).
            "timing": dict(getattr(diag, "ms", None) or {}, select_reads=getattr(diag, "select_reads", 0),
                           shape=round((_time.perf_counter() - _t_shape) * 1000, 1))}


#: Requests in flight: thread id -> (started, request line). Read by the
#: stall watchdog (`_stall_watchdog`), nothing else.
_INFLIGHT: Dict[int, tuple] = {}
_STALL_DUMPED = [0.0]
#: `/page_status` answers by (url, cids?), each with the time it was made,
#: and one lock per key so concurrent asks share one scan.
_STATUS_MEMO: Dict[tuple, tuple] = {}
_STATUS_MEMO_GATES: Dict[tuple, threading.Lock] = {}
_STATUS_MEMO_GUARD = threading.Lock()
_STATUS_MEMO_S = 4.0
#: Serialises chunk-level layouts (see the `/layout` route).
_CHUNK_LAYOUT_LOCK = threading.Lock()
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Domvec-Client")
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
            url = _document_url(str(body.get("url") or ""))
            items = [it for it in (body.get("items") or []) if it.get("id") and str(it.get("text") or "").strip()][:400]
            if not url or not items:
                self._send(200, {"pos": {}, "hsv": {}})
                return
            try:
                t0 = time.perf_counter()
                with _foreground_encoder():
                    t1 = time.perf_counter()
                    if t1 - t0 > _PROJECT_CLIENT_S:
                        # The browser stopped waiting; encoding now would hold
                        # the GPU for no one.
                        _ENCODER_STATS["project_stale"] += 1
                        M = None
                    else:
                        M = self.workspace.embedder.embed_texts([str(it["text"])[:4000] for it in items])
                if M is None:
                    _profile("project", {"url": url, "n": len(items), "lock": round((t1 - t0) * 1000, 1), "stale": True})
                    self._send(503, {"error": "waited past the client's timeout", "lock_ms": round((t1 - t0) * 1000, 1)})
                    return
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
            # the role's TYPE or the reason it is not (`domvec/models.py`).
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            role = str(body.get("role") or "")
            from .. import models as _mt
            # Every RUNNABLE role of the one model table (synthesis 1b): triplex
            # over a chunk, the prose + code roles over a prompt. `jev` needs
            # logits gpt4all does not give, and says so.
            runnable = [r for r, sp in _mt.ROLES.items() if sp.get("runnable", True)]
            if role in _mt.ROLES and role not in runnable:
                # Its own reason, from the table -- not a list of other roles.
                self._send(400, {"error": "%s is not runnable here: %s" % (role, _mt.ROLES[role].get("why") or "no reason recorded")})
                return
            if role not in runnable or self.workspace is None:
                self._send(400, {"error": "role one of %s, with a workspace" % ", ".join(runnable)})
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
                got = _snaps.save(self.workspace, body.get("items") or [], lock=_WORK_LOCK)
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
            cur = getattr(module, attr)
            if isinstance(cur, list):           # a one-element flag list
                cur[0] = bool(body.get("on"))
                now = cur[0]
            else:
                setattr(module, attr, bool(body.get("on")))
                now = getattr(module, attr)
            self._send(200, {"name": name, "on": now})
            return

        if route == "browse":
            # G-205's one tool: a move on the session's retrieval artifact
            # (`domvec.browse`). Returns {artifact, asks, moved, version}; the
            # caller carries the asks out in the reader's own browser cell.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                with _foreground():
                    got = browse_session(self.workspace).call(
                        query=body.get("query"), scope=str(body.get("scope") or "web"), of=str(body.get("of") or ""),
                        down=body.get("down"), up=bool(body.get("up")), act=body.get("act"),
                        k=int(body.get("k") or 10))
                # The move as a run: a query read its results; `down` and
                # `act` acted on the result the cursor is in.
                art = got.get("artifact") or {}
                cur = art.get("cursor") or {}
                if got.get("moved") == "query":
                    ins = [("result%d" % (i + 1), h.get("cid")) for i, h in enumerate(art.get("results") or [])]
                elif got.get("moved") in ("down", "act") and cur.get("cid"):
                    ins = [(got["moved"], cur.get("cid"))]
                else:
                    ins = []
                args = {k: body.get(k) for k in ("query", "scope", "of", "down", "up", "act", "k")}
                got["run"] = record_call(self.workspace, str(body.get("caller") or "tool://browse"),
                                         _call_text("browse", args), ins, True,
                                         "moved %s, v%s" % (got.get("moved"), got.get("version")))
                self._send(200, got)
            except (ValueError, KeyError) as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "slate_check":
            # `check(slate)` in a cell (G-377): the dialect's own errors over a
            # slate's text -- duplicates, self-definitions, cycles, references
            # to nothing (`slate_module.check`). Reads nothing, writes nothing.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            from .. import slate_module as _sm
            diags = _sm.check(str(body.get("text") or ""), body.get("known") or ())
            self._send(200, {"diagnostics": [d.to_json() for d in diags]})
            return

        if route == "cypher":
            # Read-only Cypher over the store (G-279: `Database.cypher` in a
            # cell). A statement that writes or calls a procedure is refused.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            from . import kernel_objects as _ko
            q = str(body.get("query") or "").strip()
            if not q or _ko.WRITES.search(q):
                self._send(400, {"error": "read-only: a query that writes or calls a procedure is refused"})
                return
            try:
                rows = self.workspace.store._rows(q)
            except Exception as exc:                # noqa: BLE001
                self._send(200, {"error": "%s: %s" % (type(exc).__name__, str(exc)[:300])})
                return
            self._send(200, {"rows": [[v if isinstance(v, (str, int, float, bool, type(None))) else str(v) for v in r]
                                      for r in rows[:1000]], "n": len(rows)})
            return

        if route == "dedupe":
            # One content, one drawn chunk, store-wide (2026-10-29): every
            # chunk keyed by its markdown, one lead per content, the flipped
            # chunks handed to the projector. A write, so the writer's lock.
            if self.workspace is None or getattr(self.workspace, "read_only", False):
                self._send(403, {"error": "dedupe writes the store; this sidecar is read-only"})
                return
            got = self.workspace.store.dedupe_store(lock=_WORK_LOCK)
            got["projected"] = _project_dedup(self.workspace)
            got["report"] = self.workspace.store.duplicate_report()
            _profile("dedupe", got)
            self._send(200, got)
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
            due = _compact_due(store_mb, base, time.time(), 0.0, os.environ.get("DOMVEC_SUPERVISED") == "1",
                               _READER_IDLE[0], _LAST_WRITE[0]) if store_mb else False
            self._send(200, {"store_mb": round(store_mb, 1), "base_mb": round(base, 1), "compact": due,
                             "supervised": os.environ.get("DOMVEC_SUPERVISED") == "1"})
            if due:
                threading.Thread(target=_maybe_compact, args=(self.workspace, store_mb), daemon=True).start()
            return

        if route == "browser_state":
            # What the browser in use shows (G-279), told by the plugin every 2 s:
            # a kernel's `WebBrowser.url` reads it back.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                BROWSER_STATE.update({"url": str(body.get("url") or ""), "title": str(body.get("title") or ""), "at": time.time()})
                # G-205: inside a descended result, where the cell goes is a
                # step of that result's trace -- a diff on the artifact.
                stepped = None
                if BROWSE["session"] is not None and BROWSER_STATE["url"]:
                    stepped = BROWSE["session"].observe(BROWSER_STATE["url"])
                self._send(200, {"ok": True, **({"browse_version": stepped["version"]} if stepped else {})})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "vault_root":
            # Where the reader's vault is (G-277): a `{ref}` to a vault note is
            # read from the NOTE's own text -- the store's chunks flatten a
            # slate's tabs and lines, and the grammar saw one line. Kept only
            # when it is a folder on this machine.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                root = str(body.get("root") or "")
                from . import refs as _refs
                _refs.VAULT[0] = root if root and Path(root).is_dir() else ""
                _refs.VAULT[1] = str(body.get("name") or "")
                self._send(200, {"ok": bool(_refs.VAULT[0])})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "unfold_source":
            # A few lines that are no module on disk -- a notebook cell, a
            # selection (PLUGIN_GOAL 112, G-328/G-329): its imports as boxes
            # that unnest to their library modules, its definitions typed.
            from . import blackbox as _bb
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                got = _bb.unfold_source(str(body.get("base") or "cell://"), str(body.get("source") or ""))
                self._send(200, got or {"kind": "cell", "qual": "", "lines": [], "error": "not python"})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "ego/pairwise":
            # The halo's lateral similarities (item 81): {keys} -> a matrix.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                self._send(200, pairwise(self.workspace, list(body.get("keys") or [])[:64]))
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route in ("ego", "ego/tag"):
            # The ego set (items 74, 78): POST /ego {urls} -- the craft's notes,
            # from the plugin on each rebuild; POST /ego/tag {cid, on} -- a web
            # chunk tagged into the ego from its billboard (persisted).
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                ego_load(self.workspace)
                if route == "ego":
                    EGO["urls"] = set(str(u) for u in (body.get("urls") or []))
                else:
                    cid = str(body.get("cid") or "")
                    if not cid:
                        self._send(400, {"error": "missing cid"})
                        return
                    if body.get("on", True):
                        EGO["cids"].add(cid)
                    else:
                        EGO["cids"].discard(cid)
                    ego_save(self.workspace)
                self._send(200, {"urls": len(EGO["urls"]), "cids": sorted(EGO["cids"])})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "slate_check":
            # A slate's -- or a markdown note's trees' -- Python errors
            # (PLUGIN_GOAL 62, 63'): duplicates, self-definitions, cycles,
            # references to nothing, line by line for the editor to draw. A
            # pure function of the text; the kernel's base objects and the
            # cockpit's key stream are names that exist.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                text = str(body.get("text") or "")
                known = [str(k) for k in (body.get("known") or [])] + list(_SLATE_KNOWN)
                from .. import slate_module as _sm
                trees = _sm.trees_of(text)
                # Names the STORE has an artifact by (a note, a page title): a
                # `{ref}` to one resolves through the store -- not a NameError.
                from . import refs as _refs
                for m in _sm.REF.finditer(trees):
                    nm = m.group(1).strip()
                    if nm and nm not in known and _refs.titled(self.workspace, nm):
                        known.append(nm)
                    # A place inside a note (`Note#cell 2`): the note's title.
                    elif "#" in nm and "://" not in nm:
                        base_ = nm.split("#", 1)[0].strip()
                        if base_ and base_ not in known and _refs.titled(self.workspace, base_):
                            known.append(base_)
                diags = [] if PLANT_NO_SLATE_CHECK[0] else _sm.check(trees, known=known)
                self._send(200, {"trees": bool(trees.strip()), "diagnostics": [d.to_json() for d in diags]})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "code/sync":
            # The codebase sync on demand (`_sync_code`); the harness's door.
            # `plant` runs it as before the sync: nothing indexed.
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self._send(403, {"error": "loopback only"})
                return
            if not self.capture_allowed or self.workspace is None:
                self._send(403, {"error": "writing is off (start with --capture)"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") or {}
            except Exception:                       # noqa: BLE001
                body = {}
            if body.get("background") and not body.get("plant"):
                # Started and answered at once; `GET /code/sources` -> `sync`
                # says how far it is. Busy if a pass is already running.
                if _CODE_SYNC_STATE.get("running"):
                    self._send(200, {"started": False, "busy": True, "sync": dict(_CODE_SYNC_STATE)})
                    return
                threading.Thread(target=_sync_code, args=(self.workspace,), kwargs={"forget": list(body.get("forget") or [])},
                                 name="domvec-code-sync-now", daemon=True).start()
                self._send(200, {"started": True})
                return
            was = PLANT_NO_CODE_SYNC[0]
            PLANT_NO_CODE_SYNC[0] = bool(body.get("plant"))
            try:
                self._send(200, _sync_code(self.workspace, limit=body.get("limit"), forget=list(body.get("forget") or [])))
            finally:
                PLANT_NO_CODE_SYNC[0] = was
            return

        if route == "source":
            # A saved code artifact (P-C1/P-C5): the file written, then
            # re-indexed into the trie as the module page it is, and queued for
            # the projector -- the embed gate keeps it a delta (P-N6). This
            # repository's modules only; an installed package is read-only.
            if not self.capture_allowed or self.workspace is None:
                self._send(403, {"error": "writing is off (start with --capture)"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                url, text = str(body.get("url") or ""), body.get("text")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            got = _source_file(url)
            if got is None or not got[2] or not isinstance(text, str):
                self._send(400, {"error": "only this repository's modules (code://repo/...) are saved", "url": url})
                return
            path = got[0]
            if not path.exists() and not body.get("create"):
                self._send(404, {"error": "no such module", "url": url})
                return
            try:
                t0 = time.time()
                v0 = dict(self.workspace.vectors.report())
                with _foreground(), _WORK_LOCK:
                    if not PLANT_SOURCE_NOT_WRITTEN[0]:
                        _write_source(path, text)
                    rel = url[len("code://repo/"):]
                    res = self.workspace.index_source(path.read_text(encoding="utf-8"), rel, root="repo")
                v1 = self.workspace.vectors.report()
                if PLANT_SOURCE_NOT_PROJECTED[0]:
                    # Neither path to the 3D view: not queued for projection,
                    # and dropped from the encoder (whose batches project too).
                    self.workspace.vectors.forget(r[0] for r in self.workspace.store._rows(
                        "MATCH (c:Chunk {url: $u}) RETURN c.cid", {"u": url}))
                else:
                    _project_page(self.workspace, url)
                _LAST_WRITE[0] = time.time()
                out = {"url": url, "chunks": res.chunks, "queued": v1["queued"] - v0["queued"],
                       "skipped": v1["skipped"] - v0["skipped"], "ms": round((time.time() - t0) * 1000)}
                _profile("source", out)
                self._send(200, out)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "vectors":
            # What a restart loses, for one page (P-N6's check): the embed
            # gate's digests for its chunks. The store keeps every vector.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                url = str(json.loads(self.rfile.read(length) or b"{}").get("forget_url") or "")
                cids = [r[0] for r in self.workspace.store._rows(
                    "MATCH (c:Chunk {url: $u}) RETURN c.cid", {"u": url})] if url else []
                for c in cids:
                    self.workspace.vectors.digests.pop(c, None)
                self._send(200, {"forgot": len(cids)})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if route == "note":
            # A vault NOTE into the store as a page (`G-7`, `Workspace.index_note`):
            # the note a reader wrote retrieval links into, so its links are
            # page links like any page's -- relinked, and drawn in 3D. Writes
            # the reader's store, so gated as a capture is (`D-39`).
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            if not self.capture_allowed:
                self._send(403, {"error": "capture is off"})
                return
            if self.plugin_captures_only and self.headers.get("X-Domvec-Client") != "obsidian-plugin":
                self._send(403, {"error": "notes come from the plugin"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                path = str(body.get("path") or "").replace("\\", "/").lstrip("/")
                text = str(body.get("text") or "")
                vault = str(body.get("vault") or "vault")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            if not path.endswith(".md") or ".." in path.split("/"):
                self._send(400, {"error": "a vault-relative .md path"})
                return
            try:
                t0 = time.time()
                with _foreground(), _WORK_LOCK:
                    # Its links resolve at ingest, against the pages held now
                    # (`_link_hyperlinks`); a whole-store relink added nothing
                    # and cost 17 s (2026-10-24).
                    got = self.workspace.index_note(text, path, vault=vault)
                    out = {"url": got.url, "chunks": got.chunks, "lines": got.lines,
                           "links": [t for s, t in self.workspace.store.page_links() if s == got.url]}
                # Placed like a captured page: embedded, then projected. Without
                # this the note was embedded and never placed, so no node and
                # no edge (2026-10-24).
                _project_page(self.workspace, got.url)
                out["ms"] = round((time.time() - t0) * 1000)
                _LAST_WRITE[0] = time.time()
                _profile("note", {k: out.get(k) for k in ("url", "chunks", "ms")})
                self._send(200, out)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
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

        if route == "page_spread":
            # Read-only: is one page's cloud COLLAPSED, and is the cause its
            # INPUTS or its FIT? (G-94, 2026-11-15: Radix_tree's 40 chunks
            # and its page placed within 0.045 units of one point; 6 of 49
            # sampled pages under 0.5 against a median of 4.2.) The page's
            # stored vectors -- how many, how many distinct, their mean
            # pairwise cosine -- against the spread of the positions the
            # projector answers for them and where its page row sits.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                url = str(json.loads(self.rfile.read(length) or b"{}").get("url") or "")
                from .projector import projector as _get_proj
                import numpy as _np
                proj = _get_proj()
                if proj is None or not url:
                    self._send(200, {"url": url, "error": "no projector" if proj is None else "no url"})
                    return
                with proj.lock:
                    cids = sorted(proj.by_url.get(url) or ())
                    vecs = {c: proj.vec[c] for c in cids if c in proj.vec}
                    pos = {c: list(proj.pos[c]) for c in cids if c in proj.pos}
                    page_pos = list(proj.page_pos.get(url) or []) or None
                    page_vec = proj.page_vec.get(url) if hasattr(proj, "page_vec") else None
                    online = list(getattr(proj, "online_updates", []) or [])[-3:]
                    trained = url in (getattr(proj, "trained", None) or ())
                    # The neighbourhood that caps the cloud: `_place_chunks` scales a
                    # page's chunks into NEIGHBOURHOOD x its nearest OTHER page, so a
                    # page drawn on top of this one shrinks it to a point.
                    others = [(u, v) for u, v in proj.page_pos.items() if u != url and v]
                    scale = (getattr(proj, "page_scale", None) or {}).get(url)
                    hood = float(getattr(proj, "NEIGHBOURHOOD", 0.0) or 0.0)
                out = {"url": url, "chunks": len(cids), "with_vector": len(vecs), "with_pos": len(pos),
                       "page_pos": [round(float(x), 3) for x in page_pos] if page_pos else None,
                       "kind": type(proj).__name__, "trained": bool(trained),
                       "online_last": [{k: r.get(k) for k in ("pages_trained", "chunks_trained", "pages_moved", "chunks_moved", "at")} for r in online]}
                if vecs:
                    V = _np.asarray(list(vecs.values()), dtype=_np.float32)
                    norms = _np.linalg.norm(V, axis=1)
                    out["zero_vectors"] = int((norms < 1e-9).sum())
                    U = V / _np.maximum(norms, 1e-9)[:, None]
                    out["distinct_vectors"] = int(len({tuple(_np.round(u, 4)) for u in U}))
                    if len(U) >= 2:
                        G = U @ U.T
                        iu = _np.triu_indices(len(U), 1)
                        out["cos_mean"] = round(float(G[iu].mean()), 4)
                        out["cos_min"] = round(float(G[iu].min()), 4)
                    if page_vec is not None:
                        pv = _np.asarray(page_vec, dtype=_np.float32)
                        pv = pv / max(float(_np.linalg.norm(pv)), 1e-9)
                        out["cos_to_page_mean"] = round(float((U @ pv).mean()), 4)
                if pos:
                    P = _np.asarray(list(pos.values()), dtype=_np.float32)
                    c = P.mean(axis=0)
                    out["pos_centroid"] = [round(float(x), 3) for x in c]
                    out["pos_spread"] = round(float(_np.linalg.norm(P - c, axis=1).mean()), 4)
                    if page_pos:
                        out["page_to_centroid"] = round(float(_np.linalg.norm(_np.asarray(page_pos[:len(c)], dtype=_np.float32) - c)), 4)
                if page_pos and others:
                    O = _np.asarray([v[:len(page_pos)] for _u, v in others], dtype=_np.float64)
                    d = _np.linalg.norm(O - _np.asarray(page_pos, dtype=_np.float64), axis=1)
                    order = _np.argsort(d)[:3]
                    out["nearest_pages"] = [{"url": others[i][0], "dist": round(float(d[i]), 4)} for i in order]
                    out["room"] = round(float(d.min()) * hood, 4)
                    # The cloud's own spacing: every page's nearest-page distance.
                    A = _np.asarray([v[:len(page_pos)] for v in proj.page_pos.values() if v], dtype=_np.float64)
                    if len(A) >= 3:
                        from scipy.spatial import cKDTree as _T
                        dd, _ = _T(A).query(A, k=2)
                        out["page_nn_median"] = round(float(_np.median(dd[:, 1])), 4)
                out["page_scale"] = None if scale is None else round(float(scale), 4)
                self._send(200, out)
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
                    _write_source(path, out["text"])        # its own line endings kept
                    self.workspace.index_source(out["text"], rel, root=root)
                    res["cpg"] = getattr(self.workspace, "last_cpg", None)
                _LAST_WRITE[0] = time.time()
                _project_page(self.workspace, url)
                res["written"] = True
            _profile("cpg_mutate", {"url": url, "ops": out["applied"], "written": res["written"]})
            self._send(200, res)
            return

        if route == "tool_panels":
            # G-382 (PLUGIN_GOAL 170 a, 172 [2]): the kernel's tool panels as
            # pages at tool://kernel/<Name> -- searchable, embedded and placed
            # in 3D like any page. The SERVER renders them from the kernel's
            # own bootstrap; the client sends no text, so this is not a way
            # for a probe to write arbitrary pages (D-39). Gated as a capture.
            if self.workspace is None or not self.capture_allowed:
                self._send(403, {"error": "capture is off"})
                return
            from .. import tool_panels as _tp
            try:
                t0 = time.time()
                with _foreground(), _WORK_LOCK:
                    got = _tp.index(self.workspace)
                for g in got:
                    _project_page(self.workspace, g["url"])
                _LAST_WRITE[0] = time.time()
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
                return
            out = {"panels": got, "ms": round((time.time() - t0) * 1000)}
            _profile("tool_panels", {"n": len(got), "ms": out["ms"]})
            self._send(200, out)
            return

        if route == "dataflow":
            # G-380 (PLUGIN_GOAL 167 f, marimo style): the cells a run makes
            # stale, from the note's own text -- names defined and read, read
            # statically (`dataflow.rerun_plan`). Pure analysis: it reads no
            # store and runs nothing; the plugin re-runs what it names.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                from .. import dataflow as _df
                t0 = time.time()
                out = _df.rerun_plan(str(body.get("markdown") or ""), int(body.get("line", -1)))
                out["ms"] = round((time.time() - t0) * 1000, 2)
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "%s: %s" % (type(exc).__name__, exc)})
                return
            self._send(200, out)
            return

        if route == "code_rows":
            # G-378 (PLUGIN_GOAL 167 c; mortegon M.2-M.5): a python cell as typed
            # rows, and an edit to one row written back losslessly (LibCST).
            # Pure: reads no store and writes no file -- the plugin writes the
            # returned source into the note through its editor.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                from .. import code_rows as _cr
                src = str(body.get("source") or "")
                edit = body.get("edit") or None
                if edit:
                    op, name = str(edit.get("op") or ""), str(edit.get("name") or "")
                    if op == "value":
                        src = _cr.set_value(src, name, str(edit.get("value") or ""))
                    elif op == "type":
                        src = _cr.set_type(src, name, str(edit.get("type") or ""))
                    elif op == "rename":
                        src = _cr.rename(src, name, str(edit.get("to") or ""))
                    else:
                        raise ValueError("an edit is value, type or rename")
                out = {"source": src, "rows": [r.to_json() for r in _cr.rows(src)], "edited": bool(edit)}
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "%s: %s" % (type(exc).__name__, exc)})
                return
            self._send(200, out)
            return

        if route == "package":
            # G-375 (PLUGIN_GOAL 166 a, 167 a "Layout and indexer"): this
            # repository and installed packages are no longer indexed or
            # queued into the projector from the app -- only code scanned in
            # the browser is. `packages.index_tree` stays a library function
            # (tests, analytics). Planted `PLANT_PACKAGE_ROUTE`: open again.
            if not PLANT_PACKAGE_ROUTE[0]:
                self._send(410, {"error": "repository and package code is not indexed (G-375)",
                                 "why": "only code scanned in the browser reaches the store's index and the projector"})
                return
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

        if route == "chat_stream":
            # The plane's CHAT CELL (PLUGIN_GOAL 134): one prompt, its context
            # the cells magnetized around it (sent by the plugin, already
            # truncated), the reply written token by token as the model makes
            # it -- plain text, flushed per token, the connection closed at
            # the end. Its own model session: the browser cell's is closed
            # first and reopens on its next turn. Loopback only.
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self._send(403, {"error": "loopback only"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") or {}
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            prompt = str(body.get("prompt") or "").strip()
            if not prompt:
                self._send(400, {"error": "no prompt"})
                return
            context = [str(c) for c in (body.get("context") or []) if str(c).strip()]
            from .. import chat as _chat
            # `dry_ms`: the turn without the model -- a token a tick for that
            # long -- so the live check can put two turns in flight with the
            # lock planted away and not take the worker down with them.
            dry_ms = float(body.get("dry_ms") or 0)
            unlocked = bool(body.get("plant_unlocked")) and dry_ms > 0
            NL = chr(10)
            text = ("Context, the cells beside this one:" + NL + NL + (NL + NL + "---" + NL + NL).join(context) + NL + NL if context else "") + prompt
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "close")
            self.end_headers()
            t_ask = time.time()
            # G-385 (PLUGIN_GOAL 171): the same Hermes GGUF through llama.cpp on
            # CUDA, holding the GPU gate while it streams. `engine: "gpt4all"`
            # (or planted `PLANT_CHAT_GPT4ALL`) is the old path, kept as the arm.
            engine = str(body.get("engine") or ("gpt4all" if PLANT_CHAT_GPT4ALL[0] else "cuda"))
            lock = nullcontext() if unlocked else _chat.GEN_LOCK
            with lock:
                waited_ms = round((time.time() - t_ask) * 1000)
                be = None
                with _chat._GLOBAL:
                    if _chat._BACKEND[0] is None and not dry_ms and engine == "gpt4all":
                        _chat._BACKEND[0] = _chat.HermesBackend()
                    be = _chat._BACKEND[0]
                    if be is not None and not dry_ms:
                        be.close()
                        _chat._ACTIVE[0] = ""
                # Planted `keep_torch_cache`: torch's cache is left reserved, as
                # before -- the arm that shows what releasing it bought.
                keep = bool(body.get("keep_torch_cache"))
                vram_before = _vram(release=not keep and not dry_ms)
                _chat.IN_FLIGHT["now"] += 1
                in_flight = _chat.IN_FLIGHT["now"]
                _chat.IN_FLIGHT["peak"] = max(_chat.IN_FLIGHT["peak"], in_flight)
                t0 = time.time(); n = 0; t_first = 0.0
                try:
                    if dry_ms:
                        while (time.time() - t0) * 1000 < dry_ms:
                            if not n:
                                t_first = time.time()
                            self.wfile.write(b"."); self.wfile.flush(); n += 1
                            time.sleep(0.05)
                    elif engine == "cuda":
                        from .. import chat_cuda as _cc
                        for tok in _cc.stream(text, max_tokens=int(body.get("max_tokens") or 400)):
                            if not n:
                                t_first = time.time()
                            self.wfile.write(tok.encode("utf-8")); self.wfile.flush(); n += 1
                    else:
                        m = be._load()
                        with m.chat_session(_chat.SYSTEM, _chat.TEMPLATE):
                            for tok in m.generate(text, max_tokens=int(body.get("max_tokens") or 400), temp=0.3, streaming=True):
                                if not n:
                                    t_first = time.time()
                                self.wfile.write(str(tok).encode("utf-8")); self.wfile.flush(); n += 1
                except Exception as exc:                # noqa: BLE001
                    try:
                        self.wfile.write((chr(10) + "[error: %s]" % exc).encode("utf-8"))
                    except Exception:                   # noqa: BLE001
                        pass
                finally:
                    _chat.IN_FLIGHT["now"] -= 1
            # Where the model ran, the time to its first token, and how long
            # this turn queued behind another (PLUGIN_GOAL 159, "several minutes").
            from .. import gpu_gate as _gate                # G-385: did GPU work yield to this turn
            _gate_now = dict(_gate.STATS)
            _profile("chat_stream", {"tokens": n, "context": len(context), "ms": round((time.time() - t0) * 1000),
                                     "first_ms": round((t_first - t0) * 1000) if t_first else None,
                                     "waited_ms": waited_ms, "in_flight": in_flight, "dry": bool(dry_ms), "unlocked": unlocked, "gate": _gate_now,
                                     "engine": engine,
                                     "loaded_on": (getattr(be, "loaded_on", "") if be is not None else "") if engine != "cuda" else __import__("domvec.chat_cuda", fromlist=["x"]).loaded_on(),
                                     "prompt_chars": len(text),
                                     "tok_s": round(n / max(1e-3, time.time() - t_first), 2) if t_first and n > 1 else None,
                                     "kept_torch_cache": keep, "vram_before": vram_before, "vram_after": _vram()})
            self.close_connection = True
            return

        if route == "chat":
            # The browser cell's chat (`G-43`..`G-45`, `domvec/chat.py`): a turn
            # is the reader's prompt plus the chunks pinned since the last
            # reply, each chunk at most once per conversation. Loopback only:
            # it runs a local model and writes nothing to the workspace.
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self._send(403, {"error": "loopback only"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") or {}
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            from .. import chat as _chat
            session = str(body.get("session") or "default")
            try:
                conv = _chat.conversation(session)
                if body.get("reset"):
                    conv.reset()
                    self._send(200, conv.to_json())
                    return
                prompt = str(body.get("prompt") or "").strip()
                if not prompt:
                    self._send(400, {"error": "no prompt"})
                    return
                ctx = [c for c in (body.get("context") or []) if isinstance(c, dict)]
                turn = conv.ask(prompt, ctx)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, str(exc)[:300])})
                return
            be = _chat._BACKEND[0]
            _profile("chat", {"session": session, "delta_chars": turn.delta_chars, "context": len(turn.context),
                              "dropped": len(turn.resent_dropped), "ms": round(turn.ms)})
            self._send(200, {"turn": turn.to_json(), "sent": sorted(conv.sent), "turns": len(conv.turns),
                             "model": _chat.MODEL_FILE, "device": getattr(be, "loaded_on", "")})
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
            # The page's projected chunks go with it, NOW: the store no longer
            # has them, so the drain reports each one gone in the delta and
            # the 3D node leaves with the note. Without this a purged note's
            # chunks stayed drawn until the idle reconcile (180 s) found them
            # -- G-270 read 5 held-not-drawable after G-282/G-284 cleaned up.
            # O(page). Planted PLANT_PURGE_KEEPS_PROJECTED.
            retired = 0
            if not PLANT_PURGE_KEEPS_PROJECTED[0]:
                try:
                    from .projector import projector as _get
                    got = _get()
                    if got is not None:
                        with got.lock:
                            held = list(got.by_url.get(url) or ())
                        if held:
                            retired = got.enqueue(held)
                except Exception:                   # noqa: BLE001
                    pass
            self._send(200, {"url": url, "chunks_removed": removed, "projected_retired": retired})
            return

        if route == "purge_versions":
            # A page's kept versions only (G-253); the page stays. Gated as
            # `/purge` is: it writes the workspace.
            if not self.capture_allowed:
                self._send(403, {"error": "purge is off", "why": "the sidecar holds this workspace read-only."})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            url = (body or {}).get("url") or ""
            if not url or url.endswith("#~v"):
                self._send(400, {"error": "a page url (not its versions' url)"})
                return
            try:
                with _foreground(), _WORK_LOCK:
                    out = self.workspace.purge_versions(url)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
                return
            # Their projected nodes leave now, as `/purge` does: the drain
            # finds each cid gone from the store and reports it in the delta.
            retired = 0
            cids = out.pop("cids", [])
            try:
                from .projector import projector as _get
                got = _get()
                if got is not None and cids:
                    retired = got.enqueue(cids)
            except Exception:                       # noqa: BLE001
                pass
            out["projected_retired"] = retired
            self._send(200, out)
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
                    and self.headers.get("X-Domvec-Client") != "obsidian-plugin"):
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

        # A cell is a function node (G-279, RESERVOIR_DESIGN §4): the `{ref}`
        # tokens on its fence line are its inputs, resolved through the trie
        # and bound into the kernel BEFORE the code runs; the run is recorded
        # as a forward map, inputs -> output. Planted `PLANT_NO_REF_BINDING`:
        # refs are ignored, so the cell meets an unbound name.
        names = [str(n) for n in (body.get("refs") or []) if str(n).strip()]
        bound = {"prelude": "", "bound": [], "inputs": []}
        try:
            # The base objects (`Database`, read-only) before every cell; the
            # bootstrap defines them once per kernel. Planted
            # `PLANT_NO_BASE_OBJECTS`.
            if not PLANT_NO_BASE_OBJECTS[0]:
                from . import kernel_objects as _ko
                port = self.server.server_address[1]
                self.kernel_pool.run(note, _ko.boot("http://127.0.0.1:%d" % port))
                # Who is calling, for the calls that record themselves (`browse`).
                self.kernel_pool.run(note, "_domvec_note = %r" % note)
            # The vault facade (P-N4): `Vault`, and the note's folder as the
            # working directory. Only for a note's kernel, and only under a
            # vault root the plugin names that exists. Planted `PLANT_NO_VAULT`.
            root = str(body.get("vault_root") or "")
            in_vault = bool(root and not note.startswith("code:") and Path(root).is_dir() and not PLANT_NO_VAULT[0])
            if in_vault:
                from . import kernel_objects as _ko
                self.kernel_pool.run(note, _ko.vault_boot(root, note))
            if names and not PLANT_NO_REF_BINDING[0]:
                from . import refs as _refs
                sample = body.get("sample")
                # The note's toggle (PLUGIN_GOAL 79): its inputs from the EGO
                # alone, or from the WEB (the world, without the ego's notes).
                maps = str(body.get("maps") or "")
                allow = None
                ego_search = None
                if maps in ("ego", "web") and not PLANT_NO_MAPS[0]:
                    ego_load(self.workspace)
                    if maps == "ego":
                        allow = lambda url, cid: (cid in EGO["cids"]) or (url in EGO["urls"])
                        ego_search = lambda q: _ego_hits(self.workspace, q, 8)
                    else:
                        allow = lambda url, cid: url not in EGO["urls"]
                bound = _refs.bind(self.workspace, names,
                                   sample=int(sample) if isinstance(sample, (int, float)) else None, allow=allow,
                                   search=ego_search)
                if bound["prelude"]:
                    self.kernel_pool.run(note, bound["prelude"])
            # The note's markdown TREES first (PLUGIN_GOAL 62, 63': the extended
            # markdown cell): compiled into this kernel as the module they are,
            # so the code cell sees the names the markdown binds -- and a tree
            # that fails, fails the cell as importing a broken module would.
            # Planted `PLANT_NO_TREES`.
            md = body.get("markdown")
            trees_reply = None
            if isinstance(md, str) and md.strip() and not PLANT_NO_TREES[0]:
                from .. import slate_module as _sm
                trees = _sm.trees_of(md)
                if trees.strip():
                    tr = self.kernel_pool.run(note, _sm.compile_module(trees))
                    if isinstance(tr, dict) and tr.get("error"):
                        trees_reply = dict(tr, error="in the note's markdown trees:\n" + str(tr["error"]))
            reply = trees_reply if trees_reply is not None else self.kernel_pool.run(note, code)
            if in_vault:
                # The note's folder only for the cell: a process's working
                # directory cannot be removed on Windows, so a kernel parked
                # there would block deleting or renaming the folder (EBUSY).
                self.kernel_pool.run(note, _ko.VAULT_DONE)
            # What the cell's calls asked of the APP (a web search through the
            # browser cell, `search(..., duckduckgo=True)`): drained from the
            # kernel and handed back, for the plugin to carry out.
            if not PLANT_NO_BASE_OBJECTS[0] and not PLANT_NO_ASKS[0] and isinstance(reply, dict):
                from . import kernel_objects as _ko
                asks = _ko.parse_asks(self.kernel_pool.run(note, _ko.DRAIN))
                if asks:
                    reply = dict(reply, asks=asks)
                    # Each ask a call of the cell's note (THROUGH_STACK_SYNTHESIS
                    # 1c), with the chunk it names when it names one. A
                    # `reveal` comes from `browse`, which recorded itself.
                    for a in asks:
                        if not isinstance(a, dict) or "reveal" in a:
                            continue
                        kind = next(iter(a), "")
                        v = a.get(kind)
                        cid = v if kind in ("focus", "attach") and isinstance(v, str) else None
                        record_call(self.workspace, note, _call_text(kind, {"arg": v}),
                                    [(kind, cid)] if cid else [], True, "asked")
        except Exception as exc:                    # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if names and isinstance(reply, dict):
            reply = dict(reply, bound=bound["bound"])
            try:
                out = "\n".join(str(reply.get(k) or "") for k in ("stdout", "value", "error")).strip()
                if not getattr(self.workspace, "read_only", False):
                    with _WORK_LOCK:
                        reply["run"] = self.workspace.store.record_run(
                            note, int(body.get("line") or -1), code, bound["inputs"],
                            bool(reply.get("ok")), out)
            except Exception as exc:                # noqa: BLE001
                reply["run_error"] = "%s: %s" % (type(exc).__name__, exc)
        self._send(200, reply)

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
                    url, context_window=self.workspace.context_window,
                    md_level=getattr(self.workspace.store, "md_level", False)),
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
                    # Timed (2026-10-24: captures waited 5-37 s on the write
                    # lock while settles held it, and no record said so).
                    _ts = time.perf_counter()
                    with _WORK_LOCK:
                        _tl = time.perf_counter()
                        _got = self.workspace.ingest(
                            url, spine.trie, title=(body.get("title") or ""), complete=not union)
                    _te = time.perf_counter()
                    _counts = _got[1] if isinstance(_got, tuple) and len(_got) > 1 and isinstance(_got[1], dict) else {}
                    _profile("settle", {"url": url, "lock_wait": round((_tl - _ts) * 1000, 1),
                                        "held": round((_te - _tl) * 1000, 1), "chunks": len(before),
                                        # The row counts beside the times (2026-11-22: settles of an
                                        # already-captured page held the lock 20-24 s, ms_anchors_plain
                                        # 4.5-5.7 s, and nothing said how many rows that wrote or why).
                                        **{k: v for k, v in _counts.items()
                                           if k.startswith("ms_") or k.startswith("n_") or k.startswith("addresses_")
                                           or k.startswith("anchors_") or k in ("chunks", "anchors", "contains", "contains_parts", "retired")}})
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
            # What the store holds now, read once for the skip below and
            # handed to the write: the content an in-place rewrite replaces is
            # kept as a version from it (G-253), with no second read.
            held_md: Optional[Dict[str, str]] = None
            if dirty and not _PLANT_REWRITE_SAME[0]:
                try:
                    if _PLANT_SKIP_BY_MD[0] or not hasattr(self.workspace.store, "chunk_sigs"):
                        held = self.workspace.store.chunk_mds([c.cid for c in dirty])
                        write = [c for c in dirty if held.get(c.cid) != c.markdown]
                    else:
                        # The same markdown is not the same chunk when its
                        # ADDRESSES moved (2026-10-12): skipped, its anchors
                        # stayed one sibling off on arXiv for every capture.
                        from domvec.graphstore import anchor_sig
                        sigs = self.workspace.store.chunk_sigs([c.cid for c in dirty])
                        held_md = {cid: got[0] for cid, got in sigs.items()}
                        lines_of = lambda c: sum(1 for ln in c.lines if ln.address is not None)
                        write = [c for c in dirty
                                 if sigs.get(c.cid) != (c.markdown, anchor_sig(c), lines_of(c))]
                    phases["unchanged_skipped"] = len(dirty) - len(write)
                except Exception:                   # noqa: BLE001
                    write = dirty
            version_of: Dict[str, str] = {}
            version_md: Dict[str, str] = {}
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
                    if PLANT_CAPTURE_LOAD[0]:
                        time.sleep(0.4)
                    # A code block's text as the page holds it -- the
                    # trie's value, newlines kept -- for the code graph
                    # (G-233); the markdown line has it on one line.
                    def _held(addr, _t=getattr(spine, "trie", None)):
                        n = _t.find(addr) if _t is not None else None
                        return n.value if n is not None else None
                    _written, counts = self.workspace.ingest_chunks(
                        url, write, complete=False, removed=retired,
                        title=(body.get("title") or ""), raw_values=_held,
                        held_md=held_md)
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
                    # G-253: earlier contents this write kept, version -> position.
                    version_of = dict(counts.get("version_of") or {})
                    version_md = dict(counts.get("version_md") or {})
                    if version_of:
                        phases["versions"] = len(version_of)
                # There are chunks without vectors now. The worker embeds
                # them; this request does not wait for it -- but the page the
                # reader is ON goes to the front of the queue (2026-10-07: a
                # captured chunk waited p50 1.0 s / p90 12 s for its vector
                # behind other pages' backlog, end to end p90 4.5 s, while the
                # fold itself took 1.7 ms). Newest first: what is on screen now.
                try:
                    # G-253: the versions this write kept, to the embedder --
                    # their vectors written off the capture path, then placed.
                    if isinstance(counts, dict):
                        for vid, (md, purl) in (counts.get("version_text") or {}).items():
                            self.workspace.vectors.push(vid, md, url=purl)
                    self.workspace.vectors.prioritize([c.cid for c in dirty] + list(version_of))
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
            # And the versions it kept, placed like any chunk (G-253).
            _project(dirty_cids + retired + list(version_of))
            _project_dedup(self.workspace)
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
            # G-253: the earlier contents this capture stored, each with the
            # position it was the content of -- what the view's kept nodes of
            # those contents are covered by.
            "versions": version_of,
            "version_md": version_md,
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
                list(session.get("pending") or []) + dirty_cids + list(version_of)))
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

    def _page_status_fresh(self, url: str, query: Dict, mkey, plant_scan: bool) -> None:
        """`/page_status` computed (see the memo in `do_GET`)."""
        from .. import tokens as _tokens
        from .layout import (_ESTIMATED_PAGES, _PAGE_POS, live_projection)
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
        out = {
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
        }
        if not plant_scan:
            _STATUS_MEMO[mkey] = (time.time(), out)
        self._send(200, out)


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
            hkey = getattr(self.server, "_domvec_health_key", None)
            if hkey is None:
                hkey = self.server._domvec_health_key = object()
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
            def _levels():
                try:
                    return self.workspace.store.anchor_levels(top=12)
                except Exception:               # noqa: BLE001
                    return None
            def _health_body():
                return {"ok": True,
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
                             # D-2 on the store itself: anchors keyed at the
                             # markdown level (five parts) and not (four).
                             "anchor_levels": _levels(),
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
                                 __import__("domvec.graphstore",
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
                             "layouts": self._layout_count(),
                             # How this process was launched, so the plugin can
                             # start a fresh supervisor when one gives up
                             # (`supervisor_gave_up.json`, 2026-10-25).
                             "launch": {"python": sys.executable, "argv": list(sys.argv[1:]),
                                        "cwd": os.getcwd(),
                                        "workspace": str(getattr(self.workspace, "path", "") or ""),
                                        "supervised": os.environ.get("DOMVEC_SUPERVISED") == "1"},
                             # Opted out of Windows power throttling, as the OS
                             # reports it back (`domvec.qos`).
                             "qos": {**_qos_state(), "os": _qos_read()}}
            # **The counts never run inside the request** (2026-11-08, PLUGIN_GOAL
            # 143 "fix the way the sidecar is run"): with the lock free they
            # still took 20 s on the 32 GB store, so a reload waiting on
            # /health stalled and clients aborted (35 ConnectionAbortedError in
            # the log). They are computed on a thread and cached; the request
            # answers at once with the last result (or a bare liveness when
            # there is none yet), marked `refreshing`. Planted
            # DOMVEC_PLANT_HEALTH_INLINE=1: computed in the request, as before.
            if os.environ.get("DOMVEC_PLANT_HEALTH_INLINE") == "1" or cached is None:
                # The FIRST answer of a server is computed here, once: there
                # is nothing to serve before it.
                self._send(200, _cache_health(key=hkey, body=_health_body()))
                return
            if not _HEALTH_REFRESHING.is_set():
                _HEALTH_REFRESHING.set()
                def _refresh():
                    try:
                        _cache_health(key=hkey, body=_health_body())
                    except Exception:               # noqa: BLE001
                        pass
                    finally:
                        _HEALTH_REFRESHING.clear()
                threading.Thread(target=_refresh, name="domvec-health", daemon=True).start()
            body = dict(cached) if cached is not None else {"ok": True, "warming": True}
            body["refreshing"] = True
            body["cached_s"] = round(now - _HEALTH_CACHE.get("at", now), 1)
            # The launch is cheap and is what the plugin needs to restart a
            # sidecar: always current, never from the cache.
            body["launch"] = {"python": sys.executable, "argv": list(sys.argv[1:]), "cwd": os.getcwd(),
                              "workspace": str(getattr(self.workspace, "path", "") or ""),
                              "supervised": os.environ.get("DOMVEC_SUPERVISED") == "1"}
            self._send(200, body)
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
        if segments[0] == "keywords":
            # A chunk's keyword anchors (PLUGIN_GOAL 159), read from the
            # frequency checkpoint: `?cid=a,b,c&k=5` -> {cid: [terms]}.
            # Read-only; `plant=raw` ranks by raw count (the planted arm).
            params = parse_qs(parts.query)
            cids = [c for c in ",".join(params.get("cid") or []).split(",") if c][:64]
            try:
                k = max(1, min(int((params.get("k") or ["5"])[0]), 20))
            except ValueError:
                k = 5
            raw = (params.get("plant") or [""])[0] == "raw"
            freq = getattr(self.workspace, "freq", None)
            # Not anchors: the words of a URL. A page's links carry its host's
            # words into its text ("wikipedia", "wiki", "org" led Radix tree's
            # anchors), and the tooltip already shows the url.
            def skip_for(url: str) -> set:
                host = urlsplit(url).netloc if "://" in url else ""
                return _URL_NOISE | {w for w in re.split(r"[^a-z0-9]+", host.lower()) if w}
            out = {}
            for c in cids:
                curl = ""
                if freq is not None:
                    try:
                        r0 = self.workspace.store._rows("MATCH (c:Chunk {cid: $c}) RETURN c.url", {"c": c})
                        curl = (r0[0][0] if r0 and r0[0] else "") or ""
                    except Exception:                       # noqa: BLE001
                        curl = ""
                out[c] = freq.keywords(c, k, plant_raw_tf=raw, skip=skip_for(curl)) if freq is not None else []
            # `?url=` (repeatable): a page's anchors, over all its chunks.
            for url in (params.get("url") or [])[:16]:
                rows = self.workspace.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.cid", {"u": url})
                out[url] = freq.keywords([r[0] for r in rows if r and r[0]], k, plant_raw_tf=raw, skip=skip_for(url)) if freq is not None else []
            self._send(200, {"keywords": out})
            return

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
            _LAST_TIER1_MS[0] = {}
            with _foreground():
                pages, matching, counts = _search_pages(index, query, k, params)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            phases = dict(_LAST_TIER1_MS[0])
            _profile("search_pages", {"ms": ms, "pages": len(pages), "matching": matching,
                                      **{"ms_" + str(k2): v for k2, v in phases.items() if isinstance(v, (int, float))},
                                      # Who held the work lock when tier 1 answered: a search
                                      # takes no store lock, so a holder here names the
                                      # background work it competed with for the interpreter.
                                      "work_lock_site": (str(_WORK_LOCK.holder[1])[:80] if _WORK_LOCK.holder else "")})
            self._send(200, {"query": query, "pages": [{"url": u, "score": round(sc, 5), "n": counts.get(u)} for u, sc in pages],
                             "matching": matching, "phases": phases, "ms": ms})
            return

        if segments[0] == "lead_vectors":
            # The rows the projector is fitted on (`store.lead_vectors`), for an
            # instrument outside the app (`analytics.layout_shape --sidecar`):
            # a running sidecar holds the store as a writer and excludes
            # readers, so this is the only way to measure the store in use.
            # Read-only; values rounded to 5 places.
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            rows = self.workspace.store.lead_vectors()
            self._send(200, {"rows": [[c, u, [round(float(x), 5) for x in v]] for c, u, v in rows]})
            return

        if segments[0] == "vectors":
            # The embed queue's cumulative counters (P-N6): `skipped` is a
            # chunk offered again with the text it was embedded from -- the
            # diff a re-index of an edited note should mostly be.
            v = getattr(self.workspace, "vectors", None) if self.workspace is not None else None
            self._send(200, v.report() if v is not None else {"error": "no vector queue"})
            return

        if segments[0] == "source":
            # A code module's text (P-C1): the standalone artifact panel's
            # editable side. The trie holds the module as addresses; the FILE
            # is what a reader edits, and a save re-indexes it (POST /source).
            url = (parse_qs(parts.query).get("url") or [""])[0]
            got = _source_file(url)
            if got is None or not got[0].exists():
                self._send(404, {"error": "not a code:// python module this sidecar can read", "url": url})
                return
            path, module, editable = got
            self._send(200, {"url": url, "module": module, "editable": editable,
                             "text": path.read_text(encoding="utf-8", errors="replace")})
            return

        if segments[0] == "prototype":
            # A code chunk as a notebook cell's prototype (`G-105`): the
            # function or class it belongs to -- its address with the
            # trailing name/docstring/code step taken off -- and that scope's
            # name, docstring and CODE, read from the trie's addresses (the
            # code is kept out of the embedding, never out of the map).
            q = parse_qs(parts.query)
            cid = (q.get("cid") or [""])[0]
            try:
                rows = self.workspace.store._rows(
                    "MATCH (c:Chunk {cid: $c}) RETURN c.url, c.xpath", {"c": cid})
                if not rows or not str(rows[0][0]).startswith("code://"):
                    self._send(404, {"error": "not a stored code chunk", "cid": cid})
                    return
                url, xpath = rows[0][0], rows[0][1] or ""
                scope = re.sub(r"/(name|docstring|code)(\[\d+\])?$", "", xpath)
                # The chunk spells `function[1]` bare, the address keeps the
                # `[1]`: compared with the ordinal dropped on both sides.
                from ..markdown import _one_is_bare
                want = {_one_is_bare(scope) + "/" + k: k for k in ("name", "docstring", "code")}
                vals = {}
                for x, v in self.workspace.store._rows(
                        "MATCH (a:Address) WHERE a.url = $u RETURN a.xpath, a.value", {"u": url}):
                    k = want.get(_one_is_bare(x or ""))
                    if k:
                        vals[k] = v or ""
                if PLANT_PROTOTYPE_NO_CODE[0]:
                    vals.pop("code", None)
                # Its home module, importable: the trie keeps a module's
                # imports as links, not as text, so a prototype runs in its
                # module's namespace rather than a copy of its import lines.
                # `code://repo/` is this package; `code://pypi/` an installed one.
                rest = url[len("code://"):].split("/", 1)
                rel = re.sub(r"(/__init__)?\.py$", "", rest[1] if len(rest) > 1 else "")
                module = ((("domvec/" if rest[0] == "repo" else "") + rel).replace("/", ".")
                          if rest[0] in ("repo", "pypi") and rel else "")
                self._send(200, {"cid": cid, "url": url, "scope": scope, "name": vals.get("name", ""),
                                 "docstring": vals.get("docstring", ""), "code": vals.get("code", ""),
                                 "module": module})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, str(exc)[:200])})
            return

        if segments[0] == "chat":
            # A conversation's record: its turns and the chunks it has sent.
            from .. import chat as _chat
            q = parse_qs(parts.query)
            conv = _chat._CONVERSATIONS.get((q.get("session") or ["default"])[0])
            self._send(200, conv.to_json() if conv else {"session": None, "turns": [], "sent": []})
            return
        if segments[0] == "checkpointing":
            # Never the store, never the work lock: answerable mid-checkpoint.
            self._send(200, {"checkpointing": bool(_CHECKPOINTING[0]),
                             "since_write_s": round(time.time() - _LAST_WRITE[0], 1)})
            return

        if segments[:2] == ["code", "sources"]:
            # The modules the codebase sync reads, by the sync's OWN selection
            # (`iter_sources`) -- so a check comparing the store against the
            # disk does not reimplement what it measures. Read-only.
            from ..source import iter_sources, source_url
            base = Path(__file__).resolve().parents[1]
            pairs = list(iter_sources(base))
            empty = []
            for _p, rel in pairs:
                try:
                    if not _p.read_text(encoding="utf-8").strip():
                        empty.append(source_url("repo", rel))
                except (OSError, UnicodeDecodeError):
                    pass
            # `empty`: modules with no text at all -- nothing to chunk, so not
            # part of what search can be asked to find.
            self._send(200, {"urls": [source_url("repo", rel) for _p, rel in pairs], "empty": empty,
                             "sync": dict(_CODE_SYNC_STATE)})
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
            got["embed_reconcile"] = getattr(self.workspace, "embed_reconciled", None)
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
        if segments[0] == "runs":
            # A note's recorded forward calls, each with the refs it read (G-279).
            note = (parse_qs(parts.query).get("note") or [""])[0]
            self._send(200, {"note": note, "runs": self.workspace.store.runs_of(note)})
            return

        if segments[0] == "code_nodes":
            # The plane's RETRIEVAL BAR (PLUGIN_GOAL 133): every typed node the
            # code property graph holds -- module, class, function, statement --
            # matched by name, with its kind and address.
            try:
                q = str((parse_qs(parts.query).get("q") or [""])[0]).strip().lower()
                k = max(1, min(50, int((parse_qs(parts.query).get("k") or ["12"])[0])))
                rows = self.workspace.store._rows(
                    "MATCH (n:CodeNode) WHERE lower(n.name) CONTAINS $q "
                    "RETURN n.key, n.url, n.xpath, n.kind, n.name, n.qname, n.line LIMIT $k",
                    {"q": q, "k": k}) if q else []
                self._send(200, {"nodes": [{"key": r[0], "url": r[1], "xpath": r[2], "kind": r[3], "name": r[4],
                                            "qname": r[5], "line": r[6]} for r in rows]})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if segments[0] == "codegraph":
            # The code graph (item 93): its size, and a name's place in it --
            # kind, PageRank percentile, neighbours.
            g = CODEGRAPH["graph"]
            if g is None:
                self._send(200, {"ready": False, "error": CODEGRAPH["error"]})
                return
            name = (parse_qs(parts.query).get("name") or [""])[0]
            out = {"ready": True, "ms": CODEGRAPH["ms"], "stats": g.stats,
                   "code_rank_pages": _ensure_code_rank(self.workspace)}
            if name:
                out.update({"name": name, "kind": g.kind.get(name, ""), "rank": g.percentile(name),
                            "neighbours": [{"name": n, "edge": k} for n, k in g.neighbours(name)[:40]]})
            # The module network the ego draws (G-318): `?top=N`.
            top = (parse_qs(parts.query).get("top") or [""])[0]
            if top.isdigit():
                out["net"] = g.module_net(int(top))
            self._send(200, out)
            return

        if segments[0] == "typegraph":
            # The PageRank over the TYPE graph (G-317): the code graph's kinds,
            # weighted by the edges between their members. Empty until built.
            g = CODEGRAPH.get("graph")
            self._send(200, {"ready": g is not None, "ranks": g.type_ranks() if g is not None else {}})
            return

        if segments[0] == "browser_state":
            # The browser cell's address, as the plugin last told it (G-279).
            self._send(200, dict(BROWSER_STATE, age_s=round(time.time() - BROWSER_STATE.get("at", 0), 1) if BROWSER_STATE.get("at") else None))
            return

        if segments[0] == "ego" and len(segments) > 1 and segments[1] == "projection":
            # The ego's own projection (item 76): knowledge keys -> places.
            try:
                self._send(200, ego_projection(self.workspace))
            except Exception as exc:            # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if segments[0] == "ego":
            # The ego set (items 74, 78): its notes and its tagged chunks.
            ego_load(self.workspace)
            # Each tagged chunk's page too: its own node is drawn only when its
            # page is open, and a line to it falls back to the page's node.
            # And a title for each (PLUGIN_GOAL 159: a tagged chunk drawn in
            # the ego as its bare cid, "not sure what 'beef' ego node is
            # about"): the chunk's first line with words in it.
            # A tag whose chunk this store does not hold (tagged in another
            # store, or since dropped) is listed as missing: it names nothing.
            cid_urls, cid_titles, missing = {}, {}, []
            for cid in EGO["cids"]:
                c = self.workspace.store.chunk(cid)
                if c is not None:
                    cid_urls[cid] = c.url
                    cid_titles[cid] = md_title(c.md) or c.url
                else:
                    missing.append(cid)
            self._send(200, {"urls": sorted(EGO["urls"]), "cids": sorted(EGO["cids"]),
                             "cid_urls": cid_urls, "cid_titles": cid_titles, "missing": sorted(missing)})
            return

        if segments[0] == "ref":
            # A `{ref}` resolved through the store, with the rank-1 lines that
            # internalizing it reveals (G-278; RESERVOIR_DESIGN §3.1-3.3).
            from . import refs as _refs
            name = (parse_qs(parts.query).get("name") or [""])[0]
            # Markdown escapes in a ref are the note's, not the name's: an unnest
            # panel writes `\_\_init\_\_` so the slate draws the underscores.
            name = re.sub(r"\\(.)", r"\1", name)
            # A code artifact is a BLACK BOX (PLUGIN_GOAL 80): its rank-1
            # definitions, each a ref that unfolds the same way.
            if name.strip().startswith("code://"):
                from . import blackbox as _bb
                src = _source_file(name.strip().split("#", 1)[0])
                got = None
                if src is not None:
                    try:
                        got = _bb.unfold(name.strip(), Path(src[0]).read_text(encoding="utf-8"))
                    except OSError:
                        got = None
                if got is None:
                    self._send(200, {"name": name, "resolved": False, "lines": []})
                    return
                # Instant feedback (PLUGIN_GOAL 100): unnesting a box shows at
                # once what the search finds for that symbol -- its top three.
                lines = list(got["lines"])
                if not PLANT_NO_INSTANT[0]:
                    base_, _, qual_ = name.strip().partition("#")
                    term = (qual_.split(".")[-1] if qual_ else base_.rsplit("/", 1)[-1].rsplit(".", 1)[0]).replace("_", " ")
                    try:
                        found = self.workspace.search(term, k=3) if term.strip() else []
                    except Exception:                    # noqa: BLE001
                        found = []
                    for h in found or []:
                        c = self.workspace.store.chunk(getattr(h, "cid", None) or getattr(h, "chunk", ""))
                        if c is not None:
                            first = next((l.strip() for l in (c.md or "").splitlines() if l.strip()), "")
                            lines.append("found" + chr(9) + first[:90])
                self._send(200, {"name": name, "resolved": True, "kind": "code-" + got["kind"],
                                 "url": name.strip(), "cids": [], "lines": lines})
                return
            # `Note#Heading#Sub`, `Note#cell 2#f` (PLUGIN_GOAL 159): the note
            # resolved by its name, then the address unfolded inside its own
            # text -- a heading's section, a cell's inputs and definitions.
            base = name.split("#", 1)[0].strip()
            got = _refs.resolve(self.workspace, base) if base else None
            # Only an artifact found BY ITS NAME has an outline under that name:
            # retrieval's top hit is some other chunk, and `{Name#x}` built on
            # it would address a place the named note does not have.
            own = got is not None and got["kind"] in ("note", "page")
            lines = _refs.outline(got["value"], name) if own and "#" in name else None
            if got is None or ("#" in name and lines is None):
                self._send(200, {"name": name, "resolved": False, "lines": []})
                return
            if lines is None:
                lines = _refs.rank1(got["value"], name=name if own else "")
            self._send(200, {"name": name, "resolved": True, "kind": got["kind"], "url": got["url"],
                             "cids": got["cids"][:20], "lines": lines})
            return

        if segments[0] == "signal":
            # The reservoir's signal flow (G-292; RESERVOIR_DESIGN §5, DM
            # §6.6.4): every recorded run's inputs -> its cell note, most
            # recent first, for the 3D view to draw as lines.
            k = int((parse_qs(parts.query).get("k") or ["2000"])[0])
            self._send(200, {"edges": self.workspace.store.signal_edges(k)})
            return

        if segments[0] == "inverse_map":
            # Every recorded run that consumed a chunk, and what it produced.
            cid = (parse_qs(parts.query).get("cid") or [""])[0]
            self._send(200, {"cid": cid, "runs": self.workspace.store.inverse_map(cid)})
            return

        if segments[0] == "locks":
            # Who holds the work lock now, and who held it longest.
            self._send(200, _WORK_LOCK.report())
            return

        if segments[0] == "duplicates":
            # The store's own verdict: contents drawn more than once (0 is the
            # goal), copies marked, chunks kept drawn because they lead a group.
            # `?stats=1`: the dedup's own work counters (S-4: hashes per write).
            if (parse_qs(parts.query).get("stats") or [""])[0] == "1":
                self._send(200, dict(self.workspace.store.dedup_stats))
                return
            self._send(200, self.workspace.store.duplicate_report())
            return

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
            if (query.get("frame") or [""])[0]:
                out["page_frame"] = proj.page_frame()
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
                # Named, not only counted: which held chunks the store
                # disagrees about, and what the store says each one is.
                odd = sorted(held - now)[:12]
                if odd:
                    with _WORK_LOCK:
                        info = {}
                        for r in self.workspace.store._rows(
                                "MATCH (c:Chunk) WHERE list_contains($cids, c.cid) "
                                "OPTIONAL MATCH (p:Page)-[:HasChunk]->(c) "
                                "RETURN c.cid, c.url, c.dup_of, c.group_of, c.group_n, "
                                "c.embedding IS NULL, p.url", {"cids": odd}):
                            info[r[0]] = {"url": r[1], "dup_of": r[2] or "", "group_of": r[3] or "",
                                          "group_n": r[4], "no_vec": bool(r[5]), "page": r[6]}
                    with proj.lock:
                        out["not_drawable_sample"] = [{"cid": c, "url_held": proj.url_of.get(c),
                                                       "store": info.get(c)} for c in odd]
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
            threading.Thread(target=_warm, name="domvec-warm-controls", daemon=True).start()
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
            # 186g, `domvec/code_kg.py`): read from the source it describes --
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
        if segments[0] == "typegen":
            # T-15 (PLUGIN_GOAL 186f): a pydantic type from a trie-path
            # pattern over every stored page. Reads addresses; writes nothing.
            from .. import typegen as _tg
            params = parse_qs(parts.query)
            pattern = (params.get("pattern") or [""])[0]
            name = (params.get("name") or ["Item"])[0]
            if (params.get("mine") or [""])[0]:
                # G-388: the patterns themselves, mined from every address
                # row -- a record root repeating on 2+ pages with a shared
                # shape. Reads the trie's addresses; writes nothing.
                t0 = time.time()
                rows = self.workspace.store._rows(
                    "MATCH (a:Address) RETURN a.url, a.xpath, a.accessor, a.value LIMIT 400000", {})
                t1 = time.time()
                types = _tg.mine(rows, min_pages=int((params.get("min_pages") or ["2"])[0]),
                                 limit=int((params.get("limit") or ["50"])[0]))
                self._send(200, {"rows": len(rows), "types": types,
                                 "ms_read": round(1000 * (t1 - t0), 1),
                                 "ms_mine": round(1000 * (time.time() - t1), 1)})
                return
            if not pattern.startswith("/"):
                self._send(400, {"error": "pattern must be an xpath, e.g. /html/body/main/article[*]"})
                return
            # The prefix is usually just `/html/body/` -- nearly every row.
            # At LIMIT 200000 on a 245k-row store the type silently lost 35
            # of 2,505 instances the miner had counted (G-388 check, run 54);
            # the bound is the miner's, so the two count the same rows.
            rows = self.workspace.store._rows(
                "MATCH (a:Address) WHERE starts_with(a.xpath, $p) "
                "RETURN a.url, a.xpath, a.accessor, a.value LIMIT 400000", {"p": _tg.prefix_of(pattern)})
            self._send(200, _tg.model(rows, pattern, name))
            return
        if segments[0] == "page_status":
            from .. import tokens as _tokens
            from .layout import (_ESTIMATED_PAGES, _PAGE_POS, live_projection)
            query = parse_qs(parts.query)
            url = (query.get("url") or [""])[0]
            if not url:
                self._send(400, {"error": "no url"})
                return
            # **One scan per url at a time, and its answer kept 4 s.** Each
            # call scans every chunk for the url (no index on it, and the
            # `HasChunk` edges disagree with the chunks' own urls) twice,
            # holding the readers' lock 0.6-3.9 s on a 102k-chunk store; the
            # pipeline box asks every second. Everything else that reads --
            # the chunk view's layout, panels, the embed worker -- queued
            # behind it, and chunk view did not load (2026-10-20). Concurrent
            # asks for one url wait for the one scan. Planted
            # `DOMVEC_PLANT_STATUS_SCAN=1`: a scan per ask, as before.
            mkey = (url, bool((query.get("cids") or [""])[0]))
            plant_scan = os.environ.get("DOMVEC_PLANT_STATUS_SCAN") == "1"
            gate = None
            if not plant_scan:
                with _STATUS_MEMO_GUARD:
                    gate = _STATUS_MEMO_GATES.setdefault(mkey, threading.Lock())
                gate.acquire()
            try:
                hit = None if plant_scan else _STATUS_MEMO.get(mkey)
                if hit is not None and time.time() - hit[0] < _STATUS_MEMO_S:
                    self._send(200, dict(hit[1], memo_age_s=round(time.time() - hit[0], 2)))
                    return
                self._page_status_fresh(url, query, mkey, plant_scan)
            finally:
                if gate is not None:
                    gate.release()
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
                    # A re-fit ASKED for starts over (PLUGIN_GOAL 173 b).
                    threading.Thread(target=proj.fit, args=(self.workspace,), kwargs={"fresh": True},
                                     name="domvec-refit", daemon=True).start()
                if proj is not None and proj.projection is not None:
                    _t0 = time.perf_counter()
                    if level == "page":
                        got = projected_page_layout(self.workspace, proj)
                    else:
                        # One chunk-level layout at a time: four at once on a
                        # cold sidecar each walked every page's containment
                        # and none finished (2026-10-24). The next one, after
                        # it, reads the memos the first filled.
                        with _CHUNK_LAYOUT_LOCK:
                            got = projected_chunk_layout(self.workspace, proj)
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

        if segments[0] == "browse":
            # The artifact as it stands, and the diffs after `since`.
            params = parse_qs(parts.query)
            sess = BROWSE["session"]
            if sess is None:
                self._send(200, {"artifact": None, "version": 0, "changes": []})
            else:
                try:
                    since = int((params.get("since") or ["0"])[0])
                except ValueError:
                    since = 0
                self._send(200, {"artifact": sess.artifact, **sess.since(since)})
            return

        if segments[0] == "rank_levels":
            # The hierarchical rank's levels and its similarity audit (177e):
            # the similarity level's edges from the two embeddings, against
            # the PLANTED layout-distance edges and a random pairing, each
            # scored by the dual similarity of the pairs it links. Read-only.
            from .. import hierank
            idx = self.workspace.index
            with _foreground():
                urls, lex, sem = idx.page_forms()
                keep = [i for i, u in enumerate(urls) if hierank.page_of(u) == u]
                urls, lex, sem = [urls[i] for i in keep], lex[keep], sem[keep]
                dual = hierank.dual_similar(urls, lex, sem) if urls else []
                lay_urls, pos = idx._layout_positions(urls)
                lay = hierank.layout_similar(lay_urls, pos) if len(lay_urls) > 1 else []
                lv = hierank.levels(urls)
                idx.hier_ranks()
                info = (getattr(idx, "_hier", None) or (None, None, {}))[2]
                pr = idx._hier[1] if getattr(idx, "_hier", None) else None
            self._send(200, {
                "pages": len(urls), "hosts": len({h for h, _ in lv.values()}),
                "domains": len({d for _, d in lv.values()}),
                "multi_host_domains": sorted({d for h, d in lv.values() if d != h
                                              and sum(1 for x in lv.values() if x[1] == d) > 1})[:40],
                "audit_dual": hierank.similarity_audit(urls, lex, sem, dual) if urls else {},
                "audit_layout_planted": hierank.similarity_audit(urls, lex, sem, lay) if lay else {"edges": 0},
                "layout_pages": len(lay_urls),
                "hier": info,
                "hier_rank_spread": (round(float(pr.max() / max(pr[pr > 0].min(), 1e-12)), 2)
                                     if pr is not None and pr.size else None)})
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
            where = (params.get("where") or [""])[0]
            try:
                budget = int((params.get("budget") or ["0"])[0])
            except ValueError:
                budget = 0
            ref = (params.get("ref") or [""])[0]
            if not query and not ref:
                self._send(400, {"error": "missing q"})
            else:
                # Foreground: background training and embedding stand aside
                # while the reader waits on a search (PLUGIN_GOAL 152).
                with _foreground():
                    try:
                        trace = int((params.get("trace") or ["0"])[0])
                    except ValueError:
                        trace = 0
                    # `rank` picks the PageRank the ranking reads (177e):
                    # flat, hier, or none -- the counterfactual.
                    rank = (params.get("rank") or [""])[0]
                    rank = rank if rank in ("flat", "hier", "levels", "none", "shuffle") else ""
                    got = search_payload(
                        self.workspace, query, k, offset=offset,
                        url=scope, coarse=coarse, budget=budget, where=where, trace=trace, ref=ref,
                        rank=rank)
                self._send(200, got)
            return

        self._send(404, {"error": "no such route", "path": parts.path})


#: Words a URL is made of, never a page's subject (the keyword anchors).
_URL_NOISE = {"http", "https", "www", "com", "org", "net", "html", "htm", "php", "wiki", "index",
              "amp", "utm", "ref", "src", "url", "href", "edu", "gov", "io"}


_LAST_TIER1_MS = [{}]


def _qos_state() -> dict:
    from .. import qos as _qos
    return dict(_qos.STATE)


def _qos_read():
    from .. import qos as _qos
    return _qos.throttling_state()


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
        # Where tier 1's time went, per phase -- kept for the handler's reply
        # and the profile ring (2026-11-15: tier 1 took 0.2 s for one query
        # and 8.2 s for the next; nothing said which part).
        _LAST_TIER1_MS[0] = dict(diag.ms or {})
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
    # Full speed first (`domvec.qos`): a long-lived background process is
    # moved to the efficiency cores after ~3 s of work, and every phase this
    # process times ran at about a third of the machine's speed (2026-11-15).
    from .. import qos as _qos
    _qos.full_speed()
    # Background training steps aside for searches (PLUGIN_GOAL 152).
    # Planted: DOMVEC_PLANT_NO_TRAIN_YIELD=1.
    if os.environ.get("DOMVEC_PLANT_NO_TRAIN_YIELD") != "1":
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
            name="domvec-embed", daemon=True)
        _EMBED_THREAD.start()
    if workspace is not None and not getattr(workspace, "read_only", False)             and hasattr(workspace.store, "checkpoint"):
        threading.Thread(target=_checkpoint_forever, args=(workspace, stop),
                         name="domvec-checkpoint", daemon=True).start()
        threading.Thread(target=_integrity_forever, args=(workspace, stop),
                         name="domvec-integrity", daemon=True).start()
        threading.Thread(target=_poison_watch, args=(workspace, stop),
                         name="domvec-poison-watch", daemon=True).start()
        threading.Thread(target=_warm_containment, args=(workspace, stop),
                         name="domvec-warm-containment", daemon=True).start()
        # G-375 (PLUGIN_GOAL 166 a, 167 a "Layout and indexer"): the
        # repository is no longer synced into the store -- only code scanned
        # in the browser is indexed. Planted `PLANT_CODE_SYNC`: synced again.
        if PLANT_CODE_SYNC[0]:
            threading.Thread(target=_code_sync_forever, args=(workspace, stop),
                             name="domvec-code-sync", daemon=True).start()
    if workspace is not None:
        threading.Thread(target=_build_codegraph, args=(workspace,),
                         name="domvec-codegraph", daemon=True).start()

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
            # stays selectable. DOMVEC_PROJECTOR=chunk brings back the fit on
            # a sample of chunks.
            import os as _os
            if _os.environ.get("DOMVEC_PROJECTOR", "page") == "page":
                _projector.PROJECTOR = _projector.PageProjector(
                    dims=3, centroid=_os.environ.get("DOMVEC_PAGE_CENTROID", "semantic"))
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
        workspace.background_yield = _yield_to_foreground

        def _warm_index():
            try:
                started = time.perf_counter()
                workspace.index
                _profile("index_warm", {"ms": round((time.perf_counter() - started) * 1000, 1)})
            except Exception as exc:                # noqa: BLE001
                _profile("index_warm", {"error": "%s: %s" % (type(exc).__name__, exc)})
        threading.Thread(target=_warm_index, name="domvec-index", daemon=True).start()

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
        threading.Thread(target=_lexical, name="domvec-lexical", daemon=True).start()

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
        # A vault opens many chunks at once -- a note with several `domvec`
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
                         name="domvec-stall-watchdog", daemon=True).start()
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
