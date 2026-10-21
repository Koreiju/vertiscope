/**
 * A command terminal, in a separate pane.
 *
 * `NOTEBOOK_PANEL_DESIGN` §4a resolves `P-N2`: the switch selects a **kernel
 * run in place**, and a **command terminal is what a separate pane holds** --
 * *"shell work that is not a cell: PowerShell, a build, a git command"*. So
 * this is a view, not a strip under the editor, and the distinction is the
 * requirement rather than a layout preference.
 *
 * **It is a command runner, not an emulator.** The shell lives in the sidecar
 * (`vertiscope/obsidian/shell.py`), which already owns the notebook kernels for the
 * reason step 3 established: one long-lived process holding OS processes, one
 * gate, one list of what is running. What it does not do is a pty -- no cursor
 * control, no interactive prompts, no TUI. Every Obsidian terminal plugin
 * carries xterm.js and node-pty to get those; this carries neither, and the
 * cost is stated in the shell module rather than discovered.
 *
 * So there is no xterm.js here on purpose. A command goes down, its output
 * comes back as text, and the pane appends it. `<pre>` rather than a canvas,
 * because the output IS text and a terminal emulator would be ~50MB to render
 * text a `<pre>` already renders.
 *
 * The PANE is the session boundary, as the note is the kernel's: `cd` and
 * environment persist within a pane and not across them, so two terminals are
 * two shells and neither moves the other's prompt.
 */

import { ItemView, WorkspaceLeaf } from "obsidian";

import { Sidecar } from "./sidecar";
import { Interpreters, ShellReply } from "./types";

export const TERMINAL_VIEW = "vertiscope-terminal-view";

export class TerminalView extends ItemView {
  /** This pane's session id. Stable for the life of the view. */
  private pane = `pane-${Math.random().toString(36).slice(2, 10)}`;
  private shell = "";
  private log!: HTMLElement;
  private input!: HTMLInputElement;
  private picker!: HTMLSelectElement;
  private busy = false;
  /** Commands typed here, newest last, for up-arrow recall. */
  private history: string[] = [];
  private cursor = 0;

  constructor(leaf: WorkspaceLeaf, private sidecar: Sidecar) { super(leaf); }

  getViewType() { return TERMINAL_VIEW; }
  getIcon() { return "square-terminal"; }
  getDisplayText() { return "vertiscope terminal"; }

  async onOpen() {
    const root = this.containerEl.children[1] as HTMLElement;
    root.empty();
    root.addClass("vertiscope-terminal");

    const bar = root.createDiv({ cls: "vertiscope-terminal-bar" });
    this.picker = bar.createEl("select", { cls: "vertiscope-terminal-shell" });
    const restart = bar.createEl("button", { text: "restart" });
    restart.onclick = () => this.restart();

    this.log = root.createEl("pre", { cls: "vertiscope-terminal-log" });
    const row = root.createDiv({ cls: "vertiscope-terminal-row" });
    row.createSpan({ cls: "vertiscope-terminal-prompt", text: ">" });
    this.input = row.createEl("input", { cls: "vertiscope-terminal-input" });
    this.input.placeholder = "a command, not a cell";
    this.input.addEventListener("keydown", (e) => this.onKey(e));

    await this.discover();
    // The caveat goes where it CANNOT scroll away, not into the scrollback.
    //
    // It started as a three-line banner in the log, and in a narrow bottom
    // split that is most of the viewport: the banner wrapped, the log
    // overflowed by the first command, and every scroll left a half-line
    // against an edge -- which reads as a rendering fault rather than as
    // scrolled text. Scrollback is for what happened; a standing fact about
    // the pane is not that.
    //
    // On the bar, where it is always legible, and on the input, where it is
    // read at the moment a reader is about to type the thing it is about.
    bar.setAttribute("aria-label",
                     "Commands run in the sidecar. No pty: interactive " +
                     "prompts and TUI programs are refused.");
    bar.createSpan({ cls: "vertiscope-terminal-note", text: "no pty" });
    this.input.title = "Commands run in the sidecar. No pty: interactive " +
                       "prompts and TUI programs are refused.";
  }

  async onClose() {
    // Release the shell, because nothing can ever reach it again.
    //
    // This used to say the session was kept so a reader who closed a pane by
    // accident would find it on reopening. That was not true and could not be:
    // `pane` is a fresh random id per view instance, so a reopened pane asks
    // for a session that has never existed while the old one waits to be
    // evicted by the LRU. Four orphans accumulated across one afternoon of
    // probe runs, each an idle PowerShell.
    //
    // So either the id had to survive a close, or the shell had to not. Keeping
    // it would mean persisting the id in the leaf's view state and restoring a
    // process the reader cannot see from the outside; releasing it is honest
    // about what closing a pane means, and matches what `cd` in a closed window
    // does everywhere else.
    void this.sidecar.restartShell(this.pane);
  }

  /**
   * Populate the interpreter picker from the MACHINE, not from a list here.
   *
   * `P-N2` is a switch between interpreters, and which exist is a property of
   * the machine. A hardcoded list is wrong on every machine but the author's,
   * and wrong silently -- it offers a shell that is not installed and fails at
   * the first command.
   */
  private async discover() {
    const found = await this.sidecar.interpreters() as Interpreters | null;
    this.picker.empty();
    const shells = found?.shells ?? [];
    if (!shells.length) {
      this.picker.createEl("option", { text: "no shell found", value: "" });
      this.picker.disabled = true;
      return;
    }
    for (const s of shells) {
      this.picker.createEl("option", { text: s.name, value: s.exe });
    }
    this.shell = shells[0].exe;
    this.picker.onchange = () => {
      this.shell = this.picker.value;
      // Switching interpreter is a NEW session, and saying so beats letting a
      // reader wonder why their `cd` is gone.
      this.write(`\n— switched to ${this.picker.selectedOptions[0]?.text}; ` +
                 `this is a fresh session —\n`);
    };
  }

  private onKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !this.busy) {
      const command = this.input.value.trim();
      if (!command) return;
      this.history.push(command);
      this.cursor = this.history.length;
      this.input.value = "";
      void this.run(command);
      return;
    }
    // Up and down walk the history, which is the one terminal affordance whose
    // absence is felt immediately.
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      if (!this.history.length) return;
      e.preventDefault();
      this.cursor += e.key === "ArrowUp" ? -1 : 1;
      this.cursor = Math.max(0, Math.min(this.history.length, this.cursor));
      this.input.value = this.history[this.cursor] ?? "";
    }
  }

  private async run(command: string) {
    this.busy = true;
    this.write(`\n> ${command}\n`);
    let reply: ShellReply | null = null;
    try {
      reply = await this.sidecar.runCommand(this.pane, command, this.shell);
    } finally {
      this.busy = false;
    }
    if (!reply) {
      this.write("(no sidecar — cannot run commands)\n");
      return;
    }
    if (reply.refused) {
      // A refusal is not a failure of the shell, and the session still holds
      // whatever was set up in it. Said in those words so the reader does not
      // go looking for a broken terminal.
      this.write(`${reply.error}\n(the session is untouched)\n`);
      return;
    }
    if (reply.error) {
      this.write(`${reply.error}\n`);
      return;
    }
    if (reply.shell) this.write(`(${reply.shell})\n`);
    if (reply.output) this.write(reply.output + "\n");
  }

  private async restart() {
    await this.sidecar.restartShell(this.pane);
    this.write("\n— shell restarted; the session is fresh —\n");
  }

  private write(text: string) {
    // Follow the tail ONLY when already at it, which is what every terminal
    // does and why. A reader scrolled up is reading something; yanking them to
    // the bottom because a build printed another line takes the thing they
    // were reading away mid-sentence. Measured BEFORE appending, because
    // appending is what makes it no longer true.
    const atTail = this.log.scrollHeight - this.log.scrollTop
                   - this.log.clientHeight < 4;
    this.log.appendText(text);
    if (atTail) this.log.scrollTop = this.log.scrollHeight;
  }
}
