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
from .spherical import DISPLAY_RADIUS as _BALL_RADIUS
from .spherical import from_ball as spherical_from_ball
from .spherical import to_ball as spherical_to_ball

#: `![alt](src)` as the distiller draws media. Non-greedy on the alt so a
#: chunk holding two pictures yields the first rather than one match spanning
#: both.
_MEDIA_RE = re.compile(r"!\[([^\]]*)\]\(((?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))+)\)")

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
_LAST_FIT: Dict[str, object] = {}

#: An embedding to start the spherical fit from, when a caller
#: has one. Set by the measurement harness while the warm start
#: is being evaluated; None in ordinary use.
#: Removed: it was bound to `None` here and assigned nowhere, so the
#: warm start it guarded never ran. `_spherical_init` computes one.

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


def build_page_layout(workspace,
                      *,
                      dims: int = 3,
                      hsv: bool = True,
                      seed: int = 0,
                      neighbors: int = 15,
                      min_dist: float = 0.25,
                      spread_axes: bool = True,
                      spherical_space: bool = False) -> Dict:
    """One node per PAGE, not per chunk (`G-53`).

    **The reason is the frame rate, and it is not a small one.** Measured on
    `build/corpus123`: 12,820 chunk nodes hold 3.3 fps, and it is not the 1.4
    million triangles -- the rate does not move between sitting still and
    rotating, which a fill-bound scene would. It is 20,309 draw calls, one per
    node and one per link, because `3d-force-graph` gives each its own mesh.
    94 pages is 94.

    And it is not only cheaper, it is legible: a map of 12,820 chunks is not a
    map of anything a reader can hold.

    **A page's vector is the mean of its chunks', renormalised.** The coarse
    layer of `G-63`'s coarse-to-fine: what a page MEANS is the centre of what
    its chunks mean. A merge group contributes its group vector, because that
    is what the group says and the members are inside it.

    **Fitted on the pages themselves**, which is what makes unfolding
    coherent: `Projection.place` then transforms a chunk's own vector into
    this same fit, so a page's chunks land around where the page node was
    rather than in a second, unrelated picture.

    It is also seconds faster. A chunk-level fit over 12,820 points takes
    about 95s; 94 points takes under one.
    """
    _LAST_FIT.clear()
    titles = workspace.store.page_titles()
    # One query for the whole corpus. See `page_vectors` for what assembling
    # this piecemeal cost.
    by_page, chunk_counts = workspace.store.page_vectors()

    urls, features, meta = [], [], []
    for url in sorted(by_page):
        rows = by_page[url]
        if not rows:
            continue
        block = np.asarray(rows, dtype=np.float32)
        mean = block.mean(axis=0)
        norm = float(np.linalg.norm(mean))
        # Renormalised: the members are unit vectors and their mean is not,
        # and a shorter vector reads as a weaker one wherever a cosine is
        # taken -- the same correction `_vectorise_groups` makes one level
        # down.
        features.append(mean / norm if norm > 1e-9 else mean)
        urls.append(url)
        meta.append({"chunks": chunk_counts.get(url, len(rows)),
                     "drawn": len(rows)})

    if len(urls) < 3:
        return {"nodes": [], "edges": [], "spaces": [], "n": len(urls),
                "level": "page", "note": "too few pages to place"}

    want = dims + (3 if hsv else 0)
    features = _unit_rows(np.asarray(features, dtype=np.float32))
    width = int(min(features.shape[1], max(2, features.shape[0] - 1),
                    _LONE_TARGET))
    reduced = _unit_rows(_reduce(features, width, seed))
    # `D-11`: the page level honours `?space=S3` too.
    #
    # It did not, and nothing said so. `G-53` made pages the default and this
    # function took no `spherical_space` at all, so the request was accepted,
    # folded into `/layout`'s cache key as though it had changed something,
    # and dropped -- leaving the quaternion fit reachable only from a level
    # nobody opens by default. "Apply the updates to our UMAP metric
    # THROUGHOUT" is not met by a fit that the default surface cannot ask
    # for.
    metric = None
    spherical_fit = bool(spherical_space and hsv and dims == 3)
    if spherical_fit:
        from .spherical import output_metric as _spherical_metric

        metric = _spherical_metric()
        spherical_fit = metric is not None
    page_neighbors = min(neighbors, max(2, len(urls) - 1))
    coords = _umap(reduced, dims=want, seed=seed,
                   neighbors=page_neighbors,
                   min_dist=min_dist,
                   output_metric=metric,
                   init=(_spherical_init(reduced, dims=dims, want=want,
                                         seed=seed, neighbors=page_neighbors,
                                         min_dist=min_dist)
                         if spherical_fit else None))

    got = int(coords.shape[1])
    colours = _hsv(coords[:, dims:dims + 3]) if (hsv and got >= want) else None
    if spherical_fit and got >= want:
        # Angles are MAPPED, not rescaled -- `_spread` is an empirical CDF
        # and would destroy the geometry the metric was chosen to impose,
        # and `_framed` could only move an already-centred ball off the
        # origin. Same reasoning as the chunk-level fit, and the same
        # `G-19` centring by construction.
        coords = np.hstack([spherical_to_ball(coords[:, :dims]),
                            coords[:, dims:]])
    else:
        if spread_axes:
            coords = _spread(coords, dims)
        coords = _framed(coords, dims)
    if got < dims:
        coords = np.hstack([coords,
                            np.zeros((coords.shape[0], dims - got),
                                     dtype=np.float32)])

    global _LAST_PROJECTION
    _LAST_PROJECTION = Projection.of(dims=dims, hsv=colours is not None,
                                     fitted_n=len(urls),
                                     spherical=spherical_fit,
                                     # Chunks, not pages: growth is judged
                                     # in chunks. See `fitted_chunks`.
                                     fitted_chunks=workspace.store.chunk_count())

    # One picture per page: the first that any of its chunks showed. Read
    # from the chunks' markdown, which is where `_first_image` looks anyway.
    pictures: Dict[str, Dict] = {}
    for chunk in workspace.store.chunks():
        if chunk.url in pictures or chunk.url not in by_page:
            continue
        found = _first_image(chunk.md or "", chunk.url)
        if found is not None:
            pictures[chunk.url] = found

    # **Relaxed by content before anything records these positions.**
    # `_room_around`, the unfold, the live placement and the pane's camera
    # all read from here, so the spacing has to be right at this point or
    # every one of them inherits a cloud with no room in it.
    chunk_counts = [len(by_page.get(u) or ()) for u in urls]
    relaxed = _relax_pages(coords, chunk_counts, dims)
    if relaxed is not None and len(relaxed) == len(coords):
        coords[:, :dims] = relaxed

    here = _PAGE_POS.setdefault(_space_name(spherical_fit), {})
    here.clear()
    # Every page is fitted now; no anchor is an estimate any more.
    _ESTIMATED_PAGES.clear()
    nodes = []
    for i, url in enumerate(urls):
        here[url] = [float(v) for v in coords[i][:dims]]
        node = {
            #: The url IS the id at this level. A page has no cid, and
            #: inventing one would make the pane's "which node is this"
            #: answer differ by level.
            "cid": "page:" + url,
            "url": url,
            "title": titles.get(url) or url,
            "rank": 0.0,
            "chars": 0,
            "tokens": 0,
            "copies": 1,
            #: How many chunks this page holds, which is what the node
            #: stands for and what unfolding will reveal.
            "members": meta[i]["chunks"],
            "level": "page",
            #: The size the renderer draws it at, and it has to MEAN
            #: something. Without this every page drew identically -- a
            #: 1,173-chunk reference index the same dot as a 15-chunk stub --
            #: and the map lost the one thing a collapsed view is for. Square
            #: root rather than the count, because `3d-force-graph` sizes a
            #: sphere as `cbrt(val)`, and a raw count would make the largest
            #: page eighty times the radius of the smallest.
            "val": float(max(1.0, meta[i]["chunks"] ** 0.5)),
            "pos": [float(v) for v in coords[i][:dims]],
        }
        if colours is not None:
            node["hsv"] = [float(v) for v in colours[i]]
        picture = pictures.get(url)
        if picture is not None:
            #: A page that showed pictures looks like one of them. The
            #: collapsed view lost every billboard when it stopped drawing
            #: chunks, and a map of ninety-six identical spheres is a map
            #: nobody can navigate by sight.
            node["image"] = picture
        nodes.append(node)

    known = {u: "page:" + u for u in urls}
    edges = []
    for source, target in workspace.store.page_links():
        if source in known and target in known and source != target:
            edges.append({"source": known[source], "target": known[target]})

    return {
        "nodes": nodes,
        "edges": edges,
        "spaces": ["semantic"],
        #: Which output space this actually IS. Its absence was half of
        #: `D-11`: a pane asking for S3 got Euclidean and had no field to
        #: read that would have told it.
        "space": "S3" if spherical_fit else "euclidean",
        "n": len(nodes),
        "level": "page",
        "dims": dims,
        "hsv": colours is not None,
        "fitted_dims": int(min(got, want)),
        "chunks": sum(m["chunks"] for m in meta),
        # The fields the pane's caption reads. Omitting them made it say
        # "96 chunks · · fit unreported" over a picture of 96 PAGES fitted on
        # the semantic space -- three wrong statements in one line, from a
        # report that simply did not answer the questions being asked of it.
        "fitted_on": {"semantic": True},
        "spacing": _spacing(coords, dims),
        "images": sum(1 for n in nodes if n.get("image")),
    }


def build_layout(workspace,
                 *,
                 dims: int = 3,
                 hsv: bool = True,
                 seed: int = 0,
                 neighbors: int = 15,
                 min_dist: float = 0.25,
                 spread_axes: bool = True,
                 spherical_space: bool = False) -> Dict:
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

    # Every live chunk, in a fixed order -- taken from the STORE.
    #
    # This enumerated `freq.rows` and that was a real hole. The projector
    # fits on the semantic space alone, by the goal's own instruction, and
    # then took its membership from the LEXICAL one: a chunk with a perfectly
    # good vector but no frequency row simply did not exist as far as the
    # picture was concerned. Measured on `build/corpus123`: 13,999 chunks,
    # 13,999 stored vectors, 13,999 embedding rows -- and 6,174 frequency
    # rows. Nine thousand chunks were in the workspace and not in the map,
    # with nothing anywhere saying so.
    #
    # The frequency row is still looked up, because pagerank is indexed by it
    # and the lexical fallback needs it, but a chunk without one is now placed
    # by the space the fit actually uses and simply carries rank 0.
    cids: List[str] = []
    rows: List[int] = []
    redundant = 0
    grouped = 0
    no_vector = 0
    freq_row = {cid: row for row, cid in enumerate(freq.rows) if cid}
    has_semantic = embeddings is not None and embeddings.matrix is not None
    for cid in sorted(meta):
        if cid:
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
            # One node per merge GROUP, not per member (`G-27`). The members
            # keep their chunks, their vectors and their addresses -- they are
            # still what a retrieval hit resolves to -- but the picture shows
            # the thing they add up to, because that is what the merge layer
            # is for. The group's lead carries it; the others are not drawn.
            #
            # Dropped before the fit for the same reason duplicates are: the
            # members sit inside one DBSCAN radius of each other, so drawing
            # all of them spends the projector's neighbourhood budget on a
            # region it has already described.
            if meta[cid].group_of and meta[cid].group_of != cid:
                grouped += 1
                continue
            # Placed by the space the fit will actually run on, which is
            # not always the semantic one. With embeddings present a chunk
            # needs a vector; without them the fit falls back to frequency
            # and a chunk needs a ROW. Requiring a vector unconditionally
            # emptied the fallback entirely -- a workspace with no embedder
            # drew nothing, and the report said "no chunks" rather than "no
            # embedder", which is the wrong thing to tell a reader.
            if has_semantic:
                if embeddings.row_of(cid) is None:
                    no_vector += 1
                    continue
            elif cid not in freq_row:
                no_vector += 1
                continue
            cids.append(cid)
            rows.append(freq_row.get(cid, -1))

    if len(cids) < 3:
        return {"nodes": [], "edges": [], "spaces": [], "n": len(cids),
                "note": "too few chunks to place"}

    # Only the chunks that HAVE a frequency row contribute one; the rest are
    # zero there and are carried by the semantic space, which is what the fit
    # uses anyway.
    known = [r for r in rows if r >= 0]
    lexical = (np.asarray(tfidf[known].todense(), dtype=np.float32)
               if known else np.zeros((0, 1), dtype=np.float32))

    semantic: Optional[np.ndarray] = None
    if embeddings is not None and embeddings.matrix is not None:
        wanted = [embeddings.row_of(cid) for cid in cids]
        if all(r is not None for r in wanted):
            semantic = np.asarray(embeddings.matrix[wanted], dtype=np.float32)
            # A merge group's node stands for the merged text, so it is placed
            # by the vector of that text -- re-vectorised at aggregation time,
            # or the members' mean when no embedder was loaded. Using the lead
            # member's own vector would put a node for eight chunks wherever
            # the first of them happened to land.
            #
            # Substituted here rather than in the matrix, because the matrix
            # is retrieval's and the lead is still a 256-token chunk there
            # (`G-27`). Only the PICTURE asks this question.
            for i, cid in enumerate(cids):
                if meta[cid].group_n > 1:
                    merged = workspace.store.group_embedding(cid)
                    if merged:
                        semantic[i] = np.asarray(merged, dtype=np.float32)

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
    # The projector's embedding space (`G-17`..`G-19`). Three of the six
    # components are hyperspherical ANGLES generating a unit quaternion, and
    # the metric between two points is the angle between the rotations they
    # name; the other three stay Euclidean and carry the colour, under a
    # product metric, so the colour still comes from the same fit as the
    # position.
    #
    # Only when the shape is the one the metric assumes: three spatial
    # components and three colour ones. A workspace too small to fit six is
    # laid out the old way and the report says so, which is the same rule
    # every other fallback in this module follows.
    #
    # **Off by default, on the measurement, and this is a finding rather than
    # a preference.** Scored as neighbourhood retention against the space the
    # fit is OF -- of a chunk's ten nearest neighbours by cosine over the
    # encoder's vectors, how many are still among its ten nearest in the
    # picture -- on 4,985 nodes of `build/vaultws256`:
    #
    #     euclidean                       0.375 - 0.400
    #     S3, colour weight 1.0           0.188
    #     S3, colour weight 0.1           0.189
    #     S3, warm-started from euclidean 0.186
    #     S3, angle scaled x8             0.166 - 0.186
    #
    # Three explanations were tested and all three are wrong. It is not the
    # product metric being unbalanced: 1.0 and 0.1 give the same answer. It is
    # not the angle parameterisation's singularity at the identity: starting
    # the fit from a layout that already has structure gives the same answer.
    # It is not only the metric's bounded range against UMAP's `a`/`b` curve:
    # scaling the angle by eight moved the median radius from 10.8 to 49.8 and
    # left retention where it was.
    #
    # So the metric is implemented, gradient-checked against finite
    # differences, and available -- and on this corpus it draws a picture that
    # keeps less than half as many of the encoder's neighbourhoods as the
    # Euclidean one. Shipping that as the default would be shipping a
    # regression in the one property a projection is answerable for. The flag
    # is how `G-18` gets exercised and swept; the number above is what has to
    # move before it becomes the default.
    metric = None
    spherical_fit = bool(spherical_space and hsv and dims == 3)
    if spherical_fit:
        from .spherical import output_metric as _spherical_metric

        metric = _spherical_metric()
        spherical_fit = metric is not None
    coords = _umap(features, dims=want, seed=seed,
                   neighbors=neighbors, min_dist=min_dist,
                   output_metric=metric,
                   init=(_spherical_init(features, dims=dims, want=want,
                                         seed=seed, neighbors=neighbors,
                                         min_dist=min_dist)
                         if spherical_fit else None))

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
    if spherical_fit and got >= want:
        # The spatial components are ANGLES, so they are not rescaled -- they
        # are mapped. `to_ball` sends the identity rotation to the origin and
        # makes the rotation angle the radius, which centres the cloud by
        # construction (`G-19`) instead of by measuring an extent and
        # subtracting it.
        #
        # `_spread` and `_framed` are skipped rather than reordered. Both are
        # rescalings of unconstrained coordinates, and an angle is not one: an
        # empirical CDF over φ₁ would destroy the very geometry the metric was
        # chosen to impose, and re-framing a ball that is already centred and
        # bounded could only move it off the origin.
        coords = np.hstack([spherical_to_ball(coords[:, :dims]),
                            coords[:, dims:]])
    else:
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
        # A lead speaks for its group, so its label and its size are the
        # group's. Assembled rather than stored, like everywhere else, so a
        # member rewritten by the next drain cannot leave a stale copy of
        # itself in what the node says.
        text = chunk.md
        if chunk.group_n > 1:
            try:
                text = workspace.merged_markdown(cid) or chunk.md
            except Exception:                       # noqa: BLE001
                text = chunk.md
        node = {
            "cid": cid,
            "url": chunk.url,
            #: The address, so clicking this node can take the BROWSER to it
            #: (`G-40`). `unfold`'s nodes have carried it all along; these
            #: did not, so a chunk clicked in the chunk-level view had a url
            #: and no place on the page to scroll to.
            "path": chunk.xpath,
            "title": _title(text),
            #: How many addresses on the page draw this, so the pane can say
            #: "125 copies" instead of silently standing for 125 things.
            "copies": chunk.dup_n,
            #: How many chunks this node stands for (`G-26`). 1 unless stage
            #: two merged it with others.
            "members": chunk.group_n,
            "rank": (float(ranks[row]) if 0 <= row < len(ranks) else 0.0),
            "chars": chunk.chars,
            "tokens": tokens.budget(text or ""),
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
                                     fitted_n=len(cids),
                                     spherical=spherical_fit)

    return {
        "nodes": nodes,
        "edges": edges,
        "spaces": spaces,
        "n": len(nodes),
        #: Chunks the page draws more than once, left out of the fit. Reported
        #: rather than silently subtracted: `n` no longer equals the store's
        #: chunk count, and a reader comparing the two needs to see why.
        "redundant": redundant,
        #: Chunks folded into a merge group and therefore not drawn on their
        #: own. Reported for the same reason `redundant` is: `n` no longer
        #: equals the store's chunk count, and the difference now has two
        #: causes a reader has to be able to tell apart.
        "grouped": grouped,
        #: Chunks the store holds that have no semantic vector, so the fit
        #: cannot place them. Reported rather than silently dropped.
        "no_vector": no_vector,
        #: The geometry the points were laid out IN (`G-18`). "S3" means the
        #: quaternion metric ran; "euclidean" means it did not, and a reader
        #: of the picture has to be able to tell, because the two are
        #: different pictures of the same data.
        "space": "S3" if spherical_fit else "euclidean",
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
        # **COPIED, and the copy is the whole correctness of `place`.**
        #
        # `out[:, axis]` is a VIEW. The assignment two lines down overwrote
        # it in place, so the "sorted column" kept below was the RANKED
        # values, 0..1 -- not the raw coordinates a newcomer has to be
        # ranked against. `_spread_apply` then compared a raw UMAP
        # coordinate (measured: -3.42 .. 5.39) against a distribution
        # spanning 0 .. 1, so every placed point fell entirely below or
        # entirely above it, ranked to 0 or 1, and framed to exactly -300 or
        # +300: a corner. Every unfold, every live capture, every hit list
        # put its nodes there. Measured on RFC 9110: 26 chunks, all at one
        # point, 762 units from their own page node.
        column = np.array(out[:, axis], dtype=np.float32, copy=True)
        if float(column.max() - column.min()) == 0.0:
            continue                       # a collapsed axis stays collapsed
        rank = np.argsort(np.argsort(column))
        out[:, axis] = (rank / (n - 1)).astype(np.float32)
        # The sorted column IS the empirical CDF. Kept so a newcomer can be
        # placed at its own rank among the points already drawn -- a
        # `searchsorted` -- instead of re-ranking the corpus, which would
        # move every existing node a little on every capture.
        cdf[axis] = np.sort(column)
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


def _spherical_init(features: np.ndarray, *, dims: int, want: int,
                    seed: int, neighbors: int, min_dist: float):
    """The warm start the spherical fit was written for and never had.

    `spherical.from_ball` exists solely to produce this, and it had **zero
    callers**: `_WARM_INIT` was bound to `None` at module scope and never
    assigned, so the guard around it could not pass and every spherical fit
    ever measured ran from UMAP's own initialisation -- the exact condition
    `from_ball`'s docstring says collapses, because hyperspherical angles are
    singular at the identity and a fit starting near there optimises in
    ill-conditioned coordinates.

    Measured collapse, page level, no warm start: all 96 pages inside a cone
    of **15.3 degrees** about their mean direction (median 6.1) out of the
    180 available, at radius 50-135 and never near the origin. So the
    origin-centred view the goal asks for framed an empty middle with the
    corpus as a blob off to one side.

    The Euclidean fit is run first and mapped through `from_ball`. It is
    CENTRED before mapping, which is what puts the cloud's middle at the
    identity rotation rather than at an arbitrary offset -- "we center our
    focus on the origin" is a statement about where the data goes, not only
    about where the camera looks.

    Costs one extra UMAP fit. Stated rather than hidden: the spherical fit is
    roughly twice the Euclidean one, and it is off by default.
    """
    euclid = _umap(features, dims=want, seed=seed,
                   neighbors=neighbors, min_dist=min_dist)
    if int(euclid.shape[1]) < want:
        return None
    spatial = np.asarray(euclid[:, :dims], dtype=np.float64)
    spatial = spatial - spatial.mean(axis=0, keepdims=True)
    longest = float(np.linalg.norm(spatial, axis=1).max())
    if not (longest > 1e-9):
        return None
    # 0.9 of the ball, not 1.0: `from_ball` clips at the radius, and a point
    # that saturates lands at theta = pi where the map is singular again.
    spatial = spatial * (float(_BALL_RADIUS) * 0.9 / longest)
    angles = spherical_from_ball(spatial)
    return np.hstack([angles, euclid[:, dims:want]]).astype(np.float32)


def _umap(features: np.ndarray, *, dims: int, seed: int,
          neighbors: int, min_dist: float, output_metric=None,
          init=None) -> np.ndarray:
    """The final projection, or a PCA when there is too little to fit.

    UMAP needs more points than neighbours; a small workspace has fewer
    chunks than the default fifteen, and it raises rather than adapting. A
    vault with nine notes should still get a picture.
    """
    n = features.shape[0]
    k = int(max(2, min(neighbors, n - 1)))
    try:
        import umap

        kwargs = {}
        if output_metric is not None:
            # The embedding space itself, not the input metric (`G-18`). The
            # input is still cosine over the encoder's vectors; what changes
            # is the geometry the points are laid out IN.
            kwargs["output_metric"] = output_metric
        if init is not None:
            # A warm start, not a preference. Left to its own initialisation
            # the spherical fit lands on the identity rotation, where the
            # angle parameterisation is singular; see `spherical.from_ball`.
            kwargs["init"] = init
        reducer = umap.UMAP(n_components=dims, n_neighbors=k,
                            min_dist=min_dist, random_state=seed, **kwargs)
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
        sorted_column = np.asarray(cdf.get(axis), dtype=np.float32) \
            if cdf.get(axis) is not None else None
        if sorted_column is None or len(sorted_column) < 2:
            continue
        n = len(sorted_column)
        ranks = np.arange(n, dtype=np.float32) / (n - 1)
        value = out[:, axis].astype(np.float32)

        # BETWEEN its neighbours, not ON one of them.
        #
        # `searchsorted` answers an integer rank, so every newcomer landed
        # exactly where an existing point already was; interpolating puts it
        # at its true position between them, which is what this function
        # promises.
        placed = np.interp(value, sorted_column, ranks).astype(np.float32)

        # And PAST the ends, keeping the order.
        #
        # `np.interp` clamps outside the support, so every point beyond the
        # fit's range collapsed onto the boundary -- 101 of 200 chunks on one
        # axis of one page, all at the same coordinate, which is the very
        # thing `_spread` exists to prevent. The fit is over 96 page-means
        # and the chunks it places are individual, so falling outside is the
        # ORDINARY case and not an edge one.
        #
        # The tail slope is taken across the outer decile rather than the
        # last pair: one gap between two extreme points is noise, and a
        # slope read off noise sends a newcomer an arbitrary distance away.
        edge = max(1, n // 10)
        lo_span = float(sorted_column[edge] - sorted_column[0])
        hi_span = float(sorted_column[-1] - sorted_column[-1 - edge])
        below = value < sorted_column[0]
        above = value > sorted_column[-1]
        if np.any(below) and lo_span > 1e-9:
            slope = float(ranks[edge] - ranks[0]) / lo_span
            placed[below] = (ranks[0]
                             + (value[below] - sorted_column[0]) * slope)
        if np.any(above) and hi_span > 1e-9:
            slope = float(ranks[-1] - ranks[-1 - edge]) / hi_span
            placed[above] = (ranks[-1]
                             + (value[above] - sorted_column[-1]) * slope)
        out[:, axis] = placed
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
                 hsv_bands, spread_cdf, frame, fitted_n: int,
                 spherical: bool = False,
                 fitted_chunks: Optional[int] = None) -> None:
        #: Fitted on S³, so a newcomer is MAPPED to the ball rather than
        #: rescaled. Replaying `_spread` and `_framed` on angles would put it
        #: somewhere the fit never placed anything.
        self.spherical = bool(spherical)
        self.svd = svd
        self.reducer = reducer
        self.dims = dims
        self.hsv = hsv
        self.hsv_bands = hsv_bands
        self.spread_cdf = spread_cdf or {}
        self.frame_mid, self.frame_scale = frame if frame else (0.0, 1.0)
        #: How many POINTS the fit was made on -- pages for the page-level
        #: fit, chunks for the chunk-level one.
        self.fitted_n = int(fitted_n)
        #: How many CHUNKS the corpus held when this was fitted, which is the
        #: unit growth is judged in.
        #:
        #: **Not `fitted_n`, and that confusion is why "stale" meant nothing.**
        #: The page-level fit -- the one the pane actually draws -- recorded
        #: `fitted_n = len(urls)`, 112 pages, while `stale()` was handed the
        #: corpus CHUNK count, 14,787. A ratio of 132 against a threshold of
        #: 2, so the fit read stale permanently and the pane's "fit is stale,
        #: refit" was lit the whole time and meant nothing. Wiring a refit to
        #: that flag would have refit on every capture.
        self.fitted_chunks = int(fitted_chunks if fitted_chunks is not None
                                 else fitted_n)

    @classmethod
    def of(cls, *, dims: int, hsv: bool, fitted_n: int,
           spherical: bool = False,
           fitted_chunks: Optional[int] = None) -> Optional["Projection"]:
        """Collect what the fit just left on the shelf."""
        reducer = _LAST_FIT.get("reducer")
        if reducer is None or not hasattr(reducer, "transform"):
            return None
        return cls(svd=_LAST_FIT.get("svd"), reducer=reducer, dims=dims,
                   hsv=hsv, hsv_bands=_LAST_FIT.get("hsv_bands"),
                   spread_cdf=_LAST_FIT.get("spread_cdf"),
                   frame=_LAST_FIT.get("frame"), fitted_n=fitted_n,
                   spherical=spherical, fitted_chunks=fitted_chunks)

    def stale(self, n: int) -> bool:
        """True once the corpus's CHUNK count has doubled since this fit.

        `n` is a chunk count, and so is what it is compared against. See
        `fitted_chunks` for what happened when it was not.
        """
        return self.fitted_chunks > 0 and n >= 2 * self.fitted_chunks

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
        if self.spherical:
            # The same map the fit used, and for the same reason: these are
            # angles. `_spread_apply` looks a value up in a distribution of
            # unconstrained coordinates, which φ₁ is not.
            return spherical_to_ball(coords[:, :self.dims]), colours
        coords = _spread_apply(coords, self.dims, self.spread_cdf)
        coords = _frame_apply(coords, self.dims, self.frame_mid,
                              self.frame_scale)
        return coords[:, :self.dims], colours


#: How far an unfolded page's chunks spread around their page's position.
#: The page cloud spans about +/-300, so a page opening into a ball of this
#: radius reads as "these belong to that node" rather than as a second cloud
#: competing with the first.
UNFOLD_RADIUS = 90.0

#: Where `build_page_layout` actually DREW each page, PER SPACE.
#:
#: An unfolding anchors on this rather than re-deriving the page's position
#: with `place(page_mean)`. UMAP's `transform` does not reproduce its own
#: `fit_transform` output for the same point, so re-deriving put the ball of
#: chunks a median 129 units from the node it was supposed to hang off --
#: further than the ball's own radius.
#:
#: **Keyed by space, because one dict was wrong the moment both existed.**
#: Asking for `?space=S3&level=page` re-runs the page fit and would overwrite
#: euclidean anchors with spherical ones, while the pane is still being
#: served the euclidean layout out of the cache. Measured by `G-54`'s live
#: check: a page's chunks landed 378 units from it, against a ball of radius
#: 90. The pane says which space it is in and gets the anchors for that one.
_PAGE_POS: Dict[str, Dict[str, List[float]]] = {}

#: Pages whose anchor in `_PAGE_POS` is an ESTIMATE -- placed into the fit at
#: the transform of their chunks' mean -- rather than a fitted position.
#:
#: Tracked because two paths create such an anchor and only one of them sent
#: the page's node. `refresh_page_layout` registers the anchor and puts the
#: node in the layout; `place_into` then finds the anchor, concludes the page
#: already has a node, and sends chunks only. The live pane receives chunks,
#: never the layout's copy, so a page browsed after the fit drew 684 chunk
#: nodes around empty space with no hub. Every placement for a page in this
#: set now carries its node. A refit replaces the estimates and clears it.
_ESTIMATED_PAGES: set = set()


def _space_name(spherical: bool) -> str:
    return "S3" if spherical else "euclidean"


def remember_page_positions(payload, spherical: bool = False) -> int:
    """Restore `_PAGE_POS` from a layout that was NOT built in this process.

    `G-12` serves a stored fit without calling `build_page_layout`, so the
    side effect that records where each page was drawn never happens -- and
    an unfolding then has no anchor for the space it is in. Measured when
    this was missing: chunks landed **378 units** from their page against a
    ball of radius 90, which is `D-20` again by a different route.

    Returns how many pages it remembered, so a caller can tell a restored
    layout from an empty one.
    """
    nodes = (payload or {}).get("nodes") or []
    here = _PAGE_POS.setdefault(_space_name(spherical), {})
    here.clear()
    for node in nodes:
        url = node.get("url")
        pos = node.get("pos")
        if url and isinstance(pos, (list, tuple)) and len(pos) >= 3:
            here[url] = [float(v) for v in pos[:3]]
    return len(here)



def _first_md_with_image(members) -> str:
    """The markdown of the first member that shows a picture, else the first.

    Ordered by `(xpath, part)` like `first` is, so a branch's thumbnail is
    the picture a reader would meet first when they opened it -- not
    whichever chunk the store happened to return first.
    """
    ordered = sorted(members, key=lambda c: (c.xpath, c.part))
    for chunk in ordered:
        md = chunk.md or ""
        if "![" in md:
            return md
    return ordered[0].md if ordered else ""


def _room_around(url: str, space: str, anchor) -> float:
    """How much room a page actually has, before its unfolding covers a
    neighbour.

    **Why this is not a constant, which is what it was.** `UNFOLD_RADIUS`
    was 90 world units for every page in every corpus. Measured against the
    layer it has to fit inside -- 97 page nodes in the live pane -- the
    nearest-neighbour spacing between pages is **71 units at the median**
    (49 at p10, 104 at p90). So the ball a page opened into was LARGER than
    the gap to the page beside it, and **67 of the 97** had at least one
    other page inside that ball, up to five. Unfolding did not open a page;
    it spilled its chunks over whatever was next to it, and the two layers
    stopped being two layers.

    Half the nearest-neighbour distance is the largest radius that cannot
    reach a neighbour's centre; 0.45 of it leaves a visible seam between two
    open pages. Both numbers are read from `_PAGE_POS`, which is the layer-1
    layout itself, so this tracks a corpus that spreads or tightens instead
    of being re-tuned when it does.

    In trie terms: layer 1 gives every root a territory, and a patricia step
    down from that root has to draw inside it.
    """
    table = _PAGE_POS.get(space) or {}
    here = np.asarray(anchor, dtype=np.float32).reshape(3)
    nearest = np.inf
    for other, pos in table.items():
        if other == url or not pos or len(pos) < 3:
            continue
        gap = float(np.linalg.norm(
            np.asarray(pos[:3], dtype=np.float32) - here))
        if 1e-6 < gap < nearest:
            nearest = gap
    if not np.isfinite(nearest):
        # One page, or a space with no table yet: nothing to collide with,
        # so the old constant is as good an answer as any.
        return UNFOLD_RADIUS
    # Floored so a pair of near-coincident pages does not collapse their
    # unfoldings to a point, capped so a lone outlier does not open into a
    # ball the size of the corpus.
    return float(min(UNFOLD_RADIUS, max(UNFOLD_RADIUS * 0.15, nearest * 0.45)))


def _relax_pages(coords: np.ndarray, counts, dims: int,
                 rounds: int = 120) -> np.ndarray:
    """Push pages apart until each has room for its own chunks.

    Collision only, and one-sided: a pair further apart than the room they
    both need feels nothing, so the UMAP's structure is preserved wherever it
    already works and only the crowded neighbourhoods open up. Seeded from
    the fit and reported as drift, per `G-20`.

    The radius a page claims is `cbrt(chunks)`, scaled to the cloud. Cube
    root because room is a VOLUME: a page with eight times the chunks needs
    twice the radius, not eight times, and using the count directly made one
    reference index claim a third of the corpus.
    """
    if len(coords) < 2:
        return coords
    pts = np.asarray(coords[:, :dims], dtype=np.float32).copy()
    want = np.asarray([max(1.0, float(c)) ** (1.0 / 3.0) for c in counts],
                      dtype=np.float32)
    # Scale the claims so the median page keeps roughly the spacing the fit
    # already gave it. Without this the absolute units are arbitrary and the
    # relaxation either does nothing or explodes the cloud.
    gaps = []
    for i in range(len(pts)):
        d = np.linalg.norm(pts - pts[i], axis=1)
        d[i] = np.inf
        gaps.append(float(d.min()))
    median_gap = float(np.median(gaps)) or 1.0
    want = want * (median_gap / float(np.median(want) or 1.0)) * 0.5

    for _ in range(rounds):
        moved = 0.0
        for i in range(len(pts)):
            delta = pts - pts[i]
            dist = np.linalg.norm(delta, axis=1)
            dist[i] = np.inf
            need = want + want[i]
            hit = np.where(dist < need)[0]
            if not len(hit):
                continue
            for j in hit:
                d = float(dist[j]) or 1e-6
                push = (float(need[j]) - d) / d * 0.5
                step = delta[j] * push * 0.5
                pts[i] -= step
                pts[j] += step
                moved += float(np.linalg.norm(step))
        if moved < 1e-3:
            break
    return pts


def _local_positions(rows: np.ndarray, anchor, *, seed: int = 0,
                     radius: float = UNFOLD_RADIUS):
    """A fit over the page's OWN chunks, placed around `anchor`.

    **Why not the global transform, which is what this replaces.** The
    default fit is over 96 page-MEANS, and transforming individual chunks
    into it keeps almost nothing of their structure. Measured on RFC 9110,
    300 chunks, 10-NN neighbourhoods kept:

        into the page-level fit     0.086     <- what shipped
        a fit made on these chunks  0.507
        random positions            0.035

    0.086 against a random baseline of 0.035 is not a projection of anything;
    it is why a reader unfolding a few pages saw the chunks land jumbled. A
    page's mean cannot stand in for its chunks, because the mean is exactly
    the direction they all share and the differences between them are what
    is left over after it is removed.

    So the local structure comes from a local fit and the global position
    comes from the page node, which already carries it. The two claims stay
    separate: where the page is, is the corpus's business; how its chunks sit
    inside it, is the page's.

    Colour is NOT taken from here. It stays the global fit's six-dimensional
    statement so that two chunks on different pages that look alike still
    look alike (`D-1`).
    """
    block = _unit_rows(np.asarray(rows, dtype=np.float32))
    n = len(block)
    if n == 0:
        return None
    if n < 4:
        # Too few to fit anything meaningful. Spread them on a small ring so
        # they are distinguishable, rather than inventing structure.
        out = np.zeros((n, 3), dtype=np.float32)
        for i in range(n):
            angle = 2.0 * np.pi * i / max(n, 1)
            out[i] = (np.cos(angle), np.sin(angle), 0.0)
        local = out * (radius * 0.5)
    else:
        fitted = _umap(block, dims=3, seed=seed,
                       neighbors=min(15, max(2, n - 1)), min_dist=0.25)
        local = np.asarray(fitted, dtype=np.float32)[:, :3]
        local = local - local.mean(axis=0, keepdims=True)
        longest = float(np.linalg.norm(local, axis=1).max())
        if longest > 1e-9:
            local = local * (radius / longest)
    at = np.asarray(anchor, dtype=np.float32).reshape(1, 3)
    return (local + at).astype(np.float32)


def _edges_among(workspace, url: str, meta) -> List[Dict]:
    """The containment edges between whatever an unfolding just produced.

    Unfolded nodes arrived with no edges at all, so a page opened into a
    scatter of unconnected dots and the patricia structure the trie holds --
    which is the reason the trie exists -- was the one thing the picture did
    not show.

    A branch node stands for every chunk beneath it, so an edge is drawn
    between two emitted nodes when any chunk under one contains a chunk under
    the other. Self-edges are dropped: containment inside a single branch is
    what that branch already IS, and drawing it would be the node pointing at
    itself.
    """
    covers: Dict[str, str] = {}
    for info in meta:
        node_id = info["cid"]
        for cid in info.get("covers") or [info["cid"]]:
            covers[cid] = node_id
    if not covers:
        return []
    seen = set()
    out: List[Dict] = []
    for a, b in workspace.store.contains_within(url):
        source, target = covers.get(a), covers.get(b)
        if not source or not target or source == target:
            continue
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        out.append({"source": source, "target": target})
    return out


def _segments(xpath: str):
    return [s for s in (xpath or "").split("/") if s]


def _ensure_projection(workspace):
    """The live fit, built on demand if there is not one yet (`G-12`).

    A stored layout gives the pane its PICTURE without refitting, and that is
    the whole point of persisting one -- but a picture is not a fit. The
    fitted reducer is a model, it does not serialise to JSON, and `unfold`
    and `place_into` need it to put a NEWCOMER where it belongs.

    Without this, serving a stored layout after a restart left every
    unfolding answering "no fit to place into yet": the feature would have
    paid for itself in startup time and charged for it in the one gesture a
    reader makes most. Building here keeps persistence a pure optimisation.
    """
    projection = live_projection()
    if projection is not None:
        return projection
    try:
        build_page_layout(workspace, dims=3)
    except Exception:                               # noqa: BLE001
        return None
    return live_projection()


def _not_fitted_why() -> str:
    """Why nothing can be placed yet, in words that are true. This said "the
    chunk projector is fitting" while the projector had never fitted and was
    not trying to: it had refused, for want of pages (2026-10-04)."""
    try:
        from .projector import projector as _get
        p = _get()
    except Exception:                               # noqa: BLE001
        p = None
    if p is None:
        return "no projector"
    if getattr(p, "fitting", False):
        return "the projector is fitting"
    skip = getattr(p, "fit_skip", None)
    if skip:
        return "not fitted yet: %s (%s page(s), %s chunk(s))" % (
            skip.get("skipped"), skip.get("n"), skip.get("chunks"))
    if getattr(p, "fit_error", ""):
        return "not fitted: %s" % p.fit_error
    return "not fitted yet"


def unfold(workspace, url: str, path: str = "", space: str = "",
           anchor_at=None, room: float = 0.0) -> Dict:
    """One step of unravelling a page's patricia path (`G-54`).

    Not an expansion of a subtree. The reader's word for this is
    *unravelling*, and the distinction is the whole cost argument: a path is
    O(depth) and a subtree is O(everything under it). A page with 1,173 chunks
    expanded whole is the 12,820-node picture again, one page at a time.

    So a step descends the shared path until it BRANCHES, and shows the
    branches. That is patricia compression and it is already the shape of the
    trie: a run of single-child wrappers is one edge, because a chain of divs
    that nobody chose is not a decision anyone needs to click through.

    A branch holding one chunk comes back as that chunk, with its own cid --
    there is nothing left to unravel and making the reader click again to
    reach it would be a level of the tree that exists only in this function.

    Positions come from `Projection.place`, so what appears lands in the
    picture already on screen rather than in a second, unrelated one.
    """
    _cp = _live_chunk_projector()
    if _cp is None and _projector_running():
        return {"nodes": [], "path": path, "url": url, "why": _not_fitted_why()}
    projection = (_cp.projection if _cp is not None
                  else _ensure_projection(workspace))
    stored = [c for c in workspace.store.chunks(url) if not c.redundant]
    stored = [c for c in stored
              if not (c.group_of and c.group_of != c.cid)]
    prefix = _segments(path)
    under = [c for c in stored
             if _segments(c.xpath)[:len(prefix)] == prefix]
    if not under:
        return {"nodes": [], "path": path, "url": url,
                "why": "nothing under that path"}

    # Descend while there is only one way to go. This is where the "chain of
    # five wrappers costs one step" property comes from.
    depth = len(prefix)
    while True:
        nexts = {tuple(_segments(c.xpath)[:depth + 1]) for c in under
                 if len(_segments(c.xpath)) > depth}
        if len(nexts) != 1:
            break
        depth += 1

    branches: Dict[tuple, list] = {}
    leaves = []
    for chunk in under:
        parts = _segments(chunk.xpath)
        if len(parts) <= depth:
            leaves.append(chunk)                    # the node itself, here
        else:
            branches.setdefault(tuple(parts[:depth + 1]), []).append(chunk)

    vectors = workspace.store.embeddings_for(url)
    rows, meta = [], []

    def vector_of(chunk):
        if chunk.group_n > 1:
            got = workspace.store.group_embedding(chunk.cid)
            if got:
                return got
        return vectors.get(chunk.cid)

    for parts, members in sorted(branches.items()):
        block = [vector_of(c) for c in members]
        block = [v for v in block if v]
        if not block:
            continue
        mean = np.asarray(block, dtype=np.float32).mean(axis=0)
        norm = float(np.linalg.norm(mean))
        rows.append(mean / norm if norm > 1e-9 else mean)
        first = min(members, key=lambda c: (c.xpath, c.part))
        single = len(members) == 1
        meta.append({
            "cid": (first.cid if single
                    else "path:%s#/%s" % (url, "/".join(parts))),
            "url": url,
            "title": _title(first.md) or "/" + parts[-1],
            "members": len(members),
            "chars": first.chars if single else 0,
            "tokens": (tokens.budget(first.md or "") if single else 0),
            "level": "chunk" if single else "path",
            #: Sized like a page node and in the SAME unit: the square root
            #: of how many chunks it stands for. See `_room_around` for why
            #: this is not a tuning choice.
            "val": float(max(1.0, len(members) ** 0.5)),
            "path": "/" + "/".join(parts),
            #: A branch shows the first picture anything BENEATH it shows.
            #:
            #: This was `first.md if single else ""`, so a node standing for
            #: more than one chunk had no markdown and `_first_image` below
            #: had nothing to read: measured, **0 of 161 fan-out nodes
            #: carried an image** while page nodes did. A branch is a
            #: container for its subtree, and the subtree's first picture is
            #: exactly the thumbnail a container should wear -- it is the
            #: same rule `pictures` already applies one level up, where a
            #: page looks like the first image any of its chunks showed.
            #:
            #: Joined rather than concatenated in full: `_first_image` stops
            #: at the first match, so this pays for the members it has to
            #: scan before finding one and not for the whole subtree.
            "md": first.md if single else _first_md_with_image(members),
            #: Every chunk this node stands for, so `_edges_among` can map a
            #: containment edge between two chunks onto the two nodes that
            #: are actually drawn.
            "covers": [c.cid for c in members],
        })

    for chunk in leaves:
        got = vector_of(chunk)
        if not got:
            continue
        rows.append(np.asarray(got, dtype=np.float32))
        meta.append({
            "cid": chunk.cid, "url": url,
            "title": _title(chunk.md), "members": chunk.group_n,
            "chars": chunk.chars,
            "tokens": tokens.budget(chunk.md or ""),
            "level": "chunk", "path": chunk.xpath, "md": chunk.md,
            "val": float(max(1.0, max(chunk.group_n, 1) ** 0.5)),
            "covers": [chunk.cid],
        })

    if not rows:
        return {"nodes": [], "path": path, "url": url,
                "why": "nothing under that path has a vector"}
    if projection is None:
        return {"nodes": [], "path": path, "url": url,
                "why": "no fit to place into yet"}

    block = np.asarray(rows, dtype=np.float32)
    coords, colours = projection.place(block)
    if coords is None:
        return {"nodes": [], "path": path, "url": url,
                "why": "the fit could not transform these"}

    # Position from a LOCAL fit, anchored where this page sits (see
    # `_local_positions`). Colour stays the global fit's, so two chunks on
    # different pages that mean the same thing still look the same.
    if _cp is not None:
        # **Placed by the projector, and nothing else.** A branch sits at the
        # transform of its members' mean, a chunk where the stream put it,
        # the page where the fit puts what it means. No local ball, no room:
        # the trie's structure is the edges, and where a node sits is what it
        # says.
        with _cp.lock:
            for i, info in enumerate(meta):
                if info["level"] == "chunk" and info["cid"] in _cp.pos:
                    coords[i] = _cp.pos[info["cid"]]
                    if colours is not None and info["cid"] in _cp.hsv:
                        colours[i] = _cp.hsv[info["cid"]]
        nodes = []
        for i, info in enumerate(meta):
            node = dict(info)
            node.pop("md", None)
            node.pop("covers", None)
            node.update({"rank": 0.0, "copies": 1, "source": "projector",
                         "pos": [float(v) for v in coords[i]]})
            if colours is not None:
                node["hsv"] = [float(v) for v in colours[i]]
            picture = _first_image(info.get("md") or "", url)
            if picture is not None:
                node["image"] = picture
            nodes.append(node)
        parent_id = ("page:" + url if not prefix
                     else "path:%s#/%s" % (url, "/".join(prefix)))
        edges = [{"source": parent_id, "target": info["cid"]} for info in meta]
        edges.extend(_edges_among(workspace, url, meta))
        return {"nodes": nodes, "edges": edges, "parent": parent_id,
                "url": url, "source": "projector",
                "path": "/" + "/".join(_segments(path)) if prefix else "",
                "depth": depth, "branches": len(branches),
                "leaves": len(leaves)}

    anchor = None
    # The anchors for the space the READER is in, not whichever fit ran last.
    wanted = _space_name(bool(space) and space.lower() in ("s3", "spherical"))
    drawn = (_PAGE_POS.get(wanted) or {}).get(url)
    # **No borrowing from another space.** This used to fall back to
    # whichever table had the url, on the reasoning that one fitted space is
    # better than none. It is not: a euclidean page and its S3 twin are
    # nowhere near each other, so the fallback turned a MISSING anchor into
    # a WRONG one -- 378 units from the node it hangs off, silently. If this
    # space has no anchor, the code below derives one from the live fit,
    # which is at least the space the reader is in.
    if drawn and len(drawn) >= 3:
        anchor = np.asarray(drawn[:3], dtype=np.float32)
    page_rows = ([] if anchor is not None else
                 [v for v in workspace.store.embeddings_for(url).values() if v])
    if page_rows:
        mean = np.asarray(page_rows, dtype=np.float32).mean(axis=0)
        norm = float(np.linalg.norm(mean))
        where, _ = projection.place(
            (mean / norm if norm > 1e-9 else mean).reshape(1, -1))
        if where is not None and len(where):
            anchor = where[0]
    if anchor is None:
        anchor = coords.mean(axis=0)
    # **A nested step is placed inside its PARENT, not inside the page.**
    #
    # The caller knows the tree; this function sees one step of it. When a
    # parent territory is handed in, it is the one that applies -- otherwise
    # every level of a recursive expansion would be sized for the page and
    # the deeper ones would pile into the same ball. Measured without it:
    # 162 nodes over three levels in a territory computed for 31, gap 4.7px
    # against a drawn radius of 7.1.
    if anchor_at is not None and len(anchor_at) >= 3:
        anchor = np.asarray(anchor_at[:3], dtype=np.float32)
    room = float(room) if room and room > 0 else _room_around(url, wanted, anchor)
    local = _local_positions(block, anchor, seed=0, radius=room)
    if local is not None and len(local) == len(coords):
        coords = local

    nodes = []
    for i, info in enumerate(meta):
        node = dict(info)
        node.pop("md", None)
        node.pop("covers", None)
        node["rank"] = 0.0
        node["copies"] = 1
        #: The territory this branch must stay inside, and the point it is
        #: measured from. Placement alone was not enough: the pane relaxes
        #: after placing, and a 31-branch unfolding was pushed from a
        #: 33-unit ball out to 102 units inside a 74-unit gap. The boundary
        #: has to travel with the node so the force can honour it.
        node["room"] = float(room)
        node["anchor"] = [float(v) for v in anchor]
        node["pos"] = [float(v) for v in coords[i]]
        if colours is not None:
            node["hsv"] = [float(v) for v in colours[i]]
        picture = _first_image(info.get("md") or "", url)
        if picture is not None:
            node["image"] = picture
        nodes.append(node)

    # The node being unfolded is the HUB of what comes back, and without it
    # there is nothing for a containment edge to attach to (`G-6`).
    #
    # `_edges_among` alone cannot draw one at this step, and that is a
    # property of the trie rather than a bug in it: containment runs parent
    # to child, the branches are disjoint subtrees, so every edge it finds
    # lies INSIDE one branch and is dropped as a self-edge. Measured on RFC
    # 9110: 1,072 containment edges on the page, 662 with both endpoints
    # surviving, and **0** crossing two branches. The star from the parent to
    # each branch is the containment this step actually reveals, and it is
    # the 30 edges over 31 nodes the PRD recorded before the parent started
    # being removed.
    parent_id = ("page:" + url if not prefix
                 else "path:%s#/%s" % (url, "/".join(prefix)))
    edges = [{"source": parent_id, "target": info["cid"]} for info in meta]
    edges.extend(_edges_among(workspace, url, meta))

    return {"nodes": nodes,
            "edges": edges,
            "parent": parent_id,
            "url": url,
            "path": "/" + "/".join(_segments(path)) if prefix else "",
            "depth": depth, "branches": len(branches), "leaves": len(leaves)}


def warm_placement(workspace, sample: int = 4) -> Dict:
    """Run placement once, on real chunks, and throw the answer away.

    **What this pays for, measured.** `projection.place` -- UMAP's
    `transform` into the global fit -- is slow on its first calls in a
    process and fast forever after: 1,552 ms, then 699, then 7. Placing the
    SAME chunk three times in a fresh process gave 1,662 / 11 / 12 ms, so it
    is process state and not the data; and warming on a DIFFERENT page's
    vector moved the whole cost there (1,493 ms) and left the real first
    placement at 126 ms. It is JIT compilation and the nearest-neighbour
    index being built on first use.

    Before this, the reader paid it. The profiler's "1,955 ms to place ONE
    chunk" was exactly that: the first placement after a sidecar restart.

    Real chunks rather than a synthetic vector, so every path placement
    takes is exercised -- the transform, the local fit, the reads, the edge
    query -- and warmed together. Nothing is written.
    """
    import time as _time
    projection = _ensure_projection(workspace)
    if projection is None:
        return {"warmed": False, "why": "no fit to warm"}
    cids: List[str] = []
    try:
        for chunk in workspace.store.chunks():
            if chunk.redundant:
                continue
            vec = workspace.store.embedding(chunk.cid)
            if vec and any(vec):
                cids.append(chunk.cid)
            if len(cids) >= sample:
                break
    except Exception as exc:                        # noqa: BLE001
        return {"warmed": False, "why": "%s: %s" % (type(exc).__name__, exc)}
    if not cids:
        return {"warmed": False, "why": "no chunk has a vector yet"}
    started = _time.perf_counter()
    got = place_into(workspace, cids)
    return {"warmed": True, "n": len(cids),
            "ms": round((_time.perf_counter() - started) * 1000, 1),
            "timing": got.get("timing")}


def refresh_page_layout(workspace, fitted: Dict, spherical: bool = False) -> Dict:
    """The fitted page layout, brought up to date WITHOUT refitting.

    **What refitting on every new page cost, measured.** The layout was keyed
    on a hash of the Page table, so capturing ONE page invalidated it and the
    next request refit the corpus: 14 ms -> 1,189 ms. Worse than the time, a
    fresh UMAP fit over a slightly different input put every page somewhere
    else. Adding one page moved **all 113** existing pages -- the median by
    348 units, 54% of a 643-unit cloud, the worst by more than its width. A
    reader who browsed somewhere new came back to a different map.

    So the fit is kept and the corpus is reconciled against it:

    * a page the fit placed and the store still holds keeps its fitted
      position -- the map does not move;
    * a page the store no longer holds is dropped, which is what `D-22` was
      protecting against when it keyed the cache on the page table;
    * a page the fit never saw is placed INTO it, at the transform of the
      mean of its chunks' vectors -- the same thing the fit was made of.

    The caller refits only when `stale` says the chunk corpus has doubled,
    which is the bound `Projection` was designed around: 5k, 10k, 20k.
    """
    projection = live_projection()
    held = set(workspace.pages())
    kept = [n for n in (fitted.get("nodes") or []) if n.get("url") in held]
    fitted_urls = {n.get("url") for n in kept}
    fresh = sorted(held - fitted_urls)
    space = _space_name(spherical)
    table = _PAGE_POS.setdefault(space, {})
    added = []
    if projection is not None and fresh:
        for url in fresh:
            vectors = [v for v in workspace.store.embeddings_for(url).values()
                       if v and any(v)]
            if not vectors:
                continue                  # not embedded yet; next request
            mean = np.asarray(vectors, dtype=np.float32).mean(axis=0)
            norm = float(np.linalg.norm(mean))
            where, colour = projection.place(
                (mean / norm if norm > 1e-9 else mean).reshape(1, -1))
            if where is None or not len(where):
                continue
            pos = [float(v) for v in where[0][:3]]
            table[url] = pos
            _ESTIMATED_PAGES.add(url)
            count = int(workspace.store.chunk_count(url))
            node = {"cid": "page:" + url, "url": url, "title": url,
                    "rank": 0.0, "chars": 0, "tokens": 0, "copies": 1,
                    "members": count, "level": "page",
                    "val": float(max(1.0, max(count, 1) ** 0.5)),
                    "pos": pos, "estimated": True}
            if colour is not None and len(colour):
                node["hsv"] = [float(v) for v in colour[0]]
            added.append(node)
    for n in kept:
        # Re-asserted, because an estimate written by `place_into` for a page
        # the fit DID place must not survive into an unfolding's anchor.
        if n.get("pos"):
            table[n["url"]] = [float(v) for v in n["pos"][:3]]
    nodes = kept + added
    ids = {n["cid"] for n in nodes}
    edges = [e for e in (fitted.get("edges") or [])
             if e.get("source") in ids and e.get("target") in ids]
    total = workspace.store.chunk_count()
    out = dict(fitted)
    out.update({
        "nodes": nodes, "edges": edges, "n": len(nodes),
        "fresh_pages": len(added), "dropped_pages": len(fitted.get("nodes") or []) - len(kept),
        "fitted_chunks": projection.fitted_chunks if projection else None,
        "chunks_now": total,
        "stale": bool(projection and projection.stale(total)),
    })
    return out


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
    # The chunk projector answers when it has a fit: positions are the
    # stream's, not a second computation made here.
    _cp = _live_chunk_projector()
    # The page projector places chunks too when its centroid is the chunks'
    # own space (Addendum IX); the synthetic tree only when it cannot.
    if _cp is not None and getattr(_cp, "kind", "") == "page" and not getattr(_cp, "pos", None):
        return place_tree(workspace, cids, _cp)
    if _cp is not None:
        return place_projected(workspace, cids, _cp)
    if _projector_running():
        # The projector exists but is still making its first fit. Placing
        # through the old page-mean fit here built that fit as a side effect
        # and drew chunks in a model the stream never places into.
        wanted = [c for c in dict.fromkeys(cids or []) if c]
        return {"nodes": [], "unplaced": wanted, "stale": False,
                "why": _not_fitted_why(), "source": "projector"}
    projection = _ensure_projection(workspace)
    wanted = [c for c in dict.fromkeys(cids or []) if c]
    if projection is None:
        return {"nodes": [], "unplaced": wanted, "stale": True,
                "why": "no fit to place into yet"}
    if not wanted:
        return {"nodes": [], "unplaced": [], "stale": False}

    # Placement does NOT embed, and that is the change that makes live
    # capture feel live.
    #
    # It used to call `flush_vectors` here, on the grounds that a reader
    # asking where to draw a chunk is the moment someone asked for its
    # vector. True, and it made the first drain of a page block for 13.9
    # seconds while up to 256 chunks went through the encoder -- during which
    # the pane showed nothing at all, because the answer it was waiting for
    # carried every node or none.
    #
    # So the vectors are computed by a worker and this places what is ready.
    # A chunk with no vector yet comes back in `unplaced`, which is what it
    # is, and lands in the picture on a later tick. The caller is responsible
    # for starting that worker; `layout` has no business owning a thread.
    import time as _time
    #: Every part of placement, timed on its own. The profile measured 1,955
    #: ms to place ONE dirty chunk on a 151-chunk page, and "it must be the
    #: local UMAP fit" was a hypothesis; these are what test it.
    timing: Dict[str, float] = {}
    _t = _time.perf_counter()
    rows, meta, missing = [], [], []
    # One statement for the lot when there are enough of them -- see
    # `GraphStore.chunks_for_placement` for the measured crossover.
    for cid, chunk, vector in workspace.store.chunks_for_placement(wanted):
        if chunk is None or chunk.redundant:
            # A redundant chunk is deliberately not drawn -- `G-25` -- so it
            # is not "unplaced", it is placed as the copy it is.
            continue
        if chunk.group_of and chunk.group_of != cid:
            # Likewise a member of a merge group: drawn as its lead (`G-27`),
            # not missing.
            continue
        # The same substitution the fit makes -- a group is placed by what
        # it says, not by what its first member says -- is done in the read.
        if not vector or not any(vector):
            # Captured but not yet embedded. The embedding phase is
            # asynchronous by design (the goal says so), so this is the
            # normal state for a chunk seconds old, not a failure.
            missing.append(cid)
            continue
        rows.append(vector)
        meta.append(chunk)
    timing["ms_read"] = round((_time.perf_counter() - _t) * 1000, 1)
    timing["n_wanted"] = len(wanted)
    timing["n_placeable"] = len(rows)

    nodes = []
    if rows:
        block = np.asarray(rows, dtype=np.float32)
        _t = _time.perf_counter()
        coords, colours = projection.place(block)
        timing["ms_transform"] = round((_time.perf_counter() - _t) * 1000, 1)
        if coords is None:
            return {"nodes": [], "unplaced": wanted, "stale": True,
                    "why": "the fit could not transform these"}

        # Beside their page, for the same reason an unfolding is (`D-17`'s
        # neighbour, and `_local_positions` has the numbers). Transforming a
        # chunk into a fit made of page-MEANS keeps 0.078 of its 8-NN
        # neighbourhoods against a random baseline of 0.030, so a reader
        # browsing with the sensor on watched new chunks arrive in places
        # unrelated to anything -- including to the page they had just
        # opened.
        #
        # Grouped by url, because a drain can carry chunks from more than one
        # page and each belongs at its own.
        # Whichever space has anchors; live capture has no toggle of its own
        # and follows the fit the pane last asked for.
        table: Dict[str, List[float]] = {}
        space_name = ""
        for _name, got in _PAGE_POS.items():
            if got:
                table, space_name = got, _name
                break
        by_url: Dict[str, List[int]] = {}
        for i, chunk in enumerate(meta):
            by_url.setdefault(chunk.url, []).append(i)

        # **A page the fit has never seen gets an anchor anyway.**
        #
        # `_PAGE_POS` holds only the pages that existed when the fit ran, so a
        # page captured since had no entry and was silently skipped here: its
        # chunks kept their global-transform coordinates and floated with no
        # page to hang from. Measured, `local_fits: 0` on every fresh page.
        #
        # The anchor is where the fit would put the page itself -- the
        # transform of the mean of its chunks' vectors, which is what the
        # page-level fit is made of. `unfold` already derives one this way
        # when its table has no entry; placement did not. It is written back
        # to `_PAGE_POS`, so the next placement, an unfolding and
        # `_room_around` all agree on where this page is until a refit
        # replaces the estimate with a fitted position.
        fresh_pages: Dict[str, List[float]] = {}
        if not table:
            space_name = _space_name(False)
            table = _PAGE_POS.setdefault(space_name, {})
        for page_url, idx in by_url.items():
            if table.get(page_url) is not None:
                continue
            mean = block[idx].mean(axis=0)
            norm = float(np.linalg.norm(mean))
            where, _ = projection.place(
                (mean / norm if norm > 1e-9 else mean).reshape(1, -1))
            if where is None or not len(where):
                continue
            table[page_url] = [float(v) for v in where[0][:3]]
            _ESTIMATED_PAGES.add(page_url)
            fresh_pages[page_url] = table[page_url]
        timing["fresh_pages"] = len(fresh_pages)
        _t = _time.perf_counter()
        timing["local_fits"] = 0
        timing["local_rows"] = 0
        for page_url, idx in by_url.items():
            if table.get(page_url) is None:
                continue                    # the transform could not place it
            anchor = np.asarray(table[page_url][:3], dtype=np.float32)
            timing["local_fits"] += 1
            timing["local_rows"] += len(idx)
            # The same territory an unfolding gets, for the same reason: a
            # chunk arriving from a live scan belongs inside its page, not
            # 90 units away on top of the page next to it.
            local = _local_positions(
                block[idx], anchor, seed=0,
                radius=_room_around(page_url, space_name, anchor))
            if local is not None and len(local) == len(idx):
                for slot, row in zip(idx, local):
                    coords[slot] = row
        for i, chunk in enumerate(meta):
            node = {
                "cid": chunk.cid,
                "url": chunk.url,
                "title": _title(chunk.md),
                "rank": 0.0,
                "chars": chunk.chars,
                "tokens": tokens.budget(chunk.md or ""),
                "copies": chunk.dup_n,
                "members": chunk.group_n,
                #: In the page node's unit -- how many chunks it stands for
                #: -- not `sqrt(chars)`. Without this the pane fell back to
                #: character count and a live-captured chunk drew at a world
                #: radius of 17.2 against a median PAGE at 11.4: the second
                #: layer covering the first instead of nesting inside it.
                "val": float(max(1.0, max(chunk.group_n, 1) ** 0.5)),
                "level": "chunk",
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
            #: The territory, as `unfold` sends it, so a placed chunk is
            #: bound the same way a branch is. Without it a live capture's
            #: chunks were the only nodes in the picture free to wander.
            room_for = _PAGE_POS.get(space_name) or {}
            at = room_for.get(chunk.url)
            if at and len(at) >= 3:
                node["anchor"] = [float(v) for v in at[:3]]
                node["room"] = float(
                    _room_around(chunk.url, space_name,
                                 np.asarray(at[:3], dtype=np.float32)))

        timing["ms_local"] = round((_time.perf_counter() - _t) * 1000, 1)

    # **And the page itself, as a node.** A fresh page's chunks now land
    # beside an anchor, but the anchor is only a coordinate; with no node
    # there the chunks cluster around empty space and the reader cannot see
    # which page they came from, or click it. Sized in the page level's own
    # unit -- sqrt of the chunks it holds -- so it nests like any other page.
    page_nodes = []
    if rows:
        hubs = dict(fresh_pages)
        for page_url in by_url:
            if page_url in _ESTIMATED_PAGES and table.get(page_url) is not None:
                hubs.setdefault(page_url, table[page_url])
        for page_url, at in hubs.items():
            held = workspace.store.chunk_count(page_url) if hasattr(
                workspace.store, "chunk_count") else len(by_url.get(page_url, []))
            try:
                held = int(held)
            except Exception:                       # noqa: BLE001
                held = len(by_url.get(page_url, []))
            page_nodes.append({
                "cid": "page:" + page_url, "url": page_url,
                "title": page_url, "level": "page", "rank": 0.0,
                "chars": 0, "tokens": 0, "copies": 1,
                "members": held, "val": float(max(1.0, max(held, 1) ** 0.5)),
                "pos": [float(v) for v in at],
                #: Where this position came from, so a reader can tell an
                #: estimate from a fit.
                "estimated": True,
            })
        nodes.extend(page_nodes)

    # A count, not the chunks. See `GraphStore.chunk_count`.
    # The containment edges among what was just placed (`G-6`). Chunks
    # arriving from a capture or a scoped ranking had none, so they drew as
    # loose dots with the structure the trie holds left undrawn.
    _t = _time.perf_counter()
    placed_edges: List[Dict] = []
    drawn = {n["cid"] for n in nodes}
    has_parent = set()
    for page in {n["url"] for n in nodes}:
        for a, b in workspace.store.contains_within(page, among=drawn):
            if a in drawn and b in drawn and a != b:
                placed_edges.append({"source": a, "target": b})
                has_parent.add(b)
    # A fresh page node hangs only the chunks with no parent among what was
    # drawn -- the roots -- so the result is the trie's own tree under the
    # page, not a star from the page to every chunk. A star is what the
    # reader rejected when they said an expansion was "not a DAG".
    for pn in page_nodes:
        for n in nodes:
            if (n.get("url") == pn["url"] and n.get("level") != "page"
                    and n["cid"] not in has_parent):
                placed_edges.append({"source": pn["cid"], "target": n["cid"]})

    timing["ms_edges"] = round((_time.perf_counter() - _t) * 1000, 1)
    total = workspace.store.chunk_count()
    return {"timing": timing,
            "nodes": nodes, "edges": placed_edges, "unplaced": missing,
            "stale": projection.stale(total),
            "fitted_n": projection.fitted_n,
            #: The pair `stale` is actually decided on, so a reader of this
            #: reply can check the verdict instead of trusting it.
            "fitted_chunks": projection.fitted_chunks, "n": total}


# ---------------------------------------------------------------------------
# The chunk projector's answers, in the shapes the pane already reads.
#
# `projector.ChunkProjector` holds one fit over every drawable chunk and the
# position the stream last gave each of them. Everything below reads those
# positions and assembles nodes; none of it fits, relaxes or re-places
# anything, so what the pane draws is exactly what the projector computed.
# ---------------------------------------------------------------------------

def _live_chunk_projector():
    """The sidecar's projector, if it has a fit to answer from."""
    from .projector import projector as _get
    got = _get()
    return got if got is not None and got.projection is not None else None


def _projector_running() -> bool:
    """A projector exists in this process, fitted or not."""
    from .projector import projector as _get
    return _get() is not None


def _page_pictures(workspace, urls=None) -> Dict[str, Dict]:
    """Each page's first picture, read from the chunks that have one."""
    out: Dict[str, Dict] = {}
    try:
        rows = workspace.store._rows(
            "MATCH (c:Chunk) WHERE c.md CONTAINS '![' "
            "RETURN c.url, c.xpath, c.part, c.md")
    except Exception:                               # noqa: BLE001
        return out
    for url, _x, _p, md in sorted(rows, key=lambda r: (r[0] or "", r[1] or "",
                                                       r[2] or 0)):
        if not url or url in out or (urls is not None and url not in urls):
            continue
        found = _first_image(md or "", url)
        if found is not None:
            out[url] = found
    return out


#: `_page_headings`' answer, keyed on the pages asked about and the chunk count.
_HEADING_MEMO: Dict = {}


def _page_headings(workspace, urls) -> Dict[str, str]:
    """Each page's first markdown heading, for pages with no stored title.

    **A label, not a title.** 121 of 130 pages lost their titles to a write
    path that blanked them on every drain (fixed; titles come back as pages
    are visited). Until then the graph labelled them with their urls. The
    first heading is what the page says it is about, read from the page's own
    chunks in document order -- and every node that uses it says so
    (`title_source: "heading"`), so it is never passed off as the title.
    """
    import re
    urls = set(urls)
    if not urls:
        return {}
    key = (frozenset(urls), workspace.store.chunk_count())
    if _HEADING_MEMO.get("key") == key:
        return _HEADING_MEMO["value"]
    # Indented: the markdown carries the page's structure as indentation, so
    # a heading is rarely at column 0. The page's H1 is its name; a first
    # H2 in document order is usually a sidebar's ("Contents").
    h1 = re.compile(r"^[ \t]*#[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
    heading = re.compile(r"^[ \t]*#{2,3}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
    link = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
    rows = workspace.store._rows(
        "MATCH (c:Chunk) WHERE list_contains($urls, c.url) AND c.md CONTAINS '#' "
        "RETURN c.url, c.xpath, c.part, c.md", {"urls": sorted(urls)})
    out: Dict[str, str] = {}
    fallback: Dict[str, str] = {}
    for url, _x, _p, md in sorted(rows, key=lambda r: (r[0] or "", r[1] or "",
                                                       r[2] or 0)):
        if url in out:
            continue
        for pattern, into in ((h1, out), (heading, fallback)):
            if url in into:
                continue
            m = pattern.search(md or "")
            if m:
                text = link.sub(lambda g: g.group(1), m.group(1)).strip(" *_`")
                if text:
                    into[url] = text[:120]
    for url, text in fallback.items():
        out.setdefault(url, text)
    _HEADING_MEMO.update(key=key, value=out)
    return out


def projected_page_layout(workspace, proj=None) -> Optional[Dict]:
    """Every page, at the chunk projector's position for it (`G-53`).

    Pages are the default view for the frame rate (94 draw calls, not
    12,820), but they are no longer a separate fit: each page sits at the
    transform of its chunks' mean vector INTO THE CHUNK FIT, so a page and
    the chunks it unfolds into are placed by the same model.
    """
    proj = proj or _live_chunk_projector()
    if proj is None:
        return None
    with proj.lock:
        page_pos = dict(proj.page_pos)
        page_hsv = dict(proj.page_hsv)
        counts = {u: len(cs) for u, cs in proj.by_url.items()}
        epoch, seq = proj.epoch, proj.seq
    titles = workspace.store.page_titles()
    held: Dict[str, int] = {}
    try:
        for url, n in workspace.store._rows(
                "MATCH (p:Page)-[:HasChunk]->(c:Chunk) RETURN p.url, count(c)"):
            held[url] = int(n)
    except Exception:                               # noqa: BLE001
        held = dict(counts)
    pictures = _page_pictures(workspace, set(page_pos))
    headings = _page_headings(
        workspace, [u for u in page_pos if not titles.get(u)])
    here = _PAGE_POS.setdefault(_space_name(False), {})
    here.clear()
    _ESTIMATED_PAGES.clear()
    nodes = []
    for url in sorted(page_pos):
        at = page_pos[url]
        here[url] = [float(v) for v in at[:3]]
        members = held.get(url, counts.get(url, 0))
        node = {
            "cid": "page:" + url, "url": url,
            "title": titles.get(url) or headings.get(url) or url,
            #: Where the label came from: the page's stored title, its first
            #: heading (the title was lost; see `_page_headings`), or the url.
            "title_source": ("title" if titles.get(url) else
                             "heading" if headings.get(url) else "url"),
            "rank": 0.0, "chars": 0,
            "tokens": 0, "copies": 1, "members": members, "level": "page",
            "val": float(max(1.0, max(members, 1) ** 0.5)),
            "pos": [float(v) for v in at[:3]],
            #: How many of this page's chunks the projector holds a position
            #: for -- "is all of it in the map", per page.
            "projected": counts.get(url, 0),
            "source": "projector",
        }
        if url in page_hsv:
            node["hsv"] = page_hsv[url]
        if url in pictures:
            node["image"] = pictures[url]
        nodes.append(node)
    known = {n["url"] for n in nodes}
    edges = [{"source": "page:" + s, "target": "page:" + t}
             for s, t in workspace.store.page_links()
             if s in known and t in known and s != t]
    # Code pages hang in their DIRECTORY tree (G-104): module -> its folder's
    # package -> the package above. With the import links above, the
    # dependencies from variable to module to directory.
    if not PLANT_NO_CODE_TREE[0]:
        from ..packages import code_tree_edges
        for child, parent in code_tree_edges(u for u in known if u.startswith("code://")):
            edges.append({"source": "page:" + child, "target": "page:" + parent, "kind": "dir"})
    coords = (np.asarray([n["pos"] for n in nodes], dtype=np.float32)
              if nodes else np.zeros((0, 3), dtype=np.float32))
    status = proj.status(workspace)
    return {
        "nodes": nodes, "edges": edges, "spaces": ["semantic"],
        "space": "euclidean", "n": len(nodes), "level": "page", "dims": 3,
        "hsv": bool(page_hsv), "fitted_dims": 3,
        "chunks": sum(held.values()), "fitted_on": {"semantic": True},
        "spacing": _spacing(coords, 3) if len(coords) else None,
        "images": sum(1 for n in nodes if n.get("image")),
        "source": "projector", "epoch": epoch, "seq": seq,
        "projector": status,
        "fitted_chunks": status.get("fitted_chunks"),
        "chunks_now": status.get("chunks_now"),
        "stale": False, "from_store": False,
    }


def projected_chunk_layout(workspace, proj=None) -> Optional[Dict]:
    """Every drawable chunk at its projector position (`?level=chunk`)."""
    proj = proj or _live_chunk_projector()
    if proj is None:
        return None
    with proj.lock:
        pos = dict(proj.pos)
        hsv = dict(proj.hsv)
        epoch, seq = proj.epoch, proj.seq
    import time as _time
    timing: Dict[str, float] = {}
    _t = _time.perf_counter()
    # Without the markdown first: a chunk's title, picture and token count are
    # functions of its markdown, kept per (cid, chars) -- read for EVERY chunk
    # on every switch, and tokenized, they were most of a 30 s chunk-view
    # layout (2026-10-12). Only the chunks not yet kept are read in full.
    rows = workspace.store._rows(
        "MATCH (c:Chunk) RETURN c.cid, c.url, c.chars, c.group_n, c.dup_n, c.drawn")
    timing["ms_rows"] = round((_time.perf_counter() - _t) * 1000, 1)
    _t = _time.perf_counter()
    memo = _CHUNK_FACTS
    from ..graphstore import CHUNK_WRITES
    want = [cid for cid, _u, chars, *_r in rows
            if cid in pos and (PLANT_NO_FACT_MEMO[0]
                               or memo.get(cid, (None,))[0] != (int(chars or 0), CHUNK_WRITES.get(cid, 0)))]
    for i in range(0, len(want), 2000):
        part = want[i:i + 2000]
        for cid, url, md, chars in workspace.store._rows(
                "MATCH (c:Chunk) WHERE c.cid IN $cs RETURN c.cid, c.url, c.md, c.chars", {"cs": part}):
            md = md or ""
            memo[cid] = ((int(chars or 0), CHUNK_WRITES.get(cid, 0)), _title(md), tokens.budget(md), _first_image(md, url or ""))
    timing["ms_facts"] = round((_time.perf_counter() - _t) * 1000, 1)
    timing["facts_read"] = len(want)
    _t = _time.perf_counter()
    nodes = []
    kept_drawn = stale_drawn = 0
    for cid, url, chars, group_n, dup_n, drawn in rows:
        at = pos.get(cid)
        if at is None:
            continue
        _c, title, n_tokens, picture = memo.get(cid, (0, "", 0, None))
        # The place chunk view drew it last, kept on the chunk (PLUGIN_GOAL
        # 108) -- only while the fit still puts the chunk where it was drawn
        # FROM; a chunk the projector has moved since is relaxed again.
        placed = None
        if drawn is not None and len(drawn) >= 6 and not PLANT_NO_DRAWN[0]:
            if max(abs(float(drawn[3 + i]) - float(at[i])) for i in range(min(3, len(at)))) < 1e-3:
                placed = [float(v) for v in drawn[:3]]
                kept_drawn += 1
            else:
                stale_drawn += 1
        members = int(group_n or 1)
        node = {"cid": cid, "url": url, "title": title,
                "rank": 0.0, "chars": int(chars or 0),
                # How many identical renderings this node stands for (`G-25`).
                # It was a constant 1 here, so the one node per distinct
                # rendering never said it was one of several.
                "tokens": n_tokens,
                "copies": int(dup_n or 1),
                "members": members, "level": "chunk",
                "val": float(max(1.0, max(members, 1) ** 0.5)),
                "pos": at, "source": "projector"}
        if placed is not None:
            node["drawn"] = placed
            if len(drawn) >= 7:
                node["drawn_half"] = float(drawn[6])
        if cid in hsv:
            node["hsv"] = hsv[cid]
        if picture is not None:
            node["image"] = picture
        nodes.append(node)
    timing["ms_nodes"] = round((_time.perf_counter() - _t) * 1000, 1)
    _t = _time.perf_counter()
    drawn = {n["cid"] for n in nodes}
    edges = []
    for page in {n["url"] for n in nodes}:
        for a, b in workspace.store.contains_within(page, among=drawn):
            if a in drawn and b in drawn and a != b:
                edges.append({"source": a, "target": b})
    timing["ms_edges"] = round((_time.perf_counter() - _t) * 1000, 1)
    status = proj.status(workspace)
    return {"nodes": nodes, "edges": edges, "spaces": ["semantic"],
            "space": "euclidean", "n": len(nodes), "level": "chunk",
            "dims": 3, "hsv": bool(hsv), "fitted_dims": 3,
            "chunks": status.get("chunks_now"),
            "fitted_on": {"semantic": True}, "source": "projector",
            "epoch": epoch, "seq": seq, "projector": status,
            "images": sum(1 for n in nodes if n.get("image")),
            "drawn_kept": kept_drawn, "drawn_stale": stale_drawn, "timing": timing,
            "stale": False, "from_store": False}


#: Each chunk's title, token count and first picture, by cid, with the
#: `chars` they were read at (PLUGIN_GOAL 110): functions of its markdown.
_CHUNK_FACTS: Dict[str, tuple] = {}
#: Planted: every chunk's markdown read and tokenized on every layout.
PLANT_NO_FACT_MEMO = [False]


#: Planted (G-104): code pages drawn with no directory tree.
PLANT_NO_CODE_TREE = [False]


#: Planted (PLUGIN_GOAL 108): stored drawn places ignored -- chunk view
#: relaxes from the fit on every switch, as before.
PLANT_NO_DRAWN = [False]


def place_projected(workspace, cids, proj) -> Dict:
    """`place_into`, answered from the chunk projector.

    A chunk the stream has already placed is drawn where the stream put it.
    One it has not reached yet -- embedded a moment ago, still in the queue --
    is transformed here, into the same fit, and queued so the stream's own
    record catches up. Nothing is moved to sit beside its page: the page sits
    where the fit puts what it means, and so do its chunks.
    """
    import time as _time
    timing: Dict[str, float] = {}
    wanted = [c for c in dict.fromkeys(cids or []) if c]
    if not wanted:
        return {"nodes": [], "unplaced": [], "stale": False, "timing": timing,
                "source": "projector"}
    _t = _time.perf_counter()
    rows, meta, missing = [], [], []
    # A chunk drawn THROUGH another -- a duplicate (`dup_of`) or a merge
    # group's member (`group_of`) -- is never a node of its own: it is said
    # so (`aliases`) and the one that draws it is placed instead. Skipped in
    # silence, a pin on such a chunk found no node and opened no billboard
    # (G-82, 2026-10-12: 2 pins, 1 billboard).
    aliases: Dict[str, str] = {}
    # `unknown`: the store holds no such chunk -- retired by a re-cut, say --
    # as against `unplaced`, a chunk not embedded YET. A pin on an unknown
    # cid waited out 40 retries (25 s) for a vector that could never come
    # before the browser re-anchored it by address (G-82, 2026-10-17).
    held_cids: set = set()

    def _take(batch):
        for cid, chunk, vector in workspace.store.chunks_for_placement(batch):
            if chunk is None:
                continue
            held_cids.add(cid)
            if chunk.redundant or (chunk.group_of and chunk.group_of != cid):
                aliases[cid] = chunk.dup_of if chunk.redundant else chunk.group_of
                continue
            if not vector or not any(vector):
                missing.append(cid)
                continue
            if any(m.cid == cid for m in meta):
                continue
            rows.append(vector)
            meta.append(chunk)

    _take(wanted)
    extra = [t for t in dict.fromkeys(aliases.values()) if t and t not in wanted]
    if extra:
        _take(extra)
    timing["ms_read"] = round((_time.perf_counter() - _t) * 1000, 1)
    timing["n_wanted"] = len(wanted)
    timing["n_placeable"] = len(rows)

    with proj.lock:
        known = {m.cid: proj.pos.get(m.cid) for m in meta}
        known_hsv = {m.cid: proj.hsv.get(m.cid) for m in meta}
        page_at = dict(proj.page_pos)
        page_hsv = dict(proj.page_hsv)
        projection = proj.projection
    fresh = [i for i, m in enumerate(meta) if known.get(m.cid) is None]
    timing["from_stream"] = len(meta) - len(fresh)
    timing["transformed_here"] = len(fresh)
    _t = _time.perf_counter()
    if fresh:
        where, colour = projection.place(
            np.asarray([rows[i] for i in fresh], dtype=np.float32))
        if where is not None:
            for j, i in enumerate(fresh):
                known[meta[i].cid] = [float(v) for v in where[j][:3]]
                if colour is not None:
                    known_hsv[meta[i].cid] = [float(v) for v in colour[j]]
        proj.enqueue(meta[i].cid for i in fresh)
    timing["ms_transform"] = round((_time.perf_counter() - _t) * 1000, 1)

    nodes = []
    for chunk in meta:
        at = known.get(chunk.cid)
        if at is None:
            missing.append(chunk.cid)
            continue
        node = {
            "cid": chunk.cid, "url": chunk.url, "title": _title(chunk.md),
            "rank": 0.0, "chars": chunk.chars,
            "tokens": tokens.budget(chunk.md or ""),
            "copies": chunk.dup_n, "members": chunk.group_n,
            "val": float(max(1.0, max(chunk.group_n, 1) ** 0.5)),
            "level": "chunk", "pos": [float(v) for v in at], "placed": True,
            "source": "projector",
        }
        if known_hsv.get(chunk.cid):
            node["hsv"] = known_hsv[chunk.cid]
        picture = _first_image(chunk.md, chunk.url)
        if picture is not None:
            node["image"] = picture
        nodes.append(node)

    # Every page these chunks hang from, as a node at the projector's own
    # position for it. The pane ignores a node it already has; a page it has
    # never drawn (browsed after the layout was fetched) gets its hub here.
    page_nodes = []
    for url in sorted({m.url for m in meta}):
        at = page_at.get(url)
        if at is None:
            continue
        held = int(workspace.store.chunk_count(url))
        pn = {"cid": "page:" + url, "url": url, "title": url, "level": "page",
              "rank": 0.0, "chars": 0, "tokens": 0, "copies": 1,
              "members": held, "val": float(max(1.0, max(held, 1) ** 0.5)),
              "pos": [float(v) for v in at[:3]], "source": "projector"}
        if url in page_hsv:
            pn["hsv"] = page_hsv[url]
        page_nodes.append(pn)
    nodes.extend(page_nodes)

    _t = _time.perf_counter()
    placed_edges: List[Dict] = []
    drawn = {n["cid"] for n in nodes}
    has_parent = set()
    for page in {n["url"] for n in nodes}:
        for a, b in workspace.store.contains_within(page, among=drawn):
            if a in drawn and b in drawn and a != b:
                placed_edges.append({"source": a, "target": b})
                has_parent.add(b)
    for pn in page_nodes:
        for n in nodes:
            if (n.get("url") == pn["url"] and n.get("level") != "page"
                    and n["cid"] not in has_parent):
                placed_edges.append({"source": pn["cid"], "target": n["cid"]})
    timing["ms_edges"] = round((_time.perf_counter() - _t) * 1000, 1)
    status = proj.status(workspace)
    return {"timing": timing, "nodes": nodes, "edges": placed_edges, "aliases": aliases,
            "unplaced": missing, "unknown": [c for c in wanted if c not in held_cids],
            "stale": False, "source": "projector",
            "epoch": status["epoch"], "seq": status["seq"],
            "fitted_n": status.get("fit_sample"),
            "fitted_chunks": status.get("fitted_chunks"),
            "n": status.get("chunks_now")}


# ---------------------------------------------------------------------------
# Addendum VII: a page's whole patricia TREE, in one reply.
# ---------------------------------------------------------------------------

def page_tree(workspace, url: str, proj=None) -> Dict:
    """Every drawable chunk of a page, hung on the patricia tree of its DOM.

    **A tree, not a trie's index.** The reader's words: the structure wanted is
    "the subtree of all the content nodes detected in the full shadow DOM
    tree", with "intermediate path nodes, if they go from one root to one
    leaf, as a single link". So a DOM path becomes a node here only where it
    BRANCHES -- two or more children, counting the chunks rooted exactly there
    -- and every single-child chain between two such points is one link. Each
    chunk hangs from its nearest branch; each branch from its nearest branch
    above; the page is the root. Every node has exactly one parent, by
    construction, so the layout can fan it out instead of pinning it into
    the triangles a multi-parent graph forms.

    What it replaces: one patricia STEP per click (`G-54`), where a click
    showed one level of branches and drew a star from their parent to each
    and containment edges among them -- the lattices the reader saw. A page
    now opens whole, once, and closes whole.

    Positions: every node starts at the page's UMAP position (the pane's
    force layout spreads the tree around it); the page is where the projector
    put its centroid.
    """
    proj = proj or _live_chunk_projector()
    at = None
    if proj is not None:
        at = proj.page_pos.get(url)
    stored = [c for c in workspace.store.chunks(url)
              if not c.redundant and not (c.group_of and c.group_of != c.cid)]
    if not stored:
        return {"url": url, "nodes": [], "edges": [], "why": "no chunks stored for this page"}
    at = [float(v) for v in (at or [0.0, 0.0, 0.0])[:3]]

    # The trie over xpath segments: which prefixes branch, which hold chunks.
    kids: Dict[tuple, set] = {(): set()}
    held: Dict[tuple, List] = {}
    for chunk in stored:
        parts = tuple(_segments(chunk.xpath))
        for i in range(len(parts)):
            kids.setdefault(parts[:i], set()).add(parts[:i + 1])
            kids.setdefault(parts[:i + 1], set())
        held.setdefault(parts, []).append(chunk)

    def branches(prefix: tuple) -> bool:
        return prefix == () or len(kids.get(prefix, ())) + len(held.get(prefix, ())) >= 2

    def up(prefix: tuple) -> tuple:
        """The nearest drawn node at or above `prefix`."""
        p = prefix
        while not branches(p):
            p = p[:-1]
        return p

    page_id = "page:" + url

    def nid(prefix: tuple) -> str:
        return page_id if prefix == () else "path:%s#/%s" % (url, "/".join(prefix))

    # Subtree sizes and first pictures, for sizing and billboarding branches.
    below: Dict[tuple, List] = {}
    for prefix, chunks in held.items():
        p = prefix
        while True:
            below.setdefault(p, []).extend(chunks)
            if p == ():
                break
            p = p[:-1]

    nodes: List[Dict] = []
    edges: List[Dict] = []
    drawn = sorted(p for p in kids if branches(p) and p != ())
    for prefix in drawn:
        members = below.get(prefix, [])
        node = {
            "cid": nid(prefix), "url": url, "level": "path",
            "path": "/" + "/".join(prefix),
            "title": _title(_first_md_with_image(members)) or prefix[-1],
            "members": len(members), "rank": 0.0, "chars": 0, "tokens": 0,
            "copies": 1, "val": float(max(1.0, len(members) ** 0.5)),
            "pos": list(at), "source": "tree",
        }
        picture = _first_image(_first_md_with_image(members), url)
        if picture is not None:
            node["image"] = picture
        nodes.append(node)
        edges.append({"source": nid(up(prefix[:-1])), "target": node["cid"]})
    for chunk in sorted(stored, key=lambda c: (c.xpath, c.part)):
        parts = tuple(_segments(chunk.xpath))
        node = {
            "cid": chunk.cid, "url": url, "level": "chunk", "path": chunk.xpath,
            "title": _title(chunk.md), "members": chunk.group_n, "rank": 0.0,
            "chars": chunk.chars, "tokens": tokens.budget(chunk.md or ""),
            "copies": chunk.dup_n, "val": float(max(1.0, max(chunk.group_n, 1) ** 0.5)),
            "pos": list(at), "source": "tree",
        }
        picture = _first_image(chunk.md, url)
        if picture is not None:
            node["image"] = picture
        nodes.append(node)
        edges.append({"source": nid(up(parts)), "target": chunk.cid})

    parents: Dict[str, int] = {}
    for e in edges:
        parents[e["target"]] = parents.get(e["target"], 0) + 1
    return {
        "url": url, "root": page_id, "page_pos": at,
        "nodes": nodes, "edges": edges,
        "chunks": len(stored), "branches": len(drawn),
        #: Checked, not assumed: a tree has one parent per node.
        "max_parents": max(parents.values()) if parents else 0,
        "depth": max((len(p) for p in drawn), default=0),
    }


def place_tree(workspace, cids, proj) -> Dict:
    """Place chunks from a live capture ON THEIR PAGE'S TREE (Addendum VII).

    Each requested chunk comes back with every ancestor it needs in the
    page's patricia tree and the page node, and only the edges among those --
    so a chunk streamed in by a drain arrives attached to its branch, the
    same parent it has when the whole page is opened.
    """
    import time as _time
    t0 = _time.perf_counter()
    wanted = [c for c in dict.fromkeys(cids or []) if c]
    by_url: Dict[str, List[str]] = {}
    for cid, chunk, _vector in workspace.store.chunks_for_placement(wanted):
        if chunk is not None and not chunk.redundant and not (
                chunk.group_of and chunk.group_of != cid):
            by_url.setdefault(chunk.url, []).append(cid)
    nodes, edges = [], []
    for url, mine in by_url.items():
        tree = page_tree(workspace, url, proj)
        parent = {e["target"]: e["source"] for e in tree["edges"]}
        keep = set()
        for cid in mine:
            n = cid
            while n in parent and n not in keep:
                keep.add(n)
                n = parent[n]
        keep.add("page:" + url)
        nodes.extend(n for n in tree["nodes"] if n["cid"] in keep)
        at = proj.page_pos.get(url)
        if at is not None:
            nodes.append({"cid": "page:" + url, "url": url, "title": url,
                          "level": "page", "rank": 0.0, "chars": 0, "tokens": 0,
                          "copies": 1, "members": tree.get("chunks", 0),
                          "val": float(max(1.0, max(tree.get("chunks", 1), 1) ** 0.5)),
                          "pos": [float(v) for v in at[:3]], "source": "projector"})
        edges.extend(e for e in tree["edges"] if e["target"] in keep and e["source"] in keep)
    placed = {n["cid"] for n in nodes}
    return {"nodes": nodes, "edges": edges, "source": "tree",
            "unplaced": [c for c in wanted if c not in placed],
            "stale": False, "timing": {"ms": round((_time.perf_counter() - t0) * 1000, 1),
                                       "n_wanted": len(wanted)}}
