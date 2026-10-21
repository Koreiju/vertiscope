"""The repository's history, queried where it lives (2026-10-06).

*"a minimal adapter plugin design that does vectorization efficiently but
queries still directly over the git logs."*

Nothing here is a second store of the history. Git is the store; every query
below is a ``git log`` / ``git show`` / ``git diff`` call, and the only thing
kept beside it is a **vector cache** for semantic ranking.

In the patricia trie's terms this module only READS, and writes nothing into
any trie. A commit is addressed by its sha (``git://<root>/<sha12>`` is how
the unfinished trie-ingest draft spelled it, and a result's ``sha`` is that
address's last segment); the files a commit touched are named by the urls the
rest of the repository already gives them -- ``code://`` through
:func:`vertiscope.source.source_url`, ``vault://`` through
:func:`vertiscope.vault.note_url` -- so a result row can be handed to
``resolve_address`` / ``search`` unchanged. A commit that cannot be said as
"reads from git, names files by their trie urls" has left the map.

**What is vectorised** -- the project's own rule ``G-52`` (the encoder gets
prose, never code): per commit, the *subject*, each *message paragraph*
(``Co-Authored-By:`` trailers dropped, they are metadata) and the *comment /
docstring lines the diff ADDED*, joined into runs (:func:`added_prose`). The
code in a diff is never embedded; it is read with ``git show``.

**The cache** (``build/git_vectors/``)::

    vectors.npz   float32 (N, dim), L2-normalised, row i = unit i
    index.json    {model, dim, done: [sha...], units: [{sha, kind, n, h, t}]}

``h`` is the text hash: a unit whose text is already cached (a docstring
copied between commits, a repeated message paragraph) reuses that row and is
not embedded again. **Incremental**: :meth:`VectorCache.sync` takes
``git rev-list HEAD`` minus ``done`` and reads, parses and embeds only those
commits -- O(new commits), one ``git log --stdin`` for the whole batch. Commits
that left the history (rebase) are pruned. Extraction (git only) is separate
from embedding (the model), so lexical ranking over the cached text works with
no model loaded, and the embedder is created lazily on the first semantic
query and degrades to lexical when it fails.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

ROOT = "vertiscope"

#: Paths whose diffs are data, not findings: recorded pages, stores, lockfiles,
#: binaries, bundles. The commit still NAMES them; its hunks are not read.
_NO_HUNKS = re.compile(
    r"^(tests/corpus/|tests/fixtures/.*\.html$|build|node_modules/|.*/node_modules/|"
    r".*package-lock\.json$|.*\.min\.js$|obsidian-plugin/main\.js$|"
    r".*\.(png|jpg|jpeg|gif|webp|svg|ico|pdf|kuzu|bin|npz|npy|pkl|json|html)$)")

#: One unit's cap, in characters (the embedder truncates further).
UNIT_CHARS = 1200
#: Per commit cap on added-prose units: a commit that adds 400 comment runs is
#: a generated file or a mass edit, and its first runs carry its subject.
MAX_NOTES = 40
RRF_K = 60

_STOP = frozenset("a an and are as at be by for from has have in is it its of on or "
                  "that the this to was were with not no do does did into than then "
                  "so if but their there they we you i".split())


# ---- git --------------------------------------------------------------------

def git(repo: Path, *args: str, check: bool = True, stdin: Optional[str] = None) -> str:
    got = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                         check=check, input=stdin.encode("utf-8") if stdin is not None else None)
    return got.stdout.decode("utf-8", errors="replace")


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD", check=False).strip()


def rev_list(repo: Path) -> List[str]:
    """Every commit reachable from HEAD, oldest first."""
    return [r for r in git(repo, "rev-list", "--reverse", "HEAD").split() if r]


def file_url(path: str, root: str = ROOT) -> Optional[str]:
    """The trie url a touched file is addressed by, or None when the corpus
    does not hold that kind of file (imports are lazy: the lexical path must
    not pay for ``vertiscope.source``)."""
    p = PurePosixPath(path)
    if p.suffix in (".py", ".js", ".ts", ".mjs"):
        from .source import source_url
        return source_url(root, path)
    if p.suffix == ".md":
        from .vault import note_url
        return note_url(root, path)
    return None


# ---- one patch --------------------------------------------------------------

_HUNK_HEAD = re.compile(r"^@@ .* @@")


def split_patch(patch: str) -> List[Tuple[str, str, List[str]]]:
    """``git show`` output -> ``[(status, path, [hunk, ...])]``."""
    files: List[Tuple[str, str, List[str]]] = []
    path, status, hunks, cur = "", "M", [], []

    def close():
        if cur:
            hunks.append("\n".join(cur))
        if path:
            files.append((status, path, list(hunks)))

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            close()
            m = re.match(r"diff --git a/(.*?) b/(.*)$", line)
            path, status, hunks, cur = (m.group(2) if m else line), "M", [], []
            continue
        if line.startswith("new file mode"):
            status = "A"
        elif line.startswith("deleted file mode"):
            status = "D"
        elif line.startswith("rename from "):
            status = "R"
        elif _HUNK_HEAD.match(line):
            if cur:
                hunks.append("\n".join(cur))
            cur = [line]
        elif cur and (line[:1] in "+- \\"):
            cur.append(line)
    close()
    return files


_COMMENT = re.compile(r"^\s*(#|//|/\*+|\*(?!/))\s?(.*)$")


def added_prose(hunk: str) -> List[str]:
    """What a hunk SAYS: the comment and docstring lines it ADDED, joined into
    runs. Code lines, removed lines and context lines are not prose. This is
    the part of a diff the encoder reads (`G-52`)."""
    runs: List[str] = []
    cur: List[str] = []
    in_doc = False
    for line in hunk.splitlines()[1:]:
        if not line.startswith("+") or line.startswith("+++"):
            if cur:
                runs.append(" ".join(cur))
                cur = []
            continue
        body = line[1:]
        quotes = body.count('"""') + body.count("'''")
        text = None
        if in_doc or quotes:
            text = body.replace('"""', " ").replace("'''", " ").strip()
            if quotes % 2:
                in_doc = not in_doc
        else:
            m = _COMMENT.match(body)
            if m:
                text = m.group(2).strip()
        if text:
            cur.append(text)
        elif cur:
            runs.append(" ".join(cur))
            cur = []
    if cur:
        runs.append(" ".join(cur))
    return [r for r in runs if len(r) >= 12]


# ---- one commit -> units ----------------------------------------------------

def message_units(subject: str, body: str) -> List[Tuple[str, int, str]]:
    """``[(kind, n, text)]``: the subject, then each body paragraph (trailers
    dropped)."""
    out: List[Tuple[str, int, str]] = []
    if subject.strip():
        out.append(("subject", 0, subject.strip()))
    paras = [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip()]
    for i, para in enumerate(paras, 1):
        if para.startswith("Co-Authored-By:"):
            continue
        out.append(("para", i, re.sub(r"\s*\n\s*", " ", para)))
    return out


def patch_units(patch: str) -> List[Tuple[str, int, str]]:
    seen, out = set(), []
    for _status, path, hunks in split_patch(patch):
        if _NO_HUNKS.match(path):
            continue
        for hunk in hunks:
            for note in added_prose(hunk):
                if note not in seen:
                    seen.add(note)
                    out.append(("note", len(out) + 1, note))
                    if len(out) >= MAX_NOTES:
                        return out
    return out


def commit_units(subject: str, body: str, patch: str) -> List[Tuple[str, int, str]]:
    return [(k, n, t[:UNIT_CHARS]) for k, n, t in
            message_units(subject, body) + patch_units(patch)]


_SEP_COMMIT, _SEP_FIELD, _SEP_BODY = "\x01", "\x00", "\x02"
_LOG_FORMAT = "--format=%x01%H%x00%ad%x00%an%x00%s%x00%b%x02"


def read_commits(repo: Path, shas: Sequence[str]) -> List[Dict]:
    """Subject, body and added-prose units for `shas`, in ONE git call."""
    if not shas:
        return []
    raw = git(repo, "log", "--no-walk=unsorted", "--stdin", "-p", "-U0", "--no-color",
              "--no-ext-diff", "--date=format:%Y-%m-%d %H:%M", _LOG_FORMAT,
              stdin="\n".join(shas) + "\n", check=False)
    out = []
    # A stray \x01 inside a patch (a binary-ish hunk) must not forge a record:
    # a record starts only at \x01 followed by a full sha and the field NUL.
    for rec in re.split(r"\x01(?=[0-9a-f]{40}\x00)", raw):
        if not rec.strip():
            continue
        header, _, patch = rec.partition(_SEP_BODY)
        f = (header.split(_SEP_FIELD) + [""] * 5)[:5]
        sha, date, author, subject, body = f
        out.append({"sha": sha.strip(), "date": date, "author": author,
                    "subject": subject.strip(),
                    "units": commit_units(subject, body, patch)})
    return out


# ---- the vector cache -------------------------------------------------------

def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9_]{2,}", text.lower()) if t not in _STOP]


class VectorCache:
    """``build/git_vectors/``: unit texts + one float32 row per distinct text.

    `embedder` is a callable returning the embedder (lazy: it is not called
    until a vector is needed) or an object with ``embed_texts`` /
    ``embed_query``. ``embed_calls`` counts texts handed to the model, which is
    what the incremental claim is measured against."""

    def __init__(self, path: Path, repo: Path, embedder=None, *, model: str = "") -> None:
        self.path = Path(path)
        self.repo = Path(repo)
        self._embedder = embedder
        self._model_hint = model
        self.embed_calls = 0            # texts sent to the model
        self.embed_batches = 0
        self.error: str = ""
        self.meta: Dict = {"model": "", "dim": 0, "done": [], "units": []}
        self.vecs = np.zeros((0, 0), dtype=np.float32)
        self.rows: Dict[str, int] = {}  # text hash -> row in vecs
        self._load()

    # -- persistence
    def _load(self) -> None:
        try:
            self.meta = json.loads((self.path / "index.json").read_text(encoding="utf-8"))
            z = np.load(self.path / "vectors.npz")
            self.vecs = z["vecs"].astype(np.float32)
            hashes = list(z["hashes"])
            self.rows = {str(h): i for i, h in enumerate(hashes)}
        except Exception:                                   # noqa: BLE001
            self.meta = {"model": "", "dim": 0, "done": [], "units": []}
            self.vecs = np.zeros((0, 0), dtype=np.float32)
            self.rows = {}
        self._by_sha: Optional[Dict[str, List[Dict]]] = None

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        hashes = [""] * len(self.rows)
        for h, i in self.rows.items():
            hashes[i] = h
        np.savez(self.path / "vectors.npz", vecs=self.vecs, hashes=np.array(hashes))
        (self.path / "index.json").write_text(json.dumps(self.meta), encoding="utf-8")

    # -- extraction (git only, no model)
    def extract(self) -> Dict[str, int]:
        """Read the commits not yet in ``done``; drop those that left HEAD."""
        revs = rev_list(self.repo)
        have = set(self.meta["done"])
        new = [s for s in revs if s not in have]
        gone = have - set(revs)
        if gone:
            self.meta["units"] = [u for u in self.meta["units"] if u["sha"] not in gone]
            self.meta["done"] = [s for s in self.meta["done"] if s not in gone]
        added = 0
        for c in read_commits(self.repo, new):
            for kind, n, text in c["units"]:
                self.meta["units"].append({"sha": c["sha"], "kind": kind, "n": n,
                                           "h": text_hash(text), "t": text})
                added += 1
            self.meta["done"].append(c["sha"])
        # a sha git returned no record for (empty log) is still done
        seen = set(self.meta["done"])
        for s in new:
            if s not in seen:
                self.meta["done"].append(s)
        self._by_sha = None
        return {"new_commits": len(new), "new_units": added, "pruned": len(gone)}

    def embedder(self):
        if callable(self._embedder) and not hasattr(self._embedder, "embed_texts"):
            try:
                self._embedder = self._embedder()
            except Exception as exc:                        # noqa: BLE001
                self.error = "%s: %s" % (type(exc).__name__, exc)
                self._embedder = None
        return self._embedder

    def _model_name(self, emb) -> str:
        return str(getattr(emb, "model_name", "") or self._model_hint or "embedder")

    # -- embedding (the model)
    def vectorise(self, batch: int = 64) -> Dict[str, int]:
        """Embed the distinct unit texts that have no row yet. Returns counts;
        a failing embedder leaves the rows missing and sets ``error``."""
        todo: Dict[str, str] = {}
        for u in self.meta["units"]:
            if u["h"] not in self.rows and u["h"] not in todo:
                todo[u["h"]] = u["t"]
        if not todo:
            return {"embedded": 0}
        emb = self.embedder()
        if emb is None:
            return {"embedded": 0}
        name = self._model_name(emb)
        if self.meta.get("model") and self.meta["model"] != name and len(self.rows):
            # another model's vectors are not comparable: start the rows over
            self.rows, self.vecs = {}, np.zeros((0, 0), dtype=np.float32)
            todo = {u["h"]: u["t"] for u in self.meta["units"]}
        hs, texts = list(todo), list(todo.values())
        new_rows: List[np.ndarray] = []
        try:
            for i in range(0, len(texts), batch):
                chunk = texts[i:i + batch]
                self.embed_calls += len(chunk)
                self.embed_batches += 1
                arr = np.asarray(emb.embed_texts(chunk), dtype=np.float32)
                arr = arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9)
                new_rows.append(arr)
        except Exception as exc:                            # noqa: BLE001
            self.error = "%s: %s" % (type(exc).__name__, exc)
        if new_rows:
            block = np.vstack(new_rows)
            base = len(self.rows)
            self.vecs = block if self.vecs.size == 0 else np.vstack([self.vecs, block])
            for j in range(block.shape[0]):
                self.rows[hs[j]] = base + j
            self.meta["model"], self.meta["dim"] = name, int(block.shape[1])
        return {"embedded": sum(a.shape[0] for a in new_rows)}

    def sync(self, *, vectors: bool = True) -> Dict:
        """Auto-update: extract the new commits, embed what has no vector."""
        before = len(self.meta["done"])
        out = self.extract()
        if vectors:
            out.update(self.vectorise())
        if out.get("new_commits") or out.get("pruned") or out.get("embedded"):
            self.meta["head"] = head(self.repo)
            self.save()
        out["commits"] = len(self.meta["done"])
        out["were"] = before
        return out

    # -- ranking
    def by_sha(self) -> Dict[str, List[Dict]]:
        if self._by_sha is None:
            d: Dict[str, List[Dict]] = {}
            for u in self.meta["units"]:
                d.setdefault(u["sha"], []).append(u)
            self._by_sha = d
        return self._by_sha

    def semantic(self, query: str, k: int, allowed: Optional[set] = None
                 ) -> List[Tuple[str, float, Dict]]:
        """Commits ranked by their best unit's cosine to the query. Raises
        when no embedder is available -- the caller degrades to lexical."""
        emb = self.embedder()
        if emb is None or self.vecs.size == 0:
            raise RuntimeError(self.error or "no vectors")
        q = np.asarray(emb.embed_query(query), dtype=np.float32).reshape(-1)
        q = q / max(float(np.linalg.norm(q)), 1e-9)
        sims = self.vecs @ q
        best: Dict[str, Tuple[float, Dict]] = {}
        for u in self.meta["units"]:
            r = self.rows.get(u["h"])
            if r is None or (allowed is not None and u["sha"] not in allowed):
                continue
            s = float(sims[r])
            if u["sha"] not in best or s > best[u["sha"]][0]:
                best[u["sha"]] = (s, u)
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:k]
        return [(sha, s, u) for sha, (s, u) in ranked]

    def lexical(self, query: str, k: int, allowed: Optional[set] = None
                ) -> List[Tuple[str, float, Dict]]:
        """TF-IDF overlap over the cached unit texts: the no-model fallback."""
        q = tokens(query)
        if not q:
            return []
        units = self.meta["units"]
        df: Counter = Counter()
        toks = []
        for u in units:
            t = set(tokens(u["t"]))
            toks.append(t)
            df.update(t & set(q))
        n = max(len(units), 1)
        best: Dict[str, Tuple[float, Dict]] = {}
        for u, t in zip(units, toks):
            if allowed is not None and u["sha"] not in allowed:
                continue
            s = sum(math.log(1 + n / df[w]) for w in set(q) if w in t)
            if s > 0:
                s /= math.sqrt(max(len(t), 1))
                if u["sha"] not in best or s > best[u["sha"]][0]:
                    best[u["sha"]] = (s, u)
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:k]
        return [(sha, s, u) for sha, (s, u) in ranked]


# ---- direct git queries -----------------------------------------------------

_META = "--format=%H%x00%ad%x00%s"
_DATE = "--date=format:%Y-%m-%d %H:%M"


def _parse_meta(out: str) -> List[Dict]:
    rows = []
    for line in out.splitlines():
        p = line.split("\x00")
        if len(p) >= 3 and re.fullmatch(r"[0-9a-f]{40}", p[0]):
            rows.append({"sha": p[0], "date": p[1], "subject": p[2]})
    return rows


def commit_meta(repo: Path, sha: str) -> Dict:
    rows = _parse_meta(git(repo, "show", "-s", _META, _DATE, sha, check=False))
    return rows[0] if rows else {"sha": sha, "date": "", "subject": ""}


def commit_card(repo: Path, sha: str, root: str = ROOT, limit: int = 8) -> Dict:
    """Meta and touched files in ONE ``git show`` (a process spawn costs ~40 ms
    on Windows, and a result row used to pay for two)."""
    raw = git(repo, "show", "--name-status", "--no-renames", _META, _DATE, sha, check=False)
    lines = raw.splitlines()
    rows = _parse_meta(lines[0]) if lines else []
    card = rows[0] if rows else {"sha": sha, "date": "", "subject": ""}
    files = []
    for line in lines[1:]:
        status, _, path = line.partition("\t")
        if path:
            files.append({"status": status, "path": path, "url": file_url(path, root)})
    card["files"] = files[:limit] if limit else files
    return card


def files_touched(repo: Path, sha: str, root: str = ROOT, limit: int = 12) -> List[Dict]:
    out = []
    for line in git(repo, "show", "--name-status", "--format=", "--no-renames", sha,
                    check=False).splitlines():
        status, _, path = line.partition("\t")
        if path:
            out.append({"status": status, "path": path, "url": file_url(path, root)})
    return out[:limit] if limit else out


def grep_tokens(query: str) -> List[str]:
    return [t for t in re.findall(r"[A-Za-z0-9_\-\.]+", query) if t.lower() not in _STOP and len(t) > 1]


def git_grep(repo: Path, query: str, k: int, path: Optional[str] = None
             ) -> List[Tuple[str, float, Dict]]:
    """``git log --grep -i`` per word; ranked by how many distinct words the
    message holds, then newest first. Snippet: the best-matching paragraph."""
    words = grep_tokens(query)
    if not words:
        return []
    # one call, bodies included: a per-hit `git show` made this 3 s
    args = ["log", "-i", "--fixed-strings", "--format=%x01%H%x00%s%x00%b", _DATE]
    for w in words:
        args += ["--grep", w]
    args += ["-n", str(max(k * 8, 100))]
    if path:
        args += ["--", path]
    scored = []
    for order, rec in enumerate(git(repo, *args, check=False).split("\x01")[1:]):
        sha, subject, body = (rec.split("\x00") + ["", "", ""])[:3]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        row = {"sha": sha}
        units = message_units(subject, body)
        hits = [(sum(w.lower() in t.lower() for w in words), kind, n, t) for kind, n, t in units]
        hits = [h for h in hits if h[0]]
        if not hits:
            continue
        top = max(hits, key=lambda h: h[0])
        allw = sum(w.lower() in (subject + " " + body).lower() for w in words)
        scored.append((allw, -order, row["sha"], {"kind": top[1], "n": top[2], "t": top[3]}))
    scored.sort(reverse=True)
    return [(sha, float(a), u) for a, _o, sha, u in scored[:k]]


def pickaxe(repo: Path, regex: str, k: int, path: Optional[str] = None
            ) -> List[Tuple[str, float, Dict]]:
    """``git log -G<regex> -i``: commits whose DIFF added or removed a line
    matching it. Snippet: added comment lines that match, else added lines."""
    try:
        rx = re.compile(regex, re.I)
        pick_arg = "-G" + regex
    except re.error:                       # not a regex: pickaxe the literal string
        rx = re.compile(re.escape(regex), re.I)
        pick_arg = "-S" + regex
    # one call: the log picks the commits and prints their diffs for the snippet
    args = ["log", "-i", pick_arg, "-p", "-U0", "--no-color", "--no-ext-diff",
            "--format=%x01%H", "-n", str(k)]
    if path:
        args += ["--", path]
    out = []
    recs = git(repo, *args, check=False).split("\x01")[1:]
    for rank, rec in enumerate(recs):
        sha, _, patch = rec.partition("\n")
        sha = sha.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        row = {"sha": sha}
        prose, code, cur = [], [], ""
        for line in patch.splitlines():
            if line.startswith("diff --git "):
                cur = line.rsplit(" b/", 1)[-1]
            elif line.startswith("+") and not line.startswith("+++") and rx.search(line) \
                    and not _NO_HUNKS.match(cur):
                (prose if _COMMENT.match(line[1:]) else code).append(line[1:].strip())
        pick = (prose or code or [""])[0][:300]
        out.append((row["sha"], 1.0 / (1 + rank),
                    {"kind": "diff", "n": 0, "t": pick}))
    return out


def file_history(repo: Path, path: str, k: int) -> List[Dict]:
    return _parse_meta(git(repo, "log", "--follow", "-n", str(k), _META, _DATE,
                           "--", path, check=False))


def touching(repo: Path, path: str) -> set:
    return {r["sha"] for r in _parse_meta(git(repo, "log", _META, _DATE, "--", path,
                                              check=False))}


def rrf(rankings: Dict[str, Sequence[str]], k: int = RRF_K) -> List[Tuple[str, float, List[str]]]:
    """Reciprocal-rank fusion: ``sum 1/(k + rank)`` over each mode's list.
    Returns ``[(sha, score, modes)]`` best first."""
    score: Dict[str, float] = {}
    modes: Dict[str, List[str]] = {}
    for mode, shas in rankings.items():
        for rank, sha in enumerate(shas, 1):
            score[sha] = score.get(sha, 0.0) + 1.0 / (k + rank)
            modes.setdefault(sha, []).append(mode)
    return sorted(((s, v, modes[s]) for s, v in score.items()), key=lambda r: -r[1])


# ---- the search -------------------------------------------------------------

def search(repo: Path, cache: VectorCache, query: str, k: int = 8, mode: str = "any",
           path: Optional[str] = None, *, root: str = ROOT) -> Dict:
    """The five modes. ``semantic`` syncs the cache first (embedding only the
    commits git has that the cache does not) and falls back to lexical over
    the cached text if the embedder fails."""
    k = max(1, min(int(k), 50))
    allowed = touching(repo, path) if path else None
    runs: Dict[str, List[Tuple[str, float, Dict]]] = {}
    note = ""
    if mode in ("semantic", "any"):
        cache.sync(vectors=True)
        try:
            runs["semantic"] = cache.semantic(query, k * 2, allowed)
        except Exception as exc:                            # noqa: BLE001
            runs["lexical"] = cache.lexical(query, k * 2, allowed)
            note = "semantic unavailable (%s); ranked lexically over the cached text" % exc
    if mode in ("grep", "any"):
        runs["grep"] = git_grep(repo, query, k * 2, path)
    if mode == "pickaxe" or (mode == "any" and query.strip() and not re.search(r"\s", query.strip())):
        try:
            runs["pickaxe"] = pickaxe(repo, query.strip(), k * 2, path)
        except Exception as exc:                            # noqa: BLE001
            note = (note + "; " if note else "") + "pickaxe: %s" % exc
    if mode not in ("semantic", "grep", "pickaxe", "any"):
        raise ValueError("mode must be semantic|grep|pickaxe|any")
    snip = {}
    for name in ("semantic", "lexical", "grep", "pickaxe"):
        for sha, _s, u in runs.get(name, []):
            snip.setdefault(sha, u)
    fused = rrf({m: [r[0] for r in rs] for m, rs in runs.items()})[:k]
    hits = []
    for sha, score, modes in fused:
        row = commit_card(repo, sha, root)
        u = snip.get(sha, {})
        hits.append({"sha": sha[:12], "date": row["date"], "subject": row["subject"],
                     "score": round(score, 4), "matched_by": modes,
                     "snippet": (u.get("t") or "")[:400], "snippet_kind": u.get("kind", ""),
                     "files": row["files"]})
    out = {"query": query, "mode": mode, "hits": hits}
    if note:
        out["note"] = note
    return out
