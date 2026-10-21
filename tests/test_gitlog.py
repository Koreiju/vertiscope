"""`vertiscope.gitlog` / `vertiscope.obsidian.git_mcp`: queries run on git, vectors are
a cache. No model: an injected fake embedder that counts what it is handed.

Every check has a planted arm -- the defect it exists to catch, built and shown
caught -- because a check that cannot fail is not measuring.
"""

from __future__ import annotations

import json
import subprocess
import zlib
from pathlib import Path

import numpy as np
import pytest

from vertiscope import gitlog
from vertiscope.obsidian.git_mcp import GitMCP, TOOLS


# ---- a fake embedder ----------------------------------------------------------

class FakeEmbedder:
    """Hashed bag of words -> unit vector. Similar words, similar vectors, so
    ranking is checkable; ``texts`` records every text it was asked to embed."""
    model_name = "fake-bow"
    dim = 64

    def __init__(self) -> None:
        self.texts = []

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for w in gitlog.tokens(text):
            v[zlib.crc32(w.encode()) % self.dim] += 1.0
        return v

    def embed_texts(self, texts):
        self.texts.extend(texts)
        return np.vstack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim))

    def embed_query(self, q):
        return self._vec(q)


class ReEmbedsEverything(gitlog.VectorCache):
    """The planted defect: a cache that forgets what it has vectorised."""

    def vectorise(self, batch: int = 64):
        self.rows, self.vecs = {}, np.zeros((0, 0), dtype=np.float32)
        return super().vectorise(batch)


# ---- a tiny repo ---------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def _commit(repo: Path, files: dict, message: str) -> str:
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    _git(r, "config", "commit.gpgsign", "false")
    shas = {}
    shas["a"] = _commit(r, {"mod.py": "def f():\n    return 1\n"},
                        "add f\n\nThe f helper returns one.")
    shas["b"] = _commit(
        r, {"mod.py": 'def f():\n    return 1\n\n\ndef picture_dedup(nodes):\n'
                      '    """Collapse duplicated pictures across graph nodes."""\n'
                      '    # remember zebra_marker identities between draws\n'
                      '    seen = set()\n'
                      '    return [n for n in nodes if n not in seen]\n'},
        "dedupe node pictures\n\nTwo nodes showing the same image drew twice; "
        "now one image per identity.\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    shas["c"] = _commit(r, {"notes.md": "# notes\n\nunrelated gardening text\n"},
                        "write notes about gardening")
    return r, shas


def _cache(repo, tmp_path, emb=None, cls=gitlog.VectorCache):
    emb = emb or FakeEmbedder()
    return cls(tmp_path / "vec", repo, emb), emb


# ---- added_prose: comments and docstrings, not code ----------------------------

PATCH = """@@ -0,0 +1,9 @@
+import os
+# the first comment line explains the invariant
+# and the second continues it
+x = compute(os.environ)
+def g():
+    \"\"\"A docstring that says what g does.\"\"\"
+    return x + 1  # trailing comment is code's tail, not a run
+// not a python comment but a comment-shaped line in js
-# a removed comment is not added prose either
"""


def test_added_prose_takes_comments_and_docstrings_not_code():
    got = gitlog.added_prose(PATCH)
    joined = " | ".join(got)
    assert "first comment line explains the invariant and the second continues it" in joined
    assert "A docstring that says what g does." in joined
    assert "comment-shaped line in js" in joined
    for code in ("import os", "compute(os.environ)", "def g()", "return x + 1"):
        assert code not in joined
    assert "removed comment" not in joined


def test_added_prose_planted_arm_a_code_line_would_be_caught():
    # the planted defect: treating every added line as prose
    naive = [l[1:] for l in PATCH.splitlines() if l.startswith("+")]
    assert any("compute(os.environ)" in l for l in naive)
    assert not any("compute(os.environ)" in r for r in gitlog.added_prose(PATCH))


def test_message_units_drop_trailers():
    units = gitlog.message_units("subj", "para one\n\nCo-Authored-By: X <x@y>")
    assert [u[2] for u in units] == ["subj", "para one"]


# ---- incremental cache: only new shas are embedded -----------------------------

def test_incremental_sync_embeds_only_new_commits(repo, tmp_path):
    r, shas = repo
    cache, emb = _cache(r, tmp_path)
    first = cache.sync()
    assert first["new_commits"] == 3 and first["embedded"] > 0
    n_first = len(emb.texts)
    assert n_first == len(cache.rows)

    again = cache.sync()                                   # nothing moved
    assert again["new_commits"] == 0 and again["embedded"] == 0
    assert len(emb.texts) == n_first

    _commit(r, {"mod.py": "# a freshly added comment about hysteresis\nx = 2\n"},
            "tune the hysteresis\n\nOne new paragraph.")
    third = cache.sync()
    assert third["new_commits"] == 1
    delta = emb.texts[n_first:]
    assert 0 < len(delta) <= 4                             # subject, para, comment run
    assert all("hysteresis" in t or "paragraph" in t for t in delta)

    # a fresh process reads the cache from disk and embeds nothing
    cache2, emb2 = _cache(r, tmp_path)
    assert cache2.sync()["embedded"] == 0 and emb2.texts == []


def test_incremental_planted_arm_a_reembedding_cache_is_caught(repo, tmp_path):
    r, _ = repo
    cache, emb = _cache(r, tmp_path, cls=ReEmbedsEverything)
    cache.sync()
    n_first = len(emb.texts)
    _commit(r, {"mod.py": "# another comment line for the planted run\n"}, "one more commit")
    cache.sync()
    assert len(emb.texts) - n_first > 2                    # re-embedded the old rows too
    honest, emb_h = _cache(r, tmp_path / "h")
    honest.sync()
    n = len(emb_h.texts)
    _commit(r, {"mod.py": "# yet another comment line for honest\n"}, "and another one")
    honest.sync()
    assert len(emb_h.texts) - n <= 3 < len(emb.texts) - n_first + 1


def test_identical_text_is_embedded_once(repo, tmp_path):
    r, _ = repo
    _commit(r, {"x.py": "# duplicated explanation of the cache\n"}, "first copy")
    _commit(r, {"y.py": "# duplicated explanation of the cache\n"}, "second copy")
    cache, emb = _cache(r, tmp_path)
    cache.sync()
    assert sum("duplicated explanation of the cache" in t for t in emb.texts) == 1


def test_code_is_never_embedded(repo, tmp_path):
    r, _ = repo
    cache, emb = _cache(r, tmp_path)
    cache.sync()
    blob = "\n".join(emb.texts)
    assert "Collapse duplicated pictures" in blob and "zebra_marker" in blob  # comments
    assert "return [n for n in nodes" not in blob and "def picture_dedup" not in blob
    assert "Co-Authored-By" not in blob


def test_rewritten_history_is_pruned(repo, tmp_path):
    r, shas = repo
    cache, _ = _cache(r, tmp_path)
    cache.sync()
    _git(r, "reset", "-q", "--hard", shas["b"])           # c leaves HEAD
    out = cache.sync()
    assert out["pruned"] == 1 and shas["c"] not in cache.meta["done"]
    assert shas["c"] not in {u["sha"] for u in cache.meta["units"]}


def test_a_stray_separator_byte_in_a_patch_forges_no_commit(repo, tmp_path):
    r, shas = repo
    _commit(r, {"w.py": "x = '\x01'\n# a comment beside a stray control byte\n"}, "stray byte")
    got = gitlog.read_commits(r, gitlog.rev_list(r))
    assert len(got) == 4 and all(len(c["sha"]) == 40 for c in got)
    # planted: the naive split on the bare separator WOULD have forged a record
    raw = gitlog.git(r, "log", "-p", "-U0", "--format=%x01%H%x00%s%x02")
    assert len(raw.split("\x01")) - 1 > 4


# ---- git queries ---------------------------------------------------------------

def test_grep_finds_the_commit_with_the_words(repo, tmp_path):
    r, shas = repo
    got = gitlog.git_grep(r, "same image identity", 5)
    assert got and got[0][0] == shas["b"]
    assert "image" in got[0][2]["t"]
    assert gitlog.git_grep(r, "wildebeest", 5) == []       # planted: absent word -> nothing


def test_pickaxe_finds_the_commit_whose_diff_added_the_string(repo, tmp_path):
    r, shas = repo
    got = gitlog.pickaxe(r, "zebra_marker", 5)
    assert [g[0] for g in got] == [shas["b"]]
    assert "zebra_marker" in got[0][2]["t"]
    assert gitlog.pickaxe(r, "never_written_anywhere", 5) == []
    # the message has no such string, so grep must NOT find it: pickaxe and grep differ
    assert gitlog.git_grep(r, "zebra_marker", 5) == []


def test_path_filter_limits_to_commits_touching_it(repo, tmp_path):
    r, shas = repo
    assert [g[0] for g in gitlog.git_grep(r, "notes gardening", 5, path="mod.py")] == []
    assert [g[0] for g in gitlog.git_grep(r, "notes gardening", 5, path="notes.md")] == [shas["c"]]
    hist = gitlog.file_history(r, "mod.py", 10)
    assert [h["sha"] for h in hist] == [shas["b"], shas["a"]]


def test_semantic_ranks_the_relevant_commit_first_and_degrades_to_lexical(repo, tmp_path):
    r, shas = repo
    cache, _ = _cache(r, tmp_path)
    out = gitlog.search(r, cache, "duplicated pictures across nodes", 3, "semantic")
    assert out["hits"][0]["sha"] == shas["b"][:12]
    assert out["hits"][0]["matched_by"] == ["semantic"]

    def boom():
        raise RuntimeError("no GPU")
    cache2 = gitlog.VectorCache(tmp_path / "v2", r, boom)
    out2 = gitlog.search(r, cache2, "duplicated pictures across nodes", 3, "semantic")
    assert "lexical" in out2["note"] and out2["hits"][0]["sha"] == shas["b"][:12]
    assert out2["hits"][0]["matched_by"] == ["lexical"]


# ---- reciprocal-rank fusion ----------------------------------------------------

def test_rrf_orders_by_agreement_and_planted_arm():
    fused = gitlog.rrf({"semantic": ["a", "b", "c"], "grep": ["d", "b", "e"]})
    order = [f[0] for f in fused]
    assert order[0] == "b"                                 # 2nd in both beats 1st in one
    assert set(order) == {"a", "b", "c", "d", "e"}
    assert dict((f[0], f[2]) for f in fused)["b"] == ["semantic", "grep"]
    scores = {f[0]: f[1] for f in fused}
    assert scores["b"] > scores["a"] and scores["b"] > scores["d"]
    # planted: concatenating the lists (no fusion) would put 'a' first
    assert (["a", "b", "c"] + ["d", "b", "e"])[0] == "a" and order[0] != "a"
    assert scores["b"] == pytest.approx(2 / (gitlog.RRF_K + 2))


def test_any_mode_fuses_semantic_and_grep(repo, tmp_path):
    r, shas = repo
    cache, _ = _cache(r, tmp_path)
    out = gitlog.search(r, cache, "image identity", 3, "any")
    top = out["hits"][0]
    assert top["sha"] == shas["b"][:12]
    assert set(top["matched_by"]) >= {"semantic", "grep"}


# ---- the MCP surface -----------------------------------------------------------

def _call(server, name, args=None, mid=1):
    reply = server.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}})
    res = reply["result"]
    return res["isError"], (json.loads(res["content"][0]["text"]) if not res["isError"]
                            else res["content"][0]["text"])


def test_mcp_tools_and_calls(repo, tmp_path):
    r, shas = repo
    cache, _ = _cache(r, tmp_path)
    server = GitMCP(r, cache)
    listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [t["name"] for t in listed["result"]["tools"]]
    assert names == ["git_search", "git_show", "git_file_history",
                     "git_worktree_diff", "git_index_status"] == [t["name"] for t in TOOLS]

    err, status = _call(server, "git_index_status")
    assert not err and status["commits_extracted"] == 0 and status["stale_commits"] == 3

    err, found = _call(server, "git_search", {"query": "zebra_marker", "mode": "pickaxe"})
    assert not err and found["hits"][0]["sha"] == shas["b"][:12]
    assert found["hits"][0]["files"][0]["path"] == "mod.py"
    assert found["hits"][0]["files"][0]["url"].startswith("code://")

    err, shown = _call(server, "git_show", {"sha": shas["b"][:12], "path": "mod.py"})
    assert not err and "picture_dedup" in shown["text"]
    err, bad = _call(server, "git_show", {"sha": "0" * 12})
    assert err and "no such commit" in bad
    err, bad = _call(server, "git_show", {"sha": "--output=x"})
    assert err

    err, hist = _call(server, "git_file_history", {"path": "mod.py"})
    assert [c["sha"] for c in hist["commits"]] == [shas["b"][:12], shas["a"][:12]]

    (r / "mod.py").write_text("# dirty\n", encoding="utf-8")
    err, wt = _call(server, "git_worktree_diff")
    assert " M mod.py" in wt["status"] and "dirty" in wt["diff"]

    _call(server, "git_search", {"query": "pictures", "mode": "semantic"})
    err, status = _call(server, "git_index_status")
    assert status["commits_extracted"] == 3 and status["stale_commits"] == 0
    assert status["vectors"] > 0 and status["embedder_loaded"]

    bad_mode = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "git_search",
                                         "arguments": {"query": "x", "mode": "nope"}}})
    assert bad_mode["result"]["isError"]
    assert server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": "nope"}})["error"]["code"] == -32602


def test_grep_and_show_do_not_load_the_embedder(repo, tmp_path):
    r, _ = repo
    loaded = []

    def factory():
        loaded.append(1)
        return FakeEmbedder()
    server = GitMCP(r, gitlog.VectorCache(tmp_path / "v", r, factory))
    _call(server, "git_search", {"query": "gardening", "mode": "grep"})
    _call(server, "git_search", {"query": "zebra_marker", "mode": "pickaxe"})
    _call(server, "git_file_history", {"path": "mod.py"})
    assert loaded == []                                    # lazy
    _call(server, "git_search", {"query": "gardening", "mode": "semantic"})
    assert loaded == [1]                                   # planted: semantic does load it
