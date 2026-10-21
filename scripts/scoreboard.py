"""Every number `docs/PLUGIN_PRD.md` gates on, in one run.

The PRD states acceptance criteria; this prints what they currently read and
how far each is from its bar. It exists because of something this project
keeps proving: a fix here breaks its neighbours. Escaping brackets broke the
link rewriter, deduplicating lines killed the card layout, and moving to a
512-token window made the 3D nodes invisible -- each caught only by the NEXT
measurement, not by the one the change was aimed at.

So the gate is the whole board, never the one number being moved.

Two of the rows are marked `tautological` and that is not modesty. Containment
and depth-correlation come out perfect because the render indents by trie
depth and trie depth mirrors DOM depth; they confirm the absence of a bug and
say nothing about whether structure survived. A board that presented them as
successes would read as 90% done while the two measures that mean something
sat at 35% and 76%.

    python scripts/scoreboard.py --workspace build/vaultws512
    python scripts/scoreboard.py --workspace build/vaultws512 --write

`--live` additionally runs the CDP probes against a running Obsidian for the
numbers that only exist there. Without it those rows read `-` rather than
being guessed at.

The workspace must not be open elsewhere: kuzu takes an exclusive lock, so
stop the sidecar first.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from typing import Dict, Optional

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

CORPUS = REPO / "tests" / "corpus"
BASELINE = REPO / "docs" / "prd_baseline.json"

#: How far a gated measure may drift before it counts as a regression.
#:
#: These numbers are counts and ratios over a corpus that is rebuilt between
#: runs, and a rebuild is not bit-identical: chunk boundaries shift by one,
#: a picture host times out. One percentage point is below anything a change
#: to the code produces here and above the churn a rebuild produces on its
#: own. `dangling_edges` gets zero, because a single dangling edge is exactly
#: the thing worth catching and there is no noise floor under it.
_TOLERANCE = {"dangling_edges": 0.0}

#: Each row: key -> (PRD requirement, bar, direction, tautological?)
#: `direction` is +1 when higher is better.
CRITERIA = {
    "reach_mean":            ("R-C1", 0.60, +1, False),
    "reading_order":         ("R-C2", 0.95, +1, False),
    "containment":           ("R-C2", None, +1, True),
    "depth_rho":             ("R-C2", None, +1, True),
    "shape_field_exists":    ("R-C4", 1.0, +1, False),
    "chunks_over_window":    ("R-C5", 0.02, -1, False),
    # How far the WORST chunk is over, as a multiple of the window.
    #
    # `chunks_over_window` counts how many exceed and never by how much, so a
    # single chunk fifteen times the window read 1.2% and MET. A user found
    # it by opening the note. data.gov.uk renders a `<select>` of every UK
    # public body, and its aggregated label is one line of 43,546 characters
    # -- 7,745 tokens against a window of 512.
    #
    # A ratio of 1.0 is the requirement as stated. 1.5 is the bar because a
    # single indivisible unit may legitimately overrun a little; fifteen
    # times is not a little.
    "worst_overflow_ratio":  ("R-C5", 1.5, -1, False),
    "billboards_textured":   ("R-E3", 0.95, +1, False),
    "scroll_port_exists":    ("R-G2", 1.0, +1, False),
    "dangling_edges":        ("R-D2", 0.0, -1, False),
    "duplicate_chunks":      ("R-E3a", 0.02, -1, False),
}


def _offline(workspace: pathlib.Path, pages: int) -> Dict[str, object]:
    from structural_fidelity import (_canon, _page_tree, _shape, _spearman,
                                     _under, _visible_content)

    from vertiscope import tokens
    from vertiscope.address import ContentAddress
    from vertiscope.obsidian.sidecar import chunk_payload
    from vertiscope.workspace import Workspace

    out: Dict[str, object] = {}

    # Structural questions that need no store at all.
    out["shape_field_exists"] = float(
        any(f in ContentAddress.__dataclass_fields__ for f in ("shape", "template"))
        or hasattr(ContentAddress, "shape"))
    from vertiscope.obsidian.enact import ACTIONS
    out["scroll_port_exists"] = float("scroll" in ACTIONS)

    manifest = json.loads((CORPUS / "manifest.json").read_text())
    by_url = {p["url"]: p["slug"] for p in manifest["pages"] if p.get("ok")}

    with Workspace(workspace) as ws:
        chunks = list(ws.store.chunks())
        out["chunks"] = len(chunks)

        window = ws.context_window
        toks = [tokens.count(c.md or "") for c in chunks if (c.md or "").strip()]
        out["chunk_tokens_median"] = statistics.median(toks) if toks else 0
        out["chunks_over_window"] = (
            sum(1 for t in toks if t > window) / len(toks)) if toks else 0.0
        out["worst_overflow_ratio"] = (max(toks) / window) if toks else 0.0
        out["worst_chunk_tokens"] = max(toks) if toks else 0

        # Duplicate chunks, by rendered markdown.
        seen = Counter(" ".join((c.md or "").split()) for c in chunks
                       if (c.md or "").strip())
        dup = sum(n for k, n in seen.items() if n > 1)
        out["duplicate_chunks"] = dup / max(1, len(chunks))

        # Shape collapse, for R-C4's design rather than its bar.
        addresses = []
        for c in chunks:
            addresses.extend(ws.store.addresses_of(c.cid))
        exact = {(a.url, a.xpath, a.tag, a.accessor) for a, _v in addresses}
        shaped = {(a.url, _shape(a.xpath), a.tag, a.accessor) for a, _v in addresses}
        out["shape_collapse"] = 1 - len(shaped) / max(1, len(exact))
        by_shape = defaultdict(set)
        for a, v in addresses:
            by_shape[(a.url, _shape(a.xpath), a.tag, a.accessor)].add(
                " ".join((v or "").split())[:120])
        many = {k: vs for k, vs in by_shape.items()
                if sum(1 for b, _ in addresses
                       if (b.url, _shape(b.xpath), b.tag, b.accessor) == k) > 1}
        out["shape_lossy"] = (
            sum(1 for k, vs in many.items() if len(vs) > 1) / max(1, len(many)))

        # Pictures the layout would billboard -- asked of the LAYOUT's own
        # function, not of a second rule written here. A first attempt
        # counted only already-absolute srcs and reported 144 against the
        # layout's 253, because `_first_image` resolves relative ones
        # against the chunk's page. Two rules for one question is how a
        # board starts disagreeing with the thing it measures.
        from vertiscope.obsidian.layout import _first_image

        out["nodes_with_picture"] = sum(
            1 for c in chunks if _first_image(c.md or "", c.url) is not None)

        # Structural fidelity against the source pages.
        reach, rho, order_ok, order_all = [], [], 0, 0
        contain_ok = contain_all = 0
        urls = [u for u in ws.pages() if u in by_url][:pages]
        for url in urls:
            path = CORPUS / ("%s.html" % by_url[url])
            if not path.exists():
                continue
            paths = _page_tree(path.read_text(encoding="utf-8", errors="replace"))
            for chunk in list(ws.store.chunks(url))[:25]:
                payload = chunk_payload(ws, chunk.cid)
                if not payload or not payload["lines"]:
                    continue
                addressed = [p[1].split("/text()")[0]
                             for line in payload["lines"]
                             for p in [str(line.get("key") or "").split("|")]
                             if len(p) > 1]
                subtree = _under(paths, chunk.xpath)
                want = _visible_content(subtree)
                if not want:
                    continue
                got = {p for p in want
                       if any(_canon(a) == _canon(p)
                              or _canon(a).startswith(_canon(p) + "/")
                              for a in addressed)}
                reach.append(len(got) / len(want))

                positions = []
                for a in addressed:
                    for p, v in want.items():
                        if _canon(a) == _canon(p):
                            positions.append(v["order"])
                            break
                order_all += 1
                if positions == sorted(positions):
                    order_ok += 1

                pairs, drawn = [], {}
                for line in payload["lines"]:
                    parts = str(line.get("key") or "").split("|")
                    if len(parts) < 2:
                        continue
                    el = parts[1].split("/text()")[0]
                    text = line["text"]
                    d = (len(text) - len(text.lstrip(" "))) // 2
                    drawn[_canon(el)] = d
                    hit = next((v for p, v in subtree.items()
                                if _canon(p) == _canon(el)), None)
                    if hit is not None:
                        pairs.append((hit["depth"], d))
                r = _spearman(pairs)
                if r is not None:
                    rho.append(r)
                names = list(drawn)
                for a in names:
                    for b in names:
                        if a != b and b.startswith(a + "/"):
                            contain_all += 1
                            contain_ok += drawn[b] > drawn[a]

        out["reach_mean"] = statistics.mean(reach) if reach else 0.0
        out["reach_median"] = statistics.median(reach) if reach else 0.0
        out["reading_order"] = order_ok / max(1, order_all)
        out["depth_rho"] = statistics.mean(rho) if rho else 0.0
        out["containment"] = contain_ok / max(1, contain_all)
    return out


def _live() -> Dict[str, object]:
    """The numbers that only exist in the running app.

    Absent rather than guessed when Obsidian is not up: a billboard figure
    invented offline would be indistinguishable from a measured one on the
    board, and the board is the gate.
    """
    probe = REPO / "obsidian-plugin" / "probes" / "scoreboard-live.js"
    try:
        proc = subprocess.run(
            ["node", "cdp.mjs", "--file", str(probe)],
            cwd=str(REPO / "obsidian-plugin"),
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            return {"_live_error": (proc.stderr or proc.stdout).strip()[:200]}
        return json.loads(proc.stdout)
    except Exception as exc:                            # noqa: BLE001
        return {"_live_error": "%s: %s" % (type(exc).__name__, exc)}


def _fmt(key: str, value) -> str:
    if value is None:
        return "-"
    if key in ("chunks", "chunk_tokens_median", "nodes_with_picture",
               "dangling_edges", "resolved_edges", "sprites",
               "sprites_textured", "worst_chunk_tokens"):
        return str(int(value))
    if key == "worst_overflow_ratio":
        return "%.1fx" % float(value)
    if key in ("shape_field_exists", "scroll_port_exists"):
        return "yes" if value else "no"
    return "%.1f%%" % (100 * float(value))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=pathlib.Path,
                    default=REPO / "build" / "vaultws512")
    ap.add_argument("--pages", type=int, default=8)
    ap.add_argument("--live", action="store_true",
                    help="run the CDP probe here; needs Obsidian AND a free "
                         "workspace lock, which the sidecar holds")
    ap.add_argument("--live-from", type=pathlib.Path,
                    help="read the live rows from a file the probe already "
                         "wrote. The sidecar holds an exclusive kuzu lock, so "
                         "the live rows and the offline ones cannot be taken "
                         "in one process: probe first with the sidecar up, "
                         "stop it, then measure offline and merge.")
    ap.add_argument("--write", action="store_true",
                    help="write docs/prd_baseline.json")
    args = ap.parse_args(argv)

    now = _offline(args.workspace, args.pages)
    if args.live_from and args.live_from.exists():
        now.update(json.loads(args.live_from.read_text()))
    elif args.live:
        now.update(_live())

    before = {}
    if BASELINE.exists():
        before = json.loads(BASELINE.read_text()).get("measures", {})

    print("PRD scoreboard -- docs/PLUGIN_PRD.md acceptance criteria")
    print("=" * 78)
    print("%-24s %10s %10s %10s  %s"
          % ("measure", "now", "baseline", "bar", "verdict"))
    print("-" * 78)

    regressed, met = [], []
    for key in list(CRITERIA) + [k for k in now if k not in CRITERIA
                                 and not k.startswith("_")]:
        if key not in now:
            print("%-24s %10s %10s %10s  %s"
                  % (key, "-", _fmt(key, before.get(key)), "", "not measured"))
            continue
        req, bar, direction, taut = CRITERIA.get(key, ("", None, +1, False))
        value = now[key]
        was = before.get(key)
        verdict = ""
        ok = False
        if taut:
            verdict = "tautological -- confirms no bug, proves nothing"
        elif bar is not None:
            ok = (value >= bar) if direction > 0 else (value <= bar)
            verdict = "MET" if ok else "%s short of %s" % (
                req, _fmt(key, bar))
            if ok:
                met.append(key)
        # A regression is a GATED criterion that moved materially the wrong
        # way and is not already met. The first version flagged any decrease
        # in any row, and a rebuild that produced one chunk fewer -- 3136 to
        # 3135 -- reported six: `chunks`, `sprites`, `nodes_with_picture`,
        # `sprites_textured`, `billboards_textured` and `chunks_over_window`,
        # the last of which still displayed 1.2% and was still MET.
        #
        # Five of those are descriptive counts that gate nothing, and the
        # sixth was noise. A gate that fires on every rebuild is a gate
        # nobody reads, which would have cost more than the regressions it
        # was built to catch.
        if (was is not None and isinstance(value, (int, float))
                and bar is not None and not taut and not ok):
            delta = (value - was) * direction
            if delta < -_TOLERANCE.get(key, 0.01):
                verdict += "   REGRESSED"
                regressed.append(key)
        print("%-24s %10s %10s %10s  %s"
              % (key, _fmt(key, value), _fmt(key, was),
                 _fmt(key, bar) if bar is not None else "", verdict))

    if "_live_error" in now:
        print()
        print("live rows unavailable: %s" % now["_live_error"])

    print("-" * 78)
    gated = [k for k, (_r, bar, _d, taut) in CRITERIA.items()
             if bar is not None and not taut]
    print("%d of %d gated criteria met" % (len(met), len(gated)))
    if regressed:
        print("REGRESSIONS: %s" % ", ".join(regressed))

    if args.write:
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text(json.dumps(
            {"workspace": str(args.workspace), "measures": now},
            indent=2, sort_keys=True), encoding="utf-8")
        print("\nwrote %s" % BASELINE.relative_to(REPO))
    return 1 if regressed else 0


if __name__ == "__main__":
    raise SystemExit(main())
