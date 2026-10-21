"""The other end of a notebook kernel: one persistent namespace, on stdin.

Run as a subprocess by `kernel.py`, one per note. It reads one JSON request per
line, executes the code in a namespace that persists across requests, and writes
one JSON reply per line. That is the whole protocol.

**Why a driver rather than `python -i`.** An interactive interpreter is a
human interface: it prints banners and prompts, it echoes, it formats
tracebacks for a terminal, and there is no reliable marker for "this statement
is finished". Every one of those has to be parsed around. A driver has a frame
already.

**The protocol lines are marked.** Executed code writes to stdout -- that is
the point of `print` -- and a reply sharing that stream with user output could
not be told apart from it. So every reply is prefixed with `_MARK`, and the
reader ignores any line without it. Code that writes to `sys.__stdout__`
directly is then merely noise rather than a parse error that kills the kernel.

**The namespace is a dict, and it is the cell-to-cell state.** `exec` with one
mapping for both globals and locals is what makes `x = 1` in one cell visible
to `print(x)` in the next. Passing separate dicts gives module-level semantics
where a comprehension cannot see its enclosing names, which breaks ordinary
notebook code in a way that reads as a Python bug.

**Reading stdin to EOF is what prevents orphans, and it is load-bearing.** The
`for line in sys.stdin` loop below ends when the parent's pipe closes, so a
kernel dies with the sidecar even when the sidecar is KILLED rather than asked
to stop — where `KernelPool.shutdown` never gets to run. Measured: four live
kernels, `Stop-Process -Force` on the sidecar, zero left four seconds later.
A driver that instead blocked on a socket, or polled a queue, would leak one
interpreter per note on every hard restart, and nothing on screen would say so.
"""

from __future__ import annotations

import ast
import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout

#: Prefixes every reply. A unit separator, which text does not normally carry.
_MARK = "\x1fVERTISCOPE\x1f"


def _run(code: str, ns: dict) -> dict:
    """Execute one cell, capturing what it printed and what it raised."""
    out, err = io.StringIO(), io.StringIO()
    value = None
    error = None
    try:
        # Compile in `exec` mode, but if the cell ENDS in an expression,
        # evaluate that separately and report its repr -- which is what a
        # notebook does, and what makes `df.describe()` on the last line show
        # something instead of nothing. `ast` is how the split is made
        # reliable; scanning the text for a trailing expression is not.
        tree = ast.parse(code, filename="<cell>", mode="exec")
        last = tree.body[-1] if tree.body else None
        if isinstance(last, ast.Expr):
            head = ast.Module(body=tree.body[:-1], type_ignores=[])
            tail = ast.Expression(body=last.value)
            with redirect_stdout(out), redirect_stderr(err):
                if head.body:
                    exec(compile(head, "<cell>", "exec"), ns, ns)
                result = eval(compile(tail, "<cell>", "eval"), ns, ns)
            # `None` is not a value worth showing: every statement-like call
            # returns it, and printing "None" after each one is noise.
            if result is not None:
                value = repr(result)
        else:
            with redirect_stdout(out), redirect_stderr(err):
                exec(compile(tree, "<cell>", "exec"), ns, ns)
    except BaseException:                       # noqa: BLE001
        # BaseException, not Exception: a cell that calls `sys.exit()` or is
        # interrupted must be REPORTED, not allowed to take the kernel down
        # silently and leave the caller waiting for a reply that never comes.
        error = traceback.format_exc()
    return {
        "ok": error is None,
        "stdout": out.getvalue(),
        "stderr": err.getvalue(),
        "value": value,
        "error": error,
    }


def main() -> int:
    ns: dict = {"__name__": "__cell__", "__builtins__": __builtins__}
    count = 0
    # Line-buffered reads from the real stdin; replies to the real stdout,
    # captured here BEFORE any cell gets a chance to rebind `sys.stdout`.
    real_stdout = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError as exc:
            reply = {"ok": False, "stdout": "", "stderr": "",
                     "value": None, "error": f"bad request: {exc}"}
        else:
            if request.get("op") == "shutdown":
                return 0
            count += 1
            reply = _run(request.get("code") or "", ns)
        reply["count"] = count
        print(_MARK + json.dumps(reply), file=real_stdout, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
