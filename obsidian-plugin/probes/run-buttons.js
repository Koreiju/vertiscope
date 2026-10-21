/**
 * Step 2: does a run button appear on every runnable fence, in BOTH views?
 *
 *   node cdp.mjs --file probes/run-buttons.js
 *
 * `NOTEBOOK_PANEL_DESIGN` §6 step 2 is two-sided on purpose — reading view AND
 * live preview — because they are separate renderers in Obsidian and satisfying
 * one says nothing about the other. Reading view builds DOM a post-processor
 * appends to; live preview is CodeMirror and needs a widget decoration.
 *
 * Four things are asserted, and two of them are the non-vacuity arms:
 *
 *   1. both paths draw a button per runnable fence
 *   2. a NON-runnable fence gets none -- without this, "decorate everything"
 *      passes arm 1 and every ```json block grows a control that cannot run
 *   3. clicking fires the host with the right lang, line and code
 *   4. the two paths agree BYTE FOR BYTE on the cell source -- step 3 keys a
 *      stored output on a digest of it, so two spellings mean switching view
 *      modes silently invalidates the output and re-runs the cell. Measured
 *      before the fix: reading view returned a trailing newline, live preview
 *      did not.
 *
 * Writes its own probe note and deletes it, so the vault is as it was.
 */
(async () => {
  const PATH = "__probe_run_buttons.md";
  const NOTE = [
    "# Run button probe",
    "",
    "Prose before the fence.",
    "",
    "```python",
    "x = 1",
    "print(x)",
    "```",
    "",
    "```json",
    '{"not": "runnable"}',
    "```",
    "",
    "```bash",
    "echo hello",
    "```",
    "",
  ].join("\n");

  const out = { ok: true, checks: [], failures: [] };
  const check = (name, pass, detail) => {
    out.checks.push({ name, pass, detail });
    if (!pass) { out.ok = false; out.failures.push(`${name}: ${detail}`); }
  };

  const plugin = app.plugins.plugins["vertiscope-bridge"];
  if (!plugin) return JSON.stringify({ ok: false, error: "plugin not loaded" });

  // Capture run requests instead of firing a Notice per click.
  const calls = [];
  const origRun = plugin.onRunFence.bind(plugin);
  plugin.onRunFence = (req) => calls.push(req);

  let file = app.vault.getAbstractFileByPath(PATH);
  if (file) await app.vault.modify(file, NOTE);
  else file = await app.vault.create(PATH, NOTE);

  const leaf = app.workspace.getLeaf("tab");
  try {
    await leaf.openFile(file);

    // Both renderers have to be woken: a leaf renders the mode it is in, and
    // the other path's DOM does not exist until that mode has been entered.
    const counts = {};
    for (const mode of ["preview", "source"]) {
      await leaf.setViewState({
        type: "markdown",
        state: { file: PATH, mode, source: false },
      });
      await new Promise((r) => setTimeout(r, 900));
      const el = leaf.view.containerEl;
      counts[mode] = {
        reading: el.querySelectorAll(
          "pre.vertiscope-has-run > button.vertiscope-run-fence").length,
        live: el.querySelectorAll(
          ".vertiscope-run-fence-wrap > button.vertiscope-run-fence").length,
      };
    }

    // 1. one button per runnable fence, in each path. The note has three
    //    fences and two are runnable.
    check("reading view draws one button per runnable fence",
          counts.preview.reading === 2,
          `expected 2, got ${counts.preview.reading}`);
    check("live preview draws one button per runnable fence",
          counts.source.live === 2,
          `expected 2, got ${counts.source.live}`);

    // 2. NON-VACUITY: the ```json fence must have none. A `pre` with a button
    //    would mean the allow-list is not being consulted.
    const el = leaf.view.containerEl;
    const jsonPre = [...el.querySelectorAll("pre")].find((p) =>
      (p.querySelector("code")?.className || "").includes("language-json"));
    check("a non-runnable fence gets NO button",
          !!jsonPre && jsonPre.querySelectorAll("button.vertiscope-run-fence").length === 0,
          jsonPre ? "the json block has a run button" : "no json block rendered");

    // 3. clicking fires the host, from each path.
    calls.length = 0;
    el.querySelector("pre.vertiscope-has-run > button.vertiscope-run-fence")?.click();
    el.querySelector(".vertiscope-run-fence-wrap > button.vertiscope-run-fence")?.click();
    await new Promise((r) => setTimeout(r, 200));

    check("both paths fire the host on click", calls.length === 2,
          `expected 2 calls, got ${calls.length}`);
    check("the payload names the language", calls.every((c) => c.lang === "python"),
          JSON.stringify(calls.map((c) => c.lang)));
    check("the payload names the note", calls.every((c) => c.path === PATH),
          JSON.stringify(calls.map((c) => c.path)));
    // The fence opens on the 5th line, which is index 4.
    check("both paths agree on the cell's line",
          calls.length === 2 && calls[0].line === 4 && calls[1].line === 4,
          JSON.stringify(calls.map((c) => c.line)));

    // 4. NON-VACUITY for `cellSource`: identical, not merely both present.
    check("both paths agree on the cell source BYTE FOR BYTE",
          calls.length === 2 && calls[0].code === calls[1].code,
          JSON.stringify(calls.map((c) => c.code)));
    check("the cell source is the code and nothing else",
          calls.length === 2 && calls[0].code === "x = 1\nprint(x)",
          JSON.stringify(calls[0]?.code));

    out.counts = counts;
    out.calls = calls.map((c) => ({ lang: c.lang, line: c.line, code: c.code }));
  } finally {
    plugin.onRunFence = origRun;
    leaf.detach();
    // `app.fileManager.trashFile` respects the vault's own trash setting, where
    // `vault.delete` is unconditional. A probe must not be the thing that
    // decides whether a file is recoverable.
    const made = app.vault.getAbstractFileByPath(PATH);
    if (made) await app.fileManager.trashFile(made);
  }

  return JSON.stringify(out, null, 1);
})()
