"""`python -m vertiscope.analytics <url> [...]` — measure pages, write artifacts."""

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
        prog="vertiscope-analytics",
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
    parser.add_argument("--anonymity", action="store_true",
                        help="measure what each anti-tracking measure costs "
                             "the fold, arm by arm")
    parser.add_argument("--arm", default="",
                        help="with --anonymity, run only this arm")
    parser.add_argument("--scale", action="store_true",
                        help="grow a store to thousands of pages and measure "
                             "what it costs; needs no browser")
    parser.add_argument("--fidelity", action="store_true",
                        help="report how far the capture evidence reaches -- "
                             "how many pages and origins stand behind it")
    parser.add_argument("--pages", type=int, default=2000,
                        help="with --scale, how many pages to grow to")
    parser.add_argument("--visible", action="store_true",
                        help="what a reader sees, against what the trie "
                             "holds, using no addresses at all. The only "
                             "independent check on recall: innerText is "
                             "computed by layout, not by a walk")
    parser.add_argument("--resolvable", action="store_true",
                        help="ask the page whether every address in the "
                             "trie names a node it has. The only oracle "
                             "independent of the fold and the walk, which "
                             "share an addressing convention by design")
    parser.add_argument("--reach", action="store_true",
                        help="from a control in the page to a caller who "
                             "can press it: captured by the fold, drawn in "
                             "the markdown, reachable from acts(), markable "
                             "by read(). Browser-free, over the corpus")
    parser.add_argument("--spoken", action="store_true",
                        help="words the fold captured that the render never "
                             "says. Every other measure grades an ADDRESS, "
                             "and all of them can be satisfied while the "
                             "page's words go missing -- two addresses at "
                             "one element, one deduped and one suppressed, "
                             "each a counted outcome, and no line drawn. "
                             "Browser-free, over the corpus")
    parser.add_argument("--affordance", action="store_true",
                        help="what the REPL offers to interact with, "
                             "against what the page can be. The coverage "
                             "arrows score addresses; this scores whether "
                             "a drawn control is a real one")
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
    parser.add_argument("--window-check", action="store_true",
                        help="S-11's verification pass: does the token window "
                             "still hold AFTER the scan, for chunks and for "
                             "the merge groups assembled from them")
    parser.add_argument("--workspace", default="build/corpus123",
                        help="with --window-check, the store to verify")
    parser.add_argument("--plant", action="store_true",
                        help="with --window-check, inject one record that is "
                             "certainly over, so a zero cannot be vacuous")
    args = parser.parse_args(argv)

    sizes = tuple(int(s) for s in args.sizes.split(",") if s.strip())

    if args.window_check:
        # Browser-free, and outside the session for the same reason
        # `--projection` is: this reads a store that has already been
        # written, and opening a browser to ask it would add a variable.
        from .window import (measure_window, render_window_table,
                             write_window_artifact)
        report = measure_window(args.workspace, window=args.window,
                                plant=args.plant, limit=args.limit)
        print(render_window_table(report), flush=True)
        print(f"  written: "
              f"{write_window_artifact(report, pathlib.Path(args.out))}",
              flush=True)
        return 0

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

    if args.reach:
        corpus = sorted(
            (pathlib.Path(__file__).resolve().parent.parent.parent
             / "tests" / "corpus").glob("*.html"))
        if args.limit:
            corpus = corpus[:args.limit]
        from .reach import (measure_reach, render_reach_table,
                            write_reach_artifact)

        report = measure_reach(corpus, window=args.window)
        print(render_reach_table(report), flush=True)
        print("  written: %s"
              % write_reach_artifact(report, pathlib.Path(args.out)),
              flush=True)
        return 0

    if args.spoken:
        corpus = sorted(
            (pathlib.Path(__file__).resolve().parent.parent.parent
             / "tests" / "corpus").glob("*.html"))
        if args.limit:
            corpus = corpus[:args.limit]
        from .spoken import (measure_spoken, render_spoken_table,
                             write_spoken_artifact)

        report = measure_spoken(corpus, window=args.window)
        print(render_spoken_table(report), flush=True)
        print("  written: %s"
              % write_spoken_artifact(report, pathlib.Path(args.out)),
              flush=True)
        return 0

    if args.scale or args.fidelity:
        # Browser-free, and outside the session for the same reason
        # `--projection` is: growing a store to thousands of pages takes
        # minutes and there is no reason to hold a driver open through it.
        corpus = sorted(
            (pathlib.Path(__file__).resolve().parent.parent.parent
             / "tests" / "corpus").glob("*.html"))
        from .scale import (fidelity_reach, measure_scale, render_scale_table,
                            write_scale_artifact)

        if args.fidelity:
            reach = fidelity_reach(corpus)
            print("")
            print("  how far the capture evidence reaches")
            print("")
            print("    pages measured        %6d" % reach["pages"])
            print("    distinct origins      %6d" % reach["distinct_origins"])
            print("    megabytes of html     %6.1f" % reach["megabytes"])
            print("")
            print("  Every coverage, order, dedup and recall figure this")
            print("  project reports is measured on exactly these. A number")
            print("  that holds here is a claim about these documents. It is")
            print("  not evidence about the next thousand.")
            if not args.scale:
                return 0

        if args.scale:
            import tempfile

            with tempfile.TemporaryDirectory(prefix="wfh_scale_") as tmp:
                report = measure_scale(corpus,
                                       str(pathlib.Path(tmp) / "ws"),
                                       target=args.pages)
            print(render_scale_table(report), flush=True)
            print("  written: %s"
                  % write_scale_artifact(report, pathlib.Path(args.out)),
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
        if args.anonymity:
            from .anonymity import (ARMS, measure_anonymity,
                                    render_anonymity_table,
                                    write_anonymity_artifact)
            wanted = [a for a in args.arm.split(",") if a.strip()] or None
            for name in (wanted or []):
                if name not in ARMS:
                    print("unknown arm %r; have: %s"
                          % (name, ", ".join(ARMS)), flush=True)
                    return 2
            report = measure_anonymity(_targets(args), window=args.window,
                                       arms=wanted)
            print(render_anonymity_table(report), flush=True)
            print(f"  written: "
                  f"{write_anonymity_artifact(report, pathlib.Path(args.out))}",
                  flush=True)
            return 0

        if args.visible:
            from .visible import (measure_visible, render_visible_table,
                                  write_visible_artifact)
            report = measure_visible(driver, _targets(args),
                                     context_window=args.window)
            print(render_visible_table(report), flush=True)
            print(f"  written: "
                  f"{write_visible_artifact(report, pathlib.Path(args.out))}",
                  flush=True)
            return 0

        if args.resolvable:
            from .resolvable import (measure_resolvable,
                                     render_resolvable_table,
                                     write_resolvable_artifact)
            report = measure_resolvable(driver, _targets(args),
                                        context_window=args.window)
            print(render_resolvable_table(report), flush=True)
            print(f"  written: "
                  f"{write_resolvable_artifact(report, pathlib.Path(args.out))}",
                  flush=True)
            return 0

        if args.affordance:
            from .affordance import (measure_affordance,
                                     render_affordance_table,
                                     write_affordance_artifact)
            report = measure_affordance(driver, _targets(args),
                                        context_window=args.window)
            print(render_affordance_table(report), flush=True)
            print(f"  written: "
                  f"{write_affordance_artifact(report, pathlib.Path(args.out))}",
                  flush=True)
            return 0

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
            targets = _targets(args)
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
        # The same target list as every other mode, so `--corpus` means
        # one thing everywhere. The coverage arrows score against
        # `groundtruth.isControl`, so a change there moves these
        # numbers, and re-measuring the whole corpus has to be one
        # command rather than a shell loop someone has to remember.
        for url in _targets(args):
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
