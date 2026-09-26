"""The chunk projector: the one fit the 3D graph is drawn from.

**What was there before, and why it was not the pipeline.** Three unrelated
things decided where a node was drawn:

* the default view fitted UMAP on page MEANS (`build_page_layout`);
* a live capture transformed each new chunk into that page-mean fit -- and
  then threw the transform away, overwriting it with `_local_positions`, a
  small ball fitted around the page's anchor;
* the chunk view was a separate 95-second fit over every chunk
  (`build_layout`), with no transform, no growth rule, and nothing live.

So "chunks embedded and streamed into a fitted projector, refit at 2x
growth" was measured by the profiler and never decided a single position the
reader saw. This module is that projector, and the graph reads positions
from it and nowhere else.

**The model.** One UMAP fit over the drawable chunks' vectors -- a merge
group's lead speaks with its group vector, the 512-token aggregate (`G-27`),
and the 256-token members stay underneath for retrieval. Fitted on a sample
of at most `SAMPLE_CAP` rows, because a fit's cost grows with the rows it is
made of and its QUALITY stops growing long before 16,000; every other row is
placed by `transform`, which is what every chunk that arrives later gets too.

**The stream.** The embed worker hands over every chunk it has just given a
vector, and the capture path every chunk it rewrote or retired. They queue
here; a worker drains the queue in batches, transforms each batch into the
fit, and appends what moved to a log with a sequence number. A pane asks for
`delta(since)` and gets exactly the changes after the last one it saw --
O(delta), not a new layout.

**The refit.** When the corpus's chunk count reaches twice what it was at the
fit, the fit is redone in the background from a fresh sample, every chunk is
re-placed into it, and the `epoch` changes. Until the new fit is complete the
old one keeps answering, so the picture never goes blank or half-moves. A
pane that sees a new epoch reloads positions once; between refits nothing it
has drawn moves unless its own chunk changed.

**Pages** sit where the fit puts what they MEAN: the transform of the mean of
their chunks' vectors -- the same quantity the page-level fit was made of,
now placed into the chunk fit, so the two layers are one picture.

Reads from the trie's projection only through the store: a chunk is keyed by
its cid, which is the hash of its `url : xpath` span, and its url is the page
it hangs from. Nothing here writes to the store.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import nullcontext
from typing import Callable, Deque, Dict, Iterable, List, Optional, Tuple

import numpy as np

#: The largest sample a fit is made from. Every row beyond it is placed by
#: `transform`, which is how the stream places everything anyway.
SAMPLE_CAP = 4000

#: How many queued chunks one drain of the queue transforms together. A
#: `transform` has a fixed cost per call (the nearest-neighbour search is
#: batched), so small batches waste it and huge ones hold the lock.
BATCH = 256

#: How many changes the log keeps. A pane further behind than this is told
#: to reload rather than handed a partial history.
LOG_CAP = 50000


def _next_epoch(previous: int) -> int:
    """An epoch no pane can already hold.

    A counter restarted at 1 in every process, so a fresh fit after a restart
    came back as epoch 1 -- the number the open pane already had from the
    PREVIOUS process's fit. The pane saw no change, kept positions from a
    model that no longer existed, and never re-placed what it had open.
    Milliseconds since the epoch are unique across restarts and still order.
    """
    return max(int(previous) + 1, int(time.time() * 1000))


def _unit(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 1e-9 else v


class ChunkProjector:
    """Positions for every drawable chunk, kept current by a stream."""

    def __init__(self, dims: int = 3, *, sample_cap: int = SAMPLE_CAP,
                 seed: int = 0) -> None:
        self.dims = dims
        self.sample_cap = int(sample_cap)
        self.seed = seed
        self.lock = threading.RLock()
        self.projection = None
        self.epoch = 0
        self.seq = 0
        #: cid -> [x, y, z]; the answer to "where is this chunk drawn".
        self.pos: Dict[str, List[float]] = {}
        self.hsv: Dict[str, List[float]] = {}
        self.url_of: Dict[str, str] = {}
        self.by_url: Dict[str, set] = {}
        #: The vector each position was made from, kept so a page's mean can
        #: be re-derived in memory when one of its chunks changes.
        self.vec: Dict[str, np.ndarray] = {}
        self.page_pos: Dict[str, List[float]] = {}
        self.page_hsv: Dict[str, List[float]] = {}
        #: (seq, kind, id) -- kind is "chunk", "gone" or "page".
        self.log: Deque[Tuple[int, str, str]] = deque(maxlen=LOG_CAP)
        self.queue: Dict[str, None] = {}
        self.queue_lock = threading.Lock()
        self.wanted = threading.Event()
        self.fitted_chunks = 0
        self.fitted_points = 0
        self.fit_sample = 0
        self.fitting = False
        self.fit_error = ""
        self.fits: List[Dict] = []
        self.batches: Deque[Dict] = deque(maxlen=64)
        self.placed_total = 0
        #: The store's chunk count as of the worker's last growth check.
        self.chunks_now = 0
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        #: The sidecar's locks: `work_lock` around every store read (an
        #: ingest may be writing the same rows), `fit_lock` around the fit's
        #: stages (`layout._LAST_FIT` is one shelf shared by every fit).
        self.work_lock = None
        self.fit_lock = None
        #: Called with each batch record, so the sidecar's profile rings see
        #: the stream without this module importing the sidecar.
        self.on_batch: Optional[Callable[[Dict], None]] = None
        self.on_fit: Optional[Callable[[Dict], None]] = None

    # -- the fit ------------------------------------------------------------
    def fit(self, workspace) -> Dict:
        """Fit on a sample of the drawable chunks and place every one of them.

        Runs off the request path. The previous fit (if any) keeps answering
        until the new one has placed every chunk; the swap is one assignment
        under the lock.
        """
        from . import layout as L

        started = time.perf_counter()
        with self.lock:
            if self.fitting:
                return {"skipped": "already fitting"}
            self.fitting = True
        try:
            t = time.perf_counter()
            with (self.work_lock or nullcontext()):
                rows = workspace.store.lead_vectors()
                chunks_at_fit = int(workspace.store.chunk_count())
            ms_read = (time.perf_counter() - t) * 1000
            if len(rows) < 8:
                return {"skipped": "too few chunks", "n": len(rows)}
            cids = [r[0] for r in rows]
            urls = [r[1] for r in rows]
            block = np.asarray([r[2] for r in rows], dtype=np.float32)
            rng = np.random.default_rng(self.seed)
            n = len(rows)
            take = (np.arange(n) if n <= self.sample_cap
                    else np.sort(rng.choice(n, self.sample_cap, replace=False)))
            sample = L._unit_rows(block[take])

            t = time.perf_counter()
            # `_LAST_FIT` is the module's shelf for fitted stages; the fit
            # lock keeps a page fit from interleaving its stages with these.
            with (self.fit_lock or nullcontext()):
                L._LAST_FIT.clear()
                width = int(min(sample.shape[1], max(2, sample.shape[0] - 1),
                                L._LONE_TARGET))
                reduced = L._unit_rows(L._reduce(sample, width, self.seed))
                want = self.dims + 3
                coords = L._umap(reduced, dims=want, seed=self.seed,
                                 neighbors=15, min_dist=0.25)
                got = int(coords.shape[1])
                colours = (L._hsv(coords[:, self.dims:self.dims + 3])
                           if got >= want else None)
                coords = L._spread(coords, self.dims)
                coords = L._framed(coords, self.dims)
                projection = L.Projection.of(
                    dims=self.dims, hsv=colours is not None,
                    fitted_n=len(take),
                    fitted_chunks=chunks_at_fit)
            ms_fit = (time.perf_counter() - t) * 1000
            if projection is None:
                self.fit_error = "the fit produced no transformable reducer"
                return {"error": self.fit_error}

            pos: Dict[str, List[float]] = {}
            hsv: Dict[str, List[float]] = {}
            for j, i in enumerate(take):
                pos[cids[i]] = [float(v) for v in coords[j][:self.dims]]
                if colours is not None:
                    hsv[cids[i]] = [float(v) for v in colours[j]]
            t = time.perf_counter()
            rest = np.setdiff1d(np.arange(n), take)
            for lo in range(0, len(rest), 2048):
                idx = rest[lo:lo + 2048]
                where, colour = projection.place(block[idx])
                if where is None:
                    continue
                for j, i in enumerate(idx):
                    pos[cids[i]] = [float(v) for v in where[j][:self.dims]]
                    if colour is not None:
                        hsv[cids[i]] = [float(v) for v in colour[j]]
            ms_transform = (time.perf_counter() - t) * 1000

            by_url: Dict[str, set] = {}
            for cid, url in zip(cids, urls):
                by_url.setdefault(url, set()).add(cid)
            vec = {cid: block[i] for i, cid in enumerate(cids)}
            t = time.perf_counter()
            page_pos, page_hsv = self._pages(projection, by_url, vec)
            ms_pages = (time.perf_counter() - t) * 1000

            with self.lock:
                self.projection = projection
                self.pos, self.hsv, self.vec = pos, hsv, vec
                self.url_of = dict(zip(cids, urls))
                self.by_url = by_url
                self.page_pos, self.page_hsv = page_pos, page_hsv
                self.fitted_chunks = projection.fitted_chunks
                self.fitted_points = n
                self.fit_sample = len(take)
                self.epoch = _next_epoch(self.epoch)
                self.log.clear()
                self.fit_error = ""
            record = {
                "epoch": self.epoch, "chunks": n, "sample": int(len(take)),
                #: Rows are (page, chunk) pairs; a chunk reachable from two
                #: Page rows is one point. This is the denominator for
                #: "every drawable chunk is projected".
                "distinct": len(set(cids)),
                "pages": len(page_pos), "fitted_chunks": self.fitted_chunks,
                "ms_read": round(ms_read, 1), "ms_fit": round(ms_fit, 1),
                "ms_transform": round(ms_transform, 1),
                "ms_pages": round(ms_pages, 1),
                "ms": round((time.perf_counter() - started) * 1000, 1),
                "at": round(time.time(), 3),
            }
            self.fits.append(record)
            del self.fits[:-8]
            record["saved"] = self.save(workspace)
            if self.on_fit:
                try:
                    self.on_fit(record)
                except Exception:                   # noqa: BLE001
                    pass
            return record
        except Exception as exc:                    # noqa: BLE001
            self.fit_error = "%s: %s" % (type(exc).__name__, exc)
            return {"error": self.fit_error}
        finally:
            with self.lock:
                self.fitting = False

    def _pages(self, projection, by_url, vec):
        """Each page at the transform of its chunks' mean vector."""
        urls = [u for u, cs in by_url.items() if cs]
        if not urls:
            return {}, {}
        means = np.asarray([_unit(np.mean([vec[c] for c in by_url[u]], axis=0))
                            for u in urls], dtype=np.float32)
        where, colour = projection.place(means)
        if where is None:
            return {}, {}
        pos = {u: [float(v) for v in where[i][:self.dims]]
               for i, u in enumerate(urls)}
        hsv = ({u: [float(v) for v in colour[i]] for i, u in enumerate(urls)}
               if colour is not None else {})
        return pos, hsv

    # -- the stream ---------------------------------------------------------
    def enqueue(self, cids: Iterable[str]) -> int:
        """Queue chunks whose vector or existence may have changed."""
        added = 0
        with self.queue_lock:
            for cid in cids:
                if cid and cid not in self.queue:
                    self.queue[cid] = None
                    added += 1
        if added:
            self.wanted.set()
        return added

    def prioritize(self, cids: Iterable[str]) -> int:
        """Queue these chunks at the FRONT (`G-80`, hover-first): the next
        batch transforms them before anything that was waiting."""
        wanted = [c for c in dict.fromkeys(cids) if c]
        if not wanted:
            return 0
        with self.queue_lock:
            rest = [c for c in self.queue if c not in set(wanted)]
            self.queue = dict.fromkeys(wanted + rest)
        self.wanted.set()
        return len(wanted)

    def enqueue_page(self, url: str, cids: Iterable[str]) -> int:
        """Queue a page's current chunks AND any this projector still holds
        for it that the page no longer has -- they are gone, and nothing else
        will say so."""
        now = set(cids)
        with self.lock:
            held = set(self.by_url.get(url) or ())
        return self.enqueue(list(now | held))

    def drain(self, workspace) -> Optional[Dict]:
        """Transform one batch from the queue into the fit."""
        with self.queue_lock:
            if not self.queue:
                return None
            batch = list(self.queue)[:BATCH]
            for cid in batch:
                self.queue.pop(cid, None)
        projection = self.projection
        if projection is None:
            # Nothing to place into yet; they wait for the first fit, which
            # places every chunk anyway.
            return None
        started = time.perf_counter()
        t = time.perf_counter()
        read = workspace.store.chunks_for_placement(batch)
        ms_read = (time.perf_counter() - t) * 1000
        keep, gone, waiting = [], [], []
        for cid, chunk, vector in read:
            if chunk is None or chunk.redundant or (
                    chunk.group_of and chunk.group_of != cid):
                gone.append((cid, chunk.url if chunk is not None else None))
            elif not vector or not any(vector):
                waiting.append(cid)
            else:
                keep.append((cid, chunk.url, np.asarray(vector, dtype=np.float32)))
        ms_transform = 0.0
        where = colour = None
        if keep:
            t = time.perf_counter()
            where, colour = projection.place(
                np.asarray([k[2] for k in keep], dtype=np.float32))
            ms_transform = (time.perf_counter() - t) * 1000
        pages = set()
        with self.lock:
            if projection is not self.projection:
                # A refit landed while this batch was in flight: its
                # coordinates are in the old frame. Requeue rather than mix.
                self.enqueue(batch)
                return None
            for cid, url in gone:
                if cid in self.pos:
                    self.pos.pop(cid, None)
                    self.hsv.pop(cid, None)
                    self.vec.pop(cid, None)
                    was = self.url_of.pop(cid, url)
                    if was:
                        self.by_url.get(was, set()).discard(cid)
                        pages.add(was)
                    self.seq += 1
                    self.log.append((self.seq, "gone", cid))
            if where is not None:
                for i, (cid, url, v) in enumerate(keep):
                    self.pos[cid] = [float(x) for x in where[i][:self.dims]]
                    if colour is not None:
                        self.hsv[cid] = [float(x) for x in colour[i]]
                    self.vec[cid] = v
                    self.url_of[cid] = url
                    self.by_url.setdefault(url, set()).add(cid)
                    pages.add(url)
                    self.seq += 1
                    self.log.append((self.seq, "chunk", cid))
                self.placed_total += len(keep)
            if pages:
                live = {u: cs for u, cs in self.by_url.items()
                        if u in pages and cs}
                pp, ph = self._pages(projection, live, self.vec)
                for u in pages:
                    if u in pp:
                        self.page_pos[u] = pp[u]
                        if u in ph:
                            self.page_hsv[u] = ph[u]
                    elif not self.by_url.get(u):
                        self.page_pos.pop(u, None)
                        self.page_hsv.pop(u, None)
                    self.seq += 1
                    self.log.append((self.seq, "page", u))
        record = {
            "batch": len(batch), "placed": len(keep), "gone": len(gone),
            "waiting": len(waiting), "pages": len(pages),
            "ms_read": round(ms_read, 1), "ms_transform": round(ms_transform, 1),
            "ms": round((time.perf_counter() - started) * 1000, 1),
            "queue_after": len(self.queue), "seq": self.seq, "epoch": self.epoch,
            "at": round(time.time(), 3),
        }
        self.batches.append(record)
        if self.on_batch:
            try:
                self.on_batch(record)
            except Exception:                       # noqa: BLE001
                pass
        return record

    def stale(self, workspace) -> bool:
        return bool(self.fitted_chunks) and (
            workspace.store.chunk_count() >= 2 * self.fitted_chunks)

    def start(self, workspace, *, work_lock=None, fit_lock=None) -> None:
        """The worker: fit once, then drain the queue; refit at 2x growth."""
        if self._thread is not None:
            return
        self.work_lock, self.fit_lock = work_lock, fit_lock

        def run():
            # A kept fit comes back in seconds and is reconciled against the
            # store; only a missing or unreadable one is refitted.
            if not self.load(workspace):
                self.fit(workspace)
            checked = 0.0
            while not self._stop.is_set():
                self.wanted.wait(timeout=1.0)
                self.wanted.clear()
                while self.queue and not self._stop.is_set():
                    try:
                        with (self.work_lock or nullcontext()):
                            got = self.drain(workspace)
                    except Exception:               # noqa: BLE001
                        break
                    if got is None:
                        break
                if time.monotonic() - checked > 5.0:
                    checked = time.monotonic()
                    try:
                        with (self.work_lock or nullcontext()):
                            self.chunks_now = int(workspace.store.chunk_count())
                            due = self.projection is None or (
                                bool(self.fitted_chunks)
                                and self.chunks_now >= 2 * self.fitted_chunks)
                    except Exception:               # noqa: BLE001
                        due = False
                    if due and not self.fitting:
                        # Off this thread, so the stream keeps draining into
                        # the old fit while the new one is made.
                        threading.Thread(target=self.fit, args=(workspace,),
                                         name="domvec-refit",
                                         daemon=True).start()

        self._thread = threading.Thread(target=run, name="domvec-projector",
                                        daemon=True)
        self._thread.start()

    # -- persistence ----------------------------------------------------------
    #: Written beside the store. A pickle, because the UMAP model is a
    #: Python object with fitted numba state and has no other serialisation;
    #: it is read back only by this process's own code, from the workspace's
    #: own directory.
    FILE = "projector.pkl"

    def _file(self, workspace):
        from pathlib import Path
        base = getattr(workspace, "path", None)
        return Path(base) / self.FILE if base else None

    def save(self, workspace) -> bool:
        import pickle
        path = self._file(workspace)
        if path is None:
            return False
        with self.lock:
            state = {"version": 1, "dims": self.dims, "projection": self.projection,
                     "pos": self.pos, "hsv": self.hsv, "url_of": self.url_of,
                     "vec": self.vec, "page_pos": self.page_pos,
                     "page_hsv": self.page_hsv, "fitted_chunks": self.fitted_chunks,
                     "fitted_points": self.fitted_points,
                     "fit_sample": self.fit_sample, "epoch": self.epoch,
                     "fits": self.fits}
        try:
            tmp = path.with_suffix(".tmp")
            with open(tmp, "wb") as fh:
                pickle.dump(state, fh, protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(path)
            return True
        except Exception as exc:                    # noqa: BLE001
            self.fit_error = "save failed: %s: %s" % (type(exc).__name__, exc)
            return False

    def load(self, workspace) -> bool:
        """Restore a kept fit and reconcile it against the store, O(delta).

        Every drawable chunk whose vector differs from the one its position
        was made from -- or that the kept fit never saw -- is queued for the
        stream; every one the store no longer has is queued too, and the
        drain reports it gone. Nothing already placed moves.
        """
        import pickle
        path = self._file(workspace)
        if path is None or not path.exists():
            return False
        started = time.perf_counter()
        try:
            with open(path, "rb") as fh:
                state = pickle.load(fh)
            if state.get("version") != 1 or state.get("dims") != self.dims                     or state.get("projection") is None:
                return False
        except Exception as exc:                    # noqa: BLE001
            self.fit_error = "load failed: %s: %s" % (type(exc).__name__, exc)
            return False
        ms_load = (time.perf_counter() - started) * 1000
        with self.lock:
            self.projection = state["projection"]
            self.pos, self.hsv = state["pos"], state["hsv"]
            self.url_of, self.vec = state["url_of"], state["vec"]
            self.by_url = {}
            for cid, url in self.url_of.items():
                self.by_url.setdefault(url, set()).add(cid)
            self.page_pos, self.page_hsv = state["page_pos"], state["page_hsv"]
            self.fitted_chunks = state["fitted_chunks"]
            self.fitted_points = state["fitted_points"]
            self.fit_sample = state["fit_sample"]
            # A new number, so a pane from before this process reloads.
            self.epoch = _next_epoch(int(state["epoch"]))
            self.fits = list(state.get("fits") or [])
            self.log.clear()
        t = time.perf_counter()
        with (self.work_lock or nullcontext()):
            rows = workspace.store.lead_vectors()
        now = {}
        changed = []
        for cid, url, vector in rows:
            now[cid] = url
            kept = self.vec.get(cid)
            if kept is None or self.url_of.get(cid) != url or not np.allclose(
                    kept, np.asarray(vector, dtype=np.float32), atol=1e-5):
                changed.append(cid)
        gone = [c for c in self.pos if c not in now]
        self.enqueue(changed + gone)
        record = {"epoch": self.epoch, "loaded": True,
                  "chunks": len(rows), "distinct": len(now),
                  "changed": len(changed), "gone": len(gone),
                  "ms_load": round(ms_load, 1),
                  "ms_reconcile": round((time.perf_counter() - t) * 1000, 1),
                  "fitted_chunks": self.fitted_chunks, "sample": self.fit_sample,
                  "at": round(time.time(), 3)}
        self.fits.append(record)
        if self.on_fit:
            try:
                self.on_fit(record)
            except Exception:                       # noqa: BLE001
                pass
        return True

    def stop(self) -> None:
        self._stop.set()
        self.wanted.set()

    # -- reading ------------------------------------------------------------
    def status(self, workspace=None, url: str = "") -> Dict:
        total = None
        if workspace is not None:
            try:
                total = int(workspace.store.chunk_count())
            except Exception:                       # noqa: BLE001
                total = None
        last = self.batches[-1] if self.batches else None
        out = {
            "epoch": self.epoch, "seq": self.seq,
            "fitted": self.projection is not None,
            "fitting": self.fitting, "fit_error": self.fit_error,
            "fitted_chunks": self.fitted_chunks,
            "fit_sample": self.fit_sample,
            "chunks_now": total,
            "growth": (round(total / self.fitted_chunks, 3)
                       if total and self.fitted_chunks else None),
            "refit_at": 2 * self.fitted_chunks if self.fitted_chunks else None,
            "projected": len(self.pos), "pages": len(self.page_pos),
            "queue": len(self.queue), "placed_total": self.placed_total,
            "last_batch": last, "last_fit": self.fits[-1] if self.fits else None,
        }
        if url:
            out["page"] = {"url": url,
                           "projected": len(self.by_url.get(url) or ()),
                           "pos": self.page_pos.get(url)}
        return out

    def brief(self) -> Dict:
        """The state a pane polls with every delta: no store query."""
        return {"epoch": self.epoch, "fitting": self.fitting,
                "fitted_chunks": self.fitted_chunks,
                "fit_sample": self.fit_sample,
                "refit_at": 2 * self.fitted_chunks if self.fitted_chunks else None,
                "chunks_now": self.chunks_now,
                "projected": len(self.pos), "queue": len(self.queue),
                "placed_total": self.placed_total}

    def delta(self, since: int, epoch: int) -> Dict:
        """What changed after `since`, or `reload` when that cannot be said."""
        with self.lock:
            if epoch != self.epoch:
                return {"epoch": self.epoch, "seq": self.seq, "reload": True,
                        "status": self.brief()}
            if self.log and since < self.log[0][0] - 1:
                return {"epoch": self.epoch, "seq": self.seq, "reload": True,
                        "status": self.brief()}
            chunks, gone, pages = {}, set(), set()
            for seq, kind, key in self.log:
                if seq <= since:
                    continue
                if kind == "chunk":
                    chunks[key] = None
                    gone.discard(key)
                elif kind == "gone":
                    gone.add(key)
                    chunks.pop(key, None)
                else:
                    pages.add(key)
            return {
                "epoch": self.epoch, "seq": self.seq, "reload": False,
                "status": self.brief(),
                "chunks": {c: {"pos": self.pos[c], "hsv": self.hsv.get(c),
                               "url": self.url_of.get(c)}
                           for c in chunks if c in self.pos},
                "gone": sorted(gone),
                "pages": {u: {"pos": self.page_pos.get(u),
                              "hsv": self.page_hsv.get(u),
                              "projected": len(self.by_url.get(u) or ())}
                          for u in pages},
            }

    def neighbourhoods_kept(self, sample: int = 2000, k: int = 8,
                            seed: int = 0) -> Dict:
        """How much of each chunk's k-NN in the ENCODER's space survives in
        the drawn 3D space -- the measure the old local layout was justified
        by (0.078 kept, random 0.030, for chunks transformed into the
        page-mean fit). Computed on a sample, with its own random baseline.
        """
        with self.lock:
            cids = [c for c in self.pos if c in self.vec]
            if len(cids) <= k + 1:
                return {"n": len(cids)}
            V = np.asarray([self.vec[c] for c in cids], dtype=np.float32)
            X = np.asarray([self.pos[c] for c in cids], dtype=np.float32)
        V /= np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)
        rng = np.random.default_rng(seed)
        pick = rng.choice(len(cids), min(sample, len(cids)), replace=False)
        kept = []
        for i in pick:
            sim = V @ V[i]
            sim[i] = -np.inf
            near_v = set(np.argpartition(-sim, k)[:k])
            d = np.linalg.norm(X - X[i], axis=1)
            d[i] = np.inf
            near_x = set(np.argpartition(d, k)[:k])
            kept.append(len(near_v & near_x) / k)
        return {"n": len(cids), "sample": int(len(pick)), "k": k,
                "kept": round(float(np.mean(kept)), 4),
                "random": round(k / (len(cids) - 1), 5)}

    def chunk_pos(self, cid: str) -> Optional[List[float]]:
        return self.pos.get(cid)

    def page_at(self, url: str) -> Optional[List[float]]:
        return self.page_pos.get(url)


#: The sidecar's one projector. `None` until `serve()` makes it.
PROJECTOR: Optional[ChunkProjector] = None


def projector() -> Optional[ChunkProjector]:
    return PROJECTOR
