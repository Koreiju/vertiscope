"""Every prompt the user typed, word for word, with what became of it.

``python -m vertiscope.analytics.prompt_ledger`` reads this project's Claude Code
transcripts and writes ``docs/PROMPT_LEDGER.md``: each prompt verbatim, and
beside it one verdict --

* ``LIVE``        a requirement or a standing rule that still binds;
* ``PROCESS``     a standing rule about HOW the work is done (binds too);
* ``SUPERSEDED``  replaced by a later prompt, named;
* ``PARTLY``      some of it superseded (named), the rest live;
* ``ONE-OFF``     an instruction carried out at the time;
* ``QUESTION``    a question, answered at the time.

Why it exists (2026-09-27, P137): *"find where our full transcript for the
conversation is stored and make sure to capture all details from my prompts
that aren't superseded by later prompts"*. A check of the transcript against
``PLUGIN_GOAL.md`` found forty-odd substantive prompts that were never
transcribed -- the observability rules, the DAG and clumping reports, the
collider factor, the billboard fields -- living only in a transcript nobody
rereads. The loop reads THIS file's live list every pass.

The verdicts are written by hand below (``VERDICTS``), keyed by prompt
number; the prompts themselves are always re-read from the transcript, so
the verbatim can never drift. A prompt with no verdict is printed as
``UNREVIEWED`` -- the pressure that makes the next one get read.
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPTS = os.path.join(os.path.expanduser("~"), ".claude", "projects",
                           "C--Users-user-Documents-vertiscope", "*.jsonl")
OUT = ROOT / "docs" / "PROMPT_LEDGER.md"

_MID = re.compile(r"The user sent a new message while you were working:\n(.*?)\n\n"
                  r"This is how Claude Code surfaces", re.S)
_STRIP = [re.compile(p, re.S) for p in (r"<system-reminder>.*?</system-reminder>",
                                         r"<local-command-caveat>.*?</local-command-caveat>",
                                         r"<local-command-stdout>.*?</local-command-stdout>")]


def prompts(pattern: str = TRANSCRIPTS) -> List[Dict]:
    """The user's own prompts, in time order, de-duplicated."""
    rows: List[Tuple[str, str]] = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ts = rec.get("timestamp", "")
                if rec.get("type") == "attachment":
                    att = rec.get("attachment") or {}
                    if att.get("type") == "queued_command":
                        pr = att.get("prompt")
                        imgs = sum(1 for b in (pr if isinstance(pr, list) else [])
                                   if isinstance(b, dict) and b.get("type") == "image")
                        texts = [pr] if isinstance(pr, str) else [
                            b.get("text", "") for b in (pr or [])
                            if isinstance(b, dict) and b.get("type") == "text"]
                        for t in texts:
                            t = t.strip()
                            if t and not t.startswith("<task-notification>"):
                                tag = "[mid-turn, %d image(s)] " % imgs if imgs else "[mid-turn] "
                                rows.append((ts, tag + t))
                    for r in rec.get("rendered") or []:
                        c = r.get("content") if isinstance(r, dict) else None
                        if isinstance(c, str):
                            rows += [(ts, "[mid-turn] " + m.group(1).strip()) for m in _MID.finditer(c)]
                    continue
                if rec.get("type") != "user" or rec.get("isCompactSummary") or rec.get("isMeta"):
                    continue
                content = (rec.get("message") or {}).get("content")
                texts = [content] if isinstance(content, str) else [
                    b.get("text", "") for b in (content or [])
                    if isinstance(b, dict) and b.get("type") == "text"]
                for t in texts:
                    rows += [(ts, "[mid-turn] " + m.group(1).strip()) for m in _MID.finditer(t)]
                    for rx in _STRIP:
                        t = rx.sub("", t)
                    t = t.strip()
                    if (not t or t.startswith("This session is being continued")
                            or t.startswith("[Request interrupted")
                            or t.startswith("<task-notification>")
                            or t.startswith("<ci-monitor-event>")):
                        continue
                    rows.append((ts, t))
    seen, out = set(), []
    for ts, t in sorted(rows, key=lambda r: r[0]):
        key = re.sub(r"^\[mid-turn[^\]]*\] ", "", t)[:300]
        if key in seen:
            continue
        seen.add(key)
        out.append({"ts": ts, "text": t})
    return out


# ---- the verdicts, by prompt number (P-number = position in time order) ----
#
# (status, what still binds -- or what replaced it, rows)
VERDICTS: Dict[int, Tuple[str, str, str]] = {
    1: ("QUESTION", "", ""), 2: ("ONE-OFF", "", ""), 3: ("QUESTION", "", ""),
    4: ("PROCESS", "Keep searching for similar plugins, repos and MCP tools while building.", "standing rule 1"),
    5: ("LIVE", "A kernel runs in place; a command terminal opens in a SEPARATE pane.", "P-N2"),
    6: ("ONE-OFF", "", ""), 7: ("ONE-OFF", "", ""), 8: ("ONE-OFF", "", "T-5"), 9: ("ONE-OFF", "", ""),
    10: ("ONE-OFF", "", ""), 11: ("ONE-OFF", "", ""), 12: ("ONE-OFF", "", "P-N1"), 13: ("ONE-OFF", "", ""),
    14: ("PROCESS", "See the whole Obsidian interface through MCP tools, well enough to navigate it yourself.", "G-75"),
    15: ("PROCESS", "Interact with the existing panels and the 3D graph: see and touch exactly what the user can.", "G-75"),
    16: ("PROCESS", "Fill perception gaps from GitHub prior art, ideally without images.", ""),
    17: ("ONE-OFF", "", ""),
    18: ("PROCESS", "Know every interactable surface, tool and workspace, and the relevant GitHub packages.", ""),
    19: ("ONE-OFF", "", ""),
    20: ("LIVE", "Terminal pane: a window cut (content clipped). Re-check when the terminal pane is next touched.", "P-N2"),
    21: ("LIVE", "PowerShell terminal: loose space. Re-check with P020.", "P-N2"),
    22: ("ONE-OFF", "", ""),
    23: ("SUPERSEDED", "Spherical/quaternion UMAP -- dropped by P048.", ""),
    24: ("PARTLY", "Collider 'quarter distance' factor superseded by P134 (INTEGER safety factor). LIVE: search "
         "GitHub for force layouts initialised from UMAP; duplicate chunks; image-only chunks where text "
         "should be attached; NAKED FIELDS whose names are missing; missing content in the shadow-DOM "
         "chunk rendering, which must point back to the browser.", "G-94, G-99, G-102"),
    25: ("ONE-OFF", "(image for P024)", ""), 26: ("ONE-OFF", "", "D-8"), 27: ("ONE-OFF", "", ""),
    28: ("PROCESS", "Always interface with the app yourself to confirm and actuate.", "G-75"),
    29: ("LIVE", "Billboards get their OWN diameters for collision: large square panels, not small nodes.", "G-94"),
    30: ("LIVE", "(clarifies P029: billboard panels.)", "G-94"),
    31: ("LIVE", "Patricia links and inter-markdown links must be visible in the graph.", "G-6, G-84"),
    32: ("LIVE", "No repeat chunks, repeat content within a chunk, repeat images.", "G-24, G-98"),
    33: ("LIVE", "No duplicate image billboards; billboards carry more fields than image + alt; link text "
         "excluded from the token COUNT.", "G-81, G-102"),
    34: ("LIVE", "Links excluded from counting ONLY -- everything else unchanged.", "G-86"),
    35: ("LIVE", "URL tails feed frequency vectors, never the semantic embeddings (pure text, no links).", "G-3"),
    36: ("PARTLY", "Addendum IV. Superseded: the switchable second view (P110 side panel). LIVE: two-stage "
         "chunking, db-side dedup first, embedding merges to 512, hover highlight without banners, "
         "overlay retrieval, interactive shadow-DOM chunks tied to the live page.", "Addendum IV rows"),
    37: ("PARTLY", "Repeat of P036 plus 'run the scan over 100 new pages'.", ""),
    38: ("LIVE", "The scans must be SEEN running in the browser panel.", "G-76"),
    39: ("LIVE", "The codebase, the vault and installed PyPI packages are in the corpus; dependencies tracked "
         "throughout; the scanning code is visible beside the scan.", "G-49, G-51, G-104"),
    40: ("LIVE", "Vectorize comments and docstrings only, never the code.", "G-52"),
    41: ("LIVE", "Continuous scanning while the user navigates, every chunk update streamed live to the GUI.", "S-12, G-92"),
    42: ("LIVE", "Transform batches through the fitted UMAP; re-fit when the scanned total doubles.", "G-67, G-74"),
    43: ("ONE-OFF", "", "G-65"), 44: ("ONE-OFF", "", "G-65"),
    45: ("LIVE", "Merged chunks: re-vectorize (preferred) over averaging.", "G-72"),
    46: ("LIVE", "512 max for text-only tokens; the projector shows merged vectors, retrieval runs on 256.", "G-72"),
    47: ("PARTLY", "Spherical part superseded by P048; full aggregation over what is already stored stays live.", "G-65"),
    48: ("LIVE", "Drop spherical/quaternion; focus on faster streaming and visible feedback in the projector.", ""),
    49: ("QUESTION", "", ""), 50: ("ONE-OFF", "", ""),
    51: ("PARTLY", "Spherical part superseded by P048; asynchronous processing stays live.", "G-66"),
    52: ("LIVE", "Addendum IV long statement: offline fallback, save page for offline, retrieval overlay, "
         "coarse-to-fine retrieval, billboard in 3D + browser scrolls to chunk, collapsed page view, "
         "fps, millisecond O(delta) budget.", "Addendum IV rows"),
    53: ("PARTLY", "Continuous scroll over ranked retrieval, click scopes to the url: LIVE. 'Right-click restores "
         "global scope' superseded by P128 (single right-click = browser menu).", "G-69, G-70"),
    54: ("ONE-OFF", "", ""), 55: ("ONE-OFF", "", ""), 56: ("ONE-OFF", "", ""), 57: ("ONE-OFF", "", ""),
    58: ("LIVE", "GUI degradation reports are checked by using the app.", "G-88"),
    59: ("QUESTION", "", ""), 60: ("ONE-OFF", "", ""),
    61: ("LIVE", "Unfolded nodes are LINKED in the 3D graph.", "G-6"),
    62: ("QUESTION", "", ""), 63: ("QUESTION", "", ""),
    64: ("PROCESS", "Organise every remaining item so both sides can see what changed; tested against what "
         "is recorded; the totality of contexts persists.", "design_state"),
    65: ("ONE-OFF", "", ""), 66: ("ONE-OFF", "", ""),
    67: ("PROCESS", "/goal: cover every open item by building and testing live in the running plugin; "
         "everything in the doc built and confirmed.", "G-75"),
    68: ("LIVE", "Opening pages must NOT reset other chunks' UMAP positions; every chunk gets its own 3D "
         "coordinates, not a jumble in the centre.", "G-96"),
    69: ("PROCESS", "Self-reports are not delivery: prove each requirement in the UI; full-stack observability "
         "before progress counts.", "G-75, G-103"),
    70: ("PROCESS", "Hook yourself up to the MCP tools.", "G-75"),
    71: ("PROCESS", "Treat it as HARNESS engineering: data-structure-level capture of the interface over "
         "screenshots; multi-step interactions monitored, inspected, changed, verified.", "G-75, G-103"),
    72: ("PROCESS", "Wrap the whole UI layer: frontend interactions AND traces of the backend work they cause.", "G-75"),
    73: ("PARTLY", "Chunks force-directed inside force-directed/UMAP page nodes (scale-wise). The layout "
         "scheme is now P134's stream order.", "G-92"),
    74: ("LIVE", "Recentering works; nodes never disappear from the UI.", "G-21"),
    75: ("PROCESS", "Screenshots only where data cannot tell -- like a vanished picture.", "G-103"),
    76: ("PROCESS", "(repeat of P069 + P071 + P072.)", "G-75"),
    77: ("ONE-OFF", "", ""),
    78: ("LIVE", "Guard: 3D nodes never go invisible after harness/MCP changes.", "G-21"),
    79: ("ONE-OFF", "", ""),
    80: ("PARTLY", "Two-layer UMAP superseded by P109/P134; the force-directed unfold on the patricia tree is live.", "G-84, G-95"),
    81: ("PROCESS", "Use the app yourself and state what the MCPs show; build until every observable "
         "requirement is provable through the toolspace. Tool calls everywhere, no bash scripts.", "G-75, G-103"),
    82: ("LIVE", "Nodes not clumped: per-page UMAP + force-directed patricia unfolds.", "G-85, G-93"),
    83: ("LIVE", "The patricia structure is a DAG that FANS OUT with flexible link lengths.", "G-84"),
    84: ("LIVE", "Force-directed patricia unfolds per the spec on node sizing and structure; live scans "
         "persist and stream; hover highlight and right-click markdown work -- verify every one.", "G-84, S-12, G-79"),
    85: ("LIVE", "DAG links correct and the measurement of them true.", "G-84"),
    86: ("ONE-OFF", "", ""),
    87: ("LIVE", "The page open in the browser expands when clicked; fan-out nodes carry their images.", "G-81, G-100"),
    88: ("LIVE", "Bounded links jumble an open node into a cloud: no upper bound (P134 agrees).", "G-85, G-93"),
    89: ("ONE-OFF", "", ""),
    90: ("LIVE", "Every expanded node is a tree (one parent per node).", "G-84"),
    91: ("LIVE", "(same, for the node open in the browser.)", "G-84"),
    92: ("PROCESS", "Measure with the harness until the defect is verified, then fix until the measure says so.", "G-84"),
    93: ("QUESTION", "", ""),
    94: ("LIVE", "Images on fan-out nodes; much longer max link lengths, measured twice; stream O(delta) "
         "diffs in queued batches to a fitted UMAP, re-fit at 2x; content detection from the FULLEST "
         "dictionaries; right-click highlight (non-blinding) over the chunk's box; hover chunks first; "
         "full time profile to the 3D view, observed by a listener on the graph; tests at each level.",
         "Addendum V, G-67, G-74, G-80, G-90, G-99"),
    95: ("ONE-OFF", "", ""), 96: ("ONE-OFF", "", ""), 97: ("ONE-OFF", "", ""),
    98: ("QUESTION", "", ""), 99: ("QUESTION", "", ""),
    100: ("LIVE", "The live pipeline readout is a small black box, bottom right of the browser, showing the "
          "real processing: hover, streams to the projector, every 256 chunk embedded and transformed.", "G-76"),
    101: ("LIVE", "The plugin surfaces the whole pipeline, including how the layout is computed.", "G-76"),
    102: ("LIVE", "The plugin's features run on the CURRENT pipeline, not the original code.", "G-72, G-75"),
    103: ("PROCESS", "Keep the focus on the plugin prompts, the measurements and the pipeline.", ""),
    104: ("LIVE", "No panel or log may cover the 3D view.", "G-76"),
    105: ("ONE-OFF", "", ""),
    106: ("LIVE", "All tests/sweeps inside Obsidian as a plugin-facing component, observable via MCP; remove "
          "the separate statistics panels.", "G-75, G-76"),
    107: ("ONE-OFF", "(stray keystroke)", ""),
    108: ("PROCESS", "Collect every earlier prompt on highlight-on-hover.", "G-79"),
    109: ("PARTLY", "Superseded: 'left-click expands, right-click contracts' (P128, P134: click toggles); "
          "UMAP on page centroids simplified by P134 (sub-chunk centroid through the fit). LIVE: the "
          "patricia TREE (content-node subtree, single-child chains as one link, one parent), open a "
          "page's WHOLE tree at once, much longer links; report the token-count rules.", "G-83, G-84, G-85, G-95"),
    110: ("LIVE", "Async stages so chunking never waits on vectorizing; heading + paragraph one chunk; "
          "side-by-side panel replaces the hidden second view; design from the whole context, not shims.", "G-82, G-86"),
    111: ("LIVE", "Loop on the verbatim; lenient 256 cut (closer to 256 than 512 keeps the merge).", "G-86"),
    112: ("LIVE", "Every test run on a fresh, empty store.", "G-87"),
    113: ("ONE-OFF", "", ""), 114: ("QUESTION", "", ""),
    115: ("PROCESS", "Audit by using the app; peripheral changes tracked; verbatim -> harness/MCP/tests/"
          "plugin -> user stories; store refreshes with every suite.", "G-88"),
    116: ("PROCESS", "Features verifiable over MCP first; all tests run on the plugin.", "G-75"),
    117: ("PROCESS", "All tests run inside the GUI; results observed in the app.", "G-75"),
    118: ("PROCESS", "Build and run ON THE APP, not in terminal commands.", "G-75"),
    119: ("PARTLY", "Force-directed first on the diff, from the in-page chunking, before vectors; phase "
          "contracts as state-sequence tests on the MCP surfaces: LIVE. The collapse trigger is P134's.", "G-89, G-92"),
    120: ("PARTLY", "Force-directed first: LIVE. 'Page-centroid fit first' simplified by P134.", "G-89, G-97"),
    121: ("SUPERSEDED", "Collapse after the transform -- replaced by P134 (collapse when SAVED).", "G-92"),
    122: ("LIVE", "Millisecond profile from the browser's overlay to the 3D GUI.", "G-90"),
    123: ("PARTLY", "Force-directed stays available when a page node is expanded before its transform: LIVE; "
          "the when is P134's.", "G-92"),
    124: ("LIVE", "Force-directed nodes must not be jumbled.", "G-93"),
    125: ("LIVE", "Fastest, instant, visually clean streaming layout.", "G-92, G-93"),
    126: ("LIVE", "Overlay in single-digit ms, async with vectorizing, before the 3D update.", "G-90"),
    127: ("LIVE", "Right-click never says 'nothing under the cursor' over a chunk.", "G-39"),
    128: ("LIVE", "Double right-click pins; single right-click is the browser's menu.", "G-39"),
    129: ("LIVE", "Browser navigation fully tested in the harness: overlay, back, forward, refresh, url, scan.", "P-B2"),
    130: ("LIVE", "A definition (heading + lead + list) is ONE chunk.", "G-86"),
    131: ("QUESTION", "(answered: colored nodes are chunks placed by the chunk projector's UMAP.)", ""),
    132: ("LIVE", "Billboard: minimize button; x removes from 3D only; clicking the side card re-expands it.", "G-78"),
    133: ("PROCESS", "Collect the full list first, then fix -- streaming diffs, highlights, transforms, WHEN "
          "collapses happen.", "G-91"),
    134: ("LIVE", "Addendum IX: the stream order, collapse on save, integer collision factor, root click "
          "toggles, UMAP coords persisted, everything on a page detected, media cached, hard pages, "
          "billboard HTML, notebooks + package trees, D-35, one visual-judgement loop.", "G-92..G-105, D-35"),
    135: ("PROCESS", "Every test runs through the app, observable to the tools and to Claude.", "G-103"),
    136: ("ONE-OFF", "(sidecar restarted.)", ""),
    137: ("PROCESS", "Every non-superseded detail of every prompt is carried by the loop: this ledger.", "G-103"),
    138: ("LIVE", "Both chunk panels (billboard, side card) must render like the page: inline runs whole, "
          "controls not '( label )', pictures load.", "D-36, G-102"),
    139: ("LIVE", "(repeat of P138) The panels render the page's OWN rendering of the chunk, not a "
          "reconstruction from distilled lines; the distilled form is secondary/offline.", "D-36"),
    140: ("LIVE", "Streaming must meet the millisecond overlay requirement while interacting and loading new "
          "diffs; new-diff overlays must be seen.", "D-35, D-37, G-90"),
    142: ("LIVE", "The page-centroid UMAP is the default projector.", "G-83, G-97"),
    143: ("PROCESS", "UMAP fits once and transforms after; check the docs/web before assuming.", "G-97"),
    144: ("LIVE", "Train ONLINE on the diff after it is first transformed; previous fits held fixed; parameters persist.", "G-96, G-97"),
    145: ("LIVE", "Online training uses the local CUDA runtime.", "G-97"),
    146: ("LIVE", "The browser cell must never be left blank: a hung window recovers, the last page reopens.", "D-38"),
    147: ("LIVE", "Page nodes read as pages; nothing but the reader's pages in the picture (no test leakage).", "G-94, D-39"),
    148: ("LIVE", "Scanning nodes stay NEAR the nodes they belong to; spacing alone is not the measure.", "G-93"),
    149: ("LIVE", "Refit, online updates and streaming all run the CUDA model, visibly faster.", "G-97"),
    150: ("LIVE", "Open pages drawn as a SIMPLE TREE (one parent, no cross links); favicons on url nodes; "
          "the most relevant picture (by rendered size) on chunks; the 3D billboard looks like the 2D card.",
          "G-84, G-81, G-100, G-102, D-36"),
    151: ("LIVE", "A planted search page must never lose its scan: a store switch leaves the sensor's dictionary "
          "stale unless capture restarts (fixed: backToReader + restartCapture).", "D-37, G-101"),
    152: ("LIVE", "Hover and diffs stream in milliseconds after a long scroll, never waiting on the store or "
          "downstream queues: pushed from the page, not polled.", "D-40, D-35, G-90"),
    153: ("PROCESS", "A defect seen on a named site is confirmed ON that site, timed by an observer independent of the "
          "code under test, planted arm on the same site; a fixture is a secondary arm, never the judged one.",
          "D-40, D-35, D-36, D-37, G-94"),
    154: ("LIVE", "The lag was on the Julia forum (discourse.julialang.org/latest): D-40 is judged there.", "D-40"),
    155: ("LIVE", "An open page's layout keeps its geometry: no overlaps (the page's billboard included), a spread disc, a "
          "simple planar tree, nothing flung out -- and still after an orbit.", "G-94, D-41"),
    156: ("LIVE", "An open page is laid out BY FORCES (tree springs, integer collider, page room), not a pinned geometry; "
          "a geometric layout may seed it, never replace it; the edges drawn are the tree laid out.", "G-94, D-41"),
    157: ("LIVE", "A flat star (many chunks under one page) must not rest as a ring: the forces fill a disc or ball.", "G-94, D-41"),
    158: ("LIVE", "Nothing in the 3D layout follows the camera -- no re-facing on orbit, no seeding in the camera's plane -- "
          "and what is force-directed keeps working.", "G-94, D-41"),
    159: ("LIVE", "Trace the stream stage by stage and make the app match it: fold on save, UMAP positions for projected "
          "chunks, update()-style incremental transforms for new nodes, refit re-projects; the update's scope (every chunk "
          "vs page centroids) chosen by measured GPU cost.", "G-92, G-96, G-97, G-106"),
    160: ("NOTE", "An incomplete message (\"I\"); nothing to act on.", ""),
    161: ("LIVE", "Measure duplicate nodes in the 3D view and duplicate chunks in the store, both ways, with a planted duplicate.", "G-98"),
    162: ("PROCESS", "Gate in-app runs on the reader's use of the APP, not machine-wide idle.", ''),
    163: ("LIVE", 'The pipeline checks must not break down mid-run (a run stuck seeding, fighting the reader).', 'G-75, G-87'),
    164: ("LIVE", 'The streaming force tree stays calm between rapid-fire updates.', 'G-93'),
    165: ("LIVE", "Diffs reach the store in about one capture's time however fast the page drains.", 'D-42'),
    166: ("PROCESS", 'Bring the whole stack back up after a reboot (sidecar, Obsidian with flags, plugin).', ''),
    167: ("LIVE", 'Obsidian must not freeze while scrolling the Julia forum (D-38: renderer OOM).', 'D-38'),
    168: ("LIVE", 'Formal nested requirements/design model over the design history; focused module tests; the rest of the pending requirements built; Merkle-subtree dedup as in the reference serializer; the star layout tracked; GPU update() refits observable; lighter overlays; one full-pipeline harness with time AND memory profiles, rendering included.', 'D-38, D-41, G-98, G-106'),
    169: ("LIVE", 'Obsidian froze again (D-38).', 'D-38'),
    170: ("PROCESS", 'A rapid scroll-and-hover stress gesture on the site where it happens, with time and memory profiling.', 'D-38'),
    171: ("LIVE", 'Every scanner diff reaches the 3D view with the same latency and in the same proportion.', 'G-89, G-90, D-40'),
    141: ("LIVE", "The 3D layout AFTER collapse must not be jumbled (measured as seen, on screen); the hard-page "
          "list must be a real, comprehensive in-app suite.", "G-94, G-101"),
}


def render(ps: List[Dict]) -> str:
    live = [(i, VERDICTS.get(i)) for i in range(1, len(ps) + 1)]
    lines = [
        "# Prompt ledger -- every prompt, word for word, and what became of it",
        "",
        "*Generated by `python -m vertiscope.analytics.prompt_ledger` from the Claude Code",
        "transcripts; do not edit by hand -- edit `VERDICTS` in that module.* The loop",
        "(`G-103`) reads the **Still binding** list every pass. `PLUGIN_GOAL.md` stays the",
        "binding record; this is the index that proves nothing in a transcript was lost.",
        "Transcripts cover 2026-09-12 onward; earlier direction lives only in",
        "`PLUGIN_GOAL.md` (the opening statement and Addenda I-III).",
        "",
    ]
    counts: Dict[str, int] = {}
    for _i, v in live:
        k = v[0] if v else "UNREVIEWED"
        counts[k] = counts.get(k, 0) + 1
    lines.append("**%d prompts:** " % len(ps) + ", ".join("%s %d" % kv for kv in sorted(counts.items())))
    lines += ["", "## Still binding (LIVE, PARTLY, PROCESS)", "",
              "| # | when | status | what still binds | rows |", "|---|---|---|---|---|"]
    for i, v in live:
        if v and v[0] in ("LIVE", "PARTLY", "PROCESS"):
            lines.append("| P%03d | %s | %s | %s | %s |" % (i, ps[i - 1]["ts"][:10], v[0],
                                                          v[1].replace("|", "/"), v[2]))
    un = [i for i, v in live if not v]
    if un:
        lines += ["", "## UNREVIEWED", ""] + ["- P%03d" % i for i in un]
    lines += ["", "## Superseded", "", "| # | replaced by |", "|---|---|"]
    for i, v in live:
        if v and v[0] == "SUPERSEDED":
            lines.append("| P%03d | %s |" % (i, v[1]))
    lines += ["", "## The prompts, verbatim", ""]
    for i, p in enumerate(ps, 1):
        v = VERDICTS.get(i)
        lines.append("### P%03d -- %s -- %s" % (i, p["ts"][:16].replace("T", " "), v[0] if v else "UNREVIEWED"))
        lines.append("")
        text = p["text"]
        if i > 1 and len(text) > 2000 and text[-3000:] in ps[i - 2]["text"]:
            head = text.split("\n")[0]
            lines += ["> " + head, "> *(the rest repeats P%03d word for word)*" % (i - 1), ""]
            continue
        lines += ["> " + ln if ln.strip() else ">" for ln in text.splitlines()] + [""]
    return "\n".join(lines) + "\n"


def main() -> None:
    ps = prompts()
    OUT.write_text(render(ps), encoding="utf-8")
    missing = [i for i in range(1, len(ps) + 1) if i not in VERDICTS]
    print("wrote %s: %d prompts, %d unreviewed" % (OUT, len(ps), len(missing)))


if __name__ == "__main__":
    main()
