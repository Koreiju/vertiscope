"""Is the rendering an affine map of the page?

The claim under test is that the REPL's rendering preserves the page's
structure: reading order, containment, and the grouping of a control with the
content it governs survive; absolute pixel geometry does not. "Affine" is
taken as that consequence -- *relations are preserved, the origin is not* --
rather than as linear algebra.

The patricia trie is the map. It is keyed on `url : xpath : markdown : content`
and it is the only structure both sides share, so it is where the comparison
is made. Ground truth (`groundtruth.PageTruth`) addresses the page's own
content; the trie addresses what the sensor captured; the projections address
what a reader is shown. Each arrow is scored separately, because they fail
differently and for different reasons.

The three failure modes
-----------------------
A faithful map is **injective on addresses** and **surjective onto drawn
content**. Every rendering defect this project has found is a failure of one
of those two properties, plus the degenerate third:

  loss (FN)         a thing on the page with no counterpart in the render.
                    `<img alt="">` classed as presentational and dropped; a
                    link label nested two levels below its anchor losing its
                    target.

  duplication (FN') one page address rendered more than once -- injectivity
                    gone. An anchor's href and its words drawn as two lines,
                    `[/tag/love/]` beside `[love]`.

  invention (FP)    a rendered address with no counterpart on the page. A
                    filled slot emitting its fallback text: words no reader
                    can see, indexed as though seen.

  correct omission  content the map is *right* to leave out: `display:none`
  (TN)              runs absent from the wireframe, closed-root content
                    reported unreachable rather than read as empty, redundant
                    spellings of one thing collapsed to one.

`TN` is not padding. A metric that cannot score a correct omission cannot tell
a faithful renderer from a merely verbose one, and four measurements in this
repo went wrong precisely there.

Denominators are part of the metric
-----------------------------------
Each arrow names what it is scored against, and they differ on purpose:

  page -> trie          all units. Capture has no licence to omit; a thing on
                        the page that never reached the trie is lost outright.
  page -> markdown      all units. Markdown is the semantic projection and
                        indexes `display:none` content deliberately -- a
                        hidden <meta> holding keywords is real content.
  page -> wireframe     drawn units only. The wireframe is a drawing and must
                        not show what the page does not draw.

Scoring the wireframe against everything read 78% on a page whose canvas held
every word. A coverage number is a claim about the renderer *and* a claim
about the denominator, and only one of them used to be checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..address import ContentAddress
from ..aam import INTERACTIVE
from .groundtruth import PageTruth, PageUnit

__all__ = ["Confusion", "ArrowScore", "AffineReport", "score_arrow",
           "score_dedup", "DedupScore"]


@dataclass
class Confusion:
    """One 2x2, with the vocabulary of the thing being measured."""

    tp: int = 0            # present on the page, present in the render
    fn: int = 0            # present on the page, absent from the render
    fp: int = 0            # in the render, not on the page
    tn: int = 0            # correctly omitted
    duplicated: int = 0    # extra emissions of an address already counted
    collapsed: int = 0     # a redundant spelling the render deliberately
                           # merged away, another having survived
    suspect: int = 0       # counted FN, yet its words are in the render --
                           # the signature of a scoring error, not a loss

    @property
    def recall(self) -> float:
        """Of what the page holds, how much survived. Surjectivity."""
        seen = self.tp + self.fn
        return self.tp / seen if seen else 1.0

    @property
    def precision(self) -> float:
        """Of what was rendered, how much the page actually holds."""
        drawn = self.tp + self.fp
        return self.tp / drawn if drawn else 1.0

    @property
    def injectivity(self) -> float:
        """One address, one line. 1.0 when nothing is emitted twice."""
        total = self.tp + self.duplicated
        return self.tp / total if total else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> Dict[str, float]:
        return {"tp": self.tp, "fn": self.fn, "fp": self.fp, "tn": self.tn,
                "duplicated": self.duplicated, "collapsed": self.collapsed,
                "suspect": self.suspect,
                "recall": round(self.recall, 6),
                "precision": round(self.precision, 6),
                "injectivity": round(self.injectivity, 6),
                "f1": round(self.f1, 6)}


@dataclass
class ArrowScore:
    """One arrow of the map, scored, with its losses kept for reading."""

    name: str
    denominator: str
    overall: Confusion = field(default_factory=Confusion)
    by_kind: Dict[str, Confusion] = field(default_factory=dict)
    by_origin: Dict[str, Confusion] = field(default_factory=dict)
    lost: List[PageUnit] = field(default_factory=list)
    invented: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "arrow": self.name,
            "denominator": self.denominator,
            "overall": self.overall.as_dict(),
            "by_kind": {k: c.as_dict() for k, c in sorted(self.by_kind.items())},
            "by_origin": {k: c.as_dict()
                          for k, c in sorted(self.by_origin.items())},
            "lost_sample": [
                {"kind": u.kind, "xpath": u.xpath, "value": u.value[:120],
                 "shadow": u.shadow, "drawn": u.drawn}
                for u in self.lost[:25]],
            "invented_sample": self.invented[:25],
        }


@dataclass
class OrderScore:
    """Whether the rendering reads in the order the page reads.

    The fourth thing an affine map has to preserve, and the one nothing here
    was measuring. Coverage says every unit arrived, dedup says none arrived
    twice, and both are satisfied by a page whose paragraphs come out
    shuffled.

    It is not a hypothetical. The scan keys its walk positions on absolute
    xpaths and indexes an element wherever it has same-tag siblings
    (`.../ul/li[1]`); the trie drops the index on the first of a group
    (`.../ul/li`). The lookup missed for exactly one child per group, that
    child got an unknown position, unknown positions sort last, and the first
    item of every list and card grid was drawn at the bottom of its group.
    Every address was right and every unit was present, so nothing else in
    this file could see it. Over the fixture pages it was 42 inversions of
    prose; the fix left 8.

    The reference is the ground truth's own order, which is a composed-tree
    walk -- so slotted content is scored where the page puts it, not where its
    light-DOM address would put it.

    Headings are excluded. A heading whose words live in child elements is
    deliberately drawn with the card it labels, which places it ahead of
    content the walk met earlier; counting that would make the number a
    function of how many cards a page has.
    """

    name: str
    lines: int = 0            # rendered lines that could be placed at all
    inversions: int = 0       # adjacent pairs that read out of order
    sample: List[str] = field(default_factory=list)

    @property
    def monotone(self) -> float:
        """Fraction of adjacent pairs in the right order. 1.0 is perfect."""
        pairs = max(self.lines - 1, 0)
        return 1.0 if pairs == 0 else 1.0 - self.inversions / pairs

    def as_dict(self) -> dict:
        return {
            "arrow": self.name,
            "lines": self.lines,
            "inversions": self.inversions,
            "monotone": round(self.monotone, 4),
            "sample": self.sample[:12],
        }


def score_order(name: str, truth: "PageTruth",
                rendered: Sequence[ContentAddress],
                texts: Optional[Sequence[str]] = None) -> OrderScore:
    """Count adjacent rendered lines that read out of the page's order.

    Ranked on the **unit's own xpath**, with the owner as a fallback. Ranking
    on the owner alone -- which this did, `_owner` stripping `/text()[n]` --
    collapses every text child of one element onto a single position, taken
    from the first. A paragraph is then a single point in the order, and a
    sentence with a link in it cannot be represented at all:

        page              Physics studies [matter] and [energy] across ...
        owner-keyed rank  p, a, p, a[2], p, em, p
                          -> every return to the prose is an inversion

    So the metric scored *grouping* as perfect and reading order as broken,
    which is exactly backwards. Measured on tests/fixtures/mixed_inline.html,
    one capture rendered both ways:

        label-grouped      owner-keyed  0 inversions    exact-keyed  1
        reading order      owner-keyed  3 inversions    exact-keyed  0

    It mattered: correcting the live path's order took the corpus from 4,475
    inversions to 29,776 by this measure, all of it concentrated on prose
    pages with inline links, while an independent recall check over the same
    change fell from 1,620 unseen words to 786. A metric that moves six-fold
    against a change three other measures call an improvement is reporting on
    itself.

    The owner fallback stays, and is why the quotient does not break the
    count: markdown merges an anchor's href and its words into `[words](url)`
    on purpose, so a rendered line's exact address may be one of several the
    page holds at that element. Exact first, owner second, keeps the merge
    tolerated without collapsing siblings that are genuinely apart.
    """
    rank: Dict[str, int] = {}
    for i, unit in enumerate(truth.units):
        rank.setdefault(unit.xpath, i)
    owner_rank: Dict[str, int] = {}
    for i, unit in enumerate(truth.units):
        owner_rank.setdefault(_owner(unit.xpath), i)

    placed: List[Tuple[int, str]] = []
    for i, address in enumerate(rendered):
        text = texts[i] if texts is not None and i < len(texts) else ""
        if text.lstrip().startswith("#"):
            continue                      # deliberate placement, see the class
        where = rank.get(address.xpath)
        if where is None:
            where = owner_rank.get(_owner(address.xpath))
        if where is not None:
            placed.append((where, text))

    score = OrderScore(name=name, lines=len(placed))
    for (a, _ta), (b, tb) in zip(placed, placed[1:]):
        if a > b:
            score.inversions += 1
            if len(score.sample) < 12:
                score.sample.append("{} -> {}: {}".format(a, b, tb[:60]))
    return score


def _owner(xpath: str) -> str:
    return xpath.split("/text()")[0]


@dataclass
class _Emitted:
    """What the render put on the page, indexed two ways.

    The map is a **quotient**, not a bijection, and the two indexes are what
    keep that from reading as a defect. Markdown merges an anchor's href with
    the words beneath it into one line -- `[words](target)` -- on purpose, so
    two page units legitimately arrive as one rendered line. Scored by owner
    alone that reads as fifty-six duplications on a page with none; scored by
    exact address alone it reads as fifty-six losses.

    So coverage is asked of the *owner* -- did anything representing this
    element reach the render -- and duplication is asked of the *exact
    address*, where a second emission of the same address is a real second
    line and nothing else can explain it.
    """

    # ident -> count, where ident is (xpath, accessor). Duplication.
    exact: Dict[str, int] = field(default_factory=dict)
    # the xpaths those idents cover. Coverage.
    exact_paths: Set[str] = field(default_factory=set)
    owners: Dict[str, int] = field(default_factory=dict)
    text_at: Dict[str, str] = field(default_factory=dict)
    text_by_parent: Dict[str, str] = field(default_factory=dict)
    paths_by_owner: Dict[str, Set[str]] = field(default_factory=dict)
    # Text drawn anywhere *below* a path, keyed by every ancestor of the
    # owner it was drawn at. Built once so the descendant lookup is O(1).
    text_under: Dict[str, str] = field(default_factory=dict)
    # Paths at or above a rendered *affordance*. A control's coverage is
    # structural, not textual: it is covered when the reader can act on
    # it, and its accessible name may be empty or may be the run-together
    # textContent of its children, neither of which equals any line.
    interactive_at: Set[str] = field(default_factory=set)

    @classmethod
    def of(cls, addresses: Iterable[ContentAddress],
           texts: Optional[Sequence[str]] = None) -> "_Emitted":
        out = cls()
        addresses = list(addresses)
        texts = list(texts or [])
        for i, address in enumerate(addresses):
            if address is None:
                continue
            path = address.xpath
            # Identity is (xpath, accessor), not xpath alone.
            #
            # A `ContentAddress` names *which detection at which node*. One
            # element legitimately yields several units -- an `aria-label`
            # and a `title` on the same <svg> are two facts about one node,
            # not one fact stated twice -- and they carry the same xpath with
            # different accessors.
            #
            # Keyed on xpath alone this counted them as the same address
            # emitted twice, and reported `page->trie` injectivity at 87.7%
            # with 78 duplicates. That reading is not merely wrong, it is
            # impossible: the trie is keyed by address, so it cannot hold one
            # address twice, and any duplication it appeared to show was the
            # metric discarding half the key.
            ident = f"{path}\t{address.accessor}"
            out.exact[ident] = out.exact.get(ident, 0) + 1
            out.exact_paths.add(path)
            owner = _owner(path)
            out.owners[owner] = out.owners.get(owner, 0) + 1
            out.paths_by_owner.setdefault(owner, set()).add(path)
            if i < len(texts):
                out.text_at[owner] = (out.text_at.get(owner, "") + " "
                                      + (texts[i] or "")).strip()
                # Also indexed by the owner's parent, because an inline flow
                # is merged into a line addressed at its *first* fragment --
                # a sibling of the ones absorbed, not an ancestor of them.
                # `<span>by <small>Einstein</small></span>` puts "by" and the
                # name under one parent and renders one line at the first.
                parent = owner.rsplit("/", 1)[0] if "/" in owner else owner
                out.text_by_parent[parent] = (
                    out.text_by_parent.get(parent, "") + " "
                    + (texts[i] or "")).strip()
                # And under every ancestor, for the mirror case: content
                # merged *downward*. `<a href><div><span>words</span></div>
                # </a>` renders one line addressed at the span, carrying the
                # anchor's target -- so the anchor's own unit is covered by a
                # line beneath it, which a search that only walks up can
                # never see. Links read 67.8% for exactly this.
                at = owner
                while "/" in at:
                    at = at.rsplit("/", 1)[0]
                    if not at:
                        break
                    out.text_under[at] = (out.text_under.get(at, "") + " "
                                          + (texts[i] or "")).strip()
            if address.tag in INTERACTIVE:
                out.interactive_at.add(owner)
                at = owner
                while "/" in at:
                    at = at.rsplit("/", 1)[0]
                    if not at:
                        break
                    out.interactive_at.add(at)
        return out

    def covers(self, xpath: str, value: str = "",
               kind: str = "", structural: Sequence[str] = ()) -> bool:
        """Did anything standing for this page unit reach the render?

        Address first, and content only to settle one specific question the
        address cannot: **inline merging**. Markdown joins a sentence broken
        across inline markup back into one line -- `"...miracle." by` is one
        line drawn from three page units -- and the joined line is addressed
        at the flow's owner, not at each fragment. The fragments' addresses
        are then genuinely absent while their words are genuinely present.

        Scored on addresses alone that read as ten losses on a page that
        loses nothing. Scored on content alone it is the substring test that
        was wrong four times. So the fallback is narrow: an ancestor of this
        unit must have been rendered, *and* the rendered text at that
        ancestor must actually contain this unit's words. It confirms a
        merge; it cannot excuse a loss, because a lost fragment appears in no
        ancestor's text.
        """
        if xpath in self.exact_paths:
            return True
        owner = _owner(xpath)
        if owner in self.owners:
            return True
        # A control is covered when an affordance is drawn at or below it.
        #
        # `litdev-ripple-icon-button`'s shadow root holds an <a> around a slot
        # carrying "Learn more". Markdown suppresses the empty wrapper and
        # draws the slotted label *as a link* -- the reader can press it, and
        # the affordance is not lost -- but the wrapper's own accessible name
        # is "" and no content test can ever match an empty probe. Judged by
        # content these read as six losses on a page that loses none of them.
        if kind in structural and owner in self.interactive_at:
            return True
        probe = " ".join(value.split()).lower()
        if not probe:
            return False
        # Merged into a sibling of the same flow: same parent, and the words
        # are demonstrably in what was drawn there. Bounded to one level on
        # purpose -- an unbounded search would let a single line at /html
        # "cover" the whole page, which is how a coverage number becomes a
        # tautology.
        parent = owner.rsplit("/", 1)[0] if "/" in owner else owner
        drawn = self.text_by_parent.get(parent)
        if drawn and probe in " ".join(drawn.split()).lower():
            return True
        # Or absorbed upward into an ancestor's own line.
        at = owner
        while "/" in at:
            at = at.rsplit("/", 1)[0]
            if not at:
                break
            drawn = self.text_at.get(at)
            if drawn and probe in " ".join(drawn.split()).lower():
                return True
        # Or drawn on a line *below* this element -- an anchor whose label
        # sits two elements down carries the anchor's target on the label's
        # line, and the anchor's own address is legitimately absent.
        under = self.text_under.get(owner)
        if under and probe in " ".join(under.split()).lower():
            return True
        return False

    def duplicates(self) -> int:
        """Extra emissions of one and the same address."""
        return sum(n - 1 for n in self.exact.values() if n > 1)


def score_arrow(name: str, truth: PageTruth,
                rendered: Sequence[ContentAddress],
                denominator: str = "all",
                texts: Optional[Sequence[str]] = None,
                structural: Sequence[str] = ("control",)) -> ArrowScore:
    """Score one arrow of the map, address against address.

    `denominator` selects which page units this arrow is answerable for:
    ``"all"`` for capture and for markdown, ``"drawn"`` for the wireframe.
    Units outside the denominator are scored as `tn` when the render omits
    them -- being right to leave something out is an outcome, not a silence.
    """
    score = ArrowScore(name=name, denominator=denominator)
    emitted = _Emitted.of(rendered, texts)

    # Which contents reached the render at all, in any of their spellings.
    #
    # The map is a quotient and its kernel is deliberate: "one target, one
    # line" collapses the same link in a desktop nav and a mobile drawer to
    # a single rendered line, and lit.dev's header and `mwc-drawer` carry the
    # same items twice by construction. Scored without this, every collapsed
    # spelling read as a loss and markdown's recall was understated by exactly
    # the amount of correct deduplication -- which is the kernel being counted
    # as damage.
    #
    # A collapse is only credited when some *other* spelling of the same
    # content did reach the render. If every spelling is gone, that is
    # over-dedup, and it stays a loss.
    # Everything the render drew, as one blob, for the suspicion check
    # below. Never used to decide coverage -- content matching as a *primary*
    # test is what went wrong four separate times -- only to ask whether a
    # loss already counted looks real.
    all_drawn_text = " ".join(
        " ".join((text or "").split()).lower() for text in (texts or []))

    covered_values = {
        " ".join(u.value.split()).lower()
        for u in truth.units
        if u.value.strip() and emitted.covers(u.xpath, u.value, u.kind,
                                              structural)
    }

    for unit in truth.units:
        answerable = denominator == "all" or unit.drawn
        bucket_kind = score.by_kind.setdefault(unit.kind, Confusion())
        origin = "shadow" if unit.shadow else "light"
        bucket_origin = score.by_origin.setdefault(origin, Confusion())
        covered = emitted.covers(unit.xpath, unit.value, unit.kind,
                                 structural)

        if not answerable:
            # Outside the denominator. Omitting it is correct; rendering it
            # anyway is not scored as invention either, because the page does
            # hold it -- it is simply not this arrow's business.
            if not covered:
                for b in (score.overall, bucket_kind, bucket_origin):
                    b.tn += 1
            continue

        if covered:
            for b in (score.overall, bucket_kind, bucket_origin):
                b.tp += 1
        elif " ".join(unit.value.split()).lower() in covered_values:
            # Collapsed, not lost: this content is on the page more than once
            # and the render kept one of them.
            for b in (score.overall, bucket_kind, bucket_origin):
                b.collapsed += 1
        else:
            for b in (score.overall, bucket_kind, bucket_origin):
                b.fn += 1
            # Is this loss even real?
            #
            # Seven times in this instrument's short life a *correct*
            # renderer was scored as losing something, always the same way:
            # the unit was matched against a set the renderer is not
            # answerable for, or at an address the renderer records
            # differently. Every one of those was found by hand, after
            # reporting the wrong number.
            #
            # So the check is built in. If a unit is counted lost and its
            # words are nevertheless somewhere in what was drawn, that is the
            # signature of a scoring error rather than a loss -- and the
            # instrument says so itself instead of waiting to be caught.
            # `suspect` is not subtracted from `fn`: it is a claim about the
            # measurement, and quietly correcting the number would hide
            # exactly what needs looking at.
            probe = " ".join(unit.value.split()).lower()
            if probe and len(probe) > 3 and probe in all_drawn_text:
                for b in (score.overall, bucket_kind, bucket_origin):
                    b.suspect += 1
            score.lost.append(unit)

    # Injectivity, asked of the exact address. Counted apart from tp so recall
    # is never quietly inflated by drawing one thing twice.
    score.overall.duplicated = emitted.duplicates()

    # Invention: a rendered address with no counterpart on the page at all --
    # neither the address itself nor the element it hangs from. The fallback
    # text of a filled slot was exactly this: words no reader can see, given
    # an address the composed tree does not contain.
    page_paths = {u.xpath for u in truth.units}
    page_owners = {_owner(u.xpath) for u in truth.units}
    # Every ancestor of something the page holds. Rendering at a container is
    # not invention: an inline <svg> is named by its `title` child, so ground
    # truth addresses `.../svg[4]/title/text()[1]` while the render addresses
    # the picture itself at `.../svg[4]`. The render is standing for content
    # the page really has, one level up, and counting that as a phantom
    # charged 19 inventions for 19 logos correctly drawn.
    page_ancestors: Set[str] = set()
    for unit in truth.units:
        at = _owner(unit.xpath)
        while "/" in at:
            at = at.rsplit("/", 1)[0]
            if not at:
                break
            page_ancestors.add(at)
    for ident, count in emitted.exact.items():
        path = ident.split("	", 1)[0]
        if (path in page_paths or _owner(path) in page_owners
                or _owner(path) in page_ancestors):
            continue
        score.overall.fp += count
        if len(score.invented) < 25:
            score.invented.append(path)
    return score


@dataclass
class DedupScore:
    """Deduplication as a decision, with both errors named.

    A single "dedup rate" cannot distinguish the two, and they point in
    opposite directions:

    over_dedup   distinct page content collapsed into one. This is loss, and
                 it is the dangerous direction -- a suppression rule once made
                 every search-result title vanish because an href was hidden
                 on the grounds that "the anchor speaks" while the words were
                 consumed on the grounds that "the link will draw them".

    under_dedup  redundant content emitted more than once. This is noise:
                 survivable, and the failure a keep-everything policy
                 guarantees.

    The ratio between them is what the suppression rules are really tuning.
    """

    redundant_pairs: int = 0     # page units sharing content with another
    collapsed: int = 0           # ...and correctly rendered once (TP)
    under_dedup: int = 0         # ...and rendered more than once (FN)
    over_dedup: int = 0          # distinct content collapsed away (FP)
    distinct_kept: int = 0       # distinct content kept distinct (TN)
    #: What was lost, not just how much. A count alone is undiagnosable: a
    #: corpus change moved `over_dedup` by +40 and there was no way to say
    #: which clusters, so the cause could only be guessed at. `visible` had
    #: already learned this and carries `unseen_sample`; the lesson had not
    #: crossed to the instrument next door.
    over_dedup_sample: List[Tuple[str, str]] = field(default_factory=list)
    #: The same, for the error that is seventeen times larger.
    #:
    #: `over_dedup_sample` was added because "a count alone is
    #: undiagnosable", and that argument applies with more force here:
    #: under_dedup is 11,641 against over_dedup's 670, so recall is what the
    #: aggregate is really reporting and nothing said WHICH lineages still
    #: draw twice. Carries how many lines survived, since a lineage drawing
    #: two lines and one drawing nine are different problems.
    under_dedup_sample: List[Tuple[str, str, int]] = field(default_factory=list)

    @property
    def correctness(self) -> float:
        total = (self.collapsed + self.under_dedup + self.over_dedup
                 + self.distinct_kept)
        return (self.collapsed + self.distinct_kept) / total if total else 1.0

    def as_dict(self) -> Dict[str, float]:
        return {"redundant_pairs": self.redundant_pairs,
                "under_dedup_sample": self.under_dedup_sample,
                "collapsed": self.collapsed,
                "under_dedup": self.under_dedup,
                "over_dedup": self.over_dedup,
                "distinct_kept": self.distinct_kept,
                "over_dedup_sample": list(self.over_dedup_sample),
                "correctness": round(self.correctness, 6)}


def _restates(a: PageUnit, b: PageUnit) -> bool:
    """Whether two same-valued units are one thing said twice.

    A strict ancestor-descendant relation is a restatement: a link's
    `aria-label`, the component inside it and that component's `<svg><title>`
    can all say "YouTube", and drawing three lines tells the reader the same
    thing three times.

    Two units at the *same* element are usually a restatement too -- an
    element's `title` attribute and the text node under it -- but not when
    both are text children of it. `_owner` strips `/text()[n]`, so every text
    child of one element collapses to the same owner and three backticks in
    one `<pre>` looked like one backtick restated twice. Sibling text nodes
    are separate characters on the page, and a renderer that collapsed them
    would be deleting content.
    """
    oa, ob = _owner(a.xpath), _owner(b.xpath)
    if oa == ob:
        both_text = "/text()" in a.xpath and "/text()" in b.xpath
        return not both_text
    return oa.startswith(ob + "/") or ob.startswith(oa + "/")


def score_dedup(truth: PageTruth,
                rendered: Sequence[ContentAddress],
                texts: Optional[Sequence[str]] = None,
                drawn_only: bool = True) -> DedupScore:
    """Was redundancy collapsed, and was anything distinct collapsed with it?

    Scored over what the page lays out, for the same reason the projection
    arrows are. A dedup decision is a decision about what the *reader* is
    shown, so content the page never draws cannot have been wrongly collapsed
    out of a rendering it was never going to enter. Ground truth descends into
    a folded `<select>` and marks its options undrawn; counted here they read
    as distinct content destroyed, and `over_dedup` went from 654 to 2,290
    across the corpus for a renderer that had collapsed a dropdown exactly as
    a browser does.

    **Redundancy is a lineage relation, not equality of text.** A page that
    says "inspirational" under six different quotes is not being redundant --
    it is saying a true thing six times, and a renderer that drew it once
    would be losing five. The first version of this scored exactly that as
    64 failures on a page with none.

    What redundancy actually is here is one element's content restated by an
    element it contains or is contained by: an `aria-label`, a `title` and the
    text node beneath them; a wrapper repeating its only child's words. Those
    are three spellings of one thing, arranged in a lineage, and collapsing
    them to one is the whole job. So a pair counts as redundant when one
    owner is an ancestor of the other **and** their values agree.

    Both errors are named because they point in opposite directions:

    over_dedup   every spelling of a thing gone. This is loss, and it is the
                 dangerous direction -- a suppression rule once made every
                 search-result title vanish because an href was hidden on the
                 grounds that "the anchor speaks" while the words were
                 consumed on the grounds that "the link will draw them".

    under_dedup  more than one spelling still drawn. This is noise:
                 survivable, and what a keep-everything policy guarantees.

    Judged on the page, because that is the only side where the question is
    decidable -- asking the render what was redundant is asking it to mark
    its own paper.
    """
    if drawn_only:
        truth = PageTruth(url=truth.url,
                          units=[u for u in truth.units if u.drawn],
                          elements=truth.elements,
                          shadow_hosts=truth.shadow_hosts)
    score = DedupScore()
    emitted = _Emitted.of(rendered, texts)

    def norm(value: str) -> str:
        return " ".join(value.split()).strip().lower()

    # Group by content, then keep only those groups whose members stand in a
    # lineage. Same words in unrelated places are different facts.
    by_value: Dict[str, List[PageUnit]] = {}
    for unit in truth.units:
        if norm(unit.value):
            by_value.setdefault(norm(unit.value), []).append(unit)

    # Redundancy is per **lineage cluster**, not per value.
    #
    # The principle was already written down -- one element's content restated
    # by an element it contains -- and then applied to whole value groups.
    # Hacker News puts a "hide" link on each of thirty stories: sixty units,
    # one anchor and one text node per story. Each *pair* is a genuine
    # restatement and markdown collapses it to one line, correctly. Grouped by
    # value, all sixty became one group with thirty survivors and the page was
    # charged twenty-nine under-deduplications for rendering thirty distinct
    # affordances the reader can each click.
    #
    # A page saying one true thing thirty times is not being redundant. Only
    # units standing in an ancestor-descendant relation are, and each such
    # cluster is one restatement to be scored on its own.
    clusters: List[List[PageUnit]] = []
    for _value, group in by_value.items():
        if len(group) < 2:
            continue
        pending = sorted(group, key=lambda u: len(_owner(u.xpath)))
        buckets: List[List[PageUnit]] = []
        for unit in pending:
            owner = _owner(unit.xpath)
            for bucket in buckets:
                if any(_restates(unit, m) for m in bucket):
                    bucket.append(unit)
                    break
            else:
                buckets.append([unit])
        for bucket in buckets:
            if len(bucket) > 1:
                clusters.append(bucket)
                score.redundant_pairs += len(bucket) - 1

    redundant: Set[str] = {u.xpath for c in clusters for u in c}

    for members in clusters:
        # How many distinct *lines* this lineage still produces -- not how
        # many of its members are "covered". Every member of a lineage is
        # covered by any one line drawn at the element, so counting members
        # reported 79 under-deduplications and zero correct collapses on a
        # page that collapses correctly. The question dedup asks is how many
        # times the reader is told the same thing.
        lines_drawn: Set[str] = set()
        for u in members:
            lines_drawn |= emitted.paths_by_owner.get(_owner(u.xpath), set())
        survivors = len(lines_drawn)
        if survivors == 0:
            score.over_dedup += 1
            if len(score.over_dedup_sample) < 12:
                score.over_dedup_sample.append(
                    (_owner(members[0].xpath), (members[0].value or "")[:70]))
        elif survivors == 1:
            score.collapsed += 1
        else:
            score.under_dedup += survivors - 1
            if len(score.under_dedup_sample) < 12:
                score.under_dedup_sample.append(
                    (_owner(members[0].xpath),
                     (members[0].value or "")[:70], survivors))

    # Content with no redundant partner, still present: correctly left alone.
    for unit in truth.units:
        if unit.xpath in redundant or not norm(unit.value):
            continue
        if emitted.covers(unit.xpath, unit.value):
            score.distinct_kept += 1
    return score


@dataclass
class AffineReport:
    """Every arrow of the map for one page, plus the dedup decision."""

    url: str
    arrows: List[ArrowScore] = field(default_factory=list)
    order: List[OrderScore] = field(default_factory=list)
    dedup: DedupScore = field(default_factory=DedupScore)
    page: Optional[PageTruth] = None
    timings: Dict[str, float] = field(default_factory=dict)
    # What the fold's own chunking / hashing / dedup machinery did. These are
    # counted in the page and were never read on this side: the gate that
    # decides whether a subtree is re-sent is the whole of the O(delta)
    # mechanism, and its hit rate is the most direct evidence there is that
    # the mechanism is working rather than merely present.
    algorithms: Dict[str, float] = field(default_factory=dict)
    # The shape of what reaches the trie, against the context budget the
    # reader configured. A renderer for small context windows is answerable
    # for the size of the units it produces, not only their content.
    chunking: Dict[str, float] = field(default_factory=dict)
    # Which sensor mechanisms were actually running, as the page
    # reported them. Without this a row cannot say what it measured,
    # and a comparison between two configurations is unreadable a week
    # later.
    variants: Dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "variants": dict(self.variants),
            "page": {
                "units": len(self.page.units) if self.page else 0,
                "drawn": len(self.page.drawn) if self.page else 0,
                "elements": self.page.elements if self.page else 0,
                "shadow_hosts": self.page.shadow_hosts if self.page else 0,
                "opaque_hosts": self.page.opaque_hosts if self.page else 0,
            },
            "arrows": [a.as_dict() for a in self.arrows],
            "order": [o.as_dict() for o in self.order],
            "dedup": self.dedup.as_dict(),
            "timings_ms": {k: round(v, 3) for k, v in self.timings.items()},
            "algorithms": self.algorithms,
            "chunking": self.chunking,
        }
