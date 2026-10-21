import json, os, sys, re
P = os.environ.get("VERTISCOPE_TRANSCRIPT") or r"<home>\.claude\projects\C--Users-user-Documents-vertiscope\7d99cefc-6dd8-441d-8b5c-0394e3832ea2.jsonl"
out = {}
def add(ts, content):
    texts, imgs = [], 0
    if isinstance(content, str): texts.append(content)
    elif isinstance(content, list):
        if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content): return
        for x in content:
            if not isinstance(x, dict): continue
            if x.get("type") == "text": texts.append(x.get("text", ""))
            elif x.get("type") == "image": imgs += 1
    t = re.sub(r"<system-reminder>.*?</system-reminder>", "", "\n".join(texts), flags=re.S).strip()
    if not t and not imgs: return
    if t.startswith(("<local-command", "<command-name>", "<task-notification>", "[SYSTEM NOTIFICATION", "This session is being continued", "[Request interrupted")): return
    if "<task-notification>" in t[:400]: return
    key = re.sub(r"\s+", " ", t)[:300]
    if key in out and out[key]["ts"] <= ts: return
    out[key] = {"ts": ts, "text": t, "images": imgs}
with open(P, encoding="utf-8") as f:
    for line in f:
        try: d = json.loads(line)
        except Exception: continue
        ts = d.get("timestamp", "")
        if ts < "2026-10-04": continue
        if d.get("type") == "user" and not d.get("isMeta") and not d.get("isCompactSummary"):
            add(ts, d.get("message", {}).get("content"))
        elif d.get("type") == "attachment":
            a = d.get("attachment") or {}
            if a.get("type") == "queued_command" and (a.get("origin") or {}).get("kind", "human") == "human":
                add(ts, a.get("prompt"))
rows = sorted(out.values(), key=lambda r: r["ts"])
json.dump(rows, open(sys.argv[1], "w", encoding="utf-8"), indent=1)
print(len(rows))
for o in rows: print(o["ts"][:16], o["images"], repr(o["text"][:110]))
