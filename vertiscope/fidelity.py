"""The round-trip measurement: page -> chunks -> JSONL -> widgets -> repaint.

Shared by `scripts/audit_roundtrip.py`, which reports it over the corpus, and
`tests/test_roundtrip_fidelity.py`, which asserts on it. One measurement with
two consumers rather than two implementations that can disagree — the defect
this whole check exists to catch is two pieces of code drifting apart, and it
would be absurd to introduce a fresh instance of it here.

Returns plain dicts so a worker process can send results back: the parallel
runner is what takes the corpus pass from 204s to 27s, and the test cannot
afford the serial version.
"""

from __future__ import annotations

import pathlib
import tempfile

from .markdown import read_jsonl, render_trie, write_jsonl
from .pipeline import run_pipeline
from .repl.model import Document
from .trie import AddressTrie

__all__ = ["measure", "measure_page"]


def measure(path: pathlib.Path, url: str, window: int = 1200,
            keep: int = 4) -> dict:
    source = path.read_text(encoding="utf-8", errors="replace")
    trie = AddressTrie.from_tagged(run_pipeline(source, url).tagged, url)
    chunks = render_trie(trie, context_window=window)
    lines = [line for chunk in chunks for line in chunk.lines]

    # The checkpoint hop, through a real file. Writing what was read and
    # comparing bytes is the only check that does not trust the reader and
    # the writer to be wrong in the same direction.
    with tempfile.TemporaryDirectory(prefix="vertiscope_rt_") as tmp:
        first = pathlib.Path(tmp) / "a.jsonl"
        second = pathlib.Path(tmp) / "b.jsonl"
        write_jsonl(chunks, first)
        reloaded = list(read_jsonl(first))
        write_jsonl(reloaded, second)
        identical = first.read_bytes() == second.read_bytes()

    back = [line for chunk in reloaded for line in chunk.lines]
    doc = Document.from_chunks(reloaded)

    kept_addresses = sum(
        1 for a, b in zip(lines, back)
        if (a.address is None) == (b.address is None)
        and (a.address is None or str(a.address) == str(b.address)))

    bad, mismatches = 0, []
    for widget, line in zip(doc.lines, back):
        want = "  " * line.depth + line.text
        got = widget.render()
        if got != want:
            bad += 1
            if len(mismatches) < keep:
                mismatches.append({"want": want, "got": got,
                                   "kind": widget.kind.value})

    n = len(back)
    return {
        "page": path.stem,
        "lines": len(lines),
        "reloaded_lines": n,
        "widgets": len(doc.lines),
        "identical": identical,
        "repaint": (n - bad) / n if n else 1.0,
        "bad": bad,
        "addresses": kept_addresses / len(lines) if lines else 1.0,
        "samples": [m for m in mismatches if m],
    }



def measure_page(page: dict) -> dict:
    """Runner entry point: module-level so a worker process can import it."""
    return measure(pathlib.Path(page["path"]), page["url"],
                   window=page.get("window", 1200),
                   keep=page.get("keep", 4))
