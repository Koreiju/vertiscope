/**
 * Does Obsidian still index a wikilink that lives inside a callout?
 *
 *   node cdp.mjs --file probes/graph-edges.js
 *
 * The export folds each note's distilled prose into a collapsed
 * `> [!quote]- distilled markdown` callout, so the note shows the panel once
 * instead of showing the same chunk twice. A callout is a blockquote and
 * Obsidian indexes links in blockquotes, so the vault edges should be
 * untouched -- but this is the one thing that change could have broken, and
 * it would break SILENTLY: a note with no links is a perfectly ordinary note,
 * so the graph would just go empty with nothing to see.
 *
 * Compare `resolvedEdgesFromPages` against the count the exporter printed
 * ("wikilinks N   web links that became vault edges"). They should agree.
 */
(async () => {
  const resolved = app.metadataCache.resolvedLinks || {};
  let edges = 0;
  let fromPages = 0;
  for (const [src, targets] of Object.entries(resolved)) {
    const n = Object.values(targets).reduce((a, b) => a + b, 0);
    edges += n;
    if (src.startsWith("pages/")) fromPages += n;
  }

  // A dangling link points at a note that is not there. The exporter
  // absolutises anything it could not resolve, so any dangling edge here is a
  // resolver defect rather than an unscanned page.
  const unresolved = Object.entries(app.metadataCache.unresolvedLinks || {})
    .filter(([src]) => src.startsWith("pages/"))
    .reduce((a, [, t]) => a + Object.keys(t).length, 0);

  // One note read back, so the link can be seen to be inside the quote
  // rather than merely counted.
  const sample = Object.entries(resolved)
    .find(([s, t]) => s.startsWith("pages/") && Object.keys(t).length);
  let context = null;
  if (sample) {
    const text = await app.vault.adapter.read(sample[0]);
    const line = text.split("\n").find((l) => l.includes("[["));
    context = {
      note: sample[0],
      line: (line || "").slice(0, 120),
      insideTheCallout: (line || "").trimStart().startsWith(">"),
    };
  }

  return {
    notes: app.vault.getMarkdownFiles()
      .filter((f) => f.path.startsWith("pages/")).length,
    resolvedEdgesTotal: edges,
    resolvedEdgesFromPages: fromPages,
    danglingFromPages: unresolved,
    sample: context,
  };
})()
