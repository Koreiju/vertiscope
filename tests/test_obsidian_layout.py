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

from vertiscope.obsidian.layout import _unit_rows, build_layout
from vertiscope.vectors import EmbeddingMatrix


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
    from vertiscope.workspace import Workspace
    with Workspace(tmp_path / "ws") as workspace:
        for url, html in PAGES.items():
            workspace.index_html(html, url)
        yield workspace


@pytest.fixture()
def wide(tmp_path):
    """A workspace with enough distinct chunks to support a six-way fit.

    `ws` is three small pages and cannot: neither UMAP nor PCA returns more
    components than the data has rank, so asking six of four chunks gets
    three. That is a real property of the fit, and the layout now reports it
    rather than padding -- so the tests about what a six-dimensional fit does
    need a workspace that can produce one.
    """
    from vertiscope.workspace import Workspace

    with Workspace(tmp_path / "wide") as workspace:
        for i in range(9):
            workspace.index_html(
                "<html><body><main>"
                + "".join(
                    "<article><h2>Chapter %d.%d</h2><p>%s</p>"
                    "<a href='https://w.test/p%d'>onward to %d</a></article>"
                    % (i, j, " ".join(
                        "topic%d word%d phrase%d" % (i, j, k)
                        for k in range(40)), j, j)
                    for j in range(4))
                + "</main></body></html>",
                "https://w.test/p%d" % i)
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


# --- which space the picture is of ------------------------------------------

def test_the_projection_is_semantic_alone(ws):
    """The goal names the space: "quantized semantic (and not pre-umapped
    frequency) vectors are the primary embeddings space for the *projector*".

    This module used to fit both, equalised by width -- and argued the case
    well. The arithmetic was right; the premise was not ours. Frequency keeps
    its place in retrieval, where it is one of three ranked signals, and
    leaves the picture.
    """
    report = build_layout(_with_embeddings(ws))
    assert report["spaces"] == ["semantic"], report["spaces"]
    assert report["fitted_on"]["semantic"] is True
    assert "lexical" not in report["fitted_on"], report["fitted_on"]


def test_frequency_is_the_fallback_and_says_so(ws):
    """A workspace with no embeddings still gets a picture, and is told.

    The alternative to falling back is no layout at all, which helps nobody.
    What matters is that a caller can tell the goal's projection from a
    stand-in, so `fitted_on.semantic` is False and `spaces` says frequency.
    """
    report = build_layout(ws)
    assert report["spaces"] == ["frequency"], report["spaces"]
    assert report["fitted_on"]["semantic"] is False
    assert report["nodes"], "the fallback must still place the chunks"


def test_rows_are_unit_length_before_the_fit():
    """Magnitude must not decide distance.

    Kept from the two-space version, where it stopped whichever half was
    larger from dominating. It still matters with one space: UMAP on cosine
    wants unit rows, and the zero-row guard is what keeps one empty chunk
    from collapsing the whole layout.
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
    assert both["spaces"] == ["semantic"]

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
    from vertiscope.workspace import Workspace
    with Workspace(tmp_path / "tiny") as workspace:
        workspace.index_html("<html><body><p>one</p></body></html>",
                             "https://a.test/one")
        report = build_layout(workspace)
        if report["n"] == 0:
            assert report["note"], "an empty layout with no explanation"


# --- six dimensions: three to stand in, three to be a colour --------------------

def test_the_fit_is_six_dimensional_and_the_colour_comes_out_of_it(wide):
    """Three more components of the SAME projection, not a palette.

    Colour was a hash of the host, which is a legend: it said which site a
    node came from, which the node's own label already said. Fitting six and
    spending three on hue, saturation and value means the colour carries
    directions of the joint space the three spatial axes had no room for --
    so two nodes that look alike are alike in a way the camera cannot show.
    """
    layout = build_layout(wide)
    assert layout["hsv"] is True
    assert layout["fitted_dims"] == 6
    assert layout["dims"] == 3
    for node in layout["nodes"]:
        assert len(node["pos"]) == 3, "position must stay three-dimensional"
        h, s, v = node["hsv"]
        assert 0.0 <= h <= 360.0
        assert 0.0 <= s <= 1.0
        assert 0.0 <= v <= 1.0
        assert all(np.isfinite(x) for x in node["hsv"])


def test_the_colour_actually_varies(wide):
    """Non-vacuity.

    Every assertion above is satisfied by painting every node the same
    colour, and a constant hue is exactly what a broken normalisation
    produces -- `_hsv` maps a component with no spread to the middle of its
    band on purpose, and that path must not be the one every node takes.
    """
    layout = build_layout(wide)
    hues = {round(n["hsv"][0], 1) for n in layout["nodes"]}
    assert len(hues) > 1, "every node got the same hue"


def test_asking_for_no_colour_leaves_the_projection_alone(wide):
    """The spatial answer must not move because colour was switched off.

    If it did, the position a reader sees would be a function of a display
    option, and two people looking at the same workspace would be looking at
    two different pictures.
    """
    plain = build_layout(wide, hsv=False)
    assert plain["hsv"] is False
    assert plain["fitted_dims"] == 3
    for node in plain["nodes"]:
        assert "hsv" not in node


def test_a_fit_too_narrow_for_six_says_so_rather_than_inventing_a_colour(ws):
    """A workspace of four chunks cannot yield six components.

    Neither reducer returns more components than the data has rank. The first
    version padded the shortfall with zeros and coloured from them, putting
    every node at hue 180 -- the middle of the band, where `_hsv` sends a
    component with no spread -- while the report still said `hsv: true`. A
    constant colour claiming to be a measurement is worse than the host
    palette, which at least says what it is.
    """
    layout = build_layout(ws)
    assert layout["requested_dims"] == 6
    if layout["fitted_dims"] < 6:
        assert layout["hsv"] is False
        assert all("hsv" not in n for n in layout["nodes"])
    # Position keeps its three slots either way; a node with two coordinates
    # is a crash, not a flat layout.
    assert all(len(n["pos"]) == 3 for n in layout["nodes"])


def test_a_flat_component_does_not_become_a_nan(ws):
    """One NaN in a colour paints a node invisible, and there is no error.

    A component with no spread happens on a workspace too small to fit
    properly, which is the case where a viewer most needs to see something.
    """
    from vertiscope.obsidian.layout import _hsv

    flat = np.zeros((5, 3), dtype=np.float32)
    out = _hsv(flat)
    assert np.isfinite(out).all()
    # The middle of each band, not zero: a saturation of 0 is grey and a
    # value of 0 is black, and both read as "this node failed".
    assert out[0][1] > 0.0 and out[0][2] > 0.0


# --- billboards ----------------------------------------------------------------

def test_a_chunk_that_showed_a_picture_reports_it(tmp_path):
    """So the viewer can billboard the chunk rather than draw a dot for it."""
    from vertiscope.workspace import Workspace

    def page(n):
        return ("<html><body><main>"
                + "".join(
                    "<article><h3>Book %d.%d</h3>"
                    "<img src='media/cache/%d-%d.jpg' alt='Cover of book %d'>"
                    "<p>%s</p></article>" % (n, i, n, i, i,
                        " ".join("shelf%d tale%d word%d" % (n, i, k)
                                 for k in range(40)))
                    for i in range(4))
                + "</main></body></html>")

    with Workspace(tmp_path / "ws") as workspace:
        # Several pages, because one page under a 2048-token window is often
        # a single chunk and `build_layout` needs three before it places
        # anything at all.
        for n in range(6):
            workspace.index_html(page(n), "https://shelf.test/p%d" % n)
        layout = build_layout(workspace)
        assert layout["images"] > 0, "no chunk reported a picture"
        for node in layout["nodes"]:
            picture = node.get("image")
            if picture is None:
                continue
            # Absolutised HERE, where the chunk's own url is in hand. A
            # viewer resolving a relative path would resolve it against the
            # vault.
            assert picture["src"].startswith("https://shelf.test/")
            assert picture["alt"], "a billboard with no caption says nothing"


def test_a_picture_the_viewer_could_not_fetch_is_not_reported(tmp_path):
    """`images` has to count billboards that can actually be drawn.

    Reporting a count the viewer then fails to render makes a dead asset host
    and an empty corpus look the same from the status bar.
    """
    from vertiscope.obsidian.layout import _first_image

    assert _first_image("![a](data:image/png;base64,AAAA)", "https://x.test/") is None
    assert _first_image("no picture here", "https://x.test/") is None
    got = _first_image("![a cover](c.jpg)", "https://x.test/p/")
    assert got == {"src": "https://x.test/p/c.jpg", "alt": "a cover"}


# --- reading vectors back is not the same question as being able to make them ---

class _StubEmbedder:
    """768-dim, deterministic, no model.

    What is under test is whether stored vectors are READ BACK, which is
    linear algebra and bookkeeping. A real embedder would make this test a
    minute long and would not exercise one extra line of it.
    """

    dim = 768

    def embed_texts(self, texts, **_kw):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            seed = abs(hash(text)) % (2 ** 32)
            out[i] = np.random.default_rng(seed).normal(size=self.dim)
        return out

    def embed_query(self, text):
        return self.embed_texts([text])[0]


def test_a_workspace_opened_to_read_still_sees_its_stored_vectors(tmp_path):
    """The defect that kept the semantic half dark everywhere.

    `__init__` said `self.embeddings = EmbeddingMatrix() if embedder is not
    None else None`, which conflates two different questions: whether this
    process can MAKE vectors, and whether the store already HAS them. Every
    reader -- the sidecar, the 3D view, any query -- opens without an
    embedder, so it had no matrix, `_hydrate_embeddings` returned on its
    first line, and the vectors sat on the Chunk nodes unread.

    What it looked like from outside is the reason this is easy to miss:
    `build_layout` reported `spaces: ['frequency']` and `equalised: false` on
    a workspace holding 793 x 768 embeddings -- character for character what
    a workspace that had never been embedded reports.
    """
    from vertiscope.workspace import Workspace

    pages = {
        "https://a.test/": "<html><body><main>"
                           + "".join("<p>alpha beta gamma %d</p>" % i
                                     for i in range(40))
                           + "</main></body></html>",
        "https://b.test/": "<html><body><main>"
                           + "".join("<p>delta epsilon zeta %d</p>" % i
                                     for i in range(40))
                           + "</main></body></html>",
        "https://c.test/": "<html><body><main>"
                           + "".join("<p>eta theta iota %d</p>" % i
                                     for i in range(40))
                           + "</main></body></html>",
        "https://d.test/": "<html><body><main>"
                           + "".join("<p>kappa lambda mu %d</p>" % i
                                     for i in range(40))
                           + "</main></body></html>",
    }

    path = tmp_path / "ws"
    with Workspace(path, embedder=_StubEmbedder()) as writer:
        for url, html in pages.items():
            writer.index_html(html, url)
        writer.flush_vectors()
        written = writer.index.embeddings.matrix.shape[0]
    assert written > 0, "the fixture never wrote a vector"

    # Reopened the way every reader opens it: no embedder.
    with Workspace(path) as reader:
        index = reader.index
        assert index.embeddings is not None, \
            "a reader cannot see vectors that are on disk"
        assert index.embeddings.matrix is not None
        layout = build_layout(reader)
        assert "semantic" in layout["spaces"], layout["spaces"]
        assert layout["fitted_on"]["semantic"] is True, layout["fitted_on"]


def test_a_workspace_with_no_vectors_still_reports_none(tmp_path):
    """The guard that keeps the fix from changing anything else.

    An always-present but EMPTY matrix scores every chunk 0 on the semantic
    axis, and under the strict triple product a zero is a veto -- so search
    would answer nothing and report it as an absence of matches. The matrix
    appears because the store HAS vectors, never merely because someone
    opened the workspace.
    """
    from vertiscope.workspace import Workspace

    with Workspace(tmp_path / "empty") as ws:
        ws.index_html("<html><body><p>a paragraph</p></body></html>",
                      "https://none.test/")
        assert ws.index.embeddings is None


# --- the layout arrives in a cube a viewer can frame ---------------------------

def test_the_projection_is_centred_and_scaled_to_a_known_cube(wide):
    """UMAP has no natural origin or scale; a viewer cannot guess one.

    Raw, the cloud sits wherever the fit put it at whatever size the point
    count produced. At 98 chunks that was small and near enough to the origin
    to look right; at 3,136 it spread far wider while each node stayed the
    same size, and the pane drew 390,000 triangles while lighting 1.5% of its
    pixels. Delivered in a known cube, the same camera frames either.
    """
    from vertiscope.obsidian.layout import _EXTENT

    layout = build_layout(wide)
    assert layout["extent"] == _EXTENT
    axes = list(zip(*[n["pos"] for n in layout["nodes"]]))
    widest = max(max(a) - min(a) for a in axes)
    assert abs(widest - 2 * _EXTENT) < 1.0, \
        "widest axis spans %.1f, expected %.1f" % (widest, 2 * _EXTENT)
    for axis in axes:
        mid = (max(axis) + min(axis)) / 2
        assert abs(mid) < 1.0, "an axis is off-centre by %.1f" % mid


def test_the_colour_is_not_rescaled_with_the_position(wide):
    """`_framed` touches the spatial columns only.

    Hue is an angle and saturation and value are fractions; scaling them into
    a spatial cube would make every node the same colour, which is the exact
    failure `_hsv` guards against at the other end.
    """
    layout = build_layout(wide)
    for node in layout["nodes"]:
        h, s, v = node["hsv"]
        assert 0.0 <= h <= 360.0 and 0.0 <= s <= 1.0 and 0.0 <= v <= 1.0


def test_a_collapsed_axis_does_not_divide_by_nothing(wide):
    """Every point identical on one axis is a real outcome of a poor fit."""
    import numpy as np

    from vertiscope.obsidian.layout import _framed

    flat = np.zeros((6, 6), dtype=np.float32)
    flat[:, 0] = np.arange(6)          # one axis varies, two do not
    out = _framed(flat, 3)
    assert np.isfinite(out).all()
