"""What a reader can see, against what the trie holds -- without addresses.

`resolvable.py` asks the page whether every address the trie holds names a
real node. It proves the map's addresses are real and says nothing about
completeness: content that never entered the trie is invisible to it.

Completeness is measured by the affine arrows, against `groundtruth` -- and
that is tier 2, a separate implementation which deliberately shares the
*addressing convention*, because two maps that address differently cannot be
compared at all. An error in the convention is invisible to it, and one was.

So recall has never had an independent check. This is one, and it works by
refusing to use addresses at all.

`innerText` is the browser's own answer to *what does a reader see here*. It
respects `display:none`, `visibility`, collapsed whitespace and line breaking,
and it is computed by layout rather than by anyone's walk. Comparing its lines
against the trie's *values* -- as strings, with no reference to where either
side thinks the content lives -- cannot be fooled by an addressing mistake,
because addressing never enters the comparison.

What it reports:

  seen        a line the reader gets and the trie holds somewhere. Where is
              not asked; this measure has no opinion about that.
  unseen      a line the reader gets and no trie value contains. Content the
              REPL cannot show at any address, which is the failure the goal
              names first: what we see in the webpage is what we get in the
              REPL.

The asymmetry is deliberate. The reverse direction -- trie values a reader
cannot see -- is `resolvable`'s and the coverage arrows' business, and mixing
them would produce one number that answers neither question.

Two limits, stated because they bound the claim:

* `innerText` is a *rendering*, so it drops content the trie is right to hold:
  an `alt`, an `aria-label`, an `href`. Those are absences in `innerText`, not
  in the trie, and are never counted here -- this measure only ever asks
  whether something the reader sees is missing.
* it collapses and re-breaks whitespace its own way, so the comparison is on
  normalized text and short lines are matched by containment. A one-character
  line proves nothing and is skipped.

    python -m vertiscope.analytics --visible --corpus
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from typing import Dict, List, Optional, Sequence

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")

#: Lines shorter than this are skipped: a "." or a "|" appears in almost any
#: haystack by chance, so matching one proves nothing either way.
MIN_LINE = 12

VISIBLE_JS = r"""
// The browser's own answer to what a reader sees. Layout decides it, not a
// walk, which is the whole point: no convention shared with the fold can
// influence what comes back.
var text = document.body ? (document.body.innerText || '') : '';
var out = [], seen = {};
var lines = text.split(/\n+/);
for (var i = 0; i < lines.length; i++) {
  var line = lines[i].replace(/\s+/g, ' ').trim();
  if (line.length < arguments[0]) continue;
  if (seen[line]) continue;            // a repeated line is one question
  seen[line] = 1;
  out.push(line);
}
return out;
"""


def _norm(value: str) -> str:
    return " ".join((value or "").split())


def _tokens(text):
    """Content words, lowercased.

    Split on anything that is not alphanumeric, rather than stripping
    punctuation inside a token. `innerText` joins adjacent elements with no
    separator -- arxiv renders a label span and a heading as
    "Title:Language Models are Few-Shot Learners" -- and stripping punctuation
    within the token turned that into the single word "titlelanguage", which
    exists nowhere and is therefore missing by construction. Arabic
    navigation on ar.wikipedia produced the same artifact at length.

    Words shorter than three characters are dropped: they occur in any
    haystack by chance and prove nothing either way.
    """
    out, word = [], []
    for ch in _norm(text).lower():
        if ch.isalnum():
            word.append(ch)
        elif word:
            if len(word) >= 3:
                out.append("".join(word))
            word = []
    if len(word) >= 3:
        out.append("".join(word))
    return out


def _run_blob(values):
    """Every value's letters and digits, in order, with all separators gone.

    Given the values the page **draws as text**, not every value. `innerText`
    is composed of text nodes, so a run the browser joined is a run of text
    nodes; splicing an `href` or a `title` in between them breaks exactly the
    adjacency this exists to recognise. A link's target sits between its own
    words and the next element's -- `Bookmarks Extensions Privacy` reads as
    one run for a reader and as
    `bookmarks` + `httpsenwikipediaorgwikiextension` + `extensions` here --
    so 216 of one page's 216 unseen words were machine values wedged into a
    reader's sentence.

    `innerText` joins adjacent elements with whatever the layout dictates and
    sometimes with nothing at all: `km<sup>2</sup>` reads as `km2`, a navbox of
    links reads as one run, and Chinese and Korean have no word spacing to
    begin with. The trie holds those parts separately and correctly.

    Stripping separators from both sides and asking whether the run appears
    *in reading order* answers "is this content here" without asking the trie
    to reproduce the browser's joining. It replaced a greedy segmentation
    against a word set, which could not consume `km` + `2` because a
    one-character token is not a word and was excluded from the set -- 246
    misses on one page, every one of them the superscript in an area column.
    """
    out = []
    for value in values:
        for ch in (value or "").lower():
            if ch.isalnum():
                out.append(ch)
    return "".join(out)


def score_visible(lines: Sequence[str], values: Sequence[str],
                  drawn: Optional[Sequence[str]] = None) -> dict:
    """How many of the words a reader sees are in the trie at all.

    Measured on **words, not lines**. `innerText` lines are layout-joined runs
    across several elements -- arxiv renders "Search Submit Donate Log in" as
    one line from four separate links -- so requiring a line to appear
    contiguously in the trie asks the trie to reproduce the browser's line
    breaking, which it neither does nor should. Scored that way, 59% of what a
    reader sees read as missing, and almost none of it was.

    A word is the smallest unit both sides agree on, and it carries no
    assumption about where content lives, which is the point of this tier.
    """
    held = set()
    for value in values:
        held.update(_tokens(value))
    # Presence is asked of every value -- a word is in the trie or it is not,
    # whichever kind of value holds it. Adjacency is asked only of the values
    # the page draws as text, because those are what `innerText` concatenates.
    blob = _run_blob(values if drawn is None else drawn)

    total = 0
    missing_words = 0
    incomplete = []
    for line in lines:
        words = _tokens(line)
        if not words:
            continue
        total += len(words)
        gone = []
        for word in words:
            if word in held:
                continue
            # A run the browser joined: present in reading order once the
            # separators both sides disagree about are removed.
            if word in blob:
                continue
            gone.append(word)
        missing_words += len(gone)
        if gone:
            incomplete.append((line[:90], gone[:6]))

    return {
        "lines": len(lines),
        "words": total,
        "unseen": missing_words,
        "lines_incomplete": len(incomplete),
        "recall": (total - missing_words) / total if total else 1.0,
        "unseen_sample": incomplete[:8],
    }


def measure_visible(driver, urls: Sequence[str], *,
                    context_window: int = 1200,
                    min_line: int = MIN_LINE) -> dict:
    from ..sensing import Sensor
    from ..stream import StreamingScan
    from .drift import _settle

    rows: List[dict] = []
    for url in urls:
        row: Dict[str, object] = {"url": url}
        try:
            driver.get("about:blank")
            driver.get(url)
            time.sleep(1.6)
            sensor = Sensor(driver, url, budget=context_window)
            sensor.boot()
            time.sleep(0.6)
            spine = StreamingScan(url, context_window=context_window)
            _settle(sensor, spine)
            leaves = list(spine.trie.leaves())
            values = [leaf.value or "" for leaf in leaves]
            drawn = [leaf.value or "" for leaf in leaves
                     if (getattr(leaf.address, "accessor", "") or "")
                     .startswith("text()")]
            lines = driver.execute_script(VISIBLE_JS, min_line)
            row.update(score_visible(lines, values, drawn=drawn))
        except Exception as exc:                       # noqa: BLE001
            row["error"] = "{}: {}".format(type(exc).__name__, exc)[:200]
        rows.append(row)
        print("  [{}/{}] {}".format(
            len(rows), len(urls),
            row.get("error") or "lines={} unseen={}".format(
                row.get("lines"), row.get("unseen"))),
            file=sys.stderr, flush=True)
    return {"rows": rows, "min_line": min_line,
            "context_window": context_window, "t": time.time()}


def render_visible_table(report: dict) -> str:
    rows = [r for r in report.get("rows", []) if not r.get("error")]
    if not rows:
        return "  no visibility measurements"

    out = ["", "  what a reader sees, against what the trie holds", ""]
    out.append("  {:<48}{:>8}{:>9}{:>10}".format(
        "page", "lines", "unseen", "recall"))
    bad = [r for r in rows if r["unseen"]]
    for row in sorted(bad, key=lambda r: -r["unseen"])[:12]:
        label = row["url"].rsplit("/", 1)[-1]
        out.append("  {:<48}{:>8}{:>9}{:>9.1f}%".format(
            label[:47], row["lines"], row["unseen"], 100 * row["recall"]))

    lines = sum(r["lines"] for r in rows)
    words = sum(r.get("words", 0) for r in rows)
    unseen = sum(r["unseen"] for r in rows)
    clean = [r for r in rows if not r["unseen"]]
    out.append("")
    out.append("  pages                    {:>7}".format(len(rows)))
    out.append("  pages showing everything {:>7}".format(len(clean)))
    out.append("  visible lines            {:>7}".format(lines))
    out.append("  words a reader sees      {:>7}".format(words))
    # Against words, not lines. Dividing an unseen *word* count by a *line*
    # count reported 51% missing where the word figure was a few percent.
    out.append("  UNSEEN                   {:>7}   {:.2f}% of the words a "
               "reader sees are not in the trie".format(
                   unseen, 100.0 * unseen / words if words else 0.0))
    out.append("")
    out.append("  `innerText` is computed by layout, not by a walk, so no")
    out.append("  convention shared with the fold can influence it -- and no")
    out.append("  address is used in the comparison, so an addressing mistake")
    out.append("  cannot hide a miss. This is the only independent check on")
    out.append("  recall this project has.")
    return chr(10).join(out)


def write_visible_artifact(report: dict,
                           out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
                           ) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "visible.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = dict(row)
            record["t"] = report.get("t")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
