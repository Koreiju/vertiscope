"""One Python kernel per note, as subprocesses the sidecar owns.

`NOTEBOOK_PANEL_DESIGN` §4: *"variables shared between cells in one note but
isolated from other notes"*. So the unit is the NOTE, not the vault and not the
cell — a note is what a reader thinks in, and it makes a kernel's lifetime match
a leaf's.

**Why the sidecar owns these and not the plugin.** The plugin is a renderer
inside Electron; spawning and reaping OS processes from there means the
processes outlive a pane, a reload leaks them, and there is no single place that
knows what is running. The sidecar is already the one long-lived process that
holds the workspace, it already has a gate for the dangerous route (`enact`),
and it already answers only on loopback. Adding one more gated capability there
is one door to reason about instead of two.

**It is off by default and the gate is on the SERVER.** Executing code from a
note is a larger capability than anything else here -- `enact` presses a button
in a browser, this runs arbitrary Python with the sidecar's own privileges. The
flag lives on the server for the same reason `enact`'s does: a plugin setting is
a client asserting something about itself, and the client is a page renderer in
an app the user installs plugins into. `POST /kernel` without `--kernel` answers
403 and says which, so a caller can tell refused from unavailable.

**A cell cannot hang the kernel forever.** Every request carries a deadline. On
a timeout the subprocess is killed rather than left running, because the reply
it would eventually send would arrive out of band and be read as the answer to
some LATER cell -- a wrong answer attributed to the wrong code, which is worse
than a slow one. The note's next request starts a fresh kernel, and the reply
says the state was lost.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional

#: Matches `_kernel_driver._MARK`. A reply is only a reply if it carries this.
_MARK = "\x1fVERTISCOPE\x1f"

#: Where the driver lives, by path rather than by `-m`. `-m` needs the package
#: importable in the child's working directory, which is the sidecar's cwd and
#: not ours to assume.
_DRIVER = Path(__file__).resolve().parent / "_kernel_driver.py"

#: Seconds a single cell may run before its kernel is killed. Generous, because
#: a real cell reads a file or fits a model; finite, because an accidental
#: `while True` must not need a process manager to recover from.
DEFAULT_TIMEOUT = 60.0

#: Kernels held open at once. A vault can have thousands of notes and each
#: kernel is a Python process; without a cap, a reader clicking through notes
#: accumulates interpreters until the machine swaps. The least recently used is
#: retired, which loses that note's variables -- said in the reply rather than
#: hidden, because silently-empty state reads as a bug in the user's code.
MAX_KERNELS = 8


class KernelError(RuntimeError):
    """A kernel could not be started, or died in a way the caller must hear."""


class _Kernel:
    """One subprocess and the lock that serialises access to it."""

    def __init__(self, note: str) -> None:
        self.note = note
        self.lock = threading.Lock()
        self.started = time.time()
        self.last_used = self.started
        self.executions = 0
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-u", str(_DRIVER)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                # No shell, and no inherited window on Windows: a kernel that
                # flashed a console per note would be unusable.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise KernelError(f"could not start a kernel: {exc}") from exc

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def _reap(self) -> None:
        """Close the pipes, whatever state the process is in.

        A killed subprocess leaves its `TextIOWrapper`s to be finalised by the
        garbage collector, which tries to flush a pipe whose other end is gone
        and raises `OSError: [Errno 22]` from inside `__del__`. Python prints
        that as "Exception ignored in:" with a traceback pointing at whatever
        line happened to trigger the collection -- so a timeout in one cell
        surfaced as a scary unrelated error somewhere else entirely. Closing
        them here makes the failure the one that actually happened.
        """
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:                   # noqa: BLE001
                pass

    def kill(self) -> None:
        """End it now and release the pipes."""
        try:
            self.proc.kill()
        except Exception:                       # noqa: BLE001
            pass
        self._reap()

    def close(self) -> None:
        """Ask, then insist. A driver blocked in `exec` will not read stdin."""
        if not self.alive:
            self._reap()
            return
        try:
            self.proc.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=2)
            self._reap()
        except Exception:                       # noqa: BLE001
            self.kill()

    def run(self, code: str, timeout: float) -> dict:
        """Execute one cell. Raises `KernelError` if the kernel is unusable."""
        if not self.alive:
            raise KernelError("kernel exited")
        deadline = time.time() + timeout
        try:
            self.proc.stdin.write(json.dumps({"code": code}) + "\n")
            self.proc.stdin.flush()
        except Exception as exc:                # noqa: BLE001
            raise KernelError(f"kernel stopped accepting input: {exc}") from exc

        # The deadline is enforced by a WATCHDOG, not by checking the clock
        # between reads.
        #
        # `readline()` on a pipe blocks until a line arrives, so a `while True:
        # pass` cell produces exactly one read that never returns and a
        # deadline test that never runs again. Measured: the first version hung
        # indefinitely on precisely that cell, with a 2s timeout set.
        #
        # `select` is not an option -- it does not accept pipes on Windows. A
        # reader thread plus a queue would work, and is a thread per cell.
        # Killing the process is both simpler and the thing we actually want:
        # the cell has to die anyway, and killing it makes `readline` return ""
        # on EOF, which the loop below already understands.
        # TWO events, not one. `done` is ours and means "stand down"; `killed`
        # is the watchdog's and means "I ended it". One event for both cannot
        # tell a timeout's EOF from a cell that called `os._exit`, and it leaves
        # a race where a reply arriving as the alarm expires gets its healthy
        # kernel killed anyway.
        done = threading.Event()
        killed = threading.Event()

        def _watchdog() -> None:
            if done.wait(max(0.0, deadline - time.time())):
                return                          # finished in time; stand down
            killed.set()
            try:
                self.proc.kill()
            except Exception:                   # noqa: BLE001
                pass

        alarm = threading.Thread(target=_watchdog, daemon=True)
        alarm.start()
        try:
            # Read until a MARKED line. Unmarked lines are a cell writing to
            # the real stdout past the redirect; they are noise, not protocol,
            # and dropping them is what keeps such a cell from killing the
            # kernel.
            while True:
                line = self.proc.stdout.readline()
                if line == "":
                    # EOF. Either the watchdog killed it, or the cell exited
                    # the interpreter. Those need different messages: one is a
                    # timeout the caller can retry, the other is a dead kernel.
                    if killed.is_set():
                        raise TimeoutError(f"cell exceeded {timeout:g}s")
                    raise KernelError("kernel closed its output")
                if line.startswith(_MARK):
                    self.executions += 1
                    self.last_used = time.time()
                    return json.loads(line[len(_MARK):])
        finally:
            # Wakes the watchdog whether we succeeded or raised, so a finished
            # cell does not have its kernel killed moments later by an alarm
            # nobody cancelled.
            done.set()


class KernelPool:
    """Per-note kernels, capped and reaped.

    Thread-safe because the sidecar is a `ThreadingHTTPServer`: two notes can be
    running cells at once, and two cells of ONE note must not be, which is what
    each kernel's own lock is for.
    """

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT,
                 max_kernels: int = MAX_KERNELS) -> None:
        self.timeout = timeout
        self.max_kernels = max_kernels
        self._kernels: Dict[str, _Kernel] = {}
        self._guard = threading.Lock()

    # -- lifetime ---------------------------------------------------------
    def _evict_if_needed(self) -> Optional[str]:
        """Retire the least recently used kernel. Returns whose, if any."""
        if len(self._kernels) < self.max_kernels:
            return None
        oldest = min(self._kernels.values(), key=lambda k: k.last_used)
        self._kernels.pop(oldest.note, None)
        oldest.close()
        return oldest.note

    def shutdown(self) -> None:
        with self._guard:
            for kernel in list(self._kernels.values()):
                kernel.close()
            self._kernels.clear()

    def status(self) -> dict:
        with self._guard:
            return {
                "kernels": [
                    {"note": k.note, "alive": k.alive,
                     "executions": k.executions,
                     "age_s": round(time.time() - k.started, 1)}
                    for k in self._kernels.values()
                ],
                "max_kernels": self.max_kernels,
                "timeout_s": self.timeout,
            }

    def restart(self, note: str) -> bool:
        """Drop a note's kernel. The next run starts a fresh one."""
        with self._guard:
            kernel = self._kernels.pop(note, None)
        if kernel is None:
            return False
        kernel.close()
        return True

    # -- execution --------------------------------------------------------
    def run(self, note: str, code: str) -> dict:
        """Run `code` in `note`'s kernel, starting or replacing it as needed."""
        evicted = None
        fresh = False
        with self._guard:
            kernel = self._kernels.get(note)
            if kernel is not None and not kernel.alive:
                # It died between requests -- a cell called os._exit, or it was
                # killed from outside. Replace it and SAY the state is gone.
                self._kernels.pop(note, None)
                kernel = None
            if kernel is None:
                evicted = self._evict_if_needed()
                kernel = _Kernel(note)
                self._kernels[note] = kernel
                fresh = True

        # Outside the pool guard: a long cell in one note must not block
        # another note from starting. Inside the KERNEL's lock: two cells of one
        # note share a namespace, so running them concurrently would interleave
        # writes to it.
        with kernel.lock:
            try:
                reply = kernel.run(code, self.timeout)
            except TimeoutError as exc:
                # Kill rather than abandon. A reply that arrives after we have
                # stopped waiting would be read as the answer to a later cell.
                with self._guard:
                    self._kernels.pop(note, None)
                # `kill`, not `close`: the watchdog has already killed it, and
                # `close` would try to write a shutdown line down a dead pipe.
                kernel.kill()
                return {"ok": False, "stdout": "", "stderr": "", "value": None,
                        "error": f"TimeoutError: {exc}", "count": 0,
                        "kernel": "killed on timeout; state lost"}
            except KernelError as exc:
                with self._guard:
                    self._kernels.pop(note, None)
                kernel.kill()
                return {"ok": False, "stdout": "", "stderr": "", "value": None,
                        "error": f"KernelError: {exc}", "count": 0,
                        "kernel": "died; state lost"}

        if fresh:
            reply["kernel"] = "started"
        if evicted:
            # Named, because the reader whose variables just vanished is not the
            # reader who caused it.
            reply["evicted"] = evicted
        return reply
