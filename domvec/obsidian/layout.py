"""A 3D placement for the chunks, from both vector spaces at once.

The goal states the projection precisely, and the precision is the point:
bring the frequency vectors to the semantic dimensionality FIRST, concatenate,
then run one final UMAP. Not two layouts blended, and not a UMAP of whichever
space happens to be wider.

Why it has to be done that way. Tf-idf over a corpus is tens of thousands of
columns and a nomic embedding is 768, so concatenating them raw hands the
distance function to the lexical space by sheer count -- the semantic half
would contribute about one part in fifty of every distance, and the result
would be a tf-idf layout with a rounding error in it. Reducing the frequency
side to the same width makes the two halves equal in DIMENSION.

Equal dimension is not yet equal weight, because a 768-wide tf-idf projection
and a 768-wide embedding need not have the same magnitude. So each half is
L2-normalised before the join: after that both contribute a unit vector, and
a cosine distance over the concatenation is the mean of the two cosines. That
is what "equal information dimensions" has to mean operationally, and it is
one line that is easy to leave out and impossible to notice missing -- the
layout still looks like a layout.

This runs in Python rather than in the plugin because the vectors, numpy and
UMAP are all already here. The plugin renders; it does not fit.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import numpy as np

from .. import tokens

#: `![alt](src)` as the distiller draws media. Non-greedy on the alt so a
#: chunk holding two pictures yields the first rather than one match spanning
#: both.
_MEDIA_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")

#: Width of each half when there is nothing to match. Only reached when the
#: workspace has no embeddings at all, where "equal halves" is moot and this
#: is just a sane reduction before UMAP.
_LONE_TARGET = 128

#: Half the width of the cube the layout is delivered in. The projection is
#: centred on the origin and scaled so its widest axis spans `2 * _EXTENT`.
#:
#: UMAP's output has no natural origin or scale -- it is whatever the fit
#: happened to produce -- so a viewer receiving it raw gets a cloud sitting
#: somewhere off-axis at a size that depends on how many points went in. That
#: is exactly what went wrong: at 98 chunks the cloud was small and near
#: enough to the origin to look right, and at 3,136 it spread far wider while
#: each node stayed the same size, so the pane rendered 390,000 triangles and
#: still looked empty -- 1.5% of pixels lit, every node a speck.
#:
#: Delivered in a known cube instead, the picture is self-similar: the same
#: camera frames 98 nodes and 3,136 nodes alike, and the viewer can size a
#: node against a span it knows.
_EXTENT = 300.0


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise each row, leaving all-zero rows alone.

    A zero row is a chunk with no terms in the vocabulary -- a retired row, or
    one whose whole content was punctuation. Dividing by its norm makes it
    NaN, and a single NaN propagates through UMAP into every coordinate, so
    the whole layout collapses to nothing on one empty chunk.
    """
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _reduce(dense: np.ndarray, target: int, seed: int) -> np.ndarray:
    """Bring a wide space down to `target` columns.

    Truncated SVD rather than a random projection: it is deterministic given
    a seed, and on tf-idf it is latent semantic analysis, which is the
    reduction this data has always been read with.
    """
    if dense.shape[1] <= target:
        # Already narrow enough. Padding to `target` would add columns of
        # zeros, which are equal in count and empty of information -- the
        # thing this module exists to avoid.
        return dense
    from sklearn.decomposition import TruncatedSVD

    # Never more components than the data can support.
    k = int(min(target, dense.shape[0] - 1, dense.shape[1] - 1))
    if k < 2:
        return dense
    return TruncatedSVD(n_components=k, random_state=seed).fit_transform(dense)


def build_layout(workspace,
                 *,
                 dims: int = 3,
                 hsv: bool = True,
                 seed: int = 0,
                 neighbors: int = 15,
                 min_dist: float = 0.1) -> Dict:
    """Every live chunk placed in `dims` dimensions, with the graph's edges.

    The report says which spaces it used. A layout fitted on frequency alone
    and one fitted on both are different pictures, and a caller that cannot
    tell them apart will read a lexical clustering as a semantic one.
    """
    index = workspace.index
    freq = index.freq
    embeddings = index.embeddings

    tfidf = freq.tfidf()
    meta = {c.cid: c for c in workspace.store.chunks()}

    # Live rows only, in a fixed order. A retired row keeps its slot in the
    # matrix so nothing is renumbered, and it describes no chunk.
    cids: List[str] = []
    rows: List[int] = []
    for row, cid in enumerate(freq.rows):
        if cid and cid in meta:
            cids.append(cid)
            rows.append(row)

    if len(cids) < 3:
        return {"nodes": [], "edges": [], "spaces": [], "n": len(cids),
                "note": "too few chunks to place"}

    lexical = np.asarray(tfidf[rows].todense(), dtype=np.float32)

    semantic: Optional[np.ndarray] = None
    if embeddings is not None and embeddings.matrix is not None:
        wanted = [embeddings.row_of(cid) for cid in cids]
        if all(r is not None for r in wanted):
            semantic = np.asarray(embeddings.matrix[wanted], dtype=np.float32)

    spaces = ["frequency"]
    target = semantic.shape[1] if semantic is not None else _LONE_TARGET
    left = _reduce(lexical, target, seed)
    widths = {"lexical": int(left.shape[1])}

    if semantic is not None:
        spaces.append("semantic")
        # Meet in the middle, rather than reducing one side to the other's
        # nominal width and calling it equal.
        #
        # Truncated SVD cannot produce more components than the data has rank,
        # so on a 98-chunk workspace the lexical side comes back 97 wide
        # however high the target was set. Concatenating that with a 768-wide
        # embedding gives the semantic space an eight-to-one say -- the same
        # defect this module exists to prevent, with the imbalance pointing
        # the other way, and the first version of this code reported
        # `equalised: True` while doing exactly that.
        #
        # So both halves come down to whatever width the narrower one can
        # actually reach.
        #
        # The cap is `n - 1` as well as the narrower side. Truncated SVD
        # cannot return more components than the sample count supports, so
        # asking a 768-wide embedding for 75 on a three-chunk workspace gets
        # 2 back -- and the halves end up 75 against 2, which is the same
        # lopsidedness a third way. Taking the rank bound into the width up
        # front means both calls can actually deliver what they are asked for.
        width = int(min(left.shape[1], semantic.shape[1],
                        max(2, lexical.shape[0] - 1)))
        left = _reduce(left, width, seed)
        right = _reduce(semantic, width, seed)
        widths = {"lexical": int(left.shape[1]),
                  "semantic": int(right.shape[1])}
        features = np.hstack([_unit_rows(left), _unit_rows(right)])
    else:
        features = _unit_rows(left)

    # Six components, not three: three to stand in space and three to be a
    # colour. One fit, not two -- the colour has to come from the same
    # projection as the position or it is a second, unrelated picture painted
    # on top of the first, and two chunks sitting together would carry
    # unrelated hues for no reason a viewer could read.
    #
    # Colour was a hash of the host before this, which is a legend and not a
    # measurement: it told a viewer which site a node came from, which the
    # node's own label already said. Spending three of the projection's
    # dimensions on it means hue, saturation and value each carry a direction
    # of the joint frequency+semantic space that the three spatial axes had
    # no room for -- so two nodes that look alike ARE alike in the part of the
    # space the camera cannot show.
    want = dims + (3 if hsv else 0)
    coords = _umap(features, dims=want, seed=seed,
                   neighbors=neighbors, min_dist=min_dist)

    # Only if the fit actually PRODUCED six components.
    #
    # Neither reducer can return more components than the data has rank, so a
    # workspace of four chunks yields three however many were asked for. The
    # first version of this padded the shortfall with zeros and coloured from
    # them, which put every node at hue 180 -- the middle of the band, which
    # is where `_hsv` sends a component with no spread -- while the report
    # still said `hsv: true`. A constant colour claiming to be a measurement
    # is worse than the host palette, because the host palette says what it
    # is. So the colour is dropped and the viewer is told, exactly as
    # `equalised` is asserted from the measured widths rather than from the
    # intention.
    got = int(coords.shape[1])
    colours = _hsv(coords[:, dims:dims + 3]) if (hsv and got >= want) else None
    coords = _framed(coords, dims)
    if got < dims:
        # Position must have its three slots whatever the fit managed. A flat
        # layout is visible; a node with two coordinates is a crash.
        coords = np.hstack([coords,
                            np.zeros((coords.shape[0], dims - got),
                                     dtype=np.float32)])

    ranks = index.ranks
    nodes = []
    for i, cid in enumerate(cids):
        chunk = meta[cid]
        row = rows[i]
        node = {
            "cid": cid,
            "url": chunk.url,
            "title": _title(chunk.md),
            "rank": float(ranks[row]) if row < len(ranks) else 0.0,
            "chars": chunk.chars,
            "tokens": tokens.count(chunk.md or ""),
            "pos": [float(v) for v in coords[i][:dims]],
        }
        if colours is not None:
            node["hsv"] = [float(v) for v in colours[i]]
        picture = _first_image(chunk.md, chunk.url)
        if picture is not None:
            # So the viewer can billboard the chunk rather than draw a dot
            # for it. A chunk that showed a picture should look like the
            # thing it showed.
            node["image"] = picture
        nodes.append(node)

    known = set(cids)
    edges = [{"source": a, "target": b}
             for a, b in workspace.store.edges()
             if a in known and b in known and a != b]

    return {
        "nodes": nodes,
        "edges": edges,
        "spaces": spaces,
        "n": len(nodes),
        "dims": dims,
        # Six when the colour comes from the fit. Reported because a viewer
        # that colours by hue is showing three more dimensions of the same
        # projection, and one that falls back to a per-host palette is
        # showing a legend -- and the two look identical from the outside.
        # What the fit ASKED for and what it RETURNED. They differ on a
        # workspace with fewer chunks than dimensions, and a reader of the
        # picture has to be able to tell.
        "fitted_dims": int(min(got, want)),
        "requested_dims": int(want),
        "hsv": bool(colours is not None),
        # The cube the coordinates are delivered in, so a viewer can size a
        # node against a span it knows rather than against a constant that
        # was right for one corpus.
        "extent": _EXTENT,
        "images": sum(1 for n in nodes if n.get("image")),
        # Stated so a reader of the picture knows what produced it, and
        # `equalised` is asserted from the widths rather than from the
        # intention: it means the two halves ARE the same size, not that the
        # code tried to make them so.
        "halves": dict(widths,
                       equalised=(semantic is not None
                                  and widths.get("lexical")
                                  == widths.get("semantic"))),
    }


#: Saturation and value are kept inside bands rather than mapped across their
#: full range. A component that happened to land at zero would otherwise paint
#: a node black or grey -- invisible against the pane, and indistinguishable
#: from a node the fit failed on. The bands preserve ORDER, which is what a
#: viewer can actually read off a colour, and give up only the extremes, which
#: are the two values a viewer cannot see anyway.
_SAT_BAND = (0.35, 0.85)
_VAL_BAND = (0.45, 0.95)


def _hsv(block: np.ndarray) -> np.ndarray:
    """Three projection components as (hue°, saturation, value).

    Min-max per component, because UMAP's output is unbounded and has no
    natural zero: what a component means is where a point sits relative to
    the others, so the scale has to come from the set being drawn.

    A component with no spread -- every chunk identical on that axis, which
    happens on a workspace too small to fit -- maps to the middle of its band
    rather than dividing by zero. A single NaN here would propagate into a
    colour string and paint the node invisible.
    """
    out = np.zeros((block.shape[0], 3), dtype=np.float32)
    for j in range(3):
        column = block[:, j].astype(np.float32)
        low, high = float(column.min()), float(column.max())
        unit = (np.full_like(column, 0.5) if high - low < 1e-9
                else (column - low) / (high - low))
        if j == 0:
            out[:, 0] = unit * 360.0
        elif j == 1:
            out[:, 1] = _SAT_BAND[0] + unit * (_SAT_BAND[1] - _SAT_BAND[0])
        else:
            out[:, 2] = _VAL_BAND[0] + unit * (_VAL_BAND[1] - _VAL_BAND[0])
    return out


def _first_image(md: str, base: str) -> Optional[Dict]:
    """The chunk's first picture, as an absolute source and a caption.

    Read off the rendered markdown rather than looked up in the store,
    because the markdown IS what the chunk is -- if a picture is not in the
    render, the chunk does not show it, and a node billboarding an image its
    own text never mentions would be showing something the reader cannot
    find when they open it.

    The source is absolutised here, where the chunk's own url is in hand. A
    viewer resolving a relative path against ITS OWN document would resolve
    it against the vault.
    """
    match = _MEDIA_RE.search(md or "")
    if match is None:
        return None
    alt, src = match.group(1).strip(), match.group(2).strip()
    if not src:
        return None
    try:
        from urllib.parse import urljoin

        src = urljoin(base or "", src)
    except Exception:                               # noqa: BLE001
        return None
    if not src.lower().startswith(("http://", "https://")):
        # A picture the viewer cannot fetch is not a billboard. Said here
        # rather than left for the viewer to fail on, so `images` in the
        # report counts pictures that can actually be drawn.
        return None
    return {"src": src, "alt": alt}


def _framed(coords: np.ndarray, dims: int) -> np.ndarray:
    """Centre the spatial axes on the origin and scale them to a known cube.

    The MIDPOINT of the bounding box, not the mean: what a camera has to
    frame is the extent, and a dense clump beside a few outliers has a mean
    that sits in the clump and a midpoint that sits where the picture
    actually is.

    Only the spatial columns are touched. The colour columns are normalised
    separately by `_hsv`, per component, because a hue and a position want
    different treatment -- and this runs after `_hsv` has read them, so the
    two cannot interfere.

    A degenerate axis -- every point identical, which happens when the fit
    collapses -- keeps its zeros rather than dividing by nothing.
    """
    if coords.size == 0:
        return coords
    out = np.array(coords, dtype=np.float32, copy=True)
    block = out[:, :dims]
    low = block.min(axis=0)
    high = block.max(axis=0)
    block -= (low + high) / 2.0
    widest = float(np.max(high - low))
    if widest > 1e-9:
        block *= (2.0 * _EXTENT) / widest
    out[:, :dims] = block
    return out


def _umap(features: np.ndarray, *, dims: int, seed: int,
          neighbors: int, min_dist: float) -> np.ndarray:
    """The final projection, or a PCA when there is too little to fit.

    UMAP needs more points than neighbours; a small workspace has fewer
    chunks than the default fifteen, and it raises rather than adapting. A
    vault with nine notes should still get a picture.
    """
    n = features.shape[0]
    k = int(max(2, min(neighbors, n - 1)))
    try:
        import umap

        reducer = umap.UMAP(n_components=dims, n_neighbors=k,
                            min_dist=min_dist, random_state=seed)
        return np.asarray(reducer.fit_transform(features), dtype=np.float32)
    except Exception:
        # Not silent: the caller is told which spaces were used, and a PCA of
        # the same features is still an honest projection of them -- it is
        # only a worse one. Failing outright would leave the view empty for a
        # reason no one can see from the view.
        from sklearn.decomposition import PCA

        k = int(min(dims, n - 1, features.shape[1]))
        # Returned at whatever width the data supports, NOT padded up to
        # `dims`. Padding made a shortfall invisible to the caller, which then
        # coloured nodes from columns of zeros and reported the colour as
        # fitted. The caller handles the narrow case; it cannot handle a case
        # it is not told about.
        out = PCA(n_components=k, random_state=seed).fit_transform(features)
        return np.asarray(out, dtype=np.float32)


def _title(md: str) -> str:
    for raw in (md or "").splitlines():
        line = raw.strip().lstrip("#").lstrip("-").strip()
        if line:
            return line[:80]
    return ""
