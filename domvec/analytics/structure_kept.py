"""Do headers, fields and formatting reach the encoder? -- `G-48`.

The verbatim (PLUGIN_GOAL): "We should still be very careful about headers,
fields, and formatting like the previous crypto stock panel that showed a
good example (so we include these fields and formattings in our text
vectorizations as well. I could suggest link-free markdown for quantized
embeddings while keeping the pure and full markdowns as their original
representations".

So for each stored chunk of a page, the STRUCTURE the reader sees is listed
-- heading lines, a table's header row, bold field labels, `Label: value`
fields -- and each is looked for, markup and all, in the exact string the
semantic encoder is given (`tokens.for_model`, what `vectors.push` embeds).
Kept = the element appears there whole. The denominator is the structure
the chunk HAS; a chunk with none is not asked.

Planted arm (`--plain`): the encoder given `models.plain` -- formatting and
link text flattened -- the thing the verbatim warns against; the share must
fall. Reads through the running sidecar (`/cypher`); outside the REPL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from typing import Callable, Dict, List

from .. import tokens

_HEADING = re.compile(r"^\s{0,3}(#{1,6}\s+\S.*)$", re.M)
_BOLD = re.compile(r"\*\*[^*\n]{1,60}\*\*")
_FIELD = re.compile(r"^\s*(?:[-*]\s+)?([A-Z][\w ./%()-]{1,40}):\s+\S", re.M)


def _drop_targets(s: str) -> str:
    """A structure element as the encoder should see it: link targets out."""
    return tokens.for_model(s).strip()


def elements(md: str) -> List[str]:
    """The structure a reader sees in a chunk, each as one string."""
    out: List[str] = []
    for m in _HEADING.finditer(md or ""):
        out.append(m.group(1).strip())
    lines = (md or "").splitlines()
    for i, line in enumerate(lines[:-1]):
        # A table's header row: a pipe row followed by its |---| separator.
        if line.strip().startswith("|") and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1] or ""):
            out.append(line.strip())
    out += _BOLD.findall(md or "")
    # A field is its LABEL, to the colon: the value is often a link whose
    # target the encoder rightly drops, and counting the link's bracket as
    # part of the field read four kept labels as lost (2026-10-30).
    for m in _FIELD.finditer(md or ""):
        whole = m.group(0)
        out.append(re.sub(r"^\s*[-*]\s+", "", whole[: whole.index(":") + 1]).strip())
    seen, uniq = set(), []
    for e in (_drop_targets(x) for x in out):
        if e and e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def score(chunks: List[str], encoder_text: Callable[[str], str]) -> Dict:
    asked = kept = elems = 0
    lost: List[str] = []
    for md in chunks:
        es = elements(md)
        if not es:
            continue
        asked += 1
        text = encoder_text(md)
        for e in es:
            elems += 1
            if e in text:
                kept += 1
            elif len(lost) < 6:
                lost.append(e[:80])
    return {"chunks_with_structure": asked, "elements": elems, "kept": kept,
            "share": round(kept / elems, 3) if elems else None, "lost": lost}


def _cypher(base: str, q: str) -> List[list]:
    req = urllib.request.Request(base.rstrip("/") + "/cypher", data=json.dumps({"query": q}).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r).get("rows") or []


def measure(base: str, contains: str) -> Dict:
    rows = _cypher(base, "MATCH (c:Chunk) WHERE c.url CONTAINS '%s' RETURN c.md" % contains.replace("'", ""))
    mds = [r[0] or "" for r in rows]
    from .. import models
    return {"url_contains": contains, "chunks": len(mds),
            "encoder": score(mds, tokens.for_model),
            "planted_plain": score(mds, models.plain)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m domvec.analytics.structure_kept",
                                 description="Headers, fields and formatting kept in the encoder's text (G-48).")
    ap.add_argument("contains", nargs="?", default="coinmarketcap")
    ap.add_argument("--sidecar", default="http://127.0.0.1:8788")
    a = ap.parse_args(argv)
    print(json.dumps(measure(a.sidecar, a.contains), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
