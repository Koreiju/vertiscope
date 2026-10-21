"""A command terminal, per pane, beside the notebook kernels.

`NOTEBOOK_PANEL_DESIGN` §4a: the switch selects a **kernel run** in place, and a
**command terminal** is what a *separate pane* holds — *"shell work that is not
a cell — PowerShell, a build, a git command"*.

**It is a command runner, not a pty, and the difference is worth stating.** A
real pseudo-terminal on Windows means ConPTY, which in Python means `pywinpty`
(a Rust core and a binary wheel) and in the plugin would mean `node-pty` (a
native module rebuilt per Electron version, ~50MB of xterm.js beside it — what
every Obsidian terminal plugin carries). This runs a persistent shell and pipes
its output instead. What that buys: no new dependency, on a project that guards
a four-package runtime list, and the same driver/pool/gate shape the kernel
already proved.

What it COSTS, said plainly because it will be met:

* No cursor control, so a progress bar redrawing itself arrives as many lines.
* No interactive prompts. A command that stops to ask something waits for input
  that cannot come, and hits the timeout. `git commit` without `-m` is the one
  everybody meets first.
* No TUI. `vim`, `htop`, `less` will not work, and should be refused rather than
  left to hang.

`pywinpty` is the upgrade path when those matter, and nothing here is shaped to
block it: a pty would replace `_Shell`'s pipes and keep the pool and the routes.

**Gated by the same flag as the kernel, deliberately.** A second flag would
imply a distinction that does not exist -- a Python kernel can already call
`subprocess.run`, so a reader who enabled it has shell access whether or not a
terminal pane exists. Pretending otherwise would be a permission that looks
meaningful and is not.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

#: Marks a reply, exactly as the kernel driver does and for the same reason:
#: the command's own output shares this stream, and a reply that could not be
#: told from it would be parsed as one.
_MARK = "\x1fVERTISCOPE\x1f"

DEFAULT_TIMEOUT = 120.0
MAX_SHELLS = 4

#: Programs that need a terminal this does not provide. Refused by name rather
#: than left to time out, because a hang gives the reader nothing to act on and
#: costs them the whole timeout to learn it.
_NEEDS_PTY = {
    "vim", "vi", "nvim", "nano", "emacs", "htop", "top", "less", "more",
    "man", "tmux", "screen", "ssh", "telnet", "ftp", "mc", "ranger",
}


class ShellError(RuntimeError):
    """A shell could not be started, or died in a way the caller must hear."""


def needs_a_terminal(command: str) -> str:
    """The program in `command` that this cannot run, or "".

    Checked by the POOL, before the command reaches a shell, and that placement
    is the point. Refusing is not dying: an unrunnable command must cost the
    reader the command, not the session -- their `cd`, their exports and their
    activated virtualenv all live in that process. The first version raised
    `ShellError` from inside `run()`, the pool treated it as a dead shell as it
    treats every other `ShellError`, and asking for `vim` silently threw away a
    working session.
    """
    head = command.strip().split()[0].lower() if command.strip() else ""
    stem = head.rsplit(".", 1)[0]
    return stem if stem in _NEEDS_PTY else ""


def _shells() -> List[Dict[str, str]]:
    """Shells this machine actually has, in the order they should be offered."""
    found: List[Dict[str, str]] = []
    for name, exe, args in (
        ("PowerShell 7", "pwsh", ["-NoLogo", "-NonInteractive", "-Command", "-"]),
        ("Windows PowerShell", "powershell",
         ["-NoLogo", "-NonInteractive", "-Command", "-"]),
        ("cmd", "cmd", ["/Q", "/K"]),
        ("bash", "bash", ["-s"]),
        ("zsh", "zsh", ["-s"]),
    ):
        path = shutil.which(exe)
        if path:
            found.append({"name": name, "exe": exe, "path": path,
                          "args": args})
    return found


def interpreters() -> Dict:
    """What this machine can run, for `P-N2`'s switch to be populated from.

    Discovery rather than a hardcoded list, because the list is a property of
    the machine and a fixed one is wrong on every machine but the author's.

    Jupyter kernels are included when `jupyter` is installed -- `P-N2` names
    them -- even though nothing executes through the Jupyter protocol yet. That
    is honest in both directions: the reader is told what is INSTALLED, and
    `runnable` says which of it this sidecar can currently drive.
    """
    out: Dict = {
        "python": [{
            "name": "this sidecar's interpreter",
            "path": sys.executable,
            "version": "%d.%d.%d" % sys.version_info[:3],
            "runnable": True,
        }],
        "shells": [dict(s, runnable=True) for s in _shells()],
        "jupyter_kernels": [],
    }

    # Other pythons on PATH, when they are not this one.
    for exe in ("python3", "python", "py"):
        path = shutil.which(exe)
        if path and os.path.normcase(path) != os.path.normcase(sys.executable):
            out["python"].append({"name": exe, "path": path,
                                  "version": "", "runnable": False})

    jupyter = shutil.which("jupyter")
    if jupyter:
        try:
            proc = subprocess.run([jupyter, "kernelspec", "list", "--json"],
                                  capture_output=True, text=True, timeout=20)
            specs = json.loads(proc.stdout or "{}").get("kernelspecs", {})
            for key, spec in specs.items():
                out["jupyter_kernels"].append({
                    "name": spec.get("spec", {}).get("display_name", key),
                    "key": key,
                    # Named and not runnable: this sidecar executes Python in a
                    # subprocess, not over the Jupyter protocol. Reporting them
                    # as runnable would be the claim `P-N1` is still Partial for.
                    "runnable": False,
                })
        except Exception:                       # noqa: BLE001
            # A broken or slow jupyter must not make discovery fail; the rest
            # of the answer is still true.
            pass
    return out


class _Shell:
    """One persistent shell process and the lock that serialises it."""

    def __init__(self, pane: str, spec: Dict[str, str], cwd: str = "") -> None:
        self.pane = pane
        self.spec = spec
        self.lock = threading.Lock()
        self.started = time.time()
        self.last_used = self.started
        self.commands = 0
        try:
            self.proc = subprocess.Popen(
                [spec["path"]] + list(spec["args"]),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd or None,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise ShellError(f"could not start {spec['name']}: {exc}") from exc

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def _reap(self) -> None:
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:                   # noqa: BLE001
                pass

    def kill(self) -> None:
        try:
            self.proc.kill()
        except Exception:                       # noqa: BLE001
            pass
        self._reap()

    def close(self) -> None:
        if not self.alive:
            self._reap()
            return
        try:
            self.proc.stdin.write("exit\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=2)
            self._reap()
        except Exception:                       # noqa: BLE001
            self.kill()

    def run(self, command: str, timeout: float) -> dict:
        """Run one command and collect everything it printed.

        The shell keeps running afterwards, so `cd` and environment variables
        persist between commands — which is the whole reason for a persistent
        process rather than one `subprocess.run` per command.
        """
        if not self.alive:
            raise ShellError("shell exited")

        # A sentinel ECHOED BY THE SHELL is what says the command finished.
        #
        # There is no other end-of-output signal on a pipe: the process does
        # not close its stdout, and a quiet moment is not the same as being
        # done -- a slow command would be truncated the first time it paused.
        # So the shell is asked to print a line we chose, after the command,
        # and everything before it is the output.
        token = "%s%d%s" % (_MARK, self.commands + 1, _MARK)
        try:
            self.proc.stdin.write(f"{command}\n")
            # `Write-Output` on PowerShell, `echo` elsewhere. Both go to the
            # same merged stream the command's own output is on.
            emit = ("Write-Output '%s'" if "powershell" in self.spec["exe"]
                    or self.spec["exe"] == "pwsh" else "echo '%s'")
            self.proc.stdin.write((emit % token) + "\n")
            self.proc.stdin.flush()
        except Exception as exc:                # noqa: BLE001
            raise ShellError(f"shell stopped accepting input: {exc}") from exc

        deadline = time.time() + timeout
        done, killed = threading.Event(), threading.Event()

        def _watchdog() -> None:
            if done.wait(max(0.0, deadline - time.time())):
                return
            killed.set()
            try:
                self.proc.kill()
            except Exception:                   # noqa: BLE001
                pass

        threading.Thread(target=_watchdog, daemon=True).start()
        lines: List[str] = []
        try:
            while True:
                line = self.proc.stdout.readline()
                if line == "":
                    if killed.is_set():
                        raise TimeoutError(f"command exceeded {timeout:g}s")
                    raise ShellError("shell closed its output")
                if token in line:
                    self.commands += 1
                    self.last_used = time.time()
                    return {"ok": True, "output": "".join(lines).rstrip("\n"),
                            "count": self.commands}
                lines.append(line)
        finally:
            done.set()


class ShellPool:
    """Per-pane shells. The same shape as `KernelPool`, for the same reasons."""

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT,
                 max_shells: int = MAX_SHELLS) -> None:
        self.timeout = timeout
        self.max_shells = max_shells
        self._shells: Dict[str, _Shell] = {}
        self._guard = threading.Lock()

    def shutdown(self) -> None:
        with self._guard:
            for sh in list(self._shells.values()):
                sh.close()
            self._shells.clear()

    def status(self) -> dict:
        with self._guard:
            return {
                "shells": [{"pane": s.pane, "shell": s.spec["name"],
                            "alive": s.alive, "commands": s.commands,
                            "age_s": round(time.time() - s.started, 1)}
                           for s in self._shells.values()],
                "max_shells": self.max_shells,
                "timeout_s": self.timeout,
                "available": _shells(),
            }

    def restart(self, pane: str) -> bool:
        with self._guard:
            sh = self._shells.pop(pane, None)
        if sh is None:
            return False
        sh.close()
        return True

    def run(self, pane: str, command: str, *, shell: str = "",
            cwd: str = "") -> dict:
        available = _shells()
        if not available:
            return {"ok": False, "output": "", "count": 0,
                    "error": "no shell found on PATH"}
        spec = next((s for s in available if s["exe"] == shell), available[0])

        refused = needs_a_terminal(command)
        if refused:
            # Returned, not raised: the session is untouched and still holds
            # whatever the reader had set up in it.
            return {"ok": False, "output": "", "count": 0,
                    "error": f"{refused!r} needs a real terminal, which this "
                             "is not -- it runs commands and pipes their "
                             "output. See vertiscope/obsidian/shell.py.",
                    "refused": True}

        evicted = None
        fresh = False
        with self._guard:
            sh = self._shells.get(pane)
            if sh is not None and (not sh.alive or sh.spec["exe"] != spec["exe"]):
                # A dead shell, or the reader switched interpreter. Either way
                # the old process is not the one they asked for.
                self._shells.pop(pane, None)
                sh.close()
                sh = None
            if sh is None:
                if len(self._shells) >= self.max_shells:
                    oldest = min(self._shells.values(), key=lambda s: s.last_used)
                    self._shells.pop(oldest.pane, None)
                    oldest.close()
                    evicted = oldest.pane
                sh = _Shell(pane, spec, cwd)
                self._shells[pane] = sh
                fresh = True

        with sh.lock:
            try:
                reply = sh.run(command, self.timeout)
            except TimeoutError as exc:
                with self._guard:
                    self._shells.pop(pane, None)
                sh.kill()
                return {"ok": False, "output": "", "count": 0,
                        "error": f"TimeoutError: {exc}",
                        "shell": "killed on timeout; session lost"}
            except ShellError as exc:
                with self._guard:
                    self._shells.pop(pane, None)
                sh.kill()
                return {"ok": False, "output": "", "count": 0,
                        "error": f"ShellError: {exc}"}

        reply["interpreter"] = spec["name"]
        if fresh:
            reply["shell"] = "started " + spec["name"]
        if evicted:
            reply["evicted"] = evicted
        return reply
