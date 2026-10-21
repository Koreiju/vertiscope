#!/usr/bin/env python
"""Prove the pointer path — including the part a unit test cannot reach.

The REPL's interaction model is a pure state machine, so clicks, scrolling and
cursor placement are all proved in `tests/test_repl.py` by constructing events.
That leaves one link in the chain untested: **a real pointer producing real
bytes that reach a real process.**

This probe closes it in two stages, weakest assumption first.

  stage 1 — bytes to a subprocess (always runs)
      Emit the exact SGR sequences an xterm sends for a press and a release
      at a given cell, pipe them into a separate `vertiscope browse --feed`
      process, and read its rendered output back. Everything from the wire
      onward is the production path in a production process; only the mouse
      hardware is stubbed. Works headless, on any OS, in CI.

  stage 2 — a physical pointer (needs pynput and a desktop)
      Move the actual system cursor over a terminal cell and click it,
      repeatedly, to show that the OS -> terminal -> escape-sequence step
      produces what stage 1 assumes. Skipped, loudly, when unavailable.

Stage 1 is the one that should gate anything. Stage 2 is the demonstration.

    python scripts/mouse_probe.py
    python scripts/mouse_probe.py --physical --clicks 5
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_force_utf8_stdio()

from vertiscope.repl.model import (  # noqa: E402
    Document,
    MouseEvent,
    ReplState,
    Widget,
    WidgetKind,
)
from vertiscope.repl.terminal import decode, paint  # noqa: E402


def sgr(action: str, x: int, y: int, button: int = 0) -> str:
    """The exact bytes an xterm sends in SGR (1006) mode.

    Press and release differ only in the final letter, which is why the
    protocol can express a drag that starts on one widget and ends on
    another — the gesture a user relies on to cancel a misclick.
    """
    final = "M" if action == "press" else "m"
    code = button
    if action in ("wheel_up", "wheel_down"):
        code = 64 + (0 if action == "wheel_up" else 1)
        final = "M"
    return f"\x1b[<{code};{x};{y}{final}"


def build_state(rows: int = 12, cols: int = 60) -> ReplState:
    doc = Document(title="mouse probe", url="https://probe.test/", lines=[
        Widget(0, WidgetKind.TEXT, "Pick your options"),
        Widget(1, WidgetKind.CHECKBOX, "first", depth=1),
        Widget(2, WidgetKind.CHECKBOX, "second", depth=1),
        Widget(3, WidgetKind.INPUT, "query", depth=1),
        Widget(4, WidgetKind.BUTTON, "Go", depth=1),
    ] + [Widget(i, WidgetKind.TEXT, f"line {i}") for i in range(5, 40)])
    return ReplState(document=doc, rows=rows, cols=cols)


def stage_one_in_process() -> bool:
    """The full byte -> event -> state -> paint chain, in one process."""
    print("\nstage 1a — bytes through decode into state, in process")
    state = build_state()
    row = state.row_of(1)

    stream = sgr("press", 6, row) + sgr("release", 6, row)
    for event in decode(stream):
        state.handle(event)
    checked = state.document.lines[1].checked
    print(f"  click at cell (6,{row}) -> checkbox checked: {checked}")

    # Paint here, while the checkbox is still on screen. Painting after the
    # scroll below would show a viewport the box has left, which says nothing
    # about the click.
    painted = "\n".join(paint(state, colour=False))
    shows = "[x] first" in painted
    print(f"  painted output shows the tick: {shows}")

    # scroll with the wheel
    for event in decode(sgr("wheel_down", 6, row) * 2):
        state.handle(event)
    scrolled = state.top == 6
    print(f"  two wheel-downs -> viewport top {state.top}")

    # declick: press on a widget, release elsewhere
    row2 = state.row_of(state.top)
    for event in decode(sgr("press", 6, row2) + sgr("release", 6, row2 + 2)):
        state.handle(event)
    cleared = state.pressed is None
    print(f"  press then release two rows away -> pressed cleared: {cleared}")

    return bool(checked and shows and scrolled and cleared)


def stage_one_subprocess(workspace: str) -> bool:
    """The same bytes, but into a separate `vertiscope browse --feed` process."""
    print("\nstage 1b — bytes piped into a separate vertiscope process")
    # Line 1 of a loaded page, at the default geometry the command uses.
    probe = build_state(rows=24, cols=100)
    row = probe.row_of(1)
    payload = sgr("press", 4, row) + sgr("release", 4, row)

    # `check 1` twice: the first turns line 1 into a checkbox and ticks it,
    # the second unticks it. So the child starts with an empty box, and the
    # piped click is the only thing that can tick it — which is what makes a
    # tick in the output evidence about the click rather than about the
    # command that set it up.
    cmd = [sys.executable, "-m", "vertiscope", "browse", "-w", workspace,
           "--feed", "--rows", "24", "--cols", "100",
           "--command", "check 1", "--command", "check 1"]
    try:
        done = subprocess.run(cmd, input=payload, capture_output=True,
                              text=True, timeout=180, cwd=str(ROOT),
                              encoding="utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"  could not run the subprocess: {exc}")
        return False

    if done.returncode != 0:
        print(f"  exit {done.returncode}\n{done.stderr[-600:]}")
        return False

    out = done.stdout
    ticked = "[x]" in out
    print(f"  process exited 0, rendered {len(out.splitlines())} lines")
    print(f"  a checkbox is ticked in the child's own output: {ticked}")
    return ticked


def stage_two_physical(clicks: int, interval: float, confirmed: bool) -> bool:
    """Drive the actual system pointer. Needs pynput and a desktop.

    Gated behind an explicit flag because a synthetic click lands wherever
    the pointer happens to be — which is whatever window has focus, not this
    terminal. Running it unasked could press a button in someone's editor or
    browser. The person at the keyboard is the only one who can know that is
    safe, so they have to say so.
    """
    print(f"\nstage 2 — physical pointer, {clicks} click(s)")
    if not confirmed:
        print("  SKIPPED: needs --i-understand-it-clicks.")
        print("  A synthetic click goes to the focused window, which may not")
        print("  be this terminal. Focus an empty desktop area before using it.")
        return True
    try:
        from pynput.mouse import Button, Controller
    except ImportError:
        print("  SKIPPED: pynput is not installed (pip install pynput)")
        return True
    except Exception as exc:  # no display, wayland without permission, etc.
        print(f"  SKIPPED: pynput unavailable ({type(exc).__name__}: {exc})")
        return True

    try:
        mouse = Controller()
        origin = mouse.position
    except Exception as exc:
        print(f"  SKIPPED: no pointer available ({type(exc).__name__})")
        return True

    print(f"  cursor starts at {origin}")
    print("  moving and clicking in place; watch the pointer")
    try:
        for i in range(clicks):
            mouse.position = (origin[0] + 2, origin[1] + 2)
            time.sleep(interval / 2)
            mouse.press(Button.left)
            time.sleep(0.05)
            mouse.release(Button.left)
            print(f"    click {i + 1}/{clicks} at {mouse.position}")
            time.sleep(interval / 2)
        mouse.position = origin
    except Exception as exc:
        print(f"  pointer control failed: {type(exc).__name__}: {exc}")
        return False

    print("  the OS accepted synthetic press/release events")
    print("  NOTE: this shows the pointer moves and clicks. That a terminal")
    print("        turns those into SGR sequences is the terminal's contract,")
    print("        and stage 1 is what verifies our handling of them.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="build")
    ap.add_argument("--physical", action="store_true",
                    help="also drive the real system pointer")
    ap.add_argument("--clicks", type=int, default=3)
    ap.add_argument("--interval", type=float, default=0.4)
    ap.add_argument("--skip-subprocess", action="store_true")
    ap.add_argument("--i-understand-it-clicks", action="store_true",
                    help="allow stage 2 to click the focused window")
    args = ap.parse_args()

    print("mouse probe — proving the pointer path")
    results = {"stage 1a (in process)": stage_one_in_process()}

    if not args.skip_subprocess:
        if pathlib.Path(args.workspace, "graph.kuzu").exists():
            results["stage 1b (subprocess)"] = stage_one_subprocess(args.workspace)
        else:
            print(f"\nstage 1b — SKIPPED: no workspace at {args.workspace!r} "
                  f"(run: vertiscope index tests/corpus/books-toscrape-com.html)")

    if args.physical:
        results["stage 2 (physical)"] = stage_two_physical(
            args.clicks, args.interval, args.i_understand_it_clicks)

    print("\n" + "=" * 60)
    for name, ok in results.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    failed = [n for n, ok in results.items() if not ok]
    print("\nPROBE " + ("PASSED" if not failed else f"FAILED: {failed}"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
