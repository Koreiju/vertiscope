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
    parser.add_argument("--embed", default="", metavar="DEVICE",
                        help="run the asynchronous phase for real, on `cpu` or "
                             "`gpu`. Without it `queue.flush` returns "
                             "immediately and `embed_ms` measures the "
                             "absence of embedding rather than its cost: "
                             "7,053 chunks were queued across 84 recorded "
                             "runs and none were ever embedded")
    parser.add_argument("--variants", default="",
                        help="sensor mechanisms to set for this run, as "
                             "name=on/off pairs: `dedup=on,gate=off`. "
                             "Without this no measurement can exercise "
                             "anything that is off by default, which is "
                             "how `dedup` came to be documented as on "
                             "while the code had it off")
    parser.add_argument("--stability", action="store_true",
                        help="what a page does when nothing is done to it: "
                             "two independent maps of the same live document, "
                             "no sensor between them. Their disagreement is "
                             "the resolution limit every drift score on that "
                             "page has to beat")
    parser.add_argument("--drift", action="store_true",
                        help="mutate each page repeatedly and score the "
                             "repaired trie against a fresh map of it")
    parser.add_argument("--mutations", type=int, default=10)
    parser.add_argument("--kind", default="insert",
                        choices=("insert", "delete", "edit", "relocate",
                                 "none"),
                        help="which gesture --drift applies")
    parser.add_argument("--corpus", action="store_true",
                        help="with --live-delta, run over the frozen corpus in "
                             "tests/corpus instead of the urls given")
    parser.add_argument("--limit", type=int, default=0,
                        help="with --corpus, stop after this many pages")
    parser.add_argument("--live-delta", action="store_true",
                        help="insert one node into each real page given as a "
                             "url and measure what it costs, in both chunking "
                             "modes")
    parser.add_argument("--projection", action="store_true",
                        help="measure what one change costs the markdown "
                             "projection, by change kind and page size; "
                             "needs no browser")
    parser.add_argument("--sizes", default="100,400,1600")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--qualify", type=int, default=0,
                        metavar="N",
                        help="measure each page N times and report the "
                             "instrument's own spread instead of a score")
    args = parser.parse_args(argv)

    sizes = tuple(int(s) for s in args.sizes.split(",") if s.strip())

    if args.projection:
        # Browser-free, and so deliberately outside the session below: the
        # question is how the read out of the trie scales, and opening a
        # browser to ask it would add a variable and a minute.
        from .projection import (measure_projection_scaling,
                                 render_projection_table,
                                 write_projection_artifact)
        report = measure_projection_scaling(sizes=sizes,
                                            repeats=args.repeats,
                                            context_window=args.window)
        print(render_projection_table(report), flush=True)
        print(f"  written: "
              f"{write_projection_artifact(report, pathlib.Path(args.out))}",
              flush=True)
        return 0

    def _targets(args):
        targets = list(args.urls)
        if args.corpus:
            root = pathlib.Path(__file__).resolve().parent.parent.parent
            pages = sorted((root / "tests" / "corpus").glob("*.html"))
            if args.limit:
                pages = pages[:args.limit]
            targets = [p.as_uri() for p in pages]
        return targets

    def _variants(text):
        """`dedup=on,gate=off` -> {"dedup": True, "gate": False}.

        Refuses rather than guesses: a typo that silently measured the default
        configuration is the exact failure this flag exists to prevent.
        """
        out = {}
        for part in (p.strip() for p in text.split(",")):
            if not part:
                continue
            name, sep, value = part.partition("=")
            value = value.strip().lower()
            if not sep or value not in ("on", "off", "true", "false"):
                raise SystemExit(
                    "--variants takes name=on/off pairs, not {!r}".format(part))
            out[name.strip()] = value in ("on", "true")
        return out

    def _embedder(device):
        """A real embedder, or None.

        Deliberately not the fake one. `WFH_FAKE_EMBEDDER` exists and would
        make this run without a model, and timing it would produce exactly the
        kind of number this flag was added to stop producing -- a phase that
        reports a cost for work it did not do.
        """
        if not device:
            return None
        from ..core.embedding_service import EmbeddingService
        return EmbeddingService(device=device)

    cfg = load_config()
    with browser_session(cfg) as driver:
        if args.stability:
            from .stability import (measure_stability,
                                    render_stability_table,
                                    write_stability_artifact)
            report = measure_stability(driver, _targets(args),
                                       context_window=args.window)
            print(render_stability_table(report), flush=True)
            print(f"  written: "
                  f"{write_stability_artifact(report, pathlib.Path(args.out))}",
                  flush=True)
            return 0

        if args.drift:
            from .drift import (measure_drift, render_drift_table,
                                write_drift_artifact)
            targets = list(args.urls)
            if args.corpus:
                root = pathlib.Path(__file__).resolve().parent.parent.parent
                pages = sorted((root / "tests" / "corpus").glob("*.html"))
                if args.limit:
                    pages = pages[:args.limit]
                targets = [p.as_uri() for p in pages]
            report = measure_drift(driver, targets,
                                   mutations=args.mutations,
                                   kind=args.kind,
                                   variants=_variants(args.variants),
                                   context_window=args.window)
            print(render_drift_table(report), flush=True)
            print(f"  written: "
                  f"{write_drift_artifact(report, pathlib.Path(args.out))}",
                  flush=True)
            return 0

        if args.live_delta:
            targets = list(args.urls)
            if args.corpus:
                # Frozen pages, loaded from disk and mutated in a real
                # browser. The corpus was selected for structural variety by
                # an earlier pass and committed; using it means the breadth
                # claim rests on pages chosen for reasons other than making
                # this measurement look good, and -- because they are frozen
                # -- on a run that can be replayed.
                root = pathlib.Path(__file__).resolve().parent.parent.parent
                pages = sorted((root / "tests" / "corpus").glob("*.html"))
                if args.limit:
                    pages = pages[:args.limit]
                targets = [p.as_uri() for p in pages]
            from .live_delta import (measure_live_delta,
                                     render_live_delta_table,
                                     write_live_delta_artifact)
            report = measure_live_delta(driver, targets,
                                        context_window=args.window,
                                        repeats=args.repeats)
            if args.corpus:
                from .live_delta import render_corpus_summary
                print(render_corpus_summary(report), flush=True)
            else:
                print(render_live_delta_table(report), flush=True)
            print(f"  written: "
                  f"{write_live_delta_artifact(report, pathlib.Path(args.out))}",
                  flush=True)
            return 0

        if args.delta:
            from .delta import (measure_delta_scaling, render_delta_table,
                                write_delta_artifact)
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
                                      variants=_variants(args.variants),
                                      embedder=_embedder(args.embed),
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
