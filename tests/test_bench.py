"""The parallel runner, tested on the three things that fail quietly.

A runner is easy to write and easy to get wrong in ways nothing notices: a
page that vanishes from the results, a resumed run that redoes everything, an
exception that stops a sweep four hours in. All three produce a plausible
number at the end, which is the worst failure mode a measuring instrument
has.

The measurement functions are module-level because a worker process imports
this module to find them. A closure or a lambda cannot cross that boundary,
and the failure is a pickling error at the first submit.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from vertiscope.bench import (
    completed_keys,
    default_jobs,
    run_pages,
    summarise,
)


def _double(page):
    return {"page": page["page"], "value": page["n"] * 2}


def _explode(page):
    if page["n"] == 2:
        raise ValueError("page 2 is bad")
    return {"page": page["page"], "value": page["n"]}


def _pages(n):
    return [{"page": f"p{i}", "n": i} for i in range(n)]


# --- every page is accounted for --------------------------------------------


@pytest.mark.parametrize("jobs", [1, 2])
def test_every_page_yields_exactly_one_row(jobs):
    rows = list(run_pages(_pages(6), _double, jobs=jobs))
    assert sorted(r["page"] for r in rows) == [f"p{i}" for i in range(6)]


@pytest.mark.parametrize("jobs", [1, 2])
def test_a_failing_page_is_a_row_not_a_stop(jobs):
    """A sweep that stops at the first bad page reports a biased sample.

    The pages that break the parser are the ones worth knowing about, so they
    have to arrive as data. Silently dropping them would leave a distribution
    computed only over the pages that happened to work.
    """
    rows = list(run_pages(_pages(4), _explode, jobs=jobs))
    assert len(rows) == 4
    bad = [r for r in rows if "error" in r]
    assert len(bad) == 1 and bad[0]["page"] == "p2"
    assert "ValueError" in bad[0]["error"]
    assert "page 2 is bad" in bad[0]["error"]
    # The other three still carry their answers.
    good = {r["page"]: r["value"] for r in rows if "error" not in r}
    assert good == {"p0": 0, "p1": 1, "p3": 3}


def test_a_failed_page_carries_a_traceback():
    """Without it, a sweep's failures are unactionable strings."""
    rows = list(run_pages(_pages(3), _explode, jobs=1))
    bad = next(r for r in rows if "error" in r)
    assert "ValueError" in bad["traceback"]


# --- resuming ---------------------------------------------------------------


def test_results_are_written_as_they_arrive(tmp_path):
    """Flushed per row: a killed run keeps everything it had finished."""
    out = tmp_path / "r.jsonl"
    list(run_pages(_pages(4), _double, jobs=1, results_path=out))
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert sorted(r["page"] for r in rows) == ["p0", "p1", "p2", "p3"]


def test_a_resumed_run_skips_what_is_already_recorded(tmp_path):
    out = tmp_path / "r.jsonl"
    first = list(run_pages(_pages(4), _double, jobs=1, results_path=out))
    assert len(first) == 4

    second = list(run_pages(_pages(6), _double, jobs=1,
                            results_path=out, resume=True))
    assert sorted(r["page"] for r in second) == ["p4", "p5"], \
        "a resumed run redid work it had already recorded"

    everything = [json.loads(l)
                  for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(everything) == 6


def test_resume_false_redoes_everything(tmp_path):
    out = tmp_path / "r.jsonl"
    list(run_pages(_pages(3), _double, jobs=1, results_path=out))
    again = list(run_pages(_pages(3), _double, jobs=1,
                           results_path=out, resume=False))
    assert len(again) == 3


def test_a_truncated_tail_does_not_lose_the_whole_file(tmp_path):
    """A run killed mid-write leaves half a line.

    Refusing to read the file because of it would throw away the hours the
    resume exists to protect — so the half line is dropped and its page is
    redone, which is the one page whose result was never complete anyway.
    """
    out = tmp_path / "r.jsonl"
    out.write_text('{"page": "p0", "value": 0}\n{"page": "p1", "val',
                   encoding="utf-8")
    assert completed_keys(out) == {"p0"}


def test_completed_keys_of_a_missing_file_is_empty(tmp_path):
    assert completed_keys(tmp_path / "nope.jsonl") == set()
    assert completed_keys(None) == set()


# --- the defaults -----------------------------------------------------------


def test_default_jobs_leaves_the_machine_usable():
    """Half the cores, and never zero on a single-core box."""
    import os
    assert default_jobs() == max(1, (os.cpu_count() or 2) // 2)
    assert default_jobs() >= 1


# --- reporting --------------------------------------------------------------


def test_summarise_reports_percentiles_not_a_mean():
    """A mean over a hundred thousand pages hides the tail that costs money."""
    rows = [{"page": f"p{i}", "seconds": i} for i in range(100)]
    rows.append({"page": "bad", "error": "boom"})
    out = summarise(rows, ["seconds"])
    assert out == {
        "pages": 101, "ok": 100, "failed": 1,
        "seconds": {"p50": 49.5, "p90": 90, "p99": 99, "min": 0, "max": 99},
    }


def test_summarise_ignores_a_field_no_page_reported():
    out = summarise([{"page": "p", "seconds": 1}], ["lines"])
    assert "lines" not in out and out["ok"] == 1


# --- surviving a worker that dies hard --------------------------------------


def _suicide(page):
    """Die the way a segfaulting C parser dies: no exception, no unwinding."""
    import os
    if page["page"] == "p2":
        os._exit(1)
    return {"page": page["page"], "value": page["n"]}


def test_a_page_that_kills_a_worker_does_not_kill_the_run():
    """One poison page must cost one page, not its batch.

    Measured while writing this: charging the whole in-flight batch for a
    pool death lost six good pages to one bad one. At a hundred thousand
    pages, a handful of poison pages would erase thousands of results — and
    the sweep would still print a confident summary over what survived.

    So a broken pool re-runs the survivors one at a time. A batch of one that
    dies is, unambiguously, the page that died.
    """
    rows = list(run_pages(_pages(8), _suicide, jobs=4))

    assert len(rows) == 8, "the run must still account for every page"
    failed = [r for r in rows if "error" in r]
    assert [r["page"] for r in failed] == ["p2"], \
        f"expected only p2 to fail, got {[r['page'] for r in failed]}"
    survived = {r["page"]: r["value"] for r in rows if "error" not in r}
    assert survived == {f"p{i}": i for i in range(8) if i != 2}
