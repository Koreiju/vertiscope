"""Unit tests for fence-adaptive Python code intelligence (`G-447`)."""

from __future__ import annotations

import importlib.util

from domvec import code_intel


def test_complete_import_and_cross_cell_symbols():
    # Cell 0: `from network` -> completes installed `networkx` (or `import json; json.du` -> `dumps`).
    has_nx = importlib.util.find_spec("networkx") is not None
    if has_nx:
        items_nx = code_intel.complete(["from network"], cell_index=0, line=1, col=len("from network"))
        assert any(it["label"] == "networkx" for it in items_nx)

    # Cross-cell completion: cell 0 defines `compute_degree`, cell 1 completes `compute_deg`.
    cells = [
        'def compute_degree(nodes: list[int], scale: float = 1.0) -> float:\n    """Weighted mean degree."""\n    return len(nodes) * scale',
        "val = compute_deg",
    ]
    items = code_intel.complete(cells, cell_index=1, line=1, col=len("val = compute_deg"))
    hit = next((it for it in items if it["label"] == "compute_degree"), None)
    assert hit is not None
    assert hit["type"] == "function"
    assert "Weighted mean degree" in hit["info"]


def test_signature_hover_goto_and_app_tool_boundary():
    cells = [
        'def compute_degree(nodes: list[int], scale: float = 1.0) -> float:\n    """Weighted mean degree."""\n    return len(nodes) * scale',
        "res = compute_degree([1, 2], ",
        "hits = Database.search('trie', ",
    ]
    # 1. Signature help on user cell function (2nd arg active -> index == 1).
    sigs = code_intel.signature(cells, cell_index=1, line=1, col=len(cells[1]))
    assert sigs and sigs[0]["name"] == "compute_degree"
    assert sigs[0]["index"] == 1
    assert len(sigs[0]["params"]) == 2

    # 2. Hover docstring on user cell function.
    hv = code_intel.hover(cells, cell_index=1, line=1, col=10)
    assert hv is not None
    assert hv["name"] == "compute_degree"
    assert "Weighted mean degree" in hv["docstring"]

    # 3. Go-to-definition jumps back to cell 0, line 1!
    gt = code_intel.goto(cells, cell_index=1, line=1, col=10)
    assert gt is not None
    assert gt["kind"] == "cell"
    assert gt["cell_index"] == 0
    assert gt["line"] == 1

    # 4. Kernel app tool (`Database.search`) completes & shows signature, but
    #    goto stops at `kind == "app_tool"` (Spec §13n boundary 2).
    db_sigs = code_intel.signature(cells, cell_index=2, line=1, col=len(cells[2]))
    assert db_sigs and db_sigs[0]["name"] == "search"
    db_gt = code_intel.goto(cells, cell_index=2, line=1, col=18)
    assert db_gt is not None and db_gt["kind"] == "app_tool"


def test_diagnostics_and_planted_no_code_intel():
    diags = code_intel.diagnostics(["x = 1", "def broken(\n    pass"])
    assert len(diags) >= 1
    assert diags[0]["cell_index"] == 1

    # Non-vacuity check: `PLANT_NO_CODE_INTEL` suppresses all code intelligence.
    code_intel.PLANT_NO_CODE_INTEL[0] = True
    try:
        assert code_intel.complete(["import json\njson.du"], 0, 2, 7) == []
        assert code_intel.signature(["len("], 0, 1, 4) == []
        assert code_intel.hover(["len"], 0, 1, 1) is None
        assert code_intel.goto(["len"], 0, 1, 1) is None
        assert code_intel.diagnostics(["def broken(\n"]) == []
    finally:
        code_intel.PLANT_NO_CODE_INTEL[0] = False
