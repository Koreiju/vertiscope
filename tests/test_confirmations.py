"""The record of what has been seen working MERGES; a small run forgets nothing.

On 2026-09-26 a three-check run replaced the whole record, and the design
state then reported every other requirement as never seen. The planted arm is
that replace-style write, and it must lose the rows the merge keeps.
"""

import json

from vertiscope.obsidian import confirmations


def _run(ids, passed=True):
    return [{"id": i, "asks": "asks " + i, "pass": passed, "evidence": {"n": 1}}
            for i in ids]


def test_a_small_run_keeps_every_earlier_verdict(tmp_path):
    confirmations.record(_run(["G-1", "G-2", "G-3", "G-4"]), store="working",
                         runner="t", out=tmp_path)
    got = confirmations.record(_run(["G-2"], passed=False),
                               store="fresh run_x, 12/12 pages seeded",
                               runner="t", out=tmp_path)
    by = {r["id"]: r for r in got["results"]}
    assert set(by) == {"G-1", "G-2", "G-3", "G-4"}
    assert by["G-2"]["pass"] is False and by["G-2"]["store"].startswith("fresh")
    assert by["G-1"]["pass"] is True and by["G-1"]["store"] == "working"
    md = (tmp_path / "live_confirmations.md").read_text(encoding="utf-8")
    assert "3 of 4 pass" in md and "fresh run_x" in md


def test_planted_replace_write_forgets(tmp_path):
    """Non-vacuity: the old writer (replace) loses what the merge keeps."""
    def replace(results):
        (tmp_path / "live_confirmations.json").write_text(
            json.dumps({"when": "x", "results": results}), encoding="utf-8")
    replace(_run(["G-1", "G-2", "G-3", "G-4"]))
    replace(_run(["G-2"]))
    held = json.loads((tmp_path / "live_confirmations.json").read_text())["results"]
    assert {r["id"] for r in held} == {"G-2"}


def test_an_old_replace_style_file_is_read_with_its_date(tmp_path):
    (tmp_path / "live_confirmations.json").write_text(json.dumps(
        {"when": "2026-09-20", "results": _run(["G-9"])}), encoding="utf-8")
    got = confirmations.record(_run(["G-1"]), store="working", runner="t",
                               out=tmp_path)
    by = {r["id"]: r for r in got["results"]}
    assert by["G-9"]["when"] == "2026-09-20"
