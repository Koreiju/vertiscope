"""The 3D placement, and the one property that makes it worth fitting.

The goal states the projection precisely: bring the frequency vectors to the
semantic dimensionality first, concatenate, then one final UMAP. The precision
is the point. Tf-idf over a corpus is tens of thousands of columns against a
768-wide embedding, so concatenating raw hands the distance function to the
lexical space by sheer count -- and the result would be a tf-idf layout with a
rounding error in it, which still looks exactly like a layout.
"""

import numpy as np
import pytest

from domvec.obsidian.layout import _unit_rows, build_layout
from domvec.vectors import EmbeddingMatrix


PAGES = {
    "https://a.test/glaciers": "<html><body><h1>Glaciers</h1>"
    "<p>Ice sheets retreat as the climate warms each decade.</p>"
    "<p>Mass balance is measured in metres of water equivalent.</p>"
    "</body></html>",
    "https://a.test/books": "<html><body><h1>Books</h1>"
    "<p>A catalogue of second hand paperbacks and hardbacks.</p>"
    "<p>Travel writing, poetry and a shelf of atlases.</p>"
    "</body></html>",
    "https://a.test/index": "<html><body><h1>Index</h1>"
    "<p><a href='https://a.test/books'>books</a> and "
    "<a href='https://a.test/glaciers'>glaciers</a></p></body></html>",
}


@pytest.fixture()
def ws(tmp_path):
    from domvec.workspace import Workspace
    with Workspace(tmp_path / "ws") as workspace:
        for url, html in PAGES.items():
            workspace.index_html(html, url)
        yield workspace


def _with_embeddings(workspace, dim=768, seed=0):
    """Give every chunk a semantic vector, so the join path can be exercised.

    Real embeddings need a model; the join is linear algebra and does not care
    where the vectors came from, so a seeded random matrix tests the shape of
    the thing without downloading half a gigabyte to do it.
    """
    rng = np.random.default_rng(seed)
    matrix = EmbeddingMatrix(dim=dim)
    for cid in workspace.index.freq.rows:
        if cid:
            matrix.set(cid, rng.normal(size=dim).astype(np.float32))
    workspace.index.embeddings = matrix
    return workspace


# --- the equalisation -----------------------------------------------------------

def test_the_two_halves_are_the_same_width(ws):
    """Equal DIMENSION, asserted from the widths and not from the intention.

    The first version reduced the lexical side towards the embedding's
    nominal 768 and reported success. But truncated SVD cannot produce more
    components than the data has rank, so on a small workspace it came back
    far narrower -- and the concatenation then gave the SEMANTIC space the
    lopsided say, the same defect pointing the other way, while the report
    said `equalised: True`.
    """
    report = build_layout(_with_embeddings(ws))
    halves = report["halves"]
    assert halves["equalised"] is True
    assert halves["lexical"] == halves["semantic"], halves


def test_each_half_is_unit_length_before_the_join():
    """Equal dimension is not yet equal weight.

    A 768-wide tf-idf projection and a 768-wide embedding need not have the
    same magnitude, and without normalising, whichever is larger dominates the
    distance. One line, easy to leave out, impossible to notice missing.
    """
    raw = np.array([[3.0, 4.0], [0.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    unit = _unit_rows(raw)
    assert np.allclose(np.linalg.norm(unit[0]), 1.0)
    assert np.allclose(np.linalg.norm(unit[2]), 1.0)
    # The zero row is left alone rather than divided by zero: one NaN
    # propagates through UMAP into every coordinate, so a single empty chunk
    # would collapse the whole layout.
    assert np.isfinite(unit).all()
    assert np.allclose(unit[1], 0.0)


def test_the_semantic_space_actually_moves_the_picture(ws):
    """If adding embeddings changed nothing, the join would be decoration."""
    lexical_only = build_layout(ws, seed=1)
    both = build_layout(_with_embeddings(ws), seed=1)

    assert lexical_only["spaces"] == ["frequency"]
    assert both["spaces"] == ["frequency", "semantic"]

    a = {n["cid"]: n["pos"] for n in lexical_only["nodes"]}
    b = {n["cid"]: n["pos"] for n in both["nodes"]}
    assert set(a) == set(b)
    moved = sum(1 for cid in a if not np.allclose(a[cid], b[cid], atol=1e-4))
    assert moved > 0, "the semantic half changed no coordinate at all"


# --- the payload ----------------------------------------------------------------

def test_every_live_chunk_is_placed_and_finite(ws):
    report = build_layout(ws)
    assert report["n"] == len(report["nodes"]) > 0
    coords = np.array([n["pos"] for n in report["nodes"]], dtype=np.float32)
    assert coords.shape[1] == 3
    assert np.isfinite(coords).all(), "a coordinate came back NaN or inf"
    # A projection that put every point in one place is not a projection.
    assert float(coords.std()) > 0.0


def test_edges_only_name_placed_nodes(ws):
    """A link to a node the view does not have would draw into nothing."""
    report = build_layout(ws)
    placed = {n["cid"] for n in report["nodes"]}
    for edge in report["edges"]:
        assert edge["source"] in placed and edge["target"] in placed


def test_a_workspace_too_small_to_place_says_so(tmp_path):
    """Rather than raising inside a view that then renders blank."""
    from domvec.workspace import Workspace
    with Workspace(tmp_path / "tiny") as workspace:
        workspace.index_html("<html><body><p>one</p></body></html>",
                             "https://a.test/one")
        report = build_layout(workspace)
        if report["n"] == 0:
            assert report["note"], "an empty layout with no explanation"
