/**
 * Step 4: does a cell's output land in the note, and survive?
 *
 *   node cdp.mjs --file probes/cell-outputs.js
 *
 * `NOTEBOOK_PANEL_DESIGN` §6 step 4: *output markers written, read, re-rendered
 * — output survives a restart and renders in reading view.* §1 chose
 * outputs-in-markdown over an `.ipynb` sidecar, so this is the step that says
 * whether that choice was implementable.
 *
 * Asserted, with the non-vacuity arms marked:
 *
 *   1. running a cell writes an `nb-output` block after its closing fence
 *   2. the block carries the SHA-256 of the cell's exact source
 *   3. RE-running REPLACES it rather than appending -- without this arm a note
 *      grows one output per click and the first assertion still passes
 *   4. the markers are invisible in reading view while the output renders
 *   5. the output survives the file being closed and re-read from disk
 *   6. editing the cell makes the stored hash STALE -- the property the digest
 *      exists for, and the one a content-blind hash would fail
 *   7. a failing cell stores `status=error` with its traceback
 *
 * Needs the sidecar started with `--kernel`.
 */
(async () => {
  const PATH = "__probe_outputs.md";
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

  const CODE = "print('forty-two')\n6 * 7";
  const NOTE = ["# Outputs probe", "", "```python", CODE, "```", ""].join("\n");

  let file = app.vault.getAbstractFileByPath(PATH);
  if (file) await app.vault.modify(file, NOTE);
  else file = await app.vault.create(PATH, NOTE);

  const leaf = app.workspace.getLeaf("tab");
  const countBlocks = (t) => (t.match(/<!--\s*nb-output\s/g) || []).length;

  try {
    await leaf.openFile(file);
    await leaf.setViewState({ type: "markdown",
                              state: { file: PATH, mode: "preview" } });
    await new Promise((r) => setTimeout(r, 900));

    const press = async () => {
      const btn = leaf.view.containerEl.querySelector(
        "pre.vertiscope-has-run > button.vertiscope-run-fence");
      if (!btn) return false;
      btn.click();
      await new Promise((r) => setTimeout(r, 1800));
      return true;
    };

    check("the cell drew a button", await press(), "no button found");

    let text = await app.vault.read(file);
    // 1. written, and in the right place: after the fence, not before it.
    check("an output block was written after the fence",
          /```\n<!--\s*nb-output /.test(text), JSON.stringify(text.slice(0, 260)));
    check("the output body is in the note",
          /forty-two/.test(text) && /\b42\b/.test(text),
          JSON.stringify(text));

    // 2. the digest is of the cell's EXACT source.
    const expect = await plugin.app.plugins.plugins["vertiscope-bridge"] &&
      await (async () => {
        const bytes = new TextEncoder().encode(CODE);
        const d = await crypto.subtle.digest("SHA-256", bytes);
        return Array.from(new Uint8Array(d))
          .map((b) => b.toString(16).padStart(2, "0")).join("");
      })();
    const stored = (text.match(/nb-output\s+hash=([0-9a-f]+)/) || [])[1];
    check("the stored hash is the sha256 of the cell's exact source",
          stored === expect, `stored ${stored} expected ${expect}`);
    check("the block records status and an execution count",
          /status=ok/.test(text) && /count=\d+/.test(text),
          JSON.stringify((text.match(/<!--\s*nb-output[^>]*-->/) || [])[0]));

    // 3. NON-VACUITY: re-running must REPLACE. Without this a note grows an
    //    output per click and every assertion above still holds.
    await press();
    text = await app.vault.read(file);
    check("re-running REPLACES the output rather than appending",
          countBlocks(text) === 1, `${countBlocks(text)} blocks`);

    // 4. invisible markers, visible output.
    await leaf.setViewState({ type: "markdown",
                              state: { file: PATH, mode: "preview" } });
    await new Promise((r) => setTimeout(r, 900));
    const shown = (leaf.view.containerEl.querySelector(
      ".markdown-preview-section") || leaf.view.containerEl).innerText;
    check("the markers are invisible in reading view",
          !/nb-output/.test(shown), JSON.stringify(shown.slice(0, 200)));
    check("the output renders in reading view",
          /forty-two/.test(shown), JSON.stringify(shown.slice(0, 200)));

    // 5. survives being dropped from memory and re-read from disk.
    leaf.detach();
    await new Promise((r) => setTimeout(r, 300));
    const reread = await app.vault.read(
      app.vault.getAbstractFileByPath(PATH));
    check("the output survives a close and re-read",
          /forty-two/.test(reread) && countBlocks(reread) === 1,
          `${countBlocks(reread)} blocks`);

    // 6. NON-VACUITY for the digest: editing the cell makes it stale.
    await app.vault.process(app.vault.getAbstractFileByPath(PATH),
      (t) => t.replace("6 * 7", "6 * 8"));
    const edited = await app.vault.read(app.vault.getAbstractFileByPath(PATH));
    const newHash = await (async () => {
      const bytes = new TextEncoder().encode("print('forty-two')\n6 * 8");
      const d = await crypto.subtle.digest("SHA-256", bytes);
      return Array.from(new Uint8Array(d))
        .map((b) => b.toString(16).padStart(2, "0")).join("");
    })();
    const stillStored = (edited.match(/nb-output\s+hash=([0-9a-f]+)/) || [])[1];
    check("editing the cell makes the stored hash stale",
          stillStored === stored && stillStored !== newHash,
          `stored ${stillStored} now-expected ${newHash}`);

    // 7. a failure is stored as a failure.
    await app.vault.process(app.vault.getAbstractFileByPath(PATH),
      () => ["# err", "", "```python", "1 / 0", "```", ""].join("\n"));
    const leaf2 = app.workspace.getLeaf("tab");
    await leaf2.openFile(app.vault.getAbstractFileByPath(PATH));
    await leaf2.setViewState({ type: "markdown",
                               state: { file: PATH, mode: "preview" } });
    await new Promise((r) => setTimeout(r, 900));
    leaf2.view.containerEl.querySelector(
      "pre.vertiscope-has-run > button.vertiscope-run-fence")?.click();
    await new Promise((r) => setTimeout(r, 1800));
    const failed = await app.vault.read(app.vault.getAbstractFileByPath(PATH));
    check("a failing cell stores status=error with its traceback",
          /status=error/.test(failed) && /ZeroDivisionError/.test(failed),
          JSON.stringify(failed.slice(0, 300)));
    leaf2.detach();

    out.final = failed;
  } finally {
    const made = app.vault.getAbstractFileByPath(PATH);
    if (made) await app.fileManager.trashFile(made);
  }

  return JSON.stringify(out, null, 1);
})()
