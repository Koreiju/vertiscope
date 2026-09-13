"""A 3D placement for the chunks, from the semantic space.

The goal settles which space: "quantized semantic (and not pre-umapped
frequency) vectors are the primary embeddings space for the *projector*, while
we still apply triple-retrieval with frequency-quantized-pagerank searches".
So frequency is one of three ranked signals in RETRIEVAL and is not in the
picture at all.

This module used to fit both. It brought tf-idf down to the embedding's width,
L2-normalised each half so neither dominated the distance by magnitude, and
ran one UMAP over the concatenation -- and the reasoning was right about the
arithmetic. Tf-idf raw is tens of thousands of columns against nomic's 768, so
an unreduced join hands the distance function to the lexical space by sheer
count. All of that machinery answered a question the goal has now answered
differently, and it is gone rather than disabled: `halves` and `equalised`
reported whether two spaces had been equalised, and there is one space.

What the two jobs wanted was never the same. A projection asks what a chunk
MEANS; tf-idf answers which words it contains, and on a corpus of web pages
that clusters site furniture as readily as subject matter. Retrieval can hold
both answers and rank them against each other. A picture has to pick one.

Frequency survives as the FALLBACK for a workspace with no embeddings, where
the alternative is no layout at all -- and `fitted_on.semantic` says which
happened, so a caller can tell the goal's projection from a stand-in.

The plugin renders; it does not fit.
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

#: The width a space is brought down to before UMAP. A sane reduction, not a
#: matching exercise -- there is one space to fit now.
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


#: Where each fitted stage leaves its parameters, for `Projection.of` to
#: collect the moment `build_layout` finishes.
#:
#: A module-level shelf rather than threaded return values, because every one
#: of these stages is called from one place, in one order, in one thread, and
#: widening five signatures to carry a second value would touch every caller
#: and every test for a fact that only `build_layout` consumes. It is written
#: during a fit and read immediately after; nothing else reads it.
#: How many queued chunks one live placement will embed before answering.
#:
#: A bound, not a batch size. A reader who opens a page with nine hundred new
#: chunks should see the first few hundred appear and the rest arrive on the
#: next tick, rather than watch the pane hang while the whole page is
#: embedded. The unplaced remainder is reported, so nothing is lost quietly.
_LIVE_EMBED_LIMIT = 256

_LAST_FIT: Dict[str, object] = {}

#: The most recent fit, kept so live captures can be placed into it.
#: `None` until a layout has been built, and after a build that could not
#: produce a transformable reducer.
_LAST_PROJECTION: Optional["Projection"] = None


def live_projection() -> Optional["Projection"]:
    """The fit the pane is currently showing, or None."""
    return _LAST_PROJECTION


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
    svd = TruncatedSVD(n_components=k, random_state=seed)
    out = svd.fit_transform(dense)
    # The FITTED transformer travels with its output. A chunk captured after
    # the fit has to pass through this exact projection, not a new one fitted
    # to a different sample -- two SVDs of overlapping data do not agree on
    # the sign or the order of their components, so a newcomer put through a
    # fresh one lands somewhere unrelated to the cloud it belongs in.
    _LAST_FIT["svd"] = svd
    return out


def build_layout(workspace,
                 *,
                 dims: int = 3,
                 hsv: bool = True,
                 seed: int = 0,
                 neighbors: int = 15,
                 min_dist: float = 0.25,
                 spread_axes: bool = True) -> Dict:
    """Every live chunk placed in `dims` dimensions, with the graph's edges.

    Leaves its fitted stages on `_LAST_FIT` and assembles them into
    `_LAST_PROJECTION`, which is what lets a later capture join this picture
    without refitting it.

    The report says which spaces it used. A layout fitted on frequency alone
    and one fitted on both are different pictures, and a caller that cannot
    tell them apart will read a lexical clustering as a semantic one.
    """
    index = workspace.index
    freq = index.freq
    _LAST_FIT.clear()
    embeddings = index.embeddings

    tfidf = freq.tfidf()
    meta = {c.cid: c for c in workspace.store.chunks()}

    # Live rows only, in a fixed order. A retired row keeps its slot in the
    # matrix so nothing is renumbered, and it describes no chunk.
    cids: List[str] = []
    rows: List[int] = []
    redundant = 0
    for row, cid in enumerate(freq.rows):
        if cid and cid in meta:
            # One node per distinct rendering, not one per address.
            #
            # archive.org's search page renders each result as a
            # `<tile-dispatcher>` with its own shadow root, and every one of
            # those roots carries the same accessibility hint -- so the pane
            # drew a cluster of 125 nodes all reading "Press Down Arrow to
            # preview item details". They are 125 real addresses and the trie
            # is right to hold them; what they are not is 125 things to look
            # at. The store decides this at ingest (`_same_content`), on exact
            # bytes and within one page, so nothing here is a heuristic.
            #
            # Dropped before the fit, not after: a duplicate embeds to the
            # same vector, so leaving them in spends the projector's
            # neighbourhood budget on a point it already has and pulls the
            # layout toward whichever page repeats itself most.
            if meta[cid].redundant:
                redundant += 1
                continue
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

    # The projector fits on the SEMANTIC space alone.
    #
    # It used to fit both, reduced to a common width and concatenated, and
    # this module argued the case at length: a joint fit, "not two layouts
    # blended, and not a UMAP of whichever space happens to be wider". The
    # argument was sound and the premise was not ours to choose -- the goal
    # settles it: "quantized semantic (and not pre-umapped frequency) vectors
    # are the primary embeddings space for the *projector*, while we still
    # apply triple-retrieval with frequency-quantized-pagerank searches".
    #
    # So frequency leaves the PICTURE and keeps its place in RETRIEVAL, where
    # it is one of three ranked signals. The two jobs wanted different things
    # from it and were sharing one answer: a projection is asking what a chunk
    # MEANS, and tf-idf answers what words it happens to contain, which on a
    # corpus of web pages clusters by site furniture as readily as by subject.
    #
    # Everything the equalising machinery existed for goes with it -- there is
    # no second half to be lopsided against. `_reduce` is still used, but only
    # to bring one space down to a width UMAP is comfortable with.
    spaces: List[str] = []
    widths: Dict[str, int] = {}

    if semantic is not None:
        spaces.append("semantic")
        # Rank still caps the reduction: truncated SVD cannot return more
        # components than the sample count supports, so a three-chunk
        # workspace asking a 768-wide embedding for 128 gets 2 back. Asking
        # for a width the data can actually deliver keeps the call honest.
        width = int(min(semantic.shape[1], max(2, semantic.shape[0] - 1),
                        _LONE_TARGET))
        right = _reduce(semantic, width, seed)
        widths = {"semantic": int(right.shape[1])}
        features = _unit_rows(right)
    else:
        # No embeddings, so no semantic space to fit. Frequency is the
        # FALLBACK now rather than half the picture, and `spaces` says so --
        # a caller that reads "frequency" here is being told the projection
        # is not the one the goal asks for, not that it is half of it.
        spaces.append("frequency")
        width = int(min(_LONE_TARGET, max(2, lexical.shape[0] - 1)))
        left = _reduce(lexical, width, seed)
        widths = {"lexical": int(left.shape[1])}
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
    # is. So the colour is dropped and the viewer is told -- asserted from
    # the measured components rather than from the intention, which is the
    # rule every field in this report follows.
    got = int(coords.shape[1])
    colours = _hsv(coords[:, dims:dims + 3]) if (hsv and got >= want) else None
    if spread_axes:
        coords = _spread(coords, dims)
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
            #: How many addresses on the page draw this, so the pane can say
            #: "125 copies" instead of silently standing for 125 things.
            "copies": chunk.dup_n,
            "rank": float(ranks[row]) if row < len(ranks) else 0.0,
            "chars": chunk.chars,
            "tokens": tokens.budget(chunk.md or ""),
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

    # Keep the fit, so a chunk captured a minute from now can be placed into
    # this picture rather than forcing a new one. Set even when it comes back
    # None -- a stale projection from the previous corpus would place
    # newcomers against a cloud that is no longer on screen.
    global _LAST_PROJECTION
    _LAST_PROJECTION = Projection.of(dims=dims, hsv=colours is not None,
                                     fitted_n=len(cids))

    return {
        "nodes": nodes,
        "edges": edges,
        "spaces": spaces,
        "n": len(nodes),
        #: Chunks the page draws more than once, left out of the fit. Reported
        #: rather than silently subtracted: `n` no longer equals the store's
        #: chunk count, and a reader comparing the two needs to see why.
        "redundant": redundant,
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
        # How far apart the nodes ACTUALLY are, which the cube does not say.
        #
        # `graph.ts` sized a node from `2 * extent / cbrt(n)` -- the spacing
        # of a UNIFORM cloud in this cube. UMAP does not deliver a uniform
        # cloud, and over the 3,135-node corpus the gap was 27x: a node drawn
        # with a radius near 10 units among neighbours a median 0.76 units
        # away, so every node overlapped dozens of others and the pane read as
        # a blob. Rescaling the extent cannot fix that -- `_framed` already
        # normalises the extent and the cloud is still clumped inside it.
        #
        # The fit knows the answer and was throwing it away. One kd-tree query
        # over coordinates already in hand.
        "spacing": _spacing(coords, dims),
        "images": sum(1 for n in nodes if n.get("image")),
        # What the fit actually ran on. `halves` and `equalised` lived here
        # and described a join that no longer happens -- they reported whether
        # two spaces had been brought to the same width, and there is one
        # space now. A field that can only ever say the same thing tells a
        # reader nothing, and a field that describes machinery which has been
        # removed tells them something false.
        #
        # `semantic` is the answer a caller needs: True means this is the
        # projection the goal asks for, False means the workspace had no
        # embeddings and the picture fell back to frequency.
        "fitted_on": dict(widths, semantic=semantic is not None),
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
    bands = []
    for j in range(3):
        column = block[:, j].astype(np.float32)
        low, high = float(column.min()), float(column.max())
        bands.append((low, high))
        unit = (np.full_like(column, 0.5) if high - low < 1e-9
                else (column - low) / (high - low))
        if j == 0:
            out[:, 0] = unit * 360.0
        elif j == 1:
            out[:, 1] = _SAT_BAND[0] + unit * (_SAT_BAND[1] - _SAT_BAND[0])
        else:
            out[:, 2] = _VAL_BAND[0] + unit * (_VAL_BAND[1] - _VAL_BAND[0])
    _LAST_FIT["hsv_bands"] = bands
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


def _spread(coords: np.ndarray, dims: int) -> np.ndarray:
    """Equalise the spacing along each spatial axis, keeping its order.

    The inter-spatial normalization the goal asks for: "most are way too
    compressed together to see anything discernable".

    Each spatial axis is mapped through its own empirical CDF, so the ORDER
    along every axis is preserved exactly and only the gaps change. It is not
    a rotation and not a rescale -- `_framed` already does the rescale, and
    rescaling a clumped cloud leaves it clumped.

    Why it is worth doing, measured over the 3,135-chunk corpus against the
    1,536-column space the fit was run ON -- which is the reference that
    matters, because comparing one projection to another asks whether the
    picture changed, not whether it is right:

        min_dist  transform    node px   true 10-NN kept
        0.10      none           0.44         45.3%      <- shipped before
        0.90      none           2.80         31.0%
        0.25      none           0.78         43.5%
        0.25      this           2.46         41.9%      <- shipped now

    The baseline keeps only 45.3% of true neighbours, so the honest cost of
    this transform is 3.4 points, not the 20 it appears to cost when measured
    against another projection. Reaching the same legibility through
    `min_dist` alone costs 14.3.

    Only the spatial columns move. The colour columns are already normalised
    by `_hsv`, which runs before this, so the two cannot interfere.
    """
    if coords is None or len(coords) < 3:
        return coords
    out = np.array(coords, dtype=np.float32, copy=True)
    n = out.shape[0]
    cdf: Dict[int, np.ndarray] = {}
    for axis in range(min(dims, out.shape[1])):
        column = out[:, axis]
        if float(column.max() - column.min()) == 0.0:
            continue                       # a collapsed axis stays collapsed
        rank = np.argsort(np.argsort(column))
        out[:, axis] = (rank / (n - 1)).astype(np.float32)
        # The sorted column IS the empirical CDF. Kept so a newcomer can be
        # placed at its own rank among the points already drawn -- a
        # `searchsorted` -- instead of re-ranking the corpus, which would
        # move every existing node a little on every capture.
        cdf[axis] = np.sort(column.astype(np.float32))
    _LAST_FIT["spread_cdf"] = cdf
    return out


def _spacing(coords: np.ndarray, dims: int) -> Dict:
    """Nearest-neighbour distance quantiles over the placed spatial axes.

    Quantiles rather than a mean, because the distribution is not symmetric
    and the two ends mean different things. The MEDIAN is the projection's
    own scale and is what a node should be sized against. The 5th percentile
    is not: it is dominated by near-duplicate chunks off one page -- of the
    closest 5% of pairs, 98.7% share a url and 54.5% share a title -- whose
    vectors are nearly identical, so they land on each other because that is
    correct. Sizing against p05 would shrink every node on the page to hide
    a duplication problem that belongs to the chunker.
    """
    if coords is None or len(coords) < 2:
        return {"p05": 0.0, "p25": 0.0, "p50": 0.0, "n": int(len(coords or []))}
    block = np.asarray(coords, dtype=np.float64)[:, :max(1, dims)]
    try:
        from scipy.spatial import cKDTree
        nn = np.sort(cKDTree(block).query(block, k=2)[0][:, 1])
    except Exception:                                  # noqa: BLE001
        # No scipy is not a reason to ship a layout without its scale; it is
        # a reason to pay O(n^2) once on a corpus this size.
        d = np.linalg.norm(block[:, None, :] - block[None, :, :], axis=-1)
        np.fill_diagonal(d, np.inf)
        nn = np.sort(d.min(axis=1))
    n = len(nn)
    return {"p05": float(nn[n // 20]), "p25": float(nn[n // 4]),
            "p50": float(nn[n // 2]), "n": int(n)}


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
    scale = (2.0 * _EXTENT) / widest if widest > 1e-9 else 1.0
    if widest > 1e-9:
        block *= scale
    out[:, :dims] = block
    _LAST_FIT["frame"] = ((low + high) / 2.0, scale)
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
        out = np.asarray(reducer.fit_transform(features), dtype=np.float32)
        # Kept so a later batch can be `transform`ed into this same fit rather
        # than forcing a refit of the whole corpus. That is what makes live
        # capture affordable: a page scanned while the reader browses places
        # its chunks against the cloud that is already on screen.
        _LAST_FIT["reducer"] = reducer
        return out
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
        pca = PCA(n_components=k, random_state=seed)
        out = pca.fit_transform(features)
        # The fallback is `transform`-able too, so live placement keeps
        # working on a workspace too small for UMAP rather than silently
        # becoming the one case that cannot stream.
        _LAST_FIT["reducer"] = pca
        return np.asarray(out, dtype=np.float32)


def _title(md: str) -> str:
    for raw in (md or "").splitlines():
        line = raw.strip().lstrip("#").lstrip("-").strip()
        if line:
            return line[:80]
    return ""


# --- placing what arrives after the fit --------------------------------------


def _hsv_apply(block: np.ndarray, bands) -> np.ndarray:
    """`_hsv`, against the bands the fit measured rather than this batch's."""
    out = np.zeros((block.shape[0], 3), dtype=np.float32)
    for j in range(3):
        low, high = bands[j]
        column = block[:, j].astype(np.float32)
        unit = (np.full_like(column, 0.5) if high - low < 1e-9
                else (column - low) / (high - low))
        # Clipped, because a newcomer CAN fall outside the range the fit saw
        # and a hue of 400 degrees is not a colour. Clipping puts it at the
        # end of the band, which is where it belongs.
        unit = np.clip(unit, 0.0, 1.0)
        if j == 0:
            out[:, 0] = unit * 360.0
        elif j == 1:
            out[:, 1] = _SAT_BAND[0] + unit * (_SAT_BAND[1] - _SAT_BAND[0])
        else:
            out[:, 2] = _VAL_BAND[0] + unit * (_VAL_BAND[1] - _VAL_BAND[0])
    return out


def _spread_apply(coords: np.ndarray, dims: int, cdf) -> np.ndarray:
    """`_spread`, by looking a newcomer up in the fit's own distribution.

    The fit mapped each axis through its empirical CDF. A point arriving
    later is placed at ITS rank among those values -- `searchsorted` -- so it
    lands between the neighbours it belongs between and nothing already drawn
    moves. Re-ranking the corpus instead would shift every existing node a
    little on every capture, which is a picture that will not hold still
    while a reader is looking at it.
    """
    out = np.array(coords, dtype=np.float32, copy=True)
    for axis in range(min(dims, out.shape[1])):
        sorted_column = cdf.get(axis)
        if sorted_column is None or len(sorted_column) < 2:
            continue
        pos = np.searchsorted(sorted_column, out[:, axis])
        out[:, axis] = (pos / (len(sorted_column) - 1)).astype(np.float32)
    return out


def _frame_apply(coords: np.ndarray, dims: int, mid, scale: float
                 ) -> np.ndarray:
    """`_framed`, against the box the fit measured."""
    out = np.array(coords, dtype=np.float32, copy=True)
    out[:, :dims] = (out[:, :dims] - mid) * scale
    return out


class Projection:
    """A fit, kept so that what arrives later can join it.

    The reason this exists at all: a reader browsing with the sensor running
    produces chunks continuously, and refitting UMAP over the whole corpus on
    each one is not affordable -- nor is it right, because a refit moves every
    node, and a picture that rearranges itself while someone is reading it is
    not a picture of anything.

    UMAP fits a model and can `transform` new points into it. So can the SVD
    in front of it and the PCA that stands in when there are too few points to
    fit. Every stage between them is a normalisation with parameters, and the
    parameters are what `_LAST_FIT` collected -- so the whole pipeline replays.

    **Refit on DOUBLING.** A transform is only as good as the fit behind it,
    and a fit stops describing a corpus that has grown well past it. Refitting
    when the chunk count doubles bounds the staleness at a factor of two and
    makes the refits amortised O(1): 5k, 10k, 20k, not one per capture.
    """

    def __init__(self, *, svd, reducer, dims: int, hsv: bool,
                 hsv_bands, spread_cdf, frame, fitted_n: int) -> None:
        self.svd = svd
        self.reducer = reducer
        self.dims = dims
        self.hsv = hsv
        self.hsv_bands = hsv_bands
        self.spread_cdf = spread_cdf or {}
        self.frame_mid, self.frame_scale = frame if frame else (0.0, 1.0)
        self.fitted_n = int(fitted_n)

    @classmethod
    def of(cls, *, dims: int, hsv: bool, fitted_n: int
           ) -> Optional["Projection"]:
        """Collect what the fit just left on the shelf."""
        reducer = _LAST_FIT.get("reducer")
        if reducer is None or not hasattr(reducer, "transform"):
            return None
        return cls(svd=_LAST_FIT.get("svd"), reducer=reducer, dims=dims,
                   hsv=hsv, hsv_bands=_LAST_FIT.get("hsv_bands"),
                   spread_cdf=_LAST_FIT.get("spread_cdf"),
                   frame=_LAST_FIT.get("frame"), fitted_n=fitted_n)

    def stale(self, n: int) -> bool:
        """True once the corpus has doubled since this was fitted."""
        return self.fitted_n > 0 and n >= 2 * self.fitted_n

    def place(self, semantic: np.ndarray):
        """Rows of the raw semantic space -> (positions, colours-or-None).

        Returns ``(None, None)`` rather than raising when the transform
        cannot run. A pane that failed to place three new chunks should say
        so and keep the picture it has; it should not go blank.
        """
        if semantic is None or not len(semantic):
            return None, None
        try:
            features = (self.svd.transform(semantic)
                        if self.svd is not None else semantic)
            features = _unit_rows(np.asarray(features, dtype=np.float32))
            coords = np.asarray(self.reducer.transform(features),
                                dtype=np.float32)
        except Exception:                           # noqa: BLE001
            return None, None
        colours = None
        if self.hsv and coords.shape[1] >= self.dims + 3:
            colours = _hsv_apply(coords[:, self.dims:self.dims + 3],
                                 self.hsv_bands)
        coords = _spread_apply(coords, self.dims, self.spread_cdf)
        coords = _frame_apply(coords, self.dims, self.frame_mid,
                              self.frame_scale)
        return coords[:, :self.dims], colours


def place_into(workspace, cids) -> Dict:
    """Place chunks captured after the fit, into the fit (`G-34`).

    What the browser cell produces while a reader browses: a handful of new
    or rewritten chunks, wanted on screen now, against a cloud of thousands
    that must not move to accommodate them.

    Returns the same node shape `build_layout` returns, plus `stale`, which
    says the corpus has doubled since the fit and the pane should ask for a
    real one. Nodes the projection cannot place are reported in `unplaced`
    rather than dropped: a chunk that was captured and cannot be drawn is a
    fact the pane should be able to say out loud.
    """
    projection = live_projection()
    wanted = [c for c in dict.fromkeys(cids or []) if c]
    if projection is None:
        return {"nodes": [], "unplaced": wanted, "stale": True,
                "why": "no fit to place into yet"}
    if not wanted:
        return {"nodes": [], "unplaced": [], "stale": False}

    # Embed what is waiting, now, because this IS the moment someone asked.
    #
    # `flush_vectors` exists to make vectorisation "a function of settled
    # change rather than of delta count" -- a chunk rewritten on every frame
    # of a scroll is embedded once. A live capture drains several times a
    # second, so embedding per drain would be exactly the waste that design
    # avoids; embedding when the pane asks where to draw them is the same
    # rule, reached from the other side.
    if getattr(workspace, "embedder", None) is not None:
        try:
            workspace.flush_vectors(limit=_LIVE_EMBED_LIMIT)
        except Exception:                           # noqa: BLE001
            # A failed flush leaves the chunks unembedded and they are
            # reported as awaiting a vector, which is what they are. It must
            # not take the pane down with it.
            pass

    rows, meta, missing = [], [], []
    for cid in wanted:
        chunk = workspace.store.chunk(cid)
        if chunk is None or chunk.redundant:
            # A redundant chunk is deliberately not drawn -- `G-25` -- so it
            # is not "unplaced", it is placed as the copy it is.
            continue
        vector = workspace.store.embedding(cid)
        if not vector or not any(vector):
            # Captured but not yet embedded. The embedding phase is
            # asynchronous by design (the goal says so), so this is the
            # normal state for a chunk seconds old, not a failure.
            missing.append(cid)
            continue
        rows.append(vector)
        meta.append(chunk)

    nodes = []
    if rows:
        coords, colours = projection.place(
            np.asarray(rows, dtype=np.float32))
        if coords is None:
            return {"nodes": [], "unplaced": wanted, "stale": True,
                    "why": "the fit could not transform these"}
        for i, chunk in enumerate(meta):
            node = {
                "cid": chunk.cid,
                "url": chunk.url,
                "title": _title(chunk.md),
                "rank": 0.0,
                "chars": chunk.chars,
                "tokens": tokens.budget(chunk.md or ""),
                "copies": chunk.dup_n,
                "pos": [float(v) for v in coords[i]],
                #: Placed by `transform`, not by the fit itself. The pane may
                #: want to say so, and a measurement certainly does.
                "placed": True,
            }
            if colours is not None:
                node["hsv"] = [float(v) for v in colours[i]]
            picture = _first_image(chunk.md, chunk.url)
            if picture is not None:
                node["image"] = picture
            nodes.append(node)

    total = len(workspace.store.chunks())
    return {"nodes": nodes, "unplaced": missing,
            "stale": projection.stale(total),
            "fitted_n": projection.fitted_n, "n": total}
