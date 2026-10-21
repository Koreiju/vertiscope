import json, re, sys, glob
sys.path.insert(0, ".")
import vertiscope.analytics.design_state as _ds
S = sys.argv[1]
inv = json.load(open(S + "/inventory.json", encoding="utf-8"))
norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
prd = open("docs/PLUGIN_PRD.md", encoding="utf-8").read().split("\n")
rowtxt = {}
status = {}
for l in prd:
    # design_state's own parser: the verdict is the LAST " | " cell (a row
    # holding `url|xpath` splits wrongly on a bare pipe).
    m = _ds.ROW.match(l)
    if m:
        rowtxt[m.group(1)] = norm(l)
        cells = l.split(" | ")
        status[m.group(1)] = _ds.classify(cells[-1].rstrip("| ").strip() if len(cells) > 2 else m.group(3))
code = {}
for f in glob.glob("obsidian-plugin/src/*.ts") + glob.glob("vertiscope/**/*.py", recursive=True) + glob.glob("vertiscope/core/js/*.js"):
    try: code[f] = norm(open(f, encoding="utf-8").read())
    except Exception: pass
goalnorm = norm(open("docs/PLUGIN_GOAL.md", encoding="utf-8").read())
live = {}
for l in open("build_analytics/live_confirmations.md", encoding="utf-8"):
    m = re.match(r"^\| `([A-Z]+-\d+)` \|.*?\| \*\*(pass|FAIL)\*\*", l)
    if m: live[m.group(1)] = m.group(2)
def windows(n, w=28, step=14):
    words = n.split()
    out = []
    for i in range(0, max(1, len(words) - 4), 3):
        k = " ".join(words[i:i + 6])
        if len(k) >= 22: out.append(k)
    return out[:30]
for r in inv:
    if r["kind"] == "process": continue
    n = norm(r["text"])
    ws = windows(n)
    hits = {rid for rid, t in rowtxt.items() for k in ws if k in t}
    r["prd_quote_rows"] = sorted(hits)
    r["in_goal_anywhere"] = any(k in goalnorm for k in ws)
    r["code_quotes"] = sorted({f.split("/")[-1].split("\\")[-1] for f, t in code.items() for k in ws if k in t})
    allrows = sorted(set(hits) | {x[0] for x in r.get("rows", [])})
    r["all_rows"] = [(x, status.get(x, "?"), live.get(x, "-")) for x in allrows]
json.dump(inv, open(S + "/inventory2.json", "w", encoding="utf-8"), indent=1)
from collections import Counter
c = Counter()
for r in inv:
    if r["kind"] == "process": c["process"] += 1; continue
    k = ("goal" if r["kind"] == "transcribed" or r["in_goal_anywhere"] else "no-goal") + "/" + ("rows" if r["all_rows"] else ("code" if r["code_quotes"] else "nothing"))
    c[k] += 1
print(c)
for r in inv:
    if r["kind"] != "process" and not r["all_rows"]:
        print(r["ts"], "goal" if (r["kind"] == "transcribed" or r["in_goal_anywhere"]) else "NOGOAL", r["code_quotes"][:3], repr(r["text"][:100]))
