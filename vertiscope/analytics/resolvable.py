"""Does every address in the trie name a node the page actually has?

Three tiers of independence are available for checking this map, and the
first two share assumptions with what they check:

* `drift` boots a second **sensor** and compares. That catches whatever the
  incremental path never heard about, and it is self-consistency: a
  systematic mis-reading present in both is invisible to it.
* the affine arrows compare against **`groundtruth`**, a separate
  implementation which deliberately shares the *addressing convention*,
  because two maps that address differently cannot be compared at all.
  `groundtruth.py` cites `sensor.js::stepFor` for its ordinals.

That shared convention is necessary and it is a blind spot, and one error
lived in it: truth counted only non-empty text children when assigning
`text()[n]`, so both maps were internally consistent and both wrong about
where a text node lives. Neither tier could see it.

**`document.evaluate` is the third tier and the only independent one.** The
page resolves an address or it does not. Nothing about the fold, the walk, or
the conventions they share can influence the answer, and it is available for
every address in the trie rather than only when a diagnosis stalls.

That is what this measures: for a sample of the trie's addresses, does the
path resolve, and does the node it resolves to hold the value recorded
against it. Two failures, kept apart because they mean different things:

  unresolvable   the address names nothing. The trie holds a location the
                 page does not have, and any consumer that follows addresses
                 rather than comparing sets -- the move decoder, a reader
                 clicking through -- is following it nowhere.

  mismatched     the address resolves, to a node holding something else. The
                 map points at the wrong place, which is worse than pointing
                 nowhere: nothing signals the error.

A high score here does not prove the map complete -- it says nothing about
content that never entered the trie. It proves the addresses it *does* hold
are real, which no other tier can establish.

    python -m vertiscope.analytics --resolvable --corpus
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from typing import Dict, List, Sequence

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")

#: Sampled rather than exhaustive: a page can hold 30,000 addresses and each
#: `document.evaluate` is a round trip. The sample is taken evenly across the
#: sorted addresses so it is not biased toward one region of the document.
SAMPLE = 400

RESOLVE_JS = r"""
var out = [];
for (var i = 0; i < arguments[0].length; i++) {
  var row = arguments[0][i];       // [xpath, attribute-or-empty]
  var node = null, ok = true;
  try {
    node = document.evaluate(row[0], document, null, 9, null).singleNodeValue;
  } catch (e) { ok = false; }
  if (!ok) { out.push(['bad-syntax', '']); continue; }
  if (!node) { out.push(['unresolvable', '']); continue; }
  // Read what the address says it holds, not whatever is nearest.
  //
  // An address carries an accessor naming where its value lives: `href` on
  // the element, or `text()[0]` in the node itself. Comparing an href
  // against the element's textContent reported 619 mismatches of 1,581 on
  // six pages -- every link on the corpus -- for addresses that resolved to
  // exactly the right element. The docstring said this and the code did not.
  var got = '';
  if (row[1]) {
    got = (node.getAttribute && node.getAttribute(row[1])) || '';
  } else {
    got = node.textContent || '';
  }
  out.push(['resolved', got.replace(/\s+/g, ' ').trim().slice(0, 400)]);
}
return out;
"""


#: Elements outside the HTML namespace. `document.evaluate` with unprefixed
#: names cannot match them, so an address into one of these subtrees does not
#: resolve for any standard XPath consumer -- including a reader following it
#: by hand. The node is real and the address is right about the composed tree;
#: what it is not is *resolvable*, which is a claim this map makes about every
#: address it holds.
FOREIGN = ("/svg", "/math")


def _is_foreign(xpath: str) -> bool:
    return any(step in xpath for step in FOREIGN)


def _attribute_of(accessor: str) -> str:
    """The attribute an address's value came from, or "" for a text node.

    `accessor` looks like `href|link.anchor/link` or `text()[0]|text.visible`.
    Only the part before the pipe names where the value lives; an `@`-prefixed
    accessor is a synthetic annotation with no attribute behind it.
    """
    head = (accessor or "").split("|", 1)[0]
    if not head or head.startswith("text()"):
        return ""
    if head.startswith("@"):
        # A synthetic annotation -- `@control`, `@role`. Its value is the
        # sensor's own classification, not something the page holds anywhere,
        # so there is nothing to resolve it against. Compared to an element's
        # text it reported `want: button || page: ""` as a mismatch.
        return "@"
    # `data-mw@496` is one match inside a longer attribute value.
    return head.split("@", 1)[0]


def _norm(value: str) -> str:
    return " ".join((value or "").split())


#: How much of the page side the browser sends back. The comparison is a
#: prefix of that length, not the whole value.
WINDOW = 200


def verdict(attribute, state, want, got, xpath):
    """What one resolved address proves, in one word.

    Extracted so the four ways this check has been wrong are testable.
    Each was found by reading samples, and each made the map look broken:

    * an `href` compared against the element text -- 619 mismatches of
      1,581, every link sampled, for addresses that resolved perfectly;
    * a synthetic `@control` treated as page content, when the sensor own
      classification is nowhere in the page to be found;
    * an `<svg>` or `<math>` node called unresolvable, when it is real and
      merely outside the namespace plain xpath reaches;
    * a whole value compared against a truncated window, reporting long
      COinS metadata as mismatched where the two agreed for every
      character either side could show.
    """
    if attribute == "@":
        return "synthetic"
    if state == "bad-syntax":
        return "bad-syntax"
    if state == "unresolvable":
        return "foreign" if _is_foreign(xpath) else "unresolvable"
    if not _norm(want):
        return "resolved"
    return "resolved" if _norm(want)[:WINDOW] in got else "mismatched"


def measure_resolvable(driver, urls: Sequence[str], *,
                       context_window: int = 1200,
                       sample: int = SAMPLE) -> dict:
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

            held = sorted({(leaf.address.xpath,
                            _attribute_of(leaf.address.accessor)):
                           (leaf.value or "")
                           for leaf in spine.trie.leaves()
                           if leaf.address}.items())
            row["addresses"] = len(held)
            if held:
                step = max(1, len(held) // sample)
                taken = held[::step][:sample]
                answers = driver.execute_script(
                    RESOLVE_JS, [[p, attr] for (p, attr), _v in taken])
                unresolvable, mismatched, bad, foreign = [], [], [], []
                synthetic = 0
                for ((path, attr), want), (state, got) in zip(taken, answers):
                    call = verdict(attr, state, want, got, path)
                    if call == "synthetic":
                        synthetic += 1
                    elif call == "bad-syntax":
                        bad.append(path)
                    elif call == "foreign":
                        foreign.append(path)
                    elif call == "unresolvable":
                        unresolvable.append(path)
                    elif call == "mismatched":
                        mismatched.append((path, want[:60], got[:60]))
                row.update({
                    "sampled": len(taken),
                    "synthetic": synthetic,
                    "foreign": len(foreign),
                    "foreign_sample": foreign[:5],
                    "unresolvable": len(unresolvable),
                    "mismatched": len(mismatched),
                    "bad_syntax": len(bad),
                    "unresolvable_sample": unresolvable[:5],
                    "mismatched_sample": mismatched[:5],
                })
        except Exception as exc:                       # noqa: BLE001
            row["error"] = "{}: {}".format(type(exc).__name__, exc)[:200]
        rows.append(row)
        print("  [{}/{}] {}".format(
            len(rows), len(urls),
            row.get("error") or "sampled={} unresolvable={} mismatched={}".format(
                row.get("sampled"), row.get("unresolvable"),
                row.get("mismatched"))),
            file=sys.stderr, flush=True)
    return {"rows": rows, "sample": sample,
            "context_window": context_window, "t": time.time()}


def render_resolvable_table(report: dict) -> str:
    rows = [r for r in report.get("rows", []) if not r.get("error")]
    if not rows:
        return "  no resolvability measurements"

    out = ["", "  every address asked of the page itself", ""]
    out.append("  {:<46}{:>9}{:>14}{:>12}".format(
        "page", "sampled", "unresolvable", "mismatched"))
    bad = [r for r in rows if r.get("unresolvable") or r.get("mismatched")]
    for row in sorted(bad, key=lambda r: -(r["unresolvable"] + r["mismatched"])):
        label = row["url"].rsplit("/", 1)[-1]
        out.append("  {:<46}{:>9}{:>14}{:>12}".format(
            label[:45], row["sampled"], row["unresolvable"], row["mismatched"]))

    sampled = sum(r.get("sampled", 0) for r in rows)
    un = sum(r.get("unresolvable", 0) for r in rows)
    mm = sum(r.get("mismatched", 0) for r in rows)
    syn = sum(r.get("bad_syntax", 0) for r in rows)
    out.append("")
    out.append("  pages                    {:>7}".format(len(rows)))
    out.append("  addresses asked          {:>7}".format(sampled))
    out.append("  UNRESOLVABLE             {:>7}   names nothing in the page"
               .format(un))
    out.append("  foreign namespace        {:>7}   real node, unreachable by "
               "plain xpath".format(sum(r.get("foreign", 0) for r in rows)))
    out.append("  synthetic annotation     {:>7}   the sensor's own class; "
               "nothing to resolve".format(
                   sum(r.get("synthetic", 0) for r in rows)))
    out.append("  MISMATCHED               {:>7}   resolves, holds something "
               "else".format(mm))
    out.append("  not valid xpath          {:>7}".format(syn))
    out.append("")
    out.append("  The page answers this, not the fold and not the walk, so no")
    out.append("  assumption they share can influence it. It says nothing")
    out.append("  about content that never entered the trie -- only that what")
    out.append("  is in there names somewhere real.")
    return chr(10).join(out)


def write_resolvable_artifact(report: dict,
                              out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
                              ) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "resolvable.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = dict(row)
            record["t"] = report.get("t")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
