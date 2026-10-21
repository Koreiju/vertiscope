"""The store dates its own string loss (D-48, 2026-10-07).

Twice most chunk markdown went empty with its integers intact and nothing
recorded when. `integrity.log` gets a record at every sidecar start and every
quiet interval; a count that ROSE says so. The planted arm blanks markdown
the way the working store was found and must be flagged; the null arm, a
second record with nothing changed, must not be."""

import json
from pathlib import Path

from vertiscope.obsidian import sidecar
from vertiscope.workspace import Workspace

HTML = "<html><body><h1>Title</h1>" + "".join(
    "<p>para %d with enough words to chunk</p>" % i for i in range(60)) + "</body></html>"


def _records(ws):
    return [json.loads(x) for x in (Path(ws.path) / "integrity.log").read_text().splitlines()]


def test_a_record_is_written_and_a_quiet_one_raises_nothing(tmp_path):
    sidecar._INTEGRITY_LAST.clear()
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, "http://a.test/p")
        first = sidecar._integrity_record(ws, "start")
        second = sidecar._integrity_record(ws, "quiet")
        assert first["chunks"] > 0 and first["empty_md"] == 0
        assert "ROSE" not in second                     # null arm
        assert [r["why"] for r in _records(ws)] == ["start", "quiet"]


def test_planted_blanked_markdown_is_flagged(tmp_path):
    sidecar._INTEGRITY_LAST.clear()
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, "http://a.test/p")
        sidecar._integrity_record(ws, "start")
        ws.store._execute("MATCH (c:Chunk) SET c.md = ''")
        ws.store._execute("MATCH (a:Address) SET a.akey = ''")
        got = sidecar._integrity_record(ws, "quiet")
        assert got["ROSE"]["empty_md"] == got["chunks"]
        assert got["ROSE"]["blank_akey"] == got["addresses"] > 0
        assert _records(ws)[-1]["ROSE"] == got["ROSE"]


def _blank_across_a_restart(tmp_path):
    """A loss that happens BETWEEN two processes: the new process's baseline
    is empty in memory, and only the log on disk knows what was there."""
    sidecar._INTEGRITY_LAST.clear()
    ws = Workspace(tmp_path)
    ws.index_html(HTML, "http://a.test/p")
    sidecar._integrity_record(ws, "start")
    ws.store._execute("MATCH (c:Chunk) SET c.md = ''")
    sidecar._INTEGRITY_LAST.clear()                       # "a new process"
    return ws


def test_a_loss_across_a_restart_is_flagged_and_healed(tmp_path, monkeypatch):
    monkeypatch.setattr(sidecar, "_MD_HEAL_AT", 1)
    ws = _blank_across_a_restart(tmp_path)
    try:
        rec = sidecar._integrity_record(ws, "start")
        assert rec["ROSE"]["empty_md"] == rec["chunks"] > 0
        healed = sidecar._heal_markdown(ws, rec)
        assert healed is not None and healed["empty_md"] == 0
        assert healed["why"].startswith("healed ")
    finally:
        ws.close()


def test_planted_no_heal_leaves_it_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(sidecar, "_MD_HEAL_AT", 1)
    sidecar._PLANT_NO_MD_HEAL[0] = True
    ws = _blank_across_a_restart(tmp_path)
    try:
        rec = sidecar._integrity_record(ws, "start")
        assert rec["ROSE"]["empty_md"] > 0                # still flagged
        assert sidecar._heal_markdown(ws, rec) is None
        assert sidecar._integrity_counts(ws.store)["empty_md"] == rec["chunks"]
    finally:
        sidecar._PLANT_NO_MD_HEAL[0] = False
        ws.close()
