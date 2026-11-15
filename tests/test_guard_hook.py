"""The PreToolUse guard blocks the three ad-hoc moves and lets the harness by.

`.claude/hooks/guard.mjs` is run exactly as Claude Code runs it: JSON on
stdin, exit 2 to block. Planted arms: each rule is shown a command it must
catch (a guard that blocks nothing passes every clean case); the null arm is
the harness's own commands, which must go through untouched.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "guard.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run(command, tool="Bash"):
    p = subprocess.run([NODE, str(GUARD)], input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}),
                       capture_output=True, text=True, timeout=20)
    return p.returncode, p.stderr


BLOCKED = [
    ("cdp", "curl -s http://127.0.0.1:9222/json/list"),
    ("cdp", "node -e \"fetch('http://localhost:9222/json/version')\""),
    ("store", "python - <<'EOF'\nimport kuzu\ndb = kuzu.Database('build/vault/graph.kuzu')\nEOF"),
    ("store", "python -c \"from domvec.graphstore import GraphStore; GraphStore('build/x/graph.kuzu')\""),
    ("rename", "mv build/vaultws512 build/vaultws512_old"),
    ("rename", "Rename-Item build_store -NewName build_store2"),
    ("rename", "python -m pytest -q && mv build/old build/new"),
]

ALLOWED = [
    "python -m pytest -q tests/test_index_cache.py",
    "python -m domvec.analytics.design_state",
    "cd obsidian-plugin && npm run build",
    "npx tsc --noEmit",
    "node obsidian-plugin/confirm.mjs",
    "node obsidian-plugin/cdp.mjs eval 'app.vault.getName()'",
    "python -m domvec.analytics.store_crash --source build/x/graph.kuzu --arms planted",
    "git log --oneline -5",
    "python - <<'EOF'\np='domvec/search.py'\ns=open(p).read()\nEOF",
    "ls build/",
]


@pytest.mark.parametrize("rule,command", BLOCKED)
def test_planted_command_is_blocked(rule, command):
    code, err = _run(command)
    assert code == 2, (command, code, err)
    assert "[%s]" % rule in err, err


@pytest.mark.parametrize("command", ALLOWED)
def test_harness_command_goes_through(command):
    code, err = _run(command)
    assert code == 0, (command, code, err)


def test_powershell_is_guarded_too():
    code, _ = _run("Move-Item build/a build/b", tool="PowerShell")
    assert code == 2


def test_unparseable_input_is_let_through():
    p = subprocess.run([NODE, str(GUARD)], input="not json", capture_output=True, text=True, timeout=20)
    assert p.returncode == 0
