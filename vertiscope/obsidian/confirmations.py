"""The record of what has been SEEN working: one writer, merged by requirement.

`build_analytics/live_confirmations.{json,md}` is what `design_state.md`
folds in as "seen working in the running application". It used to be written
only by `confirm.mjs`, and each run REPLACED it: a three-check run on
2026-09-26 left a record of three rows, erasing every verdict before it, and
the design state then reported 135 done rows "with no live check" on the
strength of a file that had forgotten them. The in-app runners -- the MCP
`confirm` tool and the fresh-store runner -- did not write it at all, so the
path the checks now actually take could not reach the record.

So there is one writer, here, and it MERGES: each requirement keeps its latest
verdict, and each verdict says when it was seen, at which commit, and against
WHICH STORE. That last field is not decoration. `CLAUDE.md`: a claim must be
measured against a corpus rendered by the code under test, and a verdict read
off the long-lived working store and one read off a fresh store the run seeded
itself are different claims. The record keeps them apart.

    python -m vertiscope.obsidian.confirmations results.json --store "working"
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build_analytics"


def _head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def record(results: List[Dict], *, store: str, runner: str,
           out: Path = OUT) -> Dict:
    """Merge `results` into the record; return the merged record."""
    path = out / "live_confirmations.json"
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        blob = {}
    # An old replace-style file carries one date for all its rows.
    rows = {r["id"]: dict(r, when=r.get("when") or blob.get("when", "?"))
            for r in blob.get("results") or [] if r.get("id")}
    when = time.strftime("%Y-%m-%d %H:%M")
    head = _head()
    for r in results:
        if not r.get("id"):
            continue
        rows[r["id"]] = {"id": r["id"], "asks": r.get("asks", ""),
                         "pass": bool(r.get("pass")), "evidence": r.get("evidence"),
                         "when": when, "commit": head, "store": store,
                         "runner": runner}
    merged = {"when": when, "last_run": {"when": when, "commit": head,
                                         "store": store, "runner": runner,
                                         "ids": [r.get("id") for r in results],
                                         "passed": sum(1 for r in results if r.get("pass"))},
              "results": sorted(rows.values(), key=lambda r: r["id"])}
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=1, default=str), encoding="utf-8")
    (out / "live_confirmations.md").write_text(_markdown(merged), encoding="utf-8")
    return merged


def _markdown(blob: Dict) -> str:
    rows = blob["results"]
    last = blob["last_run"]
    ok = sum(1 for r in rows if r.get("pass"))
    lines = [
        "# Live confirmations", "",
        "*Written by `vertiscope/obsidian/confirmations.py` from runs against the",
        "RUNNING plugin and sidecar. Do not edit.*", "",
        "Each requirement keeps its LATEST verdict. **%d of %d pass.** Last run "
        "%s at `%s` (%s, store: %s): %d of %d." % (
            ok, len(rows), last["when"], last["commit"], last["runner"],
            last["store"], last["passed"], len(last["ids"])), "",
        "A row here has been seen to work in the application. A requirement",
        "absent from this file has not been, whatever its status column says.",
        "The `store` column says what the check read: a fresh store the run",
        "seeded through the plugin, or the long-lived working one.", "",
        "| id | asks | verdict | seen | store | evidence |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| `%s` | %s | %s | %s `%s` | %s | `%s` |" % (
            r["id"], r.get("asks", ""), "**pass**" if r.get("pass") else "**FAIL**",
            r.get("when", "?"), r.get("commit", ""), r.get("store", "?"),
            json.dumps(r.get("evidence"), default=str)[:300].replace("|", "\\|")))
    lines.append("")
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    results = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    store = "working"
    runner = "confirm.mjs"
    if "--store" in argv:
        store = argv[argv.index("--store") + 1]
    if "--runner" in argv:
        runner = argv[argv.index("--runner") + 1]
    got = record(results.get("results", results) if isinstance(results, dict)
                 else results, store=store, runner=runner)
    print("recorded %d; %d requirements on record"
          % (len(got["last_run"]["ids"]), len(got["results"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
