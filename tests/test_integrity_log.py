"""The store dates its own string loss (D-48, 2026-10-07).

Twice most chunk markdown went empty with its integers intact and nothing
recorded when. `integrity.log` gets a record at every sidecar start and every
quiet interval; a count that ROSE says so. The planted arm blanks markdown
the way the working store was found and must be flagged; the null arm, a
second record with nothing changed, must not be."""

import json
from pathlib import Path

from domvec.obsidian import sidecar
from domvec.workspace import Workspace

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
