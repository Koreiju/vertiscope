"""The README's install path agrees with the code, statically (PLUGIN_GOAL 160).

The live proof (`python -m domvec.obsidian.newuser --both`) runs the README's
blocks in a fresh clone, venv, vault and Obsidian profile; it takes minutes.
These are the parts of it that need nothing running:

- every third-party module the package imports is declared in pyproject.
  Everything is imported lazily, so an undeclared one installs cleanly and
  fails only when its feature runs; the README's own `pip install -e .`
  crashed the sidecar on `gpt4all` (2026-11-15);
- the README's sidecar block starts on the port the plugin looks at;
- the README's blocks are the ones the proof runs, in order.

Each has a planted arm: the defect put back must be caught.
"""
import ast
import re
import sys
import tomllib
from pathlib import Path

from domvec.obsidian import newuser

REPO = Path(__file__).resolve().parents[1]

# Import name -> distribution name, where they differ.
DIST = {"sklearn": "scikit-learn", "umap": "umap-learn", "websocket": "websocket-client",
        "PIL": "pillow", "fitz": "pymupdf"}
# Pulled in by a declared dependency rather than imported in its own right.
TRANSITIVE = {"pynndescent"}


def third_party_imports(root: Path) -> dict:
    std = set(sys.stdlib_module_names)
    local = {p.stem for p in root.rglob("*.py")} | {p.name for p in root.rglob("*") if p.is_dir()}
    found: dict = {}
    for p in root.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                names = [n.module]
            for m in names:
                top = m.split(".")[0]
                # A bare import of the package's own module is a fallback for
                # running a file as a script (content_tagger's shadow_html_parser).
                if top in std or top == "domvec" or top in local:
                    continue
                found.setdefault(top, set()).add(p.relative_to(REPO).as_posix())
    return found


def declared(pyproject: dict) -> set:
    reqs = list(pyproject["project"]["dependencies"])
    for extra in pyproject["project"].get("optional-dependencies", {}).values():
        reqs += extra
    return {re.split(r"[<>=!~\[ ;]", r, maxsplit=1)[0].strip().lower().replace("_", "-") for r in reqs}


def undeclared(pyproject: dict) -> list:
    have = declared(pyproject)
    return sorted(m for m in third_party_imports(REPO / "domvec")
                  if m not in TRANSITIVE and DIST.get(m, m).lower().replace("_", "-") not in have)


def _pyproject() -> dict:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def test_every_import_is_declared():
    assert undeclared(_pyproject()) == []


def test_planted_missing_extra_is_caught():
    py = _pyproject()
    py["project"]["optional-dependencies"]["obsidian"] = [r for r in py["project"]["optional-dependencies"]["obsidian"]
                                                         if not r.startswith("gpt4all")]
    py["project"]["optional-dependencies"]["semantic"] = []
    assert "gpt4all" in undeclared(py)


def test_the_obsidian_extra_holds_what_the_sidecar_imports():
    # Not "declared somewhere": the README installs exactly `.[obsidian]`, so
    # what the sidecar needs has to be in core or that extra.
    py = _pyproject()
    have = {re.split(r"[<>=!~\[ ;]", r, maxsplit=1)[0].strip().lower().replace("_", "-")
            for r in py["project"]["dependencies"] + py["project"]["optional-dependencies"]["obsidian"]}
    need = third_party_imports(REPO / "domvec" / "obsidian")
    missing = sorted(m for m in need if m not in TRANSITIVE and DIST.get(m, m).lower().replace("_", "-") not in have)
    assert missing == []


def test_readme_blocks_are_the_proofs_steps():
    blocks = newuser.readme_blocks((REPO / "README.md").read_text(encoding="utf-8"))
    assert list(blocks) == ["install", "build", "sidecar"]
    assert '".[obsidian]"' in blocks["install"][0]
    assert newuser.GITHUB in blocks["install"][0] and newuser.VAULT_PLACEHOLDER in blocks["build"][0]
    # Planted: the plain install line comes back.
    p = newuser.Proof.__new__(newuser.Proof)
    p.blocks, p.plant, p.vault = blocks, "base_install", REPO / "x"
    assert '".[obsidian]"' not in p.script("install") and "pip install -e ." in p.script("install")


def _port_of(block: str):
    m = re.search(r"--port\s+(\d+)", block)
    return int(m.group(1)) if m else None


def test_readme_sidecar_starts_where_the_plugin_looks():
    blocks = newuser.readme_blocks((REPO / "README.md").read_text(encoding="utf-8"))
    cli_default = int(re.search(r'sv\.add_argument\("--port", type=int, default=(\d+)\)',
                                (REPO / "domvec/obsidian/__main__.py").read_text(encoding="utf-8")).group(1))
    plugin_default = int(re.search(r'sidecar: "http://127\.0\.0\.1:(\d+)"',
                                   (REPO / "obsidian-plugin/src/types.ts").read_text(encoding="utf-8")).group(1))
    port = _port_of(blocks["sidecar"][0]) or cli_default
    assert port == plugin_default == newuser.PORT
    # Planted: the README's earlier line, --port 8788, is caught.
    assert (_port_of(blocks["sidecar"][0].replace("supervise", "supervise --port 8788")) or cli_default) != plugin_default
