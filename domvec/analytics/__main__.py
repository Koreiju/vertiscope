"""`python -m domvec.analytics <url> [...]` — measure pages, write artifacts."""

from __future__ import annotations

import argparse
import pathlib
import sys

from ..browser import browser_session
from ..config import load_config
from .run import (DEFAULT_ARTIFACT_DIR, measure_page, qualify,
                  render_qualification, render_table, write_artifact)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="domvec-analytics",
        description="Score the affine map from page to REPL rendering.")
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--scrolls", type=int, default=2)
    parser.add_argument("--window", type=int, default=1200)
    parser.add_argument("--out", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--delta", action="store_true",
                        help="measure what one insertion costs against page "
                             "size, on the local scaling fixture")
    parser.add_argument("--sizes", default="100,400,1600")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--qualify", type=int, default=0,
                        metavar="N",
                        help="measure each page N times and report the "
                             "instrument's own spread instead of a score")
    args = parser.parse_args(argv)

    cfg = load_config()
    with browser_session(cfg) as driver:
        if args.delta:
            from .delta import (measure_delta_scaling, render_delta_table,
                                write_delta_artifact)
            sizes = tuple(int(s) for s in args.sizes.split(",") if s.strip())
            report = measure_delta_scaling(driver, sizes=sizes,
                                           repeats=args.repeats,
                                           context_window=args.window)
            print(render_delta_table(report), flush=True)
            print(f"  written: {write_delta_artifact(report, pathlib.Path(args.out))}",
                  flush=True)
            return 0
        for url in args.urls:
            if args.qualify:
                report = qualify(driver, url, repeats=args.qualify,
                                 scrolls=args.scrolls,
                                 context_window=args.window)
                print(render_qualification(report), flush=True)
                out = pathlib.Path(args.out)
                out.mkdir(parents=True, exist_ok=True)
                with (out / "qualification.jsonl").open(
                        "a", encoding="utf-8") as handle:
                    import json as _json
                    import time as _time
                    report["t"] = _time.time()
                    handle.write(_json.dumps(report, separators=(",", ":"))
                                 + chr(10))
                continue
            try:
                report = measure_page(driver, url, scrolls=args.scrolls,
                                      context_window=args.window)
            except Exception as exc:  # noqa: BLE001 - a failed page is a datum
                print(f"  {url}: {type(exc).__name__}: {exc}", flush=True)
                continue
            print(render_table(report), flush=True)
            path = write_artifact(report, pathlib.Path(args.out))
            print(f"  written: {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
