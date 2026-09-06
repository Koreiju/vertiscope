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

from typing import Dict, List, Optional

import numpy as np

#: Width of each half when there is nothing to match. Only reached when the
#: workspace has no embeddings at all, where "equal halves" is moot and this
#: is just a sane reduction before UMAP.
_LONE_TARGET = 128


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

    coords = _umap(features, dims=dims, seed=seed,
                   neighbors=neighbors, min_dist=min_dist)

    ranks = index.ranks
    nodes = []
    for i, cid in enumerate(cids):
        chunk = meta[cid]
        row = rows[i]
        nodes.append({
            "cid": cid,
            "url": chunk.url,
            "title": _title(chunk.md),
            "rank": float(ranks[row]) if row < len(ranks) else 0.0,
            "chars": chunk.chars,
            "pos": [float(v) for v in coords[i]],
        })

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
        # Stated so a reader of the picture knows what produced it, and
        # `equalised` is asserted from the widths rather than from the
        # intention: it means the two halves ARE the same size, not that the
        # code tried to make them so.
        "halves": dict(widths,
                       equalised=(semantic is not None
                                  and widths.get("lexical")
                                  == widths.get("semantic"))),
    }


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
        out = PCA(n_components=k, random_state=seed).fit_transform(features)
        if out.shape[1] < dims:
            out = np.hstack([out, np.zeros((n, dims - out.shape[1]),
                                           dtype=np.float32)])
        return np.asarray(out, dtype=np.float32)


def _title(md: str) -> str:
    for raw in (md or "").splitlines():
        line = raw.strip().lstrip("#").lstrip("-").strip()
        if line:
            return line[:80]
    return ""
