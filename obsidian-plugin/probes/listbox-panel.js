/**
 * Does the reported note render the way the fix claims?
 *
 *   node cdp.mjs --file probes/listbox-panel.js
 *
 * Two things were reported on `Gloucestershire Health and Care NHS Foundation
 * T-aaf4e4`: the chunk is enormous, and there is no way to tell where its
 * content sits on the page. Both are questions about what Obsidian DREW, not
 * about what is in the file -- a note can hold a wikilink Obsidian never
 * parses, and a distilled control can be in the payload and not in the DOM.
 *
 * Three things make a working panel look dead from here and each cost a round
 * of confusion once:
 *
 *  - the panel opens on MARKDOWN. The distilled HTML is behind the segmented
 *    switch, so the shadow root does not exist until `shadow DOM` is pressed;
 *  - the shadow root is on `.vertiscope-html-host`, INSIDE `.vertiscope-surface`, not
 *    on the surface itself;
 *  - Obsidian renders a section lazily, so the fence has to be scrolled into
 *    view before the code-block processor runs at all.
 */
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const out = {};

  const NOTE = process.env_NOTE ||
    "pages/Gloucestershire Health and Care NHS Foundation T-aaf4e4.md";
  const file = app.vault.getAbstractFileByPath(NOTE);
  if (!file) return { error: "note not found", note: NOTE };

  const leaf = app.workspace.getLeaf(false);
  await leaf.openFile(file, { state: { mode: "preview" } });

  for (let i = 0; i < 30; i++) {
    await sleep(600);
    if (document.querySelector(".vertiscope-surface")) break;
    document.querySelector(".markdown-preview-view, .cm-scroller")
      ?.scrollBy(0, 600);
  }
  const surface = document.querySelector(".vertiscope-surface");
  out.surface_built = !!surface;
  if (!surface) return out;

  // Press `shadow DOM`, which is what builds the distilled form at all.
  const seg = [...surface.querySelectorAll(".vertiscope-seg")]
    .find((b) => (b.textContent || "").trim() === "shadow DOM");
  out.switch_found = !!seg;
  if (seg && seg.getAttribute("aria-pressed") !== "true") seg.click();

  let root = null;
  for (let i = 0; i < 30; i++) {
    await sleep(400);
    root = surface.querySelector(".vertiscope-html-host")?.shadowRoot;
    if (root) break;
  }
  out.shadow_built = !!root;
  if (root) {
    out.selects = root.querySelectorAll("select.dv-select").length;
    out.options = root.querySelectorAll("option.dv-opt").length;
    out.fake_text_inputs = root.querySelectorAll('input[type="text"]').length;
    out.addressed = root.querySelectorAll("[data-vertiscope-address]").length;
    out.text_chars = (root.textContent || "").trim().length;
  }

  // The continuation links, as Obsidian PARSED them -- not as the file spells
  // them. A wikilink inside a callout is the case that has silently failed
  // before.
  out.resolved_out_links = Object.keys(app.metadataCache.resolvedLinks[NOTE] || {});
  const cache = app.metadataCache.getFileCache(file) || {};
  out.frontmatter_of = (cache.frontmatter || {}).of;
  out.frontmatter_index = (cache.frontmatter || {}).index;
  out.frontmatter_tokens = (cache.frontmatter || {}).tokens;

  return out;
})();
