/**
 * Step 3: does pressing a fence's button actually run the cell?
 *
 *   node cdp.mjs --file probes/kernel-run.js
 *
 * Step 2 drew the button and proved it fires the host. This closes the loop:
 * renderer -> HTTP -> sidecar -> a Python subprocess -> back. And it asserts the
 * property the step is FOR, which is not "code runs" but the isolation boundary
 * from `NOTEBOOK_PANEL_DESIGN` §4 — *variables shared between cells in one note,
 * isolated from other notes*.
 *
 * Needs the sidecar started with `--kernel`. If it was not, the probe says so
 * rather than failing obscurely, because "off" and "broken" are exactly the two
 * things the server is careful to distinguish.
 */
(async () => {
  const PATH = "__probe_kernel_run.md";
  const OTHER = "__probe_kernel_other.md";
  const out = { ok: true, checks: [], failures: [] };
  const check = (name, pass, detail) => {
    out.checks.push({ name, pass, detail });
    if (!pass) { out.ok = false; out.failures.push(`${name}: ${detail}`); }
  };

  const plugin = app.plugins.plugins["vertiscope-bridge"];
  if (!plugin) return JSON.stringify({ ok: false, error: "plugin not loaded" });

  const health = await plugin.sidecar.health();
  if (!health) {
    return JSON.stringify({ ok: false, error: "no sidecar reachable" });
  }
  if (!health.kernel) {
    return JSON.stringify({
      ok: false,
      error: "the sidecar has no kernel",
      detail: "restart it with --kernel; this probe tests execution",
    });
  }
  out.health = { pages: health.pages, kernel: health.kernel };

  // A cell that sets a variable, so a SECOND cell can prove state persisted.
  const NOTE = [
    "# Kernel probe",
    "",
    "```python",
    "probe_value = 6 * 7",
    "print('set', probe_value)",
    "```",
    "",
    "```python",
    "probe_value",
    "```",
    "",
  ].join("\n");

  let file = app.vault.getAbstractFileByPath(PATH);
  if (file) await app.vault.modify(file, NOTE);
  else file = await app.vault.create(PATH, NOTE);

  // What the BUTTON asked for, captured without stopping the real call.
  const asked = [];
  const realRun = plugin.sidecar.runCell.bind(plugin.sidecar);
  plugin.sidecar.runCell = async (note, code, lang) => {
    asked.push({ note, code, lang });
    return realRun(note, code, lang);
  };

  const leaf = app.workspace.getLeaf("tab");
  try {
    await leaf.openFile(file);
    await leaf.setViewState({
      type: "markdown",
      state: { file: PATH, mode: "preview" },
    });
    await new Promise((r) => setTimeout(r, 1000));

    const buttons = [...leaf.view.containerEl.querySelectorAll(
      "pre.vertiscope-has-run > button.vertiscope-run-fence")];
    check("both python fences drew a button", buttons.length === 2,
          `got ${buttons.length}`);

    // Press the first cell, wait for the round trip, then the second.
    buttons[0]?.click();
    await new Promise((r) => setTimeout(r, 1500));
    buttons[1]?.click();
    await new Promise((r) => setTimeout(r, 1500));

    check("the button sent the NOTE as the boundary",
          asked.length === 2 && asked.every((a) => a.note === PATH),
          JSON.stringify(asked.map((a) => a.note)));
    check("the button sent the cell's own code",
          asked.length === 2 && asked[1].code === "probe_value",
          JSON.stringify(asked.map((a) => a.code)));

    // The round trip itself, through the plugin's client.
    const first = await realRun(PATH, "probe_value");
    check("state set by the BUTTON is visible afterwards",
          first && first.ok && first.value === "42",
          JSON.stringify(first));

    // NON-VACUITY: another note must NOT see it. Without this, one shared
    // namespace passes every check above.
    const other = await realRun(OTHER, "'probe_value' in dir()");
    check("another note does NOT see it",
          other && other.ok && other.value === "False",
          JSON.stringify(other));

    // And an error comes back as an error, not as silence.
    const boom = await realRun(PATH, "1/0");
    check("a failing cell reports its exception",
          boom && boom.ok === false && /ZeroDivisionError/.test(boom.error || ""),
          JSON.stringify(boom && boom.error ? boom.error.trim().split("\n").pop() : boom));

    out.asked = asked;
  } finally {
    plugin.sidecar.runCell = realRun;
    leaf.detach();
    for (const path of [PATH]) {
      const made = app.vault.getAbstractFileByPath(path);
      if (made) await app.fileManager.trashFile(made);
    }
  }

  return JSON.stringify(out, null, 1);
})()
