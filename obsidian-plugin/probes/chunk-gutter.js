/**
 * Step 7: does the gutter show where the chunker actually cut?
 *
 *   node cdp.mjs --file probes/chunk-gutter.js
 *
 * `P-N8`, and `NOTEBOOK_PANEL_DESIGN` §5 is explicit that it is not decoration:
 * it is the only account a reader has of why retrieval returned half a section.
 *
 * Asserted, with the non-vacuity arms marked:
 *
 *   1. a gutter appears, with marks
 *   2. the marks agree with the SIDECAR's own answer for the same text -- the
 *      whole claim is that the editor shows what the chunker did, so the two
 *      have to be compared rather than each checked for plausibility
 *   3. a note that splits shows MORE THAN ONE chunk -- without this arm, a
 *      gutter that drew one span over the whole document passes arm 1 and looks
 *      right on any short note
 *   4. only the first line of a span carries a count -- the extent is the thing
 *      being communicated, and repeating the number down it says one true thing
 *      forty times
 *   5. the marks MOVE when the text changes, rather than being drawn once
 *
 * **The comparison is VIEWPORT-AWARE, and that cost a wrong failure.** A CM6
 * gutter renders markers only for the lines currently laid out, so counting DOM
 * elements counts what is on screen and not what the editor knows. Measured: 6
 * starts visible of 9 chunks, with the viewport covering 4,515 of the document's
 * 7,715 characters -- and scrolling to the end changed the count to 5. So the
 * sidecar's chunks are filtered to the visible line range before being compared,
 * which asserts the real claim rather than an artifact of where the note happened
 * to be scrolled.
 *
 * Needs the sidecar; `/chunk_preview` is ungated, so no `--kernel` required.
 */
(async () => {
  const PATH = "__probe_gutter.md";
  const out = { ok: true, checks: [], failures: [] };
  const check = (name, pass, detail) => {
    out.checks.push({ name, pass, detail });
    if (!pass) { out.ok = false; out.failures.push(`${name}: ${detail}`); }
  };

  const plugin = app.plugins.plugins["vertiscope-bridge"];
  if (!plugin) return JSON.stringify({ ok: false, error: "plugin not loaded" });
  if (!(await plugin.sidecar.health())) {
    return JSON.stringify({ ok: false, error: "no sidecar" });
  }

  // Long enough to exceed a 256-token window several times over, so the
  // boundaries are real rather than a single span covering everything.
  const para = (n) => `Paragraph ${n}. ` + ("flux pinning in a type II " +
    "superconductor carries current without resistance below its critical " +
    "temperature, and the vortex lattice is what holds it there. ").repeat(4);
  const lines = ["# Gutter probe", ""];
  for (let s = 1; s <= 4; s++) {
    lines.push(`## Section ${s}`, "");
    for (let p = 1; p <= 3; p++) lines.push(para(`${s}.${p}`), "");
  }
  const NOTE = lines.join("\n");

  let file = app.vault.getAbstractFileByPath(PATH);
  if (file) await app.vault.modify(file, NOTE);
  else file = await app.vault.create(PATH, NOTE);

  const leaf = app.workspace.getLeaf("tab");
  const read = () => {
    const el = leaf.view.containerEl;
    const cm = leaf.view.editor.cm;
    // The line range CM has actually laid out. Everything below is compared
    // against this, not against the whole document.
    const doc = cm.state.doc;
    const visible = {
      first: doc.lineAt(cm.viewport.from).number - 1,   // 0-based, as the sidecar counts
      last: doc.lineAt(cm.viewport.to).number - 1,
    };
    return {
      gutter: !!el.querySelector(".vertiscope-chunk-gutter"),
      marks: [...el.querySelectorAll(".vertiscope-chunk-mark")],
      starts: [...el.querySelectorAll(".vertiscope-chunk-start")],
      visible,
    };
  };
  /** The chunks whose START line is on screen -- the ones that can have a mark. */
  const visibleChunks = (chunks, v) =>
    (chunks || []).filter((c) => c.start_line >= v.first && c.start_line <= v.last);

  try {
    await leaf.openFile(file);
    await leaf.setViewState({ type: "markdown",
                              state: { file: PATH, mode: "source", source: false } });
    await new Promise((r) => setTimeout(r, 3000));

    let dom = read();
    check("a gutter appears with marks", dom.gutter && dom.marks.length > 0,
          `gutter=${dom.gutter} marks=${dom.marks.length}`);

    // 2. the editor against the sidecar's own answer for the same text.
    const preview = await plugin.sidecar.chunkPreview(NOTE, PATH);
    const fromSidecar = (preview?.chunks || []).length;
    check("the sidecar splits this note into several chunks",
          fromSidecar > 1, `${fromSidecar} chunks`);

    // 3. NON-VACUITY: a single span over the whole document would satisfy
    //    "a gutter appears". The START marks are the boundaries, compared
    //    against the chunks whose start is actually on screen.
    const onScreen = visibleChunks(preview?.chunks, dom.visible);
    check("the gutter shows one start per VISIBLE chunk",
          dom.starts.length === onScreen.length,
          JSON.stringify({ starts: dom.starts.length, visible_chunks: onScreen.length,
                           lines: dom.visible, total_chunks: fromSidecar }));

    // 4. the counts on the starts are those chunks' counts.
    const gutterCounts = dom.starts.map((s) => Number(s.textContent))
                                   .filter((n) => !Number.isNaN(n)).sort((a, b) => a - b);
    const sidecarCounts = onScreen.map((c) => c.tokens).sort((a, b) => a - b);
    check("the token counts match the sidecar's",
          JSON.stringify(gutterCounts) === JSON.stringify(sidecarCounts),
          JSON.stringify({ gutter: gutterCounts, sidecar: sidecarCounts }));

    // Only the first line of a span carries a number; the rest carry the bar.
    const numbered = dom.marks.filter((m) => m.textContent.trim()).length;
    check("only the first line of each chunk carries a count",
          numbered === dom.starts.length,
          `numbered=${numbered} starts=${dom.starts.length}`);

    // 5. NON-VACUITY: drawn once would pass everything above.
    //
    // Edited through the EDITOR, not through `vault.modify`. The refresh hangs
    // off `editor-change`, which is a reader typing; a write straight to the
    // vault does not raise it, so the first version of this check edited the
    // file, saw the marks unchanged, and reported a failure against code that
    // was behaving correctly for the path it is wired to.
    //
    // Inserted at the TOP so the new boundary lands inside the viewport -- an
    // append below the fold would be invisible for the same reason arm 3 had to
    // become viewport-aware.
    const beforeCounts = dom.starts.map((s) => s.textContent).join(",");
    leaf.view.editor.replaceRange("## Inserted\n\n" + para("0.1") + "\n\n",
                                  { line: 1, ch: 0 });
    await new Promise((r) => setTimeout(r, 3500));
    dom = read();
    const afterCounts = dom.starts.map((s) => s.textContent).join(",");
    check("the marks follow the text when it changes",
          afterCounts !== beforeCounts,
          JSON.stringify({ before: beforeCounts, after: afterCounts }));

    out.detail = {
      sidecar_chunks: fromSidecar,
      visible_lines: dom.visible,
      gutter_starts_after_edit: dom.starts.length,
    };
  } finally {
    leaf.detach();
    const made = app.vault.getAbstractFileByPath(PATH);
    if (made) await app.fileManager.trashFile(made);
  }

  return JSON.stringify(out, null, 1);
})()
