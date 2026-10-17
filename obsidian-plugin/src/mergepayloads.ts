/**
 * Consecutive drains of one page as ONE capture (2026-09-28: "I'm also
 * surprised that the database ingests leave out so many diffed chunks for
 * *so long*"). Captures ran one per drain, one at a time -- 0.9 s p50 on a
 * small store, 5-6 s on the reader's -- while a scroll drains several times a
 * second, so the queue grew for as long as the reader scrolled and a diff
 * waited behind every drain before it. A sensor payload is incremental, so
 * drains merge in order: the dictionary, shapes and moves concatenated (the
 * last `stats.dictSize` is the running total, which is what the sidecar's
 * restart check compares); each chunk at its LATEST emission; a chunk emitted
 * and then removed dropped; the host's own fields (boxes, pictures) left out.
 */
export function mergePayloads(ps: any[]): any {
  if (ps.length === 1) return ps[0];
  const last = ps[ps.length - 1];
  const out: any = { ...last, dict: [], shapes: [], moves: [], removed: [], chunks: [] };
  // Replayed IN DRAIN ORDER: within one drain removals precede additions
  // (the sensor reports a re-rendered node's old id gone and its content
  // present), and across drains the LAST event for an id decides. Removals
  // were applied after everything, so a chunk removed in one drain and
  // re-added in a later one was dropped from the merged capture -- a
  // stream lost under constant in-place mutation (2026-10-17, archive.org;
  // PLUGIN_GOAL 145: "persist chunk streams no matter how fast").
  const byId = new Map<string, any>();
  const gone = new Map<string, any>();
  for (const p of ps) {
    for (const d of p.dict || []) out.dict.push(d);
    for (const x of p.shapes || []) out.shapes.push(x);
    for (const m of p.moves || []) out.moves.push(m);
    for (const r of p.removed || []) { byId.delete(String(r)); gone.set(String(r), r); }
    for (const c of p.chunks || []) { gone.delete(String(c.id)); byId.delete(String(c.id)); byId.set(String(c.id), c); }
  }
  out.removed = [...gone.values()];
  out.chunks = [...byId.values()];
  delete out.boxes; delete out.pictures; delete out.inpage;
  return out;
}

/** Does `later` remove any chunk `earlier` still carries? Then merging the
 *  two would cancel that content before the store ever saw it (G-216). */
export function removesCarried(later: any, earlier: any): boolean {
  const gone = (later && later.removed) || [];
  if (!gone.length || !earlier) return false;
  const carried = new Set(((earlier.chunks || []) as any[]).map((c) => String(c.id)));
  return gone.some((r: any) => carried.has(String(r)));
}
