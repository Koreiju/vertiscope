/**
 * Step 6: does a separate pane give a working prompt, populated from the machine?
 *
 *   node cdp.mjs --file probes/terminal-pane.js
 *
 * `NOTEBOOK_PANEL_DESIGN` §6 step 6: *a cell runs in-panel AND a separate pane
 * gives a pwsh prompt; discovery lists installed kernels.* §4a is what makes
 * "separate pane" a requirement rather than a layout choice -- the in-panel
 * switch selects a kernel run, and shell work lives out here.
 *
 * Asserted, with the non-vacuity arms marked:
 *
 *   1. the pane opens and its picker is filled from DISCOVERY, not a fixed list
 *   2. a command round-trips and shows its output
 *   3. state persists across commands in one pane -- the reason for a
 *      persistent shell rather than one process per command
 *   4. a SECOND pane does not share that state -- without this arm, one global
 *      shell passes every check above
 *   5. a TUI program is refused BY NAME and the session survives it -- a
 *      refusal that killed the session would still "refuse" correctly
 *
 * Needs the sidecar started with `--kernel`, which is the terminal's gate too.
 */
(async () => {
  const out = { ok: true, checks: [], failures: [] };
  const check = (name, pass, detail) => {
    out.checks.push({ name, pass, detail });
    if (!pass) { out.ok = false; out.failures.push(`${name}: ${detail}`); }
  };

  const plugin = app.plugins.plugins["vertiscope-bridge"];
  if (!plugin) return JSON.stringify({ ok: false, error: "plugin not loaded" });
  const health = await plugin.sidecar.health();
  if (!health) return JSON.stringify({ ok: false, error: "no sidecar" });
  if (!health.kernel) {
    return JSON.stringify({ ok: false, error: "sidecar has no kernel",
                            detail: "restart it with --kernel" });
  }

  const windows = navigator.platform.toLowerCase().includes("win");
  const PWD = windows ? "(Get-Location).Path" : "pwd";
  const CD = windows ? "cd C:/Windows" : "cd /tmp";
  const MARK = windows ? "Windows" : "tmp";

  /**
   * Open a pane and wait until it EXISTS, rather than for a fixed moment.
   *
   * The first version slept 1300ms and took the last leaf. When opening was
   * slower than that -- a cold discovery fetch is enough -- both calls returned
   * the SAME leaf, both "panes" were one pane, and the isolation check failed
   * intermittently against code that was correct. An intermittent test is worse
   * than none: it teaches the reader to re-run rather than to look.
   */
  const openPane = async () => {
    const before = app.workspace.getLeavesOfType("vertiscope-terminal-view").length;
    app.commands.executeCommandById("vertiscope-bridge:vertiscope-open-terminal");
    for (let i = 0; i < 40; i++) {
      const leaves = app.workspace.getLeavesOfType("vertiscope-terminal-view");
      // The picker being populated is what says the view finished opening;
      // the leaf exists before `onOpen` has run.
      const last = leaves[leaves.length - 1];
      if (leaves.length > before &&
          last?.view?.containerEl?.querySelector(".vertiscope-terminal-input")) {
        return last;
      }
      await new Promise((r) => setTimeout(r, 100));
    }
    return null;
  };
  const drive = async (leaf, command, wait = 2500) => {
    const el = leaf.view.containerEl;
    const input = el.querySelector(".vertiscope-terminal-input");
    input.value = command;
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await new Promise((r) => setTimeout(r, wait));
    return el.querySelector(".vertiscope-terminal-log").textContent;
  };

  /**
   * The command's ANSWER: the last non-empty line of the transcript.
   *
   * Matching a mark against the whole transcript is what the first version did,
   * and it reported a false failure: the isolation check looked for "Windows"
   * in a tail that contained "started Windows PowerShell", so a correctly
   * isolated second pane read as a shared one. The session's own banner is not
   * the command's answer, and an assertion that cannot tell them apart is
   * measuring the wrong string.
   */
  const answer = (log) => {
    const lines = log.split("\n").map((l) => l.trim()).filter(Boolean);
    return lines[lines.length - 1] || "";
  };

  const first = await openPane();
  const second = await openPane();
  try {
    // Asserted as DISTINCT, not merely present: two handles to one leaf is
    // exactly what made the isolation check flake, and it would flake silently
    // again if this only counted them.
    check("two distinct terminal panes open",
          !!first && !!second && first !== second,
          `${app.workspace.getLeavesOfType("vertiscope-terminal-view").length} panes, ` +
          `same leaf: ${first === second}`);

    // 1. the picker is discovery's answer, and every entry is a real shell.
    const found = await plugin.sidecar.interpreters();
    const options = [...first.view.containerEl.querySelectorAll("select option")]
      .map((o) => o.value).filter(Boolean);
    check("the picker is filled from discovery",
          options.length > 0 &&
          options.every((v) => (found?.shells || []).some((s) => s.exe === v)),
          JSON.stringify({ options, discovered: (found?.shells || []).map(s => s.exe) }));

    // 2. a command round-trips.
    let log = await drive(first, "echo probe-one");
    check("a command round-trips with its output",
          /probe-one/.test(log), JSON.stringify(log.slice(-160)));

    // 3. state persists in this pane.
    await drive(first, CD, 2000);
    log = await drive(first, PWD, 2000);
    const firstCwd = answer(log);
    check("state persists across commands in one pane",
          firstCwd.includes(MARK), JSON.stringify(firstCwd));

    // 4. NON-VACUITY: the other pane must NOT be there. Compared as the two
    //    ANSWERS, which is unambiguous where a mark in a transcript is not.
    const otherCwd = answer(await drive(second, PWD, 2500));
    check("a second pane has its OWN session",
          !!otherCwd && otherCwd !== firstCwd,
          JSON.stringify({ first: firstCwd, second: otherCwd }));

    // 5. NON-VACUITY: refusing must not cost the session.
    const refusedLog = await drive(first, "vim notes.txt", 1500);
    check("a TUI program is refused by name",
          /vim/.test(refusedLog) && /real terminal/.test(refusedLog),
          JSON.stringify(refusedLog.slice(-200)));
    const afterCwd = answer(await drive(first, PWD, 2000));
    check("the session survives the refusal",
          afterCwd === firstCwd,
          JSON.stringify({ before: firstCwd, after: afterCwd }));

    out.transcript = first.view.containerEl
      .querySelector(".vertiscope-terminal-log").textContent;
  } finally {
    for (const leaf of app.workspace.getLeavesOfType("vertiscope-terminal-view")) {
      leaf.detach();
    }
  }

  return JSON.stringify(out, null, 1);
})()
