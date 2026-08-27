"""`python -m domvec.analytics <url> [...]` — measure pages, write artifacts."""

from __future__ import annotations

import argparse
import pathlib
import sys

from ..browser import browser_session
from ..config import load_config
from .run import DEFAULT_ARTIFACT_DIR, measure_page, render_table, write_artifact


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="domvec-analytics",
        description="Score the affine map from page to REPL rendering.")
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--scrolls", type=int, default=2)
    parser.add_argument("--window", type=int, default=1200)
    parser.add_argument("--out", default=str(DEFAULT_ARTIFACT_DIR))
    args = parser.parse_args(argv)

    cfg = load_config()
    with browser_session(cfg) as driver:
        for url in args.urls:
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
