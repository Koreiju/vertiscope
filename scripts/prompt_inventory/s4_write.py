"""Write docs/PROMPT_INVENTORY.md: every message the reader typed since
2026-10-04, where it is recorded, what it became, and whether it landed."""
import json, re, sys
from collections import Counter

S = sys.argv[1]
inv = json.load(open(S + "/inventory2.json", encoding="utf-8"))

# Manual readings for messages the matcher could not place, or placed wrongly.
NOTE = {
    0: ("G-109..G-112", "Read as 11 points (goal L2072). (1)-(5), (7)-(11) became G-109 central diff, G-110 fold/unfold, G-111 live panels, G-112 the tree, G-116 trie stream, G-117 media. (6) Obsidian's own force-directed graph as a candidate: never evaluated or ruled on -- row G-259 (Open), asked 2026-10-18."),
    9: ("G-117, G-255", "Missing images: G-117 (no status line -- unstated). The git-history search tool was built (`vertiscope-git` MCP, `368dacc`); row G-255 added 2026-10-18 (Done)."),
    10: ("G-139", "Duplicated images: one image per element (`83dfd5c`), G-139 for the page form (Confirm)."),
    11: ("G-255", "The minimal adapter -- queries run on git, vectors only a cache (`368dacc`, the `vertiscope-git` MCP used in this session); row G-255 (Done)."),
    17: ("G-130", "Stale page form on image billboards: G-130 (both forms complete, Confirm, live pass)."),
    18: ("G-115", "Voronoi repulsion: considered, then dropped on your next message (#34); G-115 telescoping instead (Partly)."),
    24: ("G-110", "Clicking a page node: G-110 fold/unfold (Partly, live pass)."),
    26: ("G-112, G-115", "The voronoi-looking fans: long edges and a dense ball -> G-112 (the tree) and G-115 (telescoping)."),
    28: ("D-44", "archive.org not detected: D-44 (Done)."),
    103: ("G-187", "The ring: G-187 no ring around an open page (Confirm)."),
    104: ("G-187", "As #103."),
    106: ("G-181", "Node sizes: G-181 one size in chunk view, pictures differ (Confirm)."),
    146: ("G-172", "Glow invisible: G-172 (Confirm, but its last live check FAILED)."),
    147: ("G-184, G-182", "Ray reveal too far: G-184 bounded cylinder (Confirm); jumbling G-182 (Confirm)."),
    148: ("G-186", "Overlay vs the context-window cut: G-186 every line its own address (Confirm)."),
    151: ("G-258", "Fixed in code; its row (added 2026-10-18) is a node click reveals the element its FIRST line draws (`graph.ts`, 2026-10-12). Not live-checked."),
    157: ("-", "Answered 2026-10-17 by your choices: unsettling had stopped; probes only while you are idle; layout kept."),
    167: ("G-211", "k = shown, n = retrieved (item 142): G-211 the k/n fields -- OPEN."),
    180: ("-", "Process: the moved-subtree re-address test fixed (2026-10-18)."),
    1: ("G-190", "Clicking a node now drives the browser (G-190, Confirm); a scanned page's url node unfolds on click (G-199)."),
    2: ("-", "Checked today: Obsidian is in dark mode (`theme-dark`, theme `obsidian`)."),
    3: ("G-109", "Checked today: torch 2.6.0+cu124, CUDA available. The central diff is G-109 (Partly; live pass)."),
    5: ("G-162", "Answered later by the overlay toggle (G-162: boxes shown or hidden by alpha only, Confirm). Their default opacity itself was never given a row."),
    7: ("-", "Process: parallel agents were used 2026-10-06 (worktree merges `b021104`, `07adc24`, `5110246`)."),
    19: ("D-46, G-130", "Empty page-side panel and blank billboards: D-46 (billboards empty/slow, Done) and the dual-panel rewrite G-130."),
    21: ("G-130", "The old dual panel: replaced by the two-form panel, G-114/G-130."),
    23: ("G-139", "Duplicate image in the markdown: one image per element (`83dfd5c`); G-139 for the HTML form."),
    30: ("D-35", "No diff updates while navigating: D-35, which FAILED its last live check."),
    35: ("G-117", "Hovered options with no overlay -- controls inside shadow roots: G-117 (every element detected) has no status line of its own. NOT VERIFIED."),
    36: ("-", "Process: the task ledger is the PRD plus `design_state.md` (computed)."),
    37: ("-", "Process (as #36)."),
    44: ("G-113, G-124", "Continuous fly-follow: G-113 (Partly, live pass), G-124 zoom kept (live pass). The PRD became the task list, as asked."),
    47: ("G-144, D-46", "Flicker: one outline per hover (G-144, Confirm); the hover panel's open/close/open loop fixed in `hoverPanel` (2026-10-06 comment)."),
    48: ("D-46", "Billboard render speed: D-46; `/chunk` 0.36-2.0 s -> 0.10-0.15 s (`d69b56e`)."),
    49: ("G-216, G-220", "Read as the virtual list RECYCLING its elements (archive.org). Constant in-place rewrites: G-216, G-220 (Confirm). If you meant something else, say so."),
    50: ("D-45", "Oversized archive boxes: boxes clipped to their own elements (`da12f24`, 258 -> 177 px); D-45 Done."),
    58: ("G-122", "Overlay split into subchunks: G-122 (one card one outline, live pass)."),
    89: ("G-145", "Freezes: G-145 (tens of thousands of nodes without a freeze, Confirm)."),
    94: ("G-145, G-146", "Freeze and image hover in chunk view: G-145, G-146."),
    99: ("G-145", "As #89."),
    120: ("-", "Process: a reminder to keep the open list -- the reason for this inventory."),
    128: ("G-178", "Typing ranks the store only; the web half runs on the search button and Enter (G-178, Confirm)."),
    130: ("G-256", "Fixed in code; its row (added 2026-10-18) is the field you are typing in gets the keyboard back when the cell's own action took it (`browser.ts` `giveBackFocus`, 2026-10-11). Not live-checked."),
    132: ("G-180", "Arrow keys step the k/n boxes at an adaptive rate: `searchfield.ts` (G-180 group, Confirm)."),
    135: ("G-182", "Jumbling and latency on streams: G-182."),
    136: ("G-182", "As #135."),
    138: ("G-182", "As #135."),
    143: ("G-254", "Load time: NO requirement was written for it at the time. Row G-254 added 2026-10-18 (Open: not yet defined or measured)."),
    145: ("G-254", "As #143."),
    150: ("G-257", "Fixed in code; its row (added 2026-10-18) is invisible pick spheres up to 21.5x the drawn node are now resized every sync (`graph.ts` `fitProxies`, planted `plantStaleProxies`, 2026-10-12). Not live-checked."),
    154: ("-", "Process (resume) -- the matcher's G-190 link is spurious."),
    155: ("G-118", "Use and debug the new MCP tools: G-118 (the MCP sees what the reader sees, Partly)."),
    157: ("G-245", "Camera and coordinate unsettling: G-245 glides and recentre (Partly)."),
    165: ("G-213", "Darken nodes in front of a presented picture: G-213 (Partly)."),
    166: ("G-185", "xyzhsv stalls, debounce faster: G-185 (Confirm, live pass)."),
    167: ("G-210, G-212", "Shown vs retrieved: G-210 tiered retrieval, G-212 the graph follows the latest re-ranked set (both Partly)."),
    168: ("G-215", "Panel toggle and right-click on hover: G-215 (Partly)."),
    169: ("G-216, G-217", "Archive leakage, chunk streams that never pipe out: G-216 (Confirm), G-217 (Partly)."),
    177: ("G-221..G-230", "Ten requests, numbered 146-159 in the goal doc: G-221 back-navigation diff, G-222 result strip, G-223 retrieval latency, G-224 click latency, G-225 the 2000 cap, G-226 oldest-first, G-227 zoom lag, G-228 huge nodes, G-229 zoom kept, G-230 per-hover spread."),
    179: ("G-232", "Fly-to/right-click toggle governs strip hovers: G-232 (Confirm)."),
    181: ("G-233..G-241", "Code artifacts: G-233..G-241 (Addendum XI)."),
    196: ("-", "Done 2026-10-18: 27 -> 105 GB free; you chose which store copy to delete."),
    199: ("-", "This inventory."),
}


def verdict(rows):
    if not rows:
        return "no row"
    st = [s for _, s, _ in rows]
    lv = [v for _, _, v in rows]
    if "FAIL" in lv:
        return "live FAIL"
    if "open" in st:
        return "open"
    if "partly" in st or "unstated" in st:
        return "partly"
    if all(s in ("confirm", "done", "superseded", "standing") for s in st):
        # Confirm = built and checked by a test or probe; only YOU move it on.
        return "landed + live check passed" if any(v == "pass" for v in lv) else "landed (tested)"
    return "?"


statuses = {}
sys.path.insert(0, ".")
import vertiscope.analytics.design_state as _ds
ST, LIVE = {}, {}
for _l in open("docs/PLUGIN_PRD.md", encoding="utf-8"):
    _l = _l.rstrip("\n"); _m = _ds.ROW.match(_l)
    if _m:
        _c = _l.split(" | ")
        ST[_m.group(1)] = _ds.classify(_c[-1].rstrip("| ").strip() if len(_c) > 2 else _m.group(3))
for _l in open("build_analytics/live_confirmations.md", encoding="utf-8"):
    _m = re.match(r"^\| `([A-Z]+-\d+)` \|.*?\| \*\*(pass|FAIL)\*\*", _l)
    if _m: LIVE[_m.group(1)] = _m.group(2)
for l in open("build_analytics/design_state.md", encoding="utf-8"):
    pass
out, counts = [], Counter()
for i, r in enumerate(inv):
    if r["kind"] == "process" and i not in NOTE:
        counts["process"] += 1
        continue
    rows = r.get("all_rows", []) if i not in NOTE or not NOTE[i][0].startswith(("NEW", "-")) else []
    note = NOTE.get(i, ("", ""))[1]
    v = verdict(rows)
    if i in NOTE:
        tag = NOTE[i][0]
        if tag == "-":
            v = "process" if note.startswith("Process") else "done (checked)"
        elif tag == "no row":
            v = "fixed in code, no row"
        elif tag.startswith("NEW"):
            v = "NOT LANDED -> new row"
        elif v == "no row":
            # The rows the hand-written note names decide it, as a matched row would.
            named = [(r_, ST.get(r_, "?"), LIVE.get(r_, "-")) for r_ in re.findall(r"\b[GD]-\d+\b", tag)]
            rows = named
            v = verdict(named) if named else "placed by hand"
    counts[v] += 1
    recorded = ("goal L%d" % r["goal_line"]) if r.get("goal_line") else ("goal (quoted)" if r.get("in_goal_anywhere") else "NOT IN THE GOAL DOC")
    rowtxt = ", ".join("%s %s%s" % (a, s, "" if lv == "-" else " / live " + lv) for a, s, lv in rows) or (NOTE.get(i, ("", ""))[0] if i in NOTE else "")
    text = " ".join(r["text"].split())
    if len(text) > 230:
        text = text[:227] + "..."
    out.append((r["ts"][:16].replace("T", " "), text.replace("|", "\\|"), "%s%s" % (recorded, " +%d img" % r["img"] if r["img"] else ""), rowtxt, v, note.replace("|", "\\|")))

FINDINGS = """## What the inventory found (2026-10-18)

**Recorded.** 38 messages from 2026-10-04 to 2026-10-18 were acted on but never transcribed into `PLUGIN_GOAL.md` -- CLAUDE.md's rule is that your words go there BEFORE they become rows. They are now under *Recovered verbatim*, so they can be checked against; the rows built from them were written without that check.

**Decomposed.** Seven of your requests had no requirement row at all and now do: load time (G-254, *"loading takes several minutes instead of seconds"* -- never measured), the git-history search tool (G-255, built 2026-10-06), three fixes that existed only in code (G-256 typing focus, G-257 drag on empty space, G-258 second node click), Obsidian's own force graph as a candidate (G-259, never evaluated or ruled on), and the newest, scans left unprojected (G-253).

**Misread or over-claimed, found and corrected.** G-233 said the markdown fences a code block; it did not (corrected 2026-10-18, the code graph now reads the trie). G-90/G-92/G-98 were Confirm with a live pass on 2026-10-07 and failed their checks on 2026-10-18 (re-run pending, one with a covered window). Several rows are Confirm while their latest live check FAILED (D-35, D-36, D-40, D-42, G-172) -- the status column and the app disagree there.

**Waiting on you** (asked in chat): G-165 the labyrintalis push (an outward action), G-259 Obsidian's force graph, G-253 whether rewritten feed items' OLD versions are stored and projected or let go, G-237/G-239 (models and agents, from Addendum XI).

**Still open by count**: 39 messages map to a row that is Partly, 10 to one that is Open, 4 to one whose live check failed. The table names each.

""".split("\n")
lines = []
lines.append("# Prompt inventory, 2026-10-04 to 2026-10-18")
lines.append("")
lines.append("*Every message the reader typed in this project's transcript since 2026-10-04 (queued ones included; harness and resume lines counted, not listed), matched to where its words are recorded verbatim in `PLUGIN_GOAL.md`, the PRD rows it became, those rows' computed status (`design_state`) and latest live verdict (`live_confirmations.md`). Generated 2026-10-18 by `scripts/prompt_inventory.py`; the hand-written notes are marked in the last column.*")
lines.append("")
lines.append("**%d messages**: %s." % (sum(counts.values()), ", ".join("%d %s" % (n, k) for k, n in counts.most_common())))
lines.append("")
lines.append("How to read the verdict: *landed (tested)* = every row it became is Confirm (built, checked by a test or probe, not yet seen by you) or Done; *+ live check passed* = one of them also passed its registered live check (`confirm.mjs`); *partly* / *open* = a row it became is still Partly/Open; *live FAIL* = a row's latest live check failed; *placed by hand* = the matcher found no row and the note says where it went.")
lines.append("")
lines += FINDINGS
lines.append("| when (UTC) | message | recorded | became | verdict | note |")
lines.append("|---|---|---|---|---|---|")
for row in out:
    lines.append("| %s |" % " | ".join(row))
open("docs/PROMPT_INVENTORY.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(counts)
