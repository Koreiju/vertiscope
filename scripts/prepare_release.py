"""A renamed, scrubbed COPY of this repository, ready to publish under a new
name -- `scripts/prepare_labyrintalis.py` generalised (2026-10-20: "remove
all secrets and push to a brand new remote (public) branch ... naming this
new branch and project 'vertiscope'").

  python scripts/prepare_release.py --name vertiscope [dest] [--force]

* Only TRACKED files (`git ls-files`), no history: commit authors and
  e-mails never leave, and nothing a past commit held can be recovered.
* Left out: `tests/corpus/` and `tests/snapshots/` -- third-party pages
  (one holds archive.org's expired CSRF token; all are other people's
  copyrighted pages). `scripts/fetch_corpus.py` fetches the corpus.
* domvec -> <name> everywhere: the package directory, imports, the plugin
  id, env-var prefixes (DOMVEC_ -> <NAME>_), prose.
* Personal information replaced: home paths (every spelling), the user
  name, the full name and the e-mail address.
* `.gitignore` extended for what must never be published: stores
  (kuzu, WAL, sqlite), models (gguf, safetensors), pickled fits, built
  bundles, media and every build/workspace directory.
* A SECRET scan of the finished copy (tokens, keys, private keys, JWTs,
  credential assignments) -- its hits go first in the report, and the
  script exits non-zero if there are any.
* `SCRUB_REPORT.md` in the copy (and ignored by it) lists what was left
  out, replaced, and every residual personal hit to review by hand.
Nothing is committed, pushed or published by this script.
"""
import re, shutil, subprocess, sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
name = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--name=")), None)
if name is None and "--name" in sys.argv:
    name = sys.argv[sys.argv.index("--name") + 1]
if not name or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
    raise SystemExit("--name must be a lower-case identifier (it becomes the package name)")
positional = [a for i, a in enumerate(sys.argv[1:], 1)
              if not a.startswith("--") and sys.argv[i - 1] != "--name"]
dest = Path(positional[0]) if positional else REPO.parent / name
if dest.exists():
    if "--force" not in sys.argv:
        raise SystemExit("%s exists; pass --force to replace it" % dest)
    keep_git = dest / ".git"
    for p in dest.iterdir():
        if p == keep_git:
            continue                     # a repository already made there is kept
        shutil.rmtree(p) if p.is_dir() else p.unlink()

EXCLUDE = (re.compile(r"^tests/corpus/"), re.compile(r"^tests/snapshots/"),
           # The scrubbers quote what they scrub (the e-mail, the names):
           # they are about publishing THIS repository and stay with it.
           re.compile(r"^scripts/prepare_(labyrintalis|release)\.py$"))
tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines()
files = [f for f in tracked if not any(x.search(f) for x in EXCLUDE)]
excluded = [f for f in tracked if any(x.search(f) for x in EXCLUDE)]

PERSONAL = [
    (re.compile(r"[A-Za-z]:[\\/]{1,2}Users/user", re.I), "<home>"),
    (re.compile(r"/[a-z]/Users/user", re.I), "<home>"),
    (re.compile(r"\bC--Users-user\b", re.I), "C--Users-user"),
    (re.compile(r"maintainer@gmail\.com", re.I), "maintainer@example.org"),
    (re.compile(r"Isaac\s+maintainer", re.I), "the maintainer"),
    (re.compile(r"\bmaintainer\b", re.I), "maintainer"),
    (re.compile(r"\buser\b", re.I), "user"),
]
RENAME = [
    (re.compile(r"DOMVEC"), name.upper()),
    (re.compile(r"Domvec"), name.capitalize()),
    (re.compile(r"domvec"), name),
]
RESIDUAL = re.compile(r"user|maintainer|Users/user|gmail", re.I)
SECRET = re.compile(
    r"(ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|gho_[A-Za-z0-9]{30,}|hf_[A-Za-z0-9]{30,}"
    r"|sk-ant-[A-Za-z0-9_-]{20,}|\bsk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"
    r"|(?i:(api[_-]?key|secret|password|passwd|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"][^'\"$<{]{12,}['\"]))")
#: Known non-secrets that look like one: a test's planted value.
SECRET_ALLOW = re.compile(r"s3cr3tT0kenValueGoesHere")

IGNORE_EXTRA = """
# ---- never published (prepare_release.py) ----------------------------------
# Stores and their logs, wherever they land.
*.kuzu
*.kuzu.*
*.wal
*.wal.*
*.db
*.sqlite
*.sqlite3
*.duckdb
# Models and fitted state.
*.gguf
*.safetensors
*.bin
*.pt
*.onnx
*.pkl
*.npy
*.npz
models/
# Built bundles and dependencies.
node_modules/
obsidian-plugin/main.js
dist/
# Workspaces, captures, media and analytics.
build*/
workspace*/
media/
snapshots/
offline_pages/
pdfs/
downloads/
test_runs/
*.log
# Third-party page corpora (fetched by scripts/fetch_corpus.py).
tests/corpus/
tests/snapshots/
# Local secrets, should any ever appear.
.env
.env.*
*.pem
*.key
# The scrub's own report stays local.
SCRUB_REPORT.md
"""

counts: Counter = Counter()
residual, secrets = [], []
binary = 0
for f in files:
    src = REPO / f
    if not src.is_file():
        continue
    out_rel = re.sub(r"(^|/)domvec(?=/|$)", r"\1" + name, f)
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
    if f == ".gitignore":
        text = text.rstrip("\n") + "\n" + IGNORE_EXTRA
    for i, line in enumerate(text.splitlines(), 1):
        if RESIDUAL.search(line):
            residual.append((out_rel, i, line.strip()[:160]))
        m = SECRET.search(line)
        if m and not SECRET_ALLOW.search(line):
            secrets.append((out_rel, i, m.group(0)[:12] + "..."))
    out.write_text(text, encoding="utf-8", newline="")

report = ["# Scrub report", "",
          "*Written by `scripts/prepare_release.py --name %s`. Nothing pushed by it.*" % name, "",
          "**Secret-pattern hits (%d)** -- must be none before publishing:" % len(secrets), ""]
report += ["- `%s:%d`: `%s`" % s for s in secrets] or ["- none"]
report += ["", "**%d files copied** (%d binary, copied as they are); **%d left out**:" % (len(files), binary, len(excluded)), "",
           "- `tests/corpus/`, `tests/snapshots/`: third-party pages (`scripts/fetch_corpus.py` fetches the corpus); the two scrub scripts (%d files in all)" % len(excluded), "",
           "**Replaced** (occurrences per pattern):", ""]
report += ["- `%s`: %d" % (p, n) for p, n in counts.most_common()]
report += ["", "**Residual hits of the personal patterns** (%d) -- to review by hand:" % len(residual), ""]
report += ["- `%s`%s: %s" % (f, (":%d" % i) if i else "", t) for f, i, t in residual[:300]] or ["- none"]
report += ["", "**Not checked here**: image and PDF contents (metadata may name the author), and anything a test fetches at run time."]
(dest / "SCRUB_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
print("copied %d files to %s; excluded %d; residual %d; SECRET HITS %d" % (len(files), dest, len(excluded), len(residual), len(secrets)))
print(dict(counts.most_common()))
for s in secrets[:20]:
    print("  secret?", s)
sys.exit(1 if secrets else 0)
