"""A minimal MCP adapter over the repository's own git history (2026-10-06).

*"a minimal adapter plugin design that does vectorization efficiently but
queries still directly over the git logs."*  Tool shapes follow the two
references the user named (jjaakkola/git-diff-mcp-server: diff / stats /
commit-range; cyanheads/git-mcp-server: log / show / status / diff with
capped, structured output) and nothing more.

Every query runs against git (`vertiscope.gitlog`): ``git log --grep``,
``git log -G`` (pickaxe over the diffs), ``git log --follow -- path``,
``git show``, ``git diff HEAD``. The one thing kept beside git is the vector
cache for semantic ranking, ``build/git_vectors/``, which brings itself up to
date from ``git rev-list HEAD`` before each semantic query. The embedder is
loaded on that first semantic query and not before, so every other tool is
instant and a failed model degrades to lexical ranking.

In the patricia trie's terms the server only reads: it writes into no trie,
addresses commits by sha and the files they touched by their ``code://`` /
``vault://`` urls.

stdout carries the protocol and nothing else; diagnostics go to stderr.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from .. import gitlog
from .mcp import PROTOCOL, SUPPORTED, _error, _ok

SERVER = {"name": "vertiscope-git", "title": "vertiscope git history", "version": "0.1.0",
          "description": "Search and read this repository's git history directly; "
                         "semantic ranking from an incremental vector cache."}

#: Output caps, in characters: an MCP result is read by a model, not a pager.
SHOW_CHARS = 14000
DIFF_CHARS = 14000

TOOLS: List[Dict] = [
    {"name": "git_search",
     "description":
         "Search the commit history. mode=semantic ranks commits by embedding "
         "similarity of the query to each commit's message paragraphs and the "
         "comment/docstring lines its diff added (cache updates itself first); "
         "grep = `git log --grep -i` (each word, ranked by words matched); "
         "pickaxe = `git log -G<regex>` over what diffs added/removed; "
         "any = reciprocal-rank fusion of semantic + grep (+ pickaxe when the "
         "query is a single token). Returns sha, date, subject, a snippet, "
         "files touched. `path` limits to commits touching it.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "k": {"type": "integer", "default": 8},
         "mode": {"type": "string", "enum": ["any", "semantic", "grep", "pickaxe"],
                  "default": "any"},
         "path": {"type": "string"}}, "required": ["query"]}},
    {"name": "git_show",
     "description": "One commit: message and diff, straight from `git show`, "
                    "capped. `path` limits the diff to one file; `context` is "
                    "the diff context lines.",
     "inputSchema": {"type": "object", "properties": {
         "sha": {"type": "string"}, "path": {"type": "string"},
         "context": {"type": "integer", "default": 3}}, "required": ["sha"]}},
    {"name": "git_file_history",
     "description": "Commits touching a path, newest first (`git log --follow`).",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "k": {"type": "integer", "default": 15}},
         "required": ["path"]}},
    {"name": "git_worktree_diff",
     "description": "Uncommitted work: `git status --short` and `git diff HEAD`, capped.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "git_index_status",
     "description": "The vector cache: commits and units vectorised, cache "
                    "path, HEAD it was last synced to, embedder state.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [cut at %d of %d chars]" % (limit, len(text))


class GitMCP:
    def __init__(self, repo: Path, cache: gitlog.VectorCache) -> None:
        self.repo = Path(repo)
        self.cache = cache
        self.handlers = {"git_search": self._search, "git_show": self._show,
                         "git_file_history": self._file_history,
                         "git_worktree_diff": self._worktree, "git_index_status": self._status}

    def _search(self, a: Dict) -> Dict:
        return gitlog.search(self.repo, self.cache, a["query"], int(a.get("k") or 8),
                             a.get("mode") or "any", a.get("path") or None)

    def _show(self, a: Dict) -> Dict:
        sha = str(a["sha"]).strip()
        if sha.startswith("-"):
            raise ValueError("not a revision: %s" % sha)
        ctx = max(0, min(int(a.get("context", 3)), 20))
        args = ["show", "--no-color", "--no-ext-diff", "-U%d" % ctx, "--stat",
                "--patch", "--date=format:%Y-%m-%d %H:%M", sha]
        if a.get("path"):
            args += ["--", a["path"]]
        out = gitlog.git(self.repo, *args, check=False)
        if not out.strip():
            raise KeyError("no such commit: %s" % sha)
        return {"sha": sha, "text": _cap(out, SHOW_CHARS),
                "files": gitlog.files_touched(self.repo, sha, limit=0)[:40]}

    def _file_history(self, a: Dict) -> Dict:
        rows = gitlog.file_history(self.repo, a["path"], int(a.get("k") or 15))
        return {"path": a["path"], "url": gitlog.file_url(a["path"]), "commits":
                [dict(r, sha=r["sha"][:12]) for r in rows]}

    def _worktree(self, a: Dict) -> Dict:
        return {"status": gitlog.git(self.repo, "status", "--short", check=False),
                "diff": _cap(gitlog.git(self.repo, "diff", "HEAD", "--no-color", "--stat",
                                        "--patch", "-U2", check=False), DIFF_CHARS)}

    def _status(self, a: Dict) -> Dict:
        c = self.cache
        revs = len(gitlog.rev_list(self.repo))
        vectors = len(c.rows)
        distinct = len({u["h"] for u in c.meta["units"]})
        emb = c._embedder if not callable(c._embedder) or hasattr(c._embedder, "embed_texts") else None
        return {"cache": str(c.path), "head": gitlog.head(self.repo),
                "synced_head": c.meta.get("head", ""),
                "commits_in_history": revs, "commits_extracted": len(c.meta["done"]),
                "units": len(c.meta["units"]), "distinct_texts": distinct,
                "vectors": vectors, "dim": c.meta.get("dim", 0),
                "model": c.meta.get("model", ""),
                "stale_commits": max(0, revs - len(c.meta["done"])),
                "embedder_loaded": emb is not None, "embedder_error": c.error,
                "embedded_this_process": c.embed_calls}

    def handle(self, message: Dict) -> Optional[Dict]:
        method = message.get("method")
        mid = message.get("id")
        if method == "initialize":
            asked = (message.get("params") or {}).get("protocolVersion")
            return _ok(mid, {
                "protocolVersion": asked if asked in SUPPORTED else PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER,
                "instructions":
                    "Search this repository's history first (git_search: "
                    "semantic for a question, grep for words, pickaxe for a "
                    "string a diff added), then read a hit with git_show. "
                    "Queries run directly on git; only semantic ranking uses "
                    "a vector cache, which updates itself from HEAD."})
        if method in ("notifications/initialized", "notifications/cancelled") or mid is None:
            return None
        if method == "ping":
            return _ok(mid, {})
        if method == "tools/list":
            return _ok(mid, {"tools": TOOLS})
        if method == "tools/call":
            params = message.get("params") or {}
            handler = self.handlers.get(params.get("name"))
            if handler is None:
                return _error(mid, -32602, "no such tool: %s" % params.get("name"))
            try:
                payload = handler(params.get("arguments") or {})
            except Exception as exc:                        # noqa: BLE001
                return _ok(mid, {"content": [{"type": "text", "text": "%s: %s" % (type(exc).__name__, exc)}],
                                 "isError": True})
            return _ok(mid, {"content": [{"type": "text",
                                          "text": json.dumps(payload, indent=2, default=str)}],
                             "isError": False})
        return _error(mid, -32601, "no such method: %s" % method)


def _lazy_embedder():
    from ..core.embedding_service import get_default_service
    return get_default_service()


def open_server(repo: Path, cache_dir: Optional[Path] = None, embedder=_lazy_embedder) -> GitMCP:
    repo = Path(repo).resolve()
    return GitMCP(repo, gitlog.VectorCache(cache_dir or (repo / "build" / "git_vectors"),
                                           repo, embedder))


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m vertiscope.obsidian.git_mcp",
                                     description="MCP server over the repository's git history.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--build", action="store_true",
                        help="vectorise every commit not yet cached, print counts, exit")
    args = parser.parse_args(argv)
    server = open_server(args.repo, args.cache)
    if args.build:
        t0 = time.time()
        out = server.cache.sync()
        out["wall_s"] = round(time.time() - t0, 1)
        out["error"] = server.cache.error
        print(json.dumps(out), file=sys.stderr)
        return 0
    print("vertiscope git MCP over %s (cache %s)" % (server.repo, server.cache.path), file=sys.stderr)
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            reply = server.handle(json.loads(raw))
        except json.JSONDecodeError as exc:
            reply = _error(None, -32700, "parse error: %s" % exc)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
