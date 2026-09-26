"""Run the live checks against a FRESH, EMPTY store, seeded by the plugin itself.

    python -m domvec.obsidian fresh                  # every check
    python -m domvec.obsidian fresh G-79 G-54        # just these
    python -m domvec.obsidian fresh --seed-only      # build the store, run nothing

**Why.** Every live check used to run against `build/corpus123`, a store
written over weeks by every past version of the sensor, the chunker and the
drain. `CLAUDE.md`: *a rendering claim must be measured against a corpus
rendered by the code under test*, and that store is a recording of what some
PAST renderer did -- its titles were blanked by one old drain, its lexical rows
lost by another, and every crash left it in whatever state the kill found it.
A check that passes there says the current code copes with old damage; a
check that fails there may be failing on the damage. (User, 2026-09-26: *"tear
down the current db so that all new tests run in a fresh and empty db"*.)

**In trie terms.** Each run starts from an empty trie: no `Page`, `Address`
or `Chunk`. The seeding phase fills it by the ONLY path the product has -- the
browser cell lands on a page, the sensor folds it, the capture writes the
page's `url : xpath : markdown : content` paths and the drain chunks and
vectorises them -- so every node every check then reads was written by the
code loaded in the app at that moment, and the seed list is the whole of the
store's contents, which makes every denominator nameable.

**What it does, in order.**

1. Deletes the previous run's workspace under `build/test_runs/` (a store this
   harness made; nothing else is touched -- `build/corpus123` is never
   opened) and makes an empty one.
2. Starts a supervised sidecar on it, on its own port, so the working
   sidecar on 8788 keeps serving the corpus.
3. Points the plugin at that sidecar (its `sidecar` setting), reloads it.
4. Seeds: navigates the browser cell through `SEED` -- local fixtures, served
   here on a loopback port, then the public pages the checks name -- and
   waits for each to land in the store and for its chunks to get vectors.
5. Reloads the plugin again, so the graph pane fits the seeded store, and
   runs the checks inside the plugin (`Live.verify`).
6. Always, even on failure: points the plugin back at the previous sidecar,
   reloads it, and stops the test sidecar. The workspace is kept until the
   next run, for a post-mortem.

The report (seed evidence plus every check's verdict) goes to
`build_analytics/fresh_run.json`.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from .live import Live

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "build" / "test_runs"
FIXTURES = ROOT / "tests" / "fixtures"
REPORT = ROOT / "build_analytics" / "fresh_run.json"
PORT = 8790

#: Local fixtures: pages whose only motion is the one a check causes.
SEED_FIXTURES = [
    "inline_prose.html", "mixed_inline.html", "link_family.html",
    "metadata_family.html", "svg_diagram.html", "shadow_catalogue.html",
]
#: The public pages the checks browse to or look for by name: G-78/G-79 open
#: Radix tree, G-80 opens Trie, and G-40/G-16 look for books.toscrape. The
#: rest give the page projector enough pages to fit and the search enough
#: overlap between pages (merge groups, G-63) to rank.
SEED_PAGES = [
    "https://en.wikipedia.org/wiki/Radix_tree",
    "https://en.wikipedia.org/wiki/Trie",
    "https://books.toscrape.com/",
    "https://en.wikipedia.org/wiki/B-tree",
    "https://en.wikipedia.org/wiki/Hash_table",
    "https://en.wikipedia.org/wiki/Suffix_tree",
]


def _get(url: str, timeout: float = 10.0) -> Optional[Dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:                               # noqa: BLE001
        return None


def _serve_fixtures():
    """The fixture directory on a loopback port (port 0: never collides)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(FIXTURES))
    handler.log_message = lambda *a, **k: None      # type: ignore[attr-defined]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def _kill_tree(proc: subprocess.Popen) -> None:
    """`supervise` runs `serve` as a CHILD; stopping the parent alone would
    leave the child holding the store and the port."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.call(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def fresh_workspace() -> Path:
    """Delete the previous test workspace(s) and make an empty one."""
    RUNS.mkdir(parents=True, exist_ok=True)
    for old in RUNS.glob("run_*"):
        shutil.rmtree(old, ignore_errors=True)
    ws = RUNS / time.strftime("run_%Y%m%d_%H%M%S")
    ws.mkdir()
    return ws


def start_sidecar(ws: Path, port: int = PORT, timeout: float = 240.0):
    """A supervised `serve --semantic --capture` on the fresh workspace."""
    log = open(ws / "sidecar.log", "w", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "domvec.obsidian", "supervise",
         "--workspace", str(ws), "--port", str(port), "--semantic", "--capture"],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=env)
    url = "http://127.0.0.1:%d" % port
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("test sidecar exited (%s); see %s"
                               % (proc.returncode, ws / "sidecar.log"))
        got = _get(url + "/health", timeout=5)
        if got and got.get("ok"):
            return proc, url, got
        time.sleep(2)
    _kill_tree(proc)
    raise RuntimeError("test sidecar did not answer /health in %gs" % timeout)


def point_plugin(live: Live, url: str) -> str:
    """Set the plugin's sidecar to `url`, persisted; return the old one."""
    got = live.evaluate(
        "(async () => { const p = app.plugins.getPlugin('domvec-bridge');"
        " const old = p.settings.sidecar; p.settings.sidecar = %s;"
        " await p.saveSettings(); return old; })()" % json.dumps(url))
    return str(got or "")


def seed(live: Live, sidecar: str, urls: List[str], *,
         per_page_s: float = 120.0) -> Dict:
    """Browse each page in the plugin and wait until the store holds it.

    Landing on a page is what captures it (`did-stop-loading` ->
    `pageChanged`), so this presses nothing: it navigates and waits. A page is
    SEEDED when `/pages` lists it and none of the store's chunks are waiting
    for a vector -- held AND embedded, the two things every later check reads.
    """
    live.act("open", "browser")
    rows = []
    for url in urls:
        t0 = time.time()
        nav = live.act("navigate", url)
        landed = (nav.get("url") or nav.get("result", {}).get("url")
                  if isinstance(nav, dict) else None)
        held = False
        health: Dict = {}
        deadline = t0 + per_page_s
        while time.time() < deadline:
            listed = _get(sidecar + "/pages") or {}
            held = any(u == url or u.rstrip("/") == url.rstrip("/")
                       for u in listed.get("urls") or [])
            health = _get(sidecar + "/health") or {}
            if held and not health.get("chunks_without_vector"):
                break
            time.sleep(2)
        rows.append({"url": url, "landed": landed, "held": held,
                     "chunks_total": health.get("chunks_total"),
                     "chunks_without_vector": health.get("chunks_without_vector"),
                     "s": round(time.time() - t0, 1)})
        print("seed %-60s held=%s chunks=%s unvectorised=%s %.0fs" % (
            url[:60], held, health.get("chunks_total"),
            health.get("chunks_without_vector"), time.time() - t0), flush=True)
    return {"pages": rows, "asked": len(urls),
            "held": sum(1 for r in rows if r["held"])}


def wait_fitted(sidecar: str, timeout: float = 300.0) -> Dict:
    """The projector has fitted the seeded store, and caught up with it."""
    deadline = time.time() + timeout
    got: Dict = {}
    while time.time() < deadline:
        got = _get(sidecar + "/projector?drawable=1", timeout=30) or {}
        if got.get("fitted") and not got.get("fitting") \
                and not got.get("queue") and not got.get("drawable_unprojected"):
            return {"ready": True, **got}
        time.sleep(3)
    return {"ready": False, **got}


def fresh_run(only: Optional[List[str]] = None, *, port: int = PORT,
              seed_only: bool = False, timeout_s: float = 2400) -> Dict:
    """Seed a fresh store through the plugin, run the checks, restore."""
    live = Live()
    ws = fresh_workspace()
    print("fresh workspace %s" % ws, flush=True)
    proc, sidecar, health0 = start_sidecar(ws, port)
    print("test sidecar %s: %s pages at start" % (sidecar, health0.get("pages")),
          flush=True)
    server, origin = _serve_fixtures()
    previous = ""
    report: Dict = {"workspace": str(ws), "sidecar": sidecar,
                    "empty_at_start": {k: health0.get(k) for k in
                                       ("pages", "chunks_total", "addresses")}}
    try:
        previous = point_plugin(live, sidecar)
        report["previous_sidecar"] = previous
        live.reload_plugin(wait=False)
        urls = ["%s/%s" % (origin, f) for f in SEED_FIXTURES] + SEED_PAGES
        report["seed"] = seed(live, sidecar, urls)
        report["projector"] = wait_fitted(sidecar)
        if not seed_only:
            report["checks"] = Live(sidecar=sidecar).verify(
                only, reload=True, timeout_s=timeout_s,
                store="fresh %s, %d/%d pages seeded" % (
                    ws.name, report["seed"]["held"], report["seed"]["asked"]))
    finally:
        if previous:
            point_plugin(live, previous)
        try:
            live.reload_plugin(wait=False)
        except Exception:                           # noqa: BLE001
            pass
        server.shutdown()
        _kill_tree(proc)
        crashes = ws / "crashes.log"
        report["crashes"] = (crashes.read_text(encoding="utf-8").splitlines()
                             if crashes.exists() else [])
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=1, default=str),
                          encoding="utf-8")
    return report


def main(argv: List[str]) -> int:
    seed_only = "--seed-only" in argv
    only = [a for a in argv if not a.startswith("--")]
    got = fresh_run(only or None, seed_only=seed_only)
    checks = got.get("checks") or {}
    print("seeded %s/%s pages; projector ready=%s" % (
        got["seed"]["held"], got["seed"]["asked"], got["projector"].get("ready")))
    for r in checks.get("results") or []:
        print("%-6s %s  %s" % (r["id"], "PASS" if r["pass"] else "FAIL",
                               json.dumps(r.get("evidence"))[:160]))
    if checks:
        print("%s/%s passed%s" % (checks.get("passed"), checks.get("total"),
              ("; stopped: " + checks["stopped_because"])
              if checks.get("stopped_because") else ""))
    print("report: %s" % REPORT)
    return 0 if (seed_only or checks.get("passed") == checks.get("total")) else 1
