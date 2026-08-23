"""Run a measurement over many pages, in parallel, without losing the run.

The audits grew up serial over 136 pages. At a thousand that is tedious and at
a hundred thousand it is impossible, so the loop moves here where every audit
can share it — and where the three things that go wrong at scale are handled
once.

**One page must not be able to end the run.** At a hundred thousand pages
something will hang and something will crash the interpreter. A hung page is
abandoned after `timeout`; a worker that dies takes its page down as a failure
and the pool is rebuilt around it.

**A killed run must not start over.** Results append to JSONL as they arrive,
and `resume` skips what a previous run already recorded. Interrupting a sweep
should cost the pages in flight, not the hours behind it.

**The machine stays usable.** `jobs` defaults to half the cores. A benchmark
that makes the desktop unusable is a benchmark nobody runs, and I have
already misread contention from my own background jobs as the suite being
slow.

The measurement function must be importable by name in a subprocess — a
module-level function, not a lambda or a closure.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, TimeoutError as _Timeout
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

__all__ = ["default_jobs", "run_pages", "completed_keys", "Result"]

Result = Dict[str, Any]


def default_jobs() -> int:
    """Half the cores, at least one.

    Half rather than all: the machine has a user on it. The parse is CPU-bound
    with no shared state, so the marginal core is close to linear and giving
    up the second half costs a factor of two on a run that is already batch.
    """
    return max(1, (os.cpu_count() or 2) // 2)


def completed_keys(results_path: Optional[pathlib.Path], key: str = "page") -> set:
    """What a previous run already recorded, so a resumed run can skip it.

    Tolerates a truncated final line: a run killed mid-write leaves one, and
    refusing to read the file because of it would throw away the whole point.
    """
    if results_path is None or not pathlib.Path(results_path).exists():
        return set()
    done = set()
    with open(results_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # truncated tail of an interrupted run
            if key in row:
                done.add(row[key])
    return done


def run_pages(
    pages: Iterable[Dict[str, Any]],
    measure: Callable[[Dict[str, Any]], Result],
    *,
    jobs: Optional[int] = None,
    timeout: float = 300.0,
    results_path: Optional[pathlib.Path] = None,
    resume: bool = True,
    key: str = "page",
    on_result: Optional[Callable[[Result], None]] = None,
) -> Iterator[Result]:
    """Apply `measure` to every page, yielding results as they finish.

    Order is completion order, not input order — at scale the alternative is
    holding the whole run in memory to sort it, and every consumer here either
    aggregates or prints.

    A result always appears for every page. A page that times out or crashes
    yields a row carrying `error`, because a sweep whose failures are silent
    reports a survivorship-biased distribution: the pages that break the
    parser are exactly the interesting ones.
    """
    pages = list(pages)
    jobs = jobs or default_jobs()

    done = completed_keys(results_path, key) if resume else set()
    todo = [p for p in pages if p.get(key) not in done]
    skipped = len(pages) - len(todo)
    if skipped:
        print(f"resuming: {skipped} of {len(pages)} already recorded")
    if not todo:
        return

    sink = None
    if results_path is not None:
        pathlib.Path(results_path).parent.mkdir(parents=True, exist_ok=True)
        sink = open(results_path, "a", encoding="utf-8")

    def _emit(row: Result) -> Result:
        if sink is not None:
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()  # a killed run keeps everything it had finished
        if on_result is not None:
            on_result(row)
        return row

    # One worker is a different program: no pickling, no pool, and a traceback
    # that points at the real frame. Debugging a measurement is the reason to
    # ask for `--jobs 1`, so it should be the plain path.
    if jobs == 1:
        try:
            for page in todo:
                yield _emit(_guarded(measure, page, key))
        finally:
            if sink is not None:
                sink.close()
        return

    pending = list(todo)
    try:
        while pending:
            # `max_tasks_per_child` recycles workers, which bounds the leak of
            # any parser holding onto memory across pages. At a hundred
            # thousand pages a small per-page leak is the difference between
            # finishing and swapping.
            # After a crash, the survivors come back one at a time. A pool
            # death cannot say *which* page killed it, so charging the whole
            # batch made one poison page fail its six innocent batch-mates —
            # at a hundred thousand pages that trades a handful of bad pages
            # for thousands of good ones. Isolating identifies the killer
            # exactly: a batch of one that dies is the page that died.
            isolate = bool(pending) and pending[0].get("_isolate")
            batch = pending[:1] if isolate else pending
            pending = pending[len(batch):]
            pool = ProcessPoolExecutor(max_workers=1 if isolate else jobs,
                                       max_tasks_per_child=64)
            futures: Dict[Any, Dict[str, Any]] = {}
            retry: List[Dict[str, Any]] = []
            try:
                # Submitting is inside the guard. A pool whose workers die on
                # startup — an unimportable measurement, a spawn that cannot
                # find the module — breaks at `submit`, and with this outside
                # the `try` the crash handling below could never run: the one
                # failure it exists for was the one that escaped it.
                for page in batch:
                    try:
                        futures[pool.submit(_guarded, measure, page, key)] = page
                    except BrokenProcessPool:
                        retry.append(page)

                # NOT a deadline computed at submit time. Every future got
                # `now + timeout` the moment it was queued, so with 12 workers
                # and 801 pages the ones waiting their turn burned their whole
                # budget in the queue: a sweep reported 279 "timeouts" out of
                # 801 that were nothing of the kind, and the failure
                # distribution it printed was mostly an artifact of its own
                # scheduling. A page's clock starts when we begin waiting on
                # it, not when it was enqueued behind three hundred others.
                # Per future, not around the loop. A dead pool makes *every*
                # remaining `result()` raise, and catching that outside the
                # loop abandoned the futures that had already succeeded: eight
                # pages in, four rows out, with p0-p3 silently gone. Each
                # future now resolves to exactly one of a result, a timeout,
                # or a retry, which is what makes "one row per page" true.
                for future in list(futures):
                    page = futures[future]
                    try:
                        yield _emit(future.result(timeout=timeout))
                    except _Timeout:
                        future.cancel()
                        yield _emit({key: page.get(key), "error": "timeout",
                                     "seconds": timeout})
                    except BrokenProcessPool:
                        retry.append(page)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            # A page that kills a worker *while running alone* is the killer,
            # and is recorded as a failure rather than retried forever —
            # without that, a reliably-fatal page is an infinite loop wearing
            # the costume of a slow run.
            if retry:
                if isolate:
                    for page in retry:
                        yield _emit({key: page.get(key),
                                     "error": "killed the worker process"})
                    print(f"  {retry[0].get(key)} kills a worker; recorded")
                else:
                    for page in retry:
                        page["_isolate"] = True
                    print(f"  worker pool died; re-running {len(retry)} "
                          f"pages one at a time to find the cause")
                    pending = retry + pending
    finally:
        if sink is not None:
            sink.close()


def _guarded(measure: Callable[[Dict[str, Any]], Result],
             page: Dict[str, Any], key: str) -> Result:
    """Run one measurement, turning an exception into a row rather than a stop."""
    started = time.perf_counter()
    try:
        row = measure(page)
    except Exception as exc:  # noqa: BLE001
        return {key: page.get(key), "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=6),
                "seconds": round(time.perf_counter() - started, 3)}
    row.setdefault(key, page.get(key))
    row.setdefault("seconds", round(time.perf_counter() - started, 3))
    return row


def summarise(rows: List[Result], fields: Iterable[str]) -> Dict[str, Any]:
    """Percentiles per field, plus the failures.

    Percentiles rather than means, because the mean of a metric over a hundred
    thousand pages is a number that cannot be acted on. p50 says what usually
    happens; p99 says what the tail costs; the failures say what to fix.
    """
    import statistics as stats

    good = [r for r in rows if "error" not in r]
    out: Dict[str, Any] = {
        "pages": len(rows),
        "ok": len(good),
        "failed": len(rows) - len(good),
    }
    for field in fields:
        values = sorted(r[field] for r in good
                        if isinstance(r.get(field), (int, float)))
        if not values:
            continue
        out[field] = {
            "p50": stats.median(values),
            "p90": values[min(len(values) - 1, int(len(values) * 0.90))],
            "p99": values[min(len(values) - 1, int(len(values) * 0.99))],
            "min": values[0],
            "max": values[-1],
        }
    return out
