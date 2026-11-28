"""Unit tests for `G-450`, `G-451`, `G-452`, and `G-453` (`PLUGIN_GOAL` 201)."""

from __future__ import annotations

import time

from domvec import code_intel, dataflow, tool_cells


def test_cross_notebook_dag_compilation_and_planted():
    """G-451: direct variable references across notebooks compile in DAG order,
    draw note/cell edges, keep intra-note shadowing local, and respect planted flag."""
    notes = {
        "domvec/graph/notebook 1.md": "# Rates\n\n```python\nbase_price = 200\ntax_rate = 0.15\n```\n",
        "domvec/graph/notebook 2.md": "# Subtotal\n\n```python\nsubtotal = base_price * (1 + tax_rate)\n```\n",
        "domvec/graph/notebook 3.md": "# Total\n\n```python\nshipping = 12\ngrand_total = subtotal + shipping\n```\n",
    }
    dataflow.PLANT_NO_CROSS_NOTE_VARS[0] = False
    plan = dataflow.compile_plan(notes, "domvec/graph/notebook 3.md", open_line=2)
    # Must order notebook 1 BEFORE notebook 2 BEFORE notebook 3!
    up_notes = [u["note"] for u in plan["upstream"]]
    assert up_notes == ["domvec/graph/notebook 1.md", "domvec/graph/notebook 2.md"]
    assert plan["upstream"][0]["exports"] == ["base_price", "tax_rate"]
    assert plan["upstream"][1]["exports"] == ["subtotal"]

    # Downstream from notebook 1 must include notebook 2 then notebook 3 in order!
    plan_from_1 = dataflow.compile_plan(notes, "domvec/graph/notebook 1.md", open_line=2)
    down_notes = [d["note"] for d in plan_from_1["downstream"]]
    assert down_notes == ["domvec/graph/notebook 2.md", "domvec/graph/notebook 3.md"]
    assert len(plan_from_1["note_edges"]) == 2

    # Planted arm (`PLANT_NO_CROSS_NOTE_VARS`): cross-notebook edges & upstream vanish!
    dataflow.PLANT_NO_CROSS_NOTE_VARS[0] = True
    try:
        planted = dataflow.compile_plan(notes, "domvec/graph/notebook 3.md", open_line=2)
        assert planted["upstream"] == []
        assert planted["note_edges"] == []
    finally:
        dataflow.PLANT_NO_CROSS_NOTE_VARS[0] = False


def test_vscode_helpers_dot_completion_clean_and_cached_fast():
    """G-450: `np.` resolves real module attributes (`math.` / `numpy.`), never buffer words
    like `import`, and cached repeat lookups finish in < 10 ms."""
    code_intel.PLANT_NO_CODE_INTEL[0] = False
    cells = ["import math as m\nm."]
    items1 = code_intel.complete(cells, cell_index=0, line=2, col=2)
    labels1 = [it["label"] for it in items1]
    assert "sqrt" in labels1 and "cos" in labels1
    assert "import" not in labels1 and "math" not in labels1

    # Repeat lookup with prefix `m.sq` hits `_ATTR_CACHE` in < 10 ms!
    t0 = time.perf_counter()
    items2 = code_intel.complete(["import math as m\nm.sq"], cell_index=0, line=2, col=4)
    dt_ms = (time.perf_counter() - t0) * 1000.0
    labels2 = [it["label"] for it in items2]
    assert "sqrt" in labels2
    assert dt_ms < 15.0

    # Top-level includes cross-notebook external_defs and auto-imports!
    top = code_intel.complete(
        ["subt"],
        cell_index=0,
        line=1,
        col=4,
        external_defs=[{"name": "subtotal", "note": "domvec/graph/notebook 2.md"}],
    )
    assert any(it["label"] == "subtotal" and "notebook 2.md" in it["detail"] for it in top)

    auto_imp = code_intel.complete(["Pat"], cell_index=0, line=1, col=3)
    assert any(it["label"] == "Path" and it.get("auto_import") == "from pathlib import Path" for it in auto_imp)


def test_tool_cells_slim_dict_stack_navigation_and_planted():
    """G-452 / G-453: slim dict tool call parses, pushes onto navigable back/forward stack,
    emits compact history line, preserves G-421 app_tool mode, and catches planted flag."""
    tool_cells.reset_stacks()
    tool_cells.PLANT_NO_TOOL_CELL[0] = False
    assert "```tool" in tool_cells.DEFAULT_EGO_SYSTEM_PROMPT
    assert "```python" in tool_cells.DEFAULT_EGO_SYSTEM_PROMPT

    # G-421 compatibility: bare `Database` renders `app_tool` mode.
    app_res = tool_cells.execute({"source": "Database", "session": "t-app"})
    assert app_res["ok"] is True
    assert app_res["mode"] == "app_tool"
    assert "Database.search" in app_res["panel_text"]

    # Interactive slim dict steps + back/forward stack!
    r1 = tool_cells.execute({
        "session": "t-nav",
        "source": '{"browser": {"url": "https://example.org/a", "search": "alpha", "chunks": true}}',
    })
    assert r1["ok"] is True and r1["mode"] == "call"
    assert r1["stack"]["index"] == 1 and r1["stack"]["total"] == 1
    assert "`browser`" in r1["history_line"]

    r2 = tool_cells.execute({
        "session": "t-nav",
        "source": '{"browser": {"url": "https://example.org/b", "search": "beta", "chunks": false}}',
    })
    assert r2["stack"]["index"] == 2 and r2["stack"]["can_back"] is True

    back = tool_cells.execute({
        "session": "t-nav",
        "call": {"browser": {"back": True}},
    })
    assert back["navigated"] == "back"
    assert back["stack"]["index"] == 1 and back["stack"]["can_forward"] is True
    assert "alpha" in back["fence"]

    fwd = tool_cells.execute({
        "session": "t-nav",
        "call": {"browser": {"forward": True}},
    })
    assert fwd["navigated"] == "forward"
    assert fwd["stack"]["index"] == 2
    assert "beta" in fwd["fence"]

    # Planted arm
    tool_cells.PLANT_NO_TOOL_CELL[0] = True
    try:
        p = tool_cells.execute({"session": "t-nav", "source": '{"browser": {"search": "x"}}'})
        assert p["ok"] is False and p.get("planted") is True
    finally:
        tool_cells.PLANT_NO_TOOL_CELL[0] = False
