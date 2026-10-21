"""Run the bridge: export a vault, or serve one.

    python -m vertiscope.obsidian export --workspace build/ws --vault ~/Vault
    python -m vertiscope.obsidian serve  --workspace build/ws

`export` names its pages by default rather than taking the whole workspace,
for the reason in the package docstring: a vault is a listable directory of
readable names and the store holds a browsing history. `--all-pages` is the
explicit opt-out.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..workspace import Workspace
from .export import export_vault
from .sidecar import serve


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `supervise` wraps `serve` in a child process that is restarted on a
    # native crash (`D-23`); every option after the workspace is serve's.
    if argv[:1] == ["supervise"]:
        from .supervise import supervise
        rest = argv[1:]
        if "--workspace" not in rest:
            print("supervise needs --workspace", file=sys.stderr)
            return 2
        i = rest.index("--workspace")
        workspace = Path(rest[i + 1])
        return supervise(workspace, rest[:i] + rest[i + 2:])
    parser = argparse.ArgumentParser(prog="python -m vertiscope.obsidian")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("export", help="write chunks into a vault as notes")
    ex.add_argument("--workspace", required=True, type=Path)
    ex.add_argument("--vault", required=True, type=Path)
    ex.add_argument("--folder", default="vertiscope",
                    help="subfolder of the vault to write into")
    ex.add_argument("--url", action="append", default=[],
                    help="a page to export; repeatable")
    ex.add_argument("--all-pages", action="store_true",
                    help="export every page in the workspace. This puts the "
                         "whole browsing history in a listable directory of "
                         "readable names -- say so deliberately.")

    sv = sub.add_parser("serve", help="loopback read-only window on the store")
    sv.add_argument("--workspace", required=True, type=Path)
    sv.add_argument("--port", type=int, default=8787)
    sv.add_argument("--kernel", action="store_true",
                    help="run notebook cells from the vault: opens "
                         "POST /kernel, one persistent Python subprocess per "
                         "note. Off by default because it executes arbitrary "
                         "code with this process's privileges -- a LARGER "
                         "permission than --enact, and gated separately for "
                         "that reason.")
    sv.add_argument("--semantic", action="store_true",
                    help="load the embedder, so chunks the browser cell "
                         "captures can be VECTORISED and therefore placed in "
                         "the projector. Without it a live capture stores its "
                         "chunks and the pane reports them as awaiting a "
                         "vector, which is honest but not much use.")
    sv.add_argument("--capture", action="store_true",
                    help="let the BROWSER CELL scan into this workspace: the "
                         "Electron pane folds the page it is showing and the "
                         "sidecar writes what it read. Off by default, and "
                         "not because it is dangerous -- it presses nothing "
                         "and runs no process -- but because writing takes "
                         "the store's WRITER lock, which excludes every other "
                         "reader, an MCP server included.")
    sv.add_argument("--allow-probe-captures", action="store_true",
                    help="accept captures from any client, not only the "
                         "plugin's browser cell. For a SCRATCH store a probe "
                         "writes into; never the reader's (D-39).")
    sv.add_argument("--kernel-timeout", type=float, default=None,
                    help="seconds one cell may run before its kernel is "
                         "killed (default 60)")
    sv.add_argument("--enact", action="store_true",
                    help="let the vault DRIVE the live page: clicking a "
                         "control in Obsidian presses it in a real browser. "
                         "Off by default. Every other route is read-only, and "
                         "this one still refuses the never-press set "
                         "(sign-in, checkout, delete, publish, send) and only "
                         "accepts addresses the workspace already holds.")

    args = parser.parse_args(argv)

    # Both subcommands READ the workspace. `serve` answers questions about it;
    # `export` reads chunks and writes markdown into the VAULT, never into the
    # store. So both take the weaker lock, which is what lets an MCP server or
    # a second reader open the same workspace at the same time.
    #
    # Two exceptions, and they are DIFFERENT permissions that happened to
    # share a flag. `--enact` drives a real browser and presses things on live
    # pages. `--capture` writes what the browser cell READ -- it presses
    # nothing and runs nothing. Deriving the lock from `--enact` alone meant
    # the browser cell's scan failed with a raw kuzu "Cannot execute write
    # operations in a read-only database", which names the symptom and not
    # the permission.
    #
    # Both still take the writer lock, so both exclude other openers.
    read_only = not (getattr(args, "enact", False)
                     or getattr(args, "capture", False))
    embedder = None
    if args.cmd == "serve":
        # The native stacks first, on this thread, before the embedder or the
        # workspace starts any other (`preload_native`: a DLL loaded later on
        # a worker deadlocked the process on the Windows loader lock).
        from .sidecar import preload_native
        print("preloaded: %s" % preload_native())
    if getattr(args, "semantic", False):
        from ..core.embedding_service import get_default_service

        embedder = get_default_service()
        print("embedder: %s" % embedder.status())
    with Workspace(args.workspace, read_only=read_only,
                   embedder=embedder) as ws:
        if args.cmd == "serve":
            # Both capabilities are named at startup, and loudly. A reader who
            # cannot see from the terminal what this process is allowed to do
            # has to read the command line to find out, and the command line is
            # the thing they may have got wrong.
            powers = []
            if args.enact:
                powers.append("ENACT -- the vault can drive a browser")
            if args.capture:
                powers.append("CAPTURE -- the browser cell can scan into this "
                              "workspace")
            if args.semantic:
                powers.append("SEMANTIC -- captured chunks get vectors")
            if args.kernel:
                powers.append("KERNEL -- the vault can RUN PYTHON here")
            print("vertiscope sidecar on http://127.0.0.1:%d  (%d pages, %s)"
                  % (args.port, len(ws.pages()),
                     " + ".join(powers) if powers else "read-only"))
            serve(ws, port=args.port, enact=args.enact,
                  capture=args.capture,
                  kernel=args.kernel, kernel_timeout=args.kernel_timeout,
                  plugin_captures_only=bool(args.capture and not args.allow_probe_captures))
            return 0

        if not args.url and not args.all_pages:
            parser.error("name pages with --url, or pass --all-pages "
                         "deliberately")
        urls = args.url or ws.pages()
        report = export_vault(ws, args.vault, urls=urls, folder=args.folder)

        print("notes       %d" % report.note_count)
        print("wikilinks   %d   web links that became vault edges"
              % report.wikilinks)
        print("unresolved  %d   left pointing at the web (target not scanned)"
              % report.unresolved)
        if report.wikilinks == 0 and report.unresolved:
            # Worth saying out loud: this is the shape of a working export of
            # pages that simply do not link to each other, and also the shape
            # of a broken resolver. Only the second is a problem, and the
            # counts alone do not distinguish them.
            print("\nnote: no link resolved. Expected when the exported pages "
                  "do not link to one another;\n      otherwise check that "
                  "link targets were scanned under the same spelling.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
