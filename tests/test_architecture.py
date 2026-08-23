"""Structural guards: the extraction's invariants, enforced.

These are cheap and they are the ones that break silently — a stray import
of a deleted module only fails on the code path that touches it, which may
be the live-scrape path nobody runs in CI.
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "domvec"
CORE = PKG / "core"

# `content_tree` was in this set and has been RESTORED — the deletion was a
# reachability-trace false positive (it is unwired, not dead; the binding
# HTML_DEDUP_CONTENT_TREE_GOAL says rendered_text must derive from it).
REMOVED = {
    "web_distiller_freq", "tfidf_cheeger_miner", "tfidf_service",
    "buta_extractor", "pq_tree", "chunk_absorber", "pattern_trie",
    "content_distiller_simple", "trie_diff",
}


def _py_files():
    return sorted(PKG.rglob("*.py"))


def test_every_module_imports():
    """Including the ones only the live path touches (scanner, browser)."""
    for path in _py_files():
        rel = path.relative_to(ROOT).with_suffix("")
        module = ".".join(rel.parts)
        if module.endswith(".__main__"):
            continue
        importlib.import_module(module)


def test_no_references_to_removed_modules():
    offenders = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        for name in REMOVED:
            # `import x` / `from x import` — not prose in docstrings.
            if f"core.{name} import" in text or f"import {name}\n" in text:
                offenders.append(f"{path.name} -> {name}")
    assert not offenders, offenders


def test_no_upstream_backend_imports():
    """Nothing may reach back into the web_fiber_haptics package."""
    offenders = []
    for path in _py_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mod = None
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
            elif isinstance(node, ast.Import):
                mod = node.names[0].name
            if mod and mod.split(".")[0] == "backend":
                offenders.append(f"{path.name}:{node.lineno} -> {mod}")
    assert not offenders, offenders


def test_graph_database_coupling_is_confined_to_one_module():
    """Kuzu is allowed, in `graphstore.py` and nowhere else.

    The original rule was "Kuzu was dropped; SQLite is the only store", which
    held while the extracted pipeline had nothing to traverse. It no longer
    does: addresses, chunks and embeddings are one linked structure, and the
    query it has to answer — address to chunk to embedding — is a traversal.

    The constraint the old rule was really protecting is not "no graph
    database" but "no store spreading through the codebase". That survives:
    exactly one module may import kuzu, so swapping the store touches one
    file, and `pipeline.py` still cannot smuggle in persistence.
    """
    allowed = {"graphstore.py"}
    offenders = [
        p.name for p in _py_files()
        if "import kuzu" in p.read_text(encoding="utf-8")
        and p.name not in allowed
    ]
    assert not offenders, offenders


def test_the_pipeline_stays_a_pure_function_of_its_inputs():
    """No module in the scan path may reach a store.

    This is the half of the old rule that always mattered: `pipeline.py` turns
    html into structure and nothing else, so it can be run against a fixture,
    a live scan or a replay without a database existing.
    """
    import ast

    pure = {"pipeline.py", "address.py", "trie.py", "markdown.py", "vectors.py"}
    stores = {"kuzu", "sqlite3", "graphstore", "store"}
    offenders = []
    for path in _py_files():
        if path.name not in pure:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mod = None
            if isinstance(node, ast.ImportFrom):
                mod = (node.module or "").lstrip(".")
            elif isinstance(node, ast.Import):
                mod = node.names[0].name
            if mod and mod.split(".")[-1] in stores:
                offenders.append(f"{path.name}:{node.lineno} -> {mod}")
    assert not offenders, offenders


def test_traceability_has_no_structural_breaks():
    """The PROCESS §7 gate: broken citations and stateless proposals are fatal.

    Absent citations are deliberately *not* fatal — see PROCESS §7. This test
    guards only the structural breaks: a citation resolving to nothing, an
    ambiguous identifier, or a proposal with no lifecycle state.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_traceability.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_bundled_js_assets_present():
    for asset in ("wfh_chunk_engine.js", "deep_serialize.js"):
        assert (CORE / "js" / asset).exists(), f"missing {asset}"


@pytest.mark.parametrize("name", ["SearchInputCollector", "PaginationCollector",
                                  "AgnosticAttr"])
def test_detection_classes_survived_extraction(name):
    """The 720-line detection closure pulled out of the deleted miner."""
    mod = importlib.import_module("domvec.core.signal_detect")
    assert hasattr(mod, name)


def test_chunkgroup_kept_its_dataclass_decorator():
    """Regression: the AST extraction initially dropped decorators, turning
    @dataclass classes into plain ones ('ChunkGroup() takes no arguments')."""
    from domvec.core.signal_detect import ChunkGroup

    assert hasattr(ChunkGroup, "__dataclass_fields__")
