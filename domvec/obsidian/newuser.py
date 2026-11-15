"""The README's install and usage, proved the way a new Obsidian user meets them.

PLUGIN_GOAL 160 (2026-11-14): "in the next push, please ensure to prove out
and test installation and usage instructions for new obsidian users in the
README".

What is run is the README itself. Every block a reader is told to type is
marked `<!-- proof: <step> -->`, and this module runs those blocks in order,
as written. Two substitutions are made, both of which a reader makes too: the
GitHub URL becomes this repository's committed tree, and `/path/to/your/vault`
becomes a new vault. Nothing else is set up for the reader:

- the clone, the virtual environment and the vault are new;
- Obsidian runs on a profile of its own (`--user-data-dir`), so nothing on this
  machine can leak in. That covers the vault list, the plugin's machine-wide
  launch template in localStorage, and the workspace ports. It runs beside the
  reader's Obsidian on its own debug port and never touches it;
- the plugin is turned on the way the README says: community plugins on, then
  `domvec bridge` enabled.

Usage is then exercised the way the README describes it:

1. the 3D graph and the browser cell are opened;
2. a local page is browsed;
3. its chunks reach the store and the graph;
4. a word from it is found by the search panel.

Planted (`plant="base_install"`): the install line goes back to
`pip install -e .`, which installs cleanly. The sidecar then dies on its first
import, and the proof must fail at the sidecar step. Found 2026-11-15 by the
first run of exactly that line: "No module named 'gpt4all'", five crashes
inside 60 s.

    python -m domvec.obsidian.newuser [--plant base_install] [--keep] [--root DIR]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
GITHUB = "https://github.com/Koreiju/vertiscope"
VAULT_PLACEHOLDER = "/path/to/your/vault"
# The plugin's default sidecar and the CLI's default port. The README starts
# the sidecar without --port, so this is the number a new user ends up on.
PORT = 8787
CDP_PORT = 9223
FIXTURE = "tests/fixtures/catalog.html"
PLANTS = {"base_install": ('".[obsidian]"', ".")}


def readme_blocks(text: str) -> Dict[str, List[str]]:
    """The README's runnable blocks, keyed by their `proof:` step, in order."""
    out: Dict[str, List[str]] = {}
    for m in re.finditer(r"<!--\s*proof:\s*([\w-]+)\s*-->\s*```(?:bash|sh)\r?\n(.*?)```", text, re.S):
        out.setdefault(m.group(1), []).append(m.group(2))
    return out


def _git_bash() -> str:
    """Git Bash, never WSL's `bash.exe` (System32), which `which` finds first."""
    git = shutil.which("git")
    if git:
        for up in (1, 2):
            cand = Path(git).resolve().parents[up] / "bin" / "bash.exe"
            if cand.exists():
                return str(cand)
    cand = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
    if cand.exists():
        return str(cand)
    raise RuntimeError("Git Bash not found (the README's blocks are bash)")


def _health(port: int = PORT, timeout: float = 3.0) -> Optional[Dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return json.load(r)
    except Exception:                                   # noqa: BLE001
        return None


def _mine(root: Path) -> List[int]:
    """Processes started under the proof's root: its Obsidian, its sidecar and
    the sidecar's children. Matched on the root's path in the command line, so
    nothing of the reader's is ever touched."""
    import psutil
    needle = str(root).lower().replace("\\", "/")
    # Never the proof itself or what started it: `--root <dir>` puts the root
    # in this process's own command line, and the first --keep run killed
    # itself at its cleanup with nothing printed (2026-11-15).
    me = psutil.Process(os.getpid())
    spare = {me.pid} | {p.pid for p in me.parents()}
    pids = []
    # Only the kinds of process the proof starts. A shell's command line holds
    # the root too, and MSYS shells are missing from psutil's parent chain:
    # the bash running `--resume` was killed with it (exit 15).
    kinds = ("python", "obsidian", "node")
    for p in psutil.process_iter(["pid", "cmdline", "exe", "name"]):
        try:
            if not str(p.info["name"] or "").lower().startswith(kinds):
                continue
            cl = " ".join(p.info["cmdline"] or []).lower().replace("\\", "/")
            exe = str(p.info["exe"] or "").lower().replace("\\", "/")
            if (needle in cl or needle in exe) and p.info["pid"] not in spare:
                pids.append(p.info["pid"])
        except Exception:                               # noqa: BLE001
            continue
    return pids


def _sample(root: Path) -> List[Dict]:
    """Each process of the proof's, as it stands: what a hung start looks like
    from outside (the early-stall rule kills on CPU and size alone)."""
    import psutil
    out = []
    for pid in _mine(root):
        try:
            p = psutil.Process(pid)
            t = p.cpu_times()
            cl = p.cmdline()
            row = {"pid": pid, "name": p.name(), "mb": round(p.memory_info().rss / 1e6, 1),
                   "cpu": round(t.user + t.system, 2), "threads": p.num_threads(),
                   "cmd": " ".join(a for a in cl[1:4])[-90:]}
            # What it is loading: the DLLs mapped so far (the newest few) and
            # the files it holds open -- names the file a stalled start is on.
            try:
                maps = [m.path for m in p.memory_maps(grouped=True) if m.path.lower().endswith((".dll", ".pyd"))]
                row["dlls"] = len(maps)
                row["last_dlls"] = [Path(x).name for x in maps[-3:]]
            except Exception as exc:                    # noqa: BLE001
                row["dlls_error"] = str(exc)[:60]
            try:
                row["open"] = [Path(f.path).name for f in p.open_files()][-4:]
            except Exception:                           # noqa: BLE001
                pass
            out.append(row)
        except Exception:                               # noqa: BLE001
            continue
    return out


def _kill_mine(root: Path) -> int:
    import psutil
    n = 0
    for _ in range(3):
        pids = _mine(root)
        if not pids:
            break
        for pid in pids:
            try:
                psutil.Process(pid).kill(); n += 1
            except Exception:                           # noqa: BLE001
                pass
        time.sleep(1.0)
    return n


class Proof:
    def __init__(self, root: Path, plant: Optional[str] = None):
        self.root = root
        self.plant = plant
        self.vault = root / "vault"
        self.profile = root / "profile"
        self.clone = root / "vertiscope"
        self.steps: List[Dict] = []
        self.blocks = readme_blocks((REPO / "README.md").read_text(encoding="utf-8"))
        self.bash = _git_bash()

    # -- the README, as a reader types it ------------------------------------

    def script(self, step: str) -> str:
        body = "\n".join(self.blocks.get(step, []))
        # The committed tree in the folder a reader's clone makes (`vertiscope`,
        # from the URL), not the one this repository's path would name.
        body = body.replace(GITHUB, "file:///" + REPO.as_posix() + " " + GITHUB.rsplit("/", 1)[1])
        body = body.replace(VAULT_PLACEHOLDER, self.vault.as_posix())
        if self.plant in PLANTS:
            a, b = PLANTS[self.plant]
            body = body.replace(a, b)
        return "set -e\n" + body

    def record(self, step: str, ok: bool, t0: float, **evidence) -> bool:
        self.steps.append({"step": step, "ok": bool(ok), "s": round(time.time() - t0, 1), **evidence})
        return bool(ok)

    def run_block(self, step: str, cwd: Path, timeout: float) -> bool:
        t0 = time.time()
        if step not in self.blocks:
            return self.record(step, False, t0, error="the README has no `proof: %s` block" % step)
        try:
            r = subprocess.run([self.bash, "-c", self.script(step)], cwd=str(cwd), capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            return self.record(step, False, t0, error="timed out after %ds" % timeout)
        tail = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip() and "[notice]" not in ln][-6:]
        return self.record(step, r.returncode == 0, t0, code=r.returncode, tail=tail)

    # -- Obsidian on a profile of its own ------------------------------------

    def open_vault(self) -> bool:
        """The README's step 2, "Open folder as vault": a profile that knows this
        one vault and nothing else, as a fresh install would after the click."""
        t0 = time.time()
        self.vault.mkdir(parents=True, exist_ok=True)
        self.profile.mkdir(parents=True, exist_ok=True)
        (self.profile / "obsidian.json").write_text(json.dumps({"vaults": {"a1b2c3d4e5f60718": {
            "path": str(self.vault), "ts": int(time.time() * 1000), "open": True}}}), encoding="utf-8")
        exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Obsidian" / "Obsidian.exe"
        if not exe.exists():
            return self.record("open_vault", False, t0, error="Obsidian.exe not found at %s" % exe)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.app_proc = subprocess.Popen([str(exe), f"--user-data-dir={self.profile}",
                                          f"--remote-debugging-port={CDP_PORT}"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL, creationflags=flags)
        ready = False
        for _ in range(90):
            time.sleep(1.0)
            if (self.vault / ".obsidian").is_dir() and self.eval("!!(window.app && app.workspace && app.workspace.layoutReady)") is True:
                ready = True
                break
        return self.record("open_vault", ready, t0, dot_obsidian=(self.vault / ".obsidian").is_dir(),
                           vault_name=self.eval("app.vault.getName()"))

    def eval(self, expr: str, timeout: float = 60.0):
        from .live import Live
        try:
            if not hasattr(self, "_live"):
                self._live = Live(sidecar=f"http://127.0.0.1:{PORT}", cdp=f"http://127.0.0.1:{CDP_PORT}", timeout=timeout)
            return self._live.evaluate(expr)
        except Exception as exc:                        # noqa: BLE001
            if hasattr(self, "_live"):
                try:
                    self._live.close()
                except Exception:                       # noqa: BLE001
                    pass
                del self._live
            return {"error": str(exc)[:200]}

    def enable_plugin(self) -> bool:
        """The README's step 4: community plugins on, then domvec bridge enabled
        (what the two switches in Settings call)."""
        t0 = time.time()
        got = self.eval("""(async () => {
            await app.plugins.setEnable(true);
            await app.plugins.loadManifests();
            const listed = Object.keys(app.plugins.manifests);
            const name = (app.plugins.manifests["domvec-bridge"] || {}).name;
            await app.plugins.enablePluginAndSave("domvec-bridge");
            for (let i = 0; i < 60 && !app.plugins.plugins["domvec-bridge"]; i++) await new Promise((r) => setTimeout(r, 500));
            const p = app.plugins.plugins["domvec-bridge"];
            return { listed, name, loaded: !!p, sidecar_setting: p && p.settings && p.settings.sidecar,
                     harness: !!window.__domvec };
        })()""")
        ok = isinstance(got, dict) and got.get("loaded") and got.get("name") == "domvec bridge"
        return self.record("enable_plugin", ok, t0, **(got if isinstance(got, dict) else {"got": got}))

    def start_sidecar(self) -> bool:
        """The README's step 5, left running as a reader leaves it."""
        t0 = time.time()
        if "sidecar" not in self.blocks:
            return self.record("sidecar", False, t0, error="the README has no `proof: sidecar` block")
        if _health(PORT):
            return self.record("sidecar", False, t0, error=f"port {PORT} is already answering: not a new user's machine")
        log = open(self.root / "sidecar.log", "w", encoding="utf-8")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.sidecar_proc = subprocess.Popen([self.bash, "-c", self.script("sidecar")], cwd=str(self.clone),
                                             stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                             creationflags=flags)
        h = None
        samples = []
        for k in range(240):
            time.sleep(1.0)
            if k % 5 == 4 and len(samples) < 24:
                samples.append({"t": k + 1, "procs": [x for x in _sample(self.root) if x["name"].lower().startswith("python")]})
            h = _health(PORT)
            if h and h.get("ok") and h.get("backend") in (None, "up"):
                break
            if self.sidecar_proc.poll() is not None:
                break
        up = bool(h and h.get("ok") and h.get("backend") in (None, "up"))
        tail = []
        if not up:
            try:
                tail = [ln for ln in (self.root / "sidecar.log").read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()][-4:]
            except Exception:                           # noqa: BLE001
                pass
        crashes = []
        if not up:
            for f in (self.vault / ".domvec" / "workspaces" / "default").glob("crashes.log"):
                crashes = [ln for ln in f.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()][-8:]
        return self.record("sidecar", up, t0, port=PORT, backend=(h or {}).get("backend"),
                           exited=self.sidecar_proc.poll(), tail=tail, crashes=crashes,
                           samples=samples if not up else samples[:2])

    def use(self) -> bool:
        """The README's *Use*: the graph, the browser cell, a page, a search.

        Short calls polled from here: one call waiting minutes inside the app
        outlived the CDP socket's timeout and read as a failure (2026-11-15)."""
        t0 = time.time()
        url = (self.clone / FIXTURE).as_uri()
        opened = self.eval("""(async () => {
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const p = app.plugins.plugins["domvec-bridge"];
            const health = await p.sidecar.health().catch((e) => ({ error: String(e) }));
            app.commands.executeCommandById("domvec-bridge:domvec-open-graph");
            app.commands.executeCommandById("domvec-bridge:domvec-open-browser");
            let b = null;
            for (let i = 0; i < 40 && !b; i++) { await sleep(250); b = app.workspace.getLeavesOfType("domvec-browser-view")[0]?.view; }
            if (b) b.go(%s);
            return { health_ok: !!(health && health.ok), browser: !!b,
                     graph_leaf: app.workspace.getLeavesOfType("domvec-graph-view").length };
        })()""" % json.dumps(url))
        if not isinstance(opened, dict) or not opened.get("browser"):
            return self.record("use", False, t0, opened=opened)
        pages, t_page = 0, None
        for k in range(180):
            time.sleep(1.0)
            pages = (_health(PORT) or {}).get("pages", 0)
            if pages >= 1:
                t_page = k + 1
                break
        GRAPH = """(() => { const g = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
            return { view: !!g, graph: !!(g && g.graph), nodes: g && g.graph ? g.graph.graphData().nodes.length : 0,
                     level: g ? g.level : null, search: !!(g && g.searchField) }; })()"""
        g, t_graph = {}, None
        for k in range(90):
            g = self.eval(GRAPH)
            if isinstance(g, dict) and g.get("nodes", 0) > 0 and g.get("search"):
                t_graph = 2 * k
                break
            time.sleep(2.0)
        word, hits, top = "spectrographs", 0, ""
        for _ in range(20):
            got = self.eval("""(async () => { const g = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
                const f = g && g.searchField; if (!f) return { hits: 0 };
                f.input.value = %s; await f.run();
                return { hits: f.hits.length, top: f.hits[0] ? String(f.hits[0].url).slice(-40) : "",
                         panel: f.el.classList.contains("is-panel") }; })()""" % json.dumps(word))
            if isinstance(got, dict) and got.get("hits"):
                hits, top = got["hits"], got.get("top", "")
                break
            time.sleep(3.0)
        ok = opened.get("health_ok") and pages >= 1 and (g or {}).get("nodes", 0) > 0 and hits >= 1
        return self.record("use", ok, t0, page=FIXTURE, pages=pages, page_after_s=t_page, graph=g,
                           graph_after_s=t_graph, word=word, hits=hits, top=top, **opened)

    # -- the whole thing ------------------------------------------------------

    def run(self) -> Dict:
        t0 = time.time()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.run_block("install", self.root, 1800)
             and self.open_vault()
             and self.run_block("build", self.clone, 900)
             and self.enable_plugin()
             and self.start_sidecar()
             and self.use())
        finally:
            killed = _kill_mine(self.root)
        failed = next((s["step"] for s in self.steps if not s["ok"]), None)
        return {"plant": self.plant, "ok": failed is None and len(self.steps) == 6, "failed_at": failed,
                "s": round(time.time() - t0, 1), "root": str(self.root), "killed": killed, "steps": self.steps}


def _rmtree(root: Path) -> None:
    """Delete the proof's own root. git's object files are read-only on Windows,
    and an `ignore_errors` delete left the clone behind, so the next run's
    `git clone` refused the folder (2026-11-15). The bit is cleared and the
    delete retried; anything still there is an error, said out loud."""
    import stat

    def clear(func, path, *_):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    for _ in range(3):
        if not root.exists():
            return
        _kill_mine(root)
        shutil.rmtree(root, onexc=clear) if sys.version_info >= (3, 12) else shutil.rmtree(root, onerror=clear)
    if root.exists():
        raise RuntimeError("could not delete the proof root %s" % root)


def prove(plant: Optional[str] = None, root: Optional[Path] = None, keep: bool = False) -> Dict:
    root = Path(root) if root else Path(tempfile.gettempdir()) / "domvec-readme-proof" / (plant or "clean")
    _rmtree(root)
    out = Proof(root, plant).run()
    if not keep:
        _rmtree(root)
        out["kept"] = False
    return out


def write_report(results: List[Dict]) -> Path:
    """`build_analytics/readme_proof.json`: what the last proof saw, per arm."""
    dest = REPO / "build_analytics" / "readme_proof.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO),
                                                         capture_output=True, text=True).stdout.strip(),
                                "arms": results}, indent=2), encoding="utf-8")
    return dest


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m domvec.obsidian.newuser", description=__doc__.split("\n")[0])
    ap.add_argument("--plant", choices=sorted(PLANTS), help="run the planted arm only")
    ap.add_argument("--both", action="store_true", help="the clean arm, then the planted one")
    ap.add_argument("--keep", action="store_true", help="keep the clone, venv and vault afterwards")
    ap.add_argument("--root", type=Path)
    ap.add_argument("--resume", choices=["sidecar"], help="on a kept --root: run only this step again")
    a = ap.parse_args(argv)
    if a.resume:
        pr = Proof(a.root, None)
        pr.app_proc = None
        try:
            pr.start_sidecar()
        finally:
            _kill_mine(a.root) if not a.keep else None
        print(json.dumps(pr.steps, indent=2))
        return 0 if pr.steps and pr.steps[-1]["ok"] else 1
    arms = [None, "base_install"] if a.both else [a.plant]
    results = [prove(p, a.root, a.keep) for p in arms]
    print(json.dumps(results, indent=2))
    print("report:", write_report(results))
    clean = next((r for r in results if r["plant"] is None), None)
    planted = next((r for r in results if r["plant"]), None)
    ok = (clean is None or clean["ok"]) and (planted is None or (not planted["ok"] and planted["failed_at"] == "sidecar"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
