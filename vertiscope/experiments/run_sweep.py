"""The continuous sweep. Harvest, then breadth, then depth, forever, resumable.

Run as:  python -m vertiscope.experiments.run_sweep [--depth-pages N]

Writes  build_sweep/urls.txt  and  build_sweep/runs.jsonl.  Both are resumed
on restart, so this can be killed and relaunched without losing a scan.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import shutil
import sys
import tempfile
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from vertiscope.browser import build_driver               # noqa: E402
from vertiscope.config import load_config                 # noqa: E402
from vertiscope.experiments.harvest import harvest        # noqa: E402
from vertiscope.experiments.sweep import Recorder, run_page  # noqa: E402
from vertiscope.repl.app import Repl                      # noqa: E402
from vertiscope.workspace import Workspace                # noqa: E402

OUT = pathlib.Path("build_sweep")

# The configurations under test. `original` is the deep serializer's own
# algorithm and is measured by the same harness, so the comparison is against
# where this design started rather than only among its own choices.
CONFIGS = {
    "default":     {},
    # A second arm identical to `default`. Each configuration visits a page
    # at a different moment, so live drift — ads, feeds, timestamps, a
    # results list that reorders — is confounded with the mechanism under
    # test. This arm measures that drift directly: any variant delta smaller
    # than default-vs-control is noise, not an effect. Without it the first
    # paired table showed a transport encoding changing the line count, which
    # is impossible by construction and was the page moving underneath.
    "control":     {},
    "original":    {"__original__": True},
    "pathdelta":   {"pathdelta": True},
    "valdict":     {"valdict": True},
    "shape":       {"shape": True},
    "packed":      {"packed": True},
    "subtreegate": {"subtreegate": True},
    "spans":       {"spans": True},
    "merge":       {"merge": True},
    "semantic":    {"semantic": True},
    "rank":        {"rank": True},
    "dedup":       {"dedup": True},
    "simhash":     {"simhash": True},
    "viewport":    {"viewport": True},
    "crosspage":   {"crosspage": True},
    "idanchor":    {"idanchor": True},
    "anchored":    {"anchored": True},
    "attrs":       {"attrs": True},
    "perchunk":    {"perchunk": True},
    "lazy":        {"lazy": True},
    "eager":       {"eager": True},
    "nocharwatch": {"charwatch": False},
    "fused":       {"fused": True},
    "nogate":      {"gate": False},
    "nocache":     {"cache": False},
    "nointern":    {"intern": False},
    "chunkdelta":  {"chunkdelta": True},
    "textdict":    {"textdict": True},
    "coalesce":    {"coalesce": True},
    "deepgate":    {"deepgate": True},
    # the combination the measurements so far point at
    "combined":    {"pathdelta": True, "valdict": True, "subtreegate": True,
                    "fused": True, "merge": True, "crosspage": True},
    "combined2":   {"pathdelta": True, "textdict": True,
                    "subtreegate": True, "deepgate": True,
                    "chunkdelta": True, "merge": True},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=int, default=5000)
    ap.add_argument("--depth-pages", type=int, default=60)
    ap.add_argument("--scrolls", type=int, default=10)
    # Scanning need not wait for the corpus to be finished. The harvester
    # appends and the scanner re-reads, so a second process can measure the
    # pages already found while the first keeps finding more — 35 minutes of
    # wall clock went into harvest alone before a single page was scanned.
    ap.add_argument("--no-harvest", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    urls_path = OUT / "urls.txt"
    rec = Recorder(OUT / "runs.jsonl")

    cfg = load_config()
    driver = build_driver(cfg, headless=True)
    driver.set_page_load_timeout(45)
    try:
        # --- 1. corpus ---------------------------------------------------
        have = len(urls_path.read_text(encoding="utf-8").splitlines()) \
            if urls_path.exists() else 0
        if have < args.targets and not args.no_harvest:
            print(f"[harvest] {have} -> {args.targets}", flush=True)
            harvest(driver, urls_path, target=args.targets,
                    progress=lambda m: print("[harvest]", m, flush=True))
        urls = [u.strip() for u in
                urls_path.read_text(encoding="utf-8").splitlines() if u.strip()]
        print(f"[corpus] {len(urls)} urls, "
              f"{len({urlsplit(u).netloc for u in urls})} hosts", flush=True)

        # --- 2. the depth sample, chosen once and stably ------------------
        # Frozen once, to a file. The sample was being recomputed from
        # urls.txt on every start — and urls.txt grows while the harvester
        # runs, so each restart drew a different 60 pages. Rows then
        # accumulated across disjoint page sets and the paired intersection
        # stayed empty no matter how many scans completed: 289 runs, zero
        # comparable pages. A panel has to be the same panel.
        rng = random.Random(20260819)
        depth_file = OUT / "depth.txt"
        if depth_file.exists():
            depth = [u.strip() for u in
                     depth_file.read_text(encoding="utf-8").splitlines()
                     if u.strip()]
        else:
            by_host = {}
            for u in urls:
                by_host.setdefault(urlsplit(u).netloc, []).append(u)
            depth = [rng.choice(v) for v in by_host.values()]
            rng.shuffle(depth)
            depth = depth[:args.depth_pages]
            depth_file.write_text(chr(10).join(depth), encoding="utf-8")
        print(f"[depth] panel frozen at {len(depth)} page(s)", flush=True)

        # --- 3. depth first: the contrast is the scarce answer ------------
        # One workspace per configuration, not one for the sweep. `open`
        # serves a page from the store when it has it, so after the first
        # configuration scanned a page every later one read the stored copy
        # and never booted a sensor — 50 of 92 rows came back "no sensor".
        # A per-variant store also keeps `crosspage` honest: it may only
        # suppress what *its own* run has already seen.
        # Page outer, configuration inner, order shuffled per page.
        # Running each configuration as a block confounded it perfectly with
        # time: every `default` visit happened minutes before every
        # `pathdelta` visit, and the pair differed by a systematic 20% in
        # lines-per-chunk across 35 pages — a difference no transport
        # encoding can cause. Interleaving puts every configuration's visit
        # to a page within the same few minutes, and shuffling stops the
        # first arm from always paying the cold-cache cost.
        names = [n for n, v in CONFIGS.items() if not v.get("__original__")]
        for u in depth:
            todo = [n for n in names if not rec.has(u, n)]
            if not todo:
                continue
            rng.shuffle(todo)
            for name in todo:
                tmp = tempfile.mkdtemp(prefix="wfh_sweep_")
                try:
                    with Workspace(tmp) as ws:
                        repl = Repl(store=ws.store, workspace=ws)
                        repl.state.rows, repl.state.cols = 40, 110
                        repl.nav.driver = driver
                        row = run_page(repl, u, name, CONFIGS[name],
                                       args.scrolls)
                        row["tier"] = "depth"
                        rec.add(row)
                        print(f"[depth] {name:12s} "
                              f"{row.get('elapsed_s',0):5.1f}s ok={row['ok']} "
                              f"{u[:56]}", flush=True)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)

        # --- 4. breadth: the rate needs pages -----------------------------
        tmp = tempfile.mkdtemp(prefix="wfh_sweep_breadth_")
        try:
            with Workspace(tmp) as ws:
                repl = Repl(store=ws.store, workspace=ws)
                repl.state.rows, repl.state.cols = 40, 110
                repl.nav.driver = driver
                for i, u in enumerate(urls):
                    if rec.has(u, "default"):
                        continue
                    row = run_page(repl, u, "default", {}, args.scrolls)
                    row["tier"] = "breadth"
                    rec.add(row)
                    print(f"[breadth] {i:5d} {row.get('elapsed_s',0):5.1f}s "
                          f"ok={row['ok']} search={row.get('search_found',0)} "
                          f"page={row.get('pagination_found',0)} {u[:50]}",
                          flush=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        rec.close()
        try:
            driver.quit()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
