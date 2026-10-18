import json, re, sys
S = sys.argv[1]
prompts = json.load(open(S + "/prompts.json", encoding="utf-8"))
goal = open("docs/PLUGIN_GOAL.md", encoding="utf-8").read().split("\n")
prd = open("docs/PLUGIN_PRD.md", encoding="utf-8").read().split("\n")
live = open("build_analytics/live_confirmations.md", encoding="utf-8").read().split("\n")
norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
# quoted lines -> normalized stream with line map
qs, qmap = [], []
for i, l in enumerate(goal):
    if l.startswith(">"):
        w = norm(l[1:])
        if w:
            qs.append(w); qmap.append(i)
stream = ""; starts = []
for w, i in zip(qs, qmap):
    starts.append((len(stream), i)); stream += w + " "
def line_of(pos):
    lo = 0
    for s, i in starts:
        if s <= pos: lo = i
        else: break
    return lo
PROCESS = re.compile(r"^(please continue\.?|try again|let's pick up where we left off|i hit my usage limit.*|the app was quit.*|are tests currently running\??|any\*|of johnwick|never mind.*)$", re.I)
# item markers
item_at = {}
for i, l in enumerate(goal):
    if l.startswith(">"):
        continue                                   # the reader's own words, not a reading
    # Every "(NN)" in a reading is an item number (the readings number them
    # globally from Addendum IX on: "(63) diffs appear at once ...").
    for m in re.finditer(r"\((\d{2,3})\)|\bitem (\d{2,3})\b", l):
        n = next(g for g in m.groups() if g)
        item_at.setdefault(i, []).append(int(n))
def items_near(ln):
    """The items of the READING under the quote at line `ln`: skip the rest
    of the quote, then every number in the paragraphs up to the next quote."""
    j = ln
    while j < len(goal) and (goal[j].startswith(">") or not goal[j].strip()):
        j += 1
    got = []
    for k in range(j, min(len(goal), j + 40)):
        if goal[k].startswith("> "):
            break
        got += item_at.get(k, [])
    return sorted(set(got))
# PRD rows by item
rows = {}
status = {}
for l in prd:
    m = re.match(r"^\| ([A-Z]+-\d+) \|", l)
    if not m: continue
    rid = m.group(1)
    st = re.search(r"\*\*(Confirm|Done|Partly|Open|Defect|Superseded|Standing)\b", l)
    status[rid] = st.group(1) if st else "?"
    # "PLUGIN_GOAL 47, 49", "PLUGIN_GOAL items 146-159", "item 91"
    for m in re.finditer(r"PLUGIN_GOAL (?:items? )?((?:\d{2,3}(?:\s*[-,]\s*|\s+and\s+)?)+)|\bitems? (\d{2,3})\b", l):
        txt = m.group(1) or m.group(2) or ""
        for a, b in re.findall(r"(\d{2,3})\s*-\s*(\d{2,3})", txt):
            for n in range(int(a), int(b) + 1):
                rows.setdefault(n, set()).add(rid)
        for n in re.findall(r"\d{2,3}", txt):
            rows.setdefault(int(n), set()).add(rid)
verdict = {}
for l in live:
    m = re.match(r"^\| `([A-Z]+-\d+)` \|.*?\| \*\*(pass|FAIL)\*\*", l)
    if m: verdict[m.group(1)] = m.group(2)
out = []
for p in prompts:
    t = p["text"].strip()
    rec = {"ts": p["ts"][:16], "img": p["images"], "text": t}
    if PROCESS.match(norm(t) and t.strip()) or len(norm(t)) < 4 and not p["images"]:
        rec["kind"] = "process"; out.append(rec); continue
    n = norm(t)
    pos = -1
    for k in (n[:60], n[:35], n[10:45], n[-40:]):
        if len(k) >= 15:
            pos = stream.find(k)
            if pos >= 0: break
    if pos < 0:
        rec["kind"] = "NOT TRANSCRIBED"; out.append(rec); continue
    ln = line_of(pos)
    its = items_near(ln)
    rids = sorted({r for i in its for r in rows.get(i, ())}, key=lambda r: (r.split("-")[0], int(r.split("-")[1])))
    rec.update(kind="transcribed", goal_line=ln + 1, items=its,
               rows=[(r, status.get(r, "?"), verdict.get(r, "-")) for r in rids])
    out.append(rec)
json.dump(out, open(S + "/inventory.json", "w", encoding="utf-8"), indent=1)
from collections import Counter
print(Counter(r["kind"] for r in out))
print("transcribed with no item number:", sum(1 for r in out if r["kind"] == "transcribed" and not r["items"]))
print("transcribed, items but no PRD row:", sum(1 for r in out if r["kind"] == "transcribed" and r["items"] and not r["rows"]))
for r in out:
    if r["kind"] == "NOT TRANSCRIBED": print("NT", r["ts"], r["img"], repr(r["text"][:120]))
