"""Stage two of chunking: merge what is the same thing said differently.

`G-26`..`G-33`. Stage one cuts a page by recursive descent to a window counted
in link-free text, and that window is a *staging* device rather than a ceiling
-- 256 because it wins on hit@1, chosen to be a strict subset of the display
context so that this stage has room to merge back up toward 512.

`G-24` already resolved the other kind of repetition: byte-identical
renderings at different addresses, decided in the database with no threshold
and no embedding. This is the case that arm cannot reach -- two chunks that
say the same thing in different words, or two halves of one thought the
descent had to cut because a token budget ran out mid-idea.

**Localised to one page, and that is the design, not a shortcut.** The goal is
coarse-to-fine over a shadow DOM; a corpus-wide clustering would merge a
paragraph on one site with a paragraph on another and call it a chunk of
nothing. Every decision here is scoped to a single url.

**Quantized semantic embeddings only.** The frequency matrix is not dimension
efficient and exists for fine-grained preservation in retrieval; it is not
what a merge should be decided on. It has a job here and it comes second --
see `verify_with_lexical`.

**The threshold is relative, because a constant is a claim about a corpus.**
Pages differ enormously in how tightly their chunks cluster: a reference table
of CSS properties is a hundred near-identical rows, a blog post is a dozen
unrelated paragraphs. An absolute cosine radius that merges sensibly on one
of those destroys the other. So the radius is read off the page's own
distribution of nearest-neighbour distances -- "within this percent distance
of the closest neighbour compared to the max of the closest neighbour
distances" -- which makes it a property of the page, the same way
`nodeRelSize` is a property of the fit and `_content_boundary` self-normalises
to the window.

**A significance gate, because a distribution needs points to have a shape.**
Under `MIN_CHUNKS` the nearest-neighbour distances are too few for their
maximum to mean anything, and the radius they imply is noise. Such a page is
left alone and says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import tokens

#: How close, as a fraction of the page's LARGEST nearest-neighbour distance,
#: two chunks must be before they may merge.
#:
#: The user's formulation: "within this percent distance of the closest
#: neighbour compared to the max of the closest neighbour distances". The max
#: is the page's own worst case -- the most isolated chunk on it -- so the
#: radius scales with how spread out that particular document is.
#:
#: 0.35 is a starting point and is meant to be swept, not defended. It is
#: exported so an experiment can move it without editing this module.
EPS_FRACTION = 0.35

#: How much tighter the page's closest pairs must be than its typical pair
#: before the page is considered to HAVE structure (`G-32`).
#:
#: The radius alone is not enough, and the tests are what showed it. Scaling
#: by `max(nn)` makes the threshold a single order statistic -- the most
#: outlier-sensitive number in the sample -- and it fails in both directions:
#:
#:   * 120 points of pure noise on a sphere have nn_max 0.578 and nn_median
#:     0.399, so a radius of 0.35 x max is 0.202, and two random pairs
#:     happened to fall inside it. Two merges, found in noise.
#:   * 30 points in five tight blobs have nn_max 0.0015, so the radius is
#:     0.0005 -- tighter than the blobs themselves -- and nothing merged at
#:     all on a page that is nothing but clusters.
#:
#: What separates those from a real page is the SHAPE of the distribution, not
#: its scale. A page with clusters has a low tail: its closest pairs are far
#: closer than its typical pair. A page without them does not, whether its
#: distances are all large (noise) or all small (uniform blobs). So the gate
#: compares the tenth percentile against the ninetieth, which is scale-free
#: and robust, and it is what "statistically significant discriminative value"
#: means for this decision.
#:
#: 0.25 is a JUDGMENT, and the corpus says so. On synthetic data the two
#: populations are three hundred times apart -- clusters at 0.001,
#: dimension-shuffled noise at 0.48 -- and it is tempting to report a clean
#: separation with a wide margin. Real pages do not oblige. Measured over 39
#: pages of `build/vaultws256`, the ratio is a continuum with no empty band:
#:
#:   0.000 archive.org/search      0.135 ar.wikipedia     0.202 books page-2
#:   0.013 discourse/latest        0.170 MDN HTML         0.260 duckduckgo
#:   0.049 arxiv cs.IR             0.197 MDN CSS          0.365 commons
#:   ...                                                  0.778 danluu
#:
#: and the synthetic null's 0.4755 sits in the middle of that range, between
#: de.wikipedia and archive.org/details. So this threshold does not separate
#: signal from noise on real pages; it says how much repetition a page must
#: have before merging is attempted at all. At 0.25 it accepts the ten pages
#: whose repetition is pronounced -- search results, forum listings, reference
#: indexes -- and declines blog posts and article pages, which is the right
#: shape of answer even though the line inside it is drawn by hand.
#:
#: What keeps spurious merges out is NOT this gate. The null arm finds zero
#: groups on real pages at 0.5 as well as at 0.25; the discriminator is the
#: radius and the per-group spread. This gate decides where the method is
#: worth running, and it is meant to be swept against retrieval, not defended.
STRUCTURE_RATIO = 0.25

#: Below this many chunks a page is not clustered at all (`G-32`).
#:
#: Not a performance guard. With nine chunks there are nine nearest-neighbour
#: distances, their maximum is one observation, and a radius derived from it
#: is a radius derived from one number. The gate is where the statistic starts
#: to describe something.
MIN_CHUNKS = 24

#: The token budget a merged chunk may not exceed, in the same unit everything
#: else is counted in -- link-free markdown (`tokens.budget`).
#:
#: 512 is the display context the goal names. Stage one's 256 is deliberately
#: half of it, so that a merge of two neighbours is the common case and fits
#: by construction.
MERGE_WINDOW = 512

#: How many members a merge may have. A cluster of forty near-identical table
#: rows is a real finding, and it is a finding about the PAGE -- rendering it
#: as one chunk would produce something no reader asked for. Past this the
#: cluster is reported and not merged.
MAX_MEMBERS = 8


@dataclass
class Group:
    """One merged chunk: the cids it is made of, in document order."""

    lead: str
    members: List[str]
    tokens: int
    #: The tightest and loosest pairwise distance inside the group, so a
    #: reader of the result can see how confident the merge was.
    spread: Tuple[float, float] = (0.0, 0.0)


@dataclass
class Aggregation:
    """What stage two decided about one page."""

    url: str
    groups: List[Group] = field(default_factory=list)
    #: Chunks left exactly as they were.
    singletons: int = 0
    #: The radius this page's own distribution implied.
    eps: float = 0.0
    #: The largest nearest-neighbour distance, which `eps` is a fraction of.
    nn_max: float = 0.0
    nn_median: float = 0.0
    #: The tenth percentile of the neighbour distances over the ninetieth.
    #: Low means the page has clusters; near one means it has none.
    structure_ratio: float = 1.0
    #: `(lead, reason)` for every group the LEXICAL second opinion doubts
    #: (`G-30`). Its own step, after the semantic decision and never mixed
    #: into it: a page's furniture shares words with everything on it, which
    #: is exactly why frequency must not be what decides a merge. Recorded
    #: rather than acted on -- the merge stands and the doubt is visible.
    lexical_warnings: List[Tuple[str, str]] = field(default_factory=list)
    #: Set when the page was under `MIN_CHUNKS` and nothing was attempted.
    skipped: str = ""
    #: Clusters found but refused, with the reason. Reported rather than
    #: silently dropped: "this page has forty near-identical rows" is a
    #: measurement, and losing it would leave the caller unable to tell a page
    #: with no redundancy from one whose redundancy was declined.
    refused: List[Tuple[int, str]] = field(default_factory=list)

    @property
    def merged_chunks(self) -> int:
        return sum(len(g.members) for g in self.groups)

    def summary(self) -> str:
        if self.skipped:
            return "%s: %s" % (self.url, self.skipped)
        return ("%s: %d groups over %d chunks, %d left alone "
                "(eps %.4f = %.2f x nn_max %.4f)"
                % (self.url, len(self.groups), self.merged_chunks,
                   self.singletons, self.eps, EPS_FRACTION, self.nn_max))


def _unit(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise rows so a dot product is a cosine.

    A zero row -- a chunk whose embedding never arrived -- is left alone
    rather than divided by nothing, and then never matches anything, which is
    the right answer for a chunk nobody has vectorised yet.
    """
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    return matrix / norms


def nearest_neighbour_distances(unit_rows: np.ndarray) -> np.ndarray:
    """Each row's cosine distance to its closest OTHER row.

    Computed from the full gram matrix rather than a neighbour index: a page
    is hundreds of chunks, not millions, and an exact answer on a small matrix
    beats an approximate one that has to be tuned.
    """
    n = unit_rows.shape[0]
    if n < 2:
        return np.zeros((n,), dtype=np.float32)
    similarity = unit_rows @ unit_rows.T
    # A row is always its own nearest neighbour at distance zero, which is not
    # an answer to the question being asked.
    np.fill_diagonal(similarity, -np.inf)
    closest = similarity.max(axis=1)
    return np.clip(1.0 - closest, 0.0, 2.0).astype(np.float32)


def radius_for(nn: np.ndarray) -> Tuple[float, float, float]:
    """The page's merge radius, from its own spread (`G-29`).

    Returns ``(eps, nn_max, nn_median)``. The maximum is the page's most
    isolated chunk: scaling by it means a document whose chunks are all far
    apart gets a wide radius and one whose chunks are packed gets a narrow
    one, which is the whole point of not using a constant.
    """
    if nn.size == 0:
        return 0.0, 0.0, 0.0
    nn_max = float(np.max(nn))
    nn_median = float(np.median(nn))
    return EPS_FRACTION * nn_max, nn_max, nn_median


def has_structure(nn: np.ndarray) -> Tuple[bool, float]:
    """Does this page's nearest-neighbour distribution have a low tail?

    Returns ``(verdict, ratio)``: the tenth percentile over the NINETIETH.
    A page with clusters has closest pairs far closer than its most isolated
    ones, so the ratio is small. A page without them has a ratio near one,
    whether its distances are all large (noise) or all small (nothing but
    clusters) -- which is exactly the pair of cases a radius scaled off the
    maximum cannot tell apart.

    **Against p90, not the median, and the difference is not cosmetic.** The
    median is contaminated by whatever it is trying to detect: on a page where
    most chunks belong to a cluster the median IS a cluster member's distance,
    so p10/median comes out near one and the page is declined for having too
    much of the structure being looked for. Measured on 40 clustered points
    among 30 isolated ones: p10/median 0.61, declined; p10/p90 near zero,
    accepted. Both percentiles are interior, so neither is the outlier the
    radius already depends on.

    Scale-free by construction, so it says the same thing about a tight page
    and a loose one.
    """
    if nn.size < 4:
        return False, 1.0
    high = float(np.percentile(nn, 90))
    if high <= 0.0:
        # Every chunk has an identical neighbour. That is `G-24`'s case, not
        # this one, and it is resolved in the database without embeddings.
        return False, 0.0
    ratio = float(np.percentile(nn, 10)) / high
    return ratio < STRUCTURE_RATIO, ratio


def _runs_within_budget(members: Sequence[str], costs: Dict[str, int],
                        window: int) -> List[List[str]]:
    """Cut a cluster into runs that fit the merge window, in document order.

    A cluster is a claim that these chunks belong together; it is not a claim
    that they fit in one context. Order is the document's, never the
    clustering's -- a merged chunk that reads out of order is not the page.
    """
    runs: List[List[str]] = []
    current: List[str] = []
    total = 0
    for cid in members:
        cost = costs.get(cid, 0)
        if current and (total + cost > window or len(current) >= MAX_MEMBERS):
            runs.append(current)
            current, total = [], 0
        current.append(cid)
        total += cost
    if current:
        runs.append(current)
    return runs


def aggregate_page(cids: Sequence[str], vectors: Sequence[Sequence[float]],
                   markdowns: Sequence[str], url: str = "",
                   *, eps_fraction: float = EPS_FRACTION,
                   min_chunks: int = MIN_CHUNKS,
                   window: int = MERGE_WINDOW) -> Aggregation:
    """Cluster one page's chunks and decide what merges (`G-26`, `G-31`).

    ``cids``, ``vectors`` and ``markdowns`` are parallel and in DOCUMENT
    ORDER, which is what lets a group be rendered as the page reads.

    DBSCAN rather than k-means or agglomerative: the number of groups is not
    known and must not be, most chunks belong to no group at all, and DBSCAN
    is the one that says "this is noise" instead of forcing every point into a
    cluster. `min_samples=2` because two chunks saying the same thing is
    exactly the case this exists for.
    """
    out = Aggregation(url=url)
    n = len(cids)
    if n < min_chunks:
        out.skipped = ("%d chunks, under the significance gate of %d"
                       % (n, min_chunks))
        out.singletons = n
        return out

    matrix = _unit(np.asarray(vectors, dtype=np.float32))
    live = np.linalg.norm(matrix, axis=1) > 1e-9
    if int(live.sum()) < min_chunks:
        out.skipped = ("%d of %d chunks have a vector, under the gate of %d"
                       % (int(live.sum()), n, min_chunks))
        out.singletons = n
        return out

    nn = nearest_neighbour_distances(matrix[live])
    eps, nn_max, nn_median = radius_for(nn)
    out.eps, out.nn_max, out.nn_median = eps, nn_max, nn_median

    structured, ratio = has_structure(nn)
    out.structure_ratio = ratio
    if not structured:
        out.skipped = ("no low tail in the neighbour distances "
                       "(p10/p90 %.2f, needs under %.2f)"
                       % (ratio, STRUCTURE_RATIO))
        out.singletons = n
        return out

    if eps <= 0.0:
        # Every chunk on the page is a duplicate of another in embedding
        # space. `G-24` handles byte-identical copies; this is the same page
        # saying one thing many ways, and a zero radius cannot separate them.
        out.skipped = "every nearest-neighbour distance is zero"
        out.singletons = n
        return out

    from sklearn.cluster import DBSCAN

    labels = np.full((n,), -1, dtype=int)
    labels[live] = DBSCAN(eps=eps, min_samples=2,
                          metric="cosine").fit_predict(matrix[live])

    costs = {cid: tokens.budget(md or "")
             for cid, md in zip(cids, markdowns)}

    clusters: Dict[int, List[str]] = {}
    for i, label in enumerate(labels):
        if label < 0:
            continue
        clusters.setdefault(int(label), []).append(cids[i])

    grouped = 0
    index = {cid: i for i, cid in enumerate(cids)}
    for label, members in sorted(clusters.items()):
        if len(members) > MAX_MEMBERS * 4:
            # A very large cluster is a finding about the page's structure,
            # not a chunk. Reported; see `refused`.
            out.refused.append((len(members), "cluster larger than %d"
                                % (MAX_MEMBERS * 4)))
            continue
        rows = [index[c] for c in members]
        block = matrix[rows]
        sim = block @ block.T
        distances = np.clip(1.0 - sim, 0.0, 2.0)
        iu = np.triu_indices(len(rows), k=1)
        spread = ((float(distances[iu].min()), float(distances[iu].max()))
                  if len(rows) > 1 else (0.0, 0.0))
        for run in _runs_within_budget(members, costs, window):
            if len(run) < 2:
                continue          # a run of one is not a merge
            out.groups.append(Group(
                lead=run[0], members=list(run),
                tokens=sum(costs.get(c, 0) for c in run),
                spread=spread))
            grouped += len(run)

    out.singletons = n - grouped
    return out


def verify_with_lexical(group: Group, lexical: Dict[str, np.ndarray],
                        floor: float = 0.10) -> Optional[str]:
    """A second opinion on a merge, from the frequency side (`G-30`).

    Its own step, after the semantic decision, never mixed into it. The two
    vectors answer different questions -- a quantized encoder says what a
    chunk MEANS, tf-idf says what words it happens to contain -- and a page's
    furniture shares words with everything on it, which is exactly why
    frequency must not be what decides a merge.

    What it is good for is the opposite direction: two chunks the encoder
    called close that share almost no vocabulary are worth a second look.
    Returns a reason string when the group looks wrong, or None.
    """
    rows = [lexical.get(cid) for cid in group.members]
    present = [r for r in rows if r is not None and np.any(r)]
    if len(present) < 2:
        return None
    block = _unit(np.asarray(present, dtype=np.float32))
    sim = block @ block.T
    iu = np.triu_indices(len(present), k=1)
    worst = float(sim[iu].min())
    if worst < floor:
        return ("lexical overlap %.3f is below %.2f -- the encoder called "
                "these close and they share almost no vocabulary"
                % (worst, floor))
    return None


def lca_distance(a: str, b: str) -> float:
    """Structural distance between two xpaths, from their lowest common
    ancestor (`G-33`).

    The tree metric the patricia paths already carry: how far each address is
    from the deepest node they share, normalised by their depths. Two cells of
    one table row are near; a header and a footer are far, however alike the
    encoder finds their wording.

    Offered as the alternative to pagerank, and the two answer different
    questions. Pagerank solves an eigenvalue problem over *linked* relevance,
    which suits aggregation along the page's link structure; this suits
    aggregation among things that sit together. Neither is wired into the
    merge yet -- `G-33` says start with the embeddings alone and MEASURE what
    each adds, and a structural term added before that measurement would be a
    preference rather than a finding.
    """
    left = [s for s in (a or "").split("/") if s]
    right = [s for s in (b or "").split("/") if s]
    shared = 0
    for x, y in zip(left, right):
        if x != y:
            break
        shared += 1
    depth = max(len(left), len(right))
    if depth == 0:
        return 0.0
    return float((len(left) - shared) + (len(right) - shared)) / (2.0 * depth)
