"""G-165 / G-268 (PLUGIN_GOAL 92, 185 -- "Prepare, don't push"): a renamed,
scrubbed COPY of this repository for review before any push.

  python scripts/prepare_labyrintalis.py [dest] [--force]

* Only TRACKED files (`git ls-files`), no history: commit authors and
  emails never leave (a push of this history would publish them).
* `tests/corpus/` is left out: third-party page snapshots (one holds
  archive.org's expired CSRF token); `scripts/fetch_corpus.py` fetches them.
* domvec -> labyrintalis everywhere: the package directory, imports, the
  plugin id, env-var prefixes (DOMVEC_ -> LABYRINTALIS_), prose.
* Personal information replaced: home paths (every spelling), the user name,
  the full name and the e-mail address.
* `SCRUB_REPORT.md` in the copy lists what was excluded, what was replaced
  (counts per pattern), and every RESIDUAL hit of the personal patterns --
  the report's job is to show what the scrub did NOT catch.
Nothing is committed, pushed or published.
"""
import re, shutil, subprocess, sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
dest = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), REPO.parent / "labyrintalis"))
if dest.exists():
    if "--force" not in sys.argv:
        raise SystemExit("%s exists; pass --force to replace it" % dest)
    shutil.rmtree(dest)

EXCLUDE = (re.compile(r"^tests/corpus/"),)
files = [f for f in subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
         if not any(x.search(f) for x in EXCLUDE)]
excluded = [f for f in subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
            if any(x.search(f) for x in EXCLUDE)]

# Personal first (longest spellings first), then the rename.
# The maintainer's own spellings come from a GITIGNORED file, so the
# scrubber that removes them does not itself publish them:
# scripts/.identity.json = {"home": "...", "name": "...", "email": "..."}.
import json as _json
_ID = _json.loads((REPO / "scripts" / ".identity.json").read_text(encoding="utf-8")) \
    if (REPO / "scripts" / ".identity.json").exists() else {}
_home, _name, _email = (re.escape(_ID.get(k, "")) for k in ("home", "name", "email"))
_last = re.escape(_ID.get("name", "").split()[-1]) if _ID.get("name") else ""
_first = re.escape(_ID.get("name", "").split()[0]) if _ID.get("name") else ""
PERSONAL = [(re.compile(p, re.I), r) for p, r in [
    (r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}" + _home, "<home>"),
    (r"/[a-z]/Users/" + _home, "<home>"),
    (r"\bC--Users-" + _home + r"\b", "C--Users-user"),
    (_email, "maintainer@example.org"),
    (_first + r"\s+" + _last, "the maintainer"),
    (r"\b" + _last + r"\b", "maintainer"),
    (r"\b" + _home + r"\b", "user"),
] if _ID]
RENAME = [
    (re.compile(r"DOMVEC"), "LABYRINTALIS"),
    (re.compile(r"Domvec"), "Labyrintalis"),
    (re.compile(r"domvec"), "labyrintalis"),
]
RESIDUAL = re.compile("|".join(x for x in (_home, _last, _email, "gmail") if x) or "(?!)", re.I)

counts: Counter = Counter()
residual = []
binary = 0
for f in files:
    src = REPO / f
    out_rel = re.sub(r"(^|/)domvec(?=/|$)", r"\1labyrintalis", f)
    out = dest / out_rel
    out.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        binary += 1
        if RESIDUAL.search(data.decode("latin-1")):
            residual.append((out_rel, 0, "(binary file)"))
        out.write_bytes(data)
        continue
    for pat, rep in PERSONAL + RENAME:
        text, n = pat.subn(rep, text)
        if n:
            counts[pat.pattern] += n
    for i, line in enumerate(text.splitlines(), 1):
        if RESIDUAL.search(line):
            residual.append((out_rel, i, line.strip()[:160]))
    out.write_text(text, encoding="utf-8", newline="")

report = ["# Scrub report", "",
          "*Written by `scripts/prepare_labyrintalis.py` -- a renamed, scrubbed copy for review. Nothing pushed.*", "",
          "**%d files copied** (%d binary, copied as they are); **%d left out**:" % (len(files), binary, len(excluded)), "",
          "- `tests/corpus/` (%d files): third-party page snapshots; `scripts/fetch_corpus.py` fetches them" % len(excluded), "",
          "**Replaced** (occurrences per pattern):", ""]
report += ["- `%s`: %d" % (p, n) for p, n in counts.most_common()]
report += ["", "**Residual hits of the personal patterns** (%d) -- what the scrub did NOT catch, to review by hand:" % len(residual), ""]
report += ["- `%s`%s: %s" % (f, (":%d" % i) if i else "", t) for f, i, t in residual[:300]] or ["- none"]
report += ["", "**Not checked here**: image and PDF contents (metadata may name the author), and anything a test fetches at run time."]
(dest / "SCRUB_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
print("copied %d files to %s; excluded %d; residual %d" % (len(files), dest, len(excluded), len(residual)))
print(dict(counts.most_common()))
