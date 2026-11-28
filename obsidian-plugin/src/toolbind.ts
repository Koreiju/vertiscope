/**
 * `+ tool` (Item 201: "instantiate the 'tool' cell, which effectively exposes
 * all actions that can be taken on a given cell's interactive components"):
 * the ```tool cell a note gets is bound to that note's OWN interactive cell --
 * its first ```browser cell's page, with `chunks: true` so the call opens onto
 * the page's chunks and controls. With no browser cell in the note, the open
 * browser pane's page; with neither, the search toolspace. Pure, so it is
 * tested without Obsidian.
 */
const F = "`".repeat(3);

/** The url on the first line inside the note's first ```browser fence, or "". */
export function browserCellUrl(noteText: string): string {
  const lines = noteText.split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (/^```browser\b/.test(lines[i].trim())) {
      for (let j = i + 1; j < lines.length && !lines[j].trim().startsWith(F); j++) {
        const u = lines[j].trim();
        if (/^https?:\/\//.test(u)) return u;
        if (u) break;
      }
    }
  }
  return "";
}

/** The ```tool cell text `+ tool` appends: bound to the note's browser cell, else the pane's page, else search. */
export function toolCellFor(noteText: string, paneUrl = ""): string {
  const url = browserCellUrl(noteText) || (/^https?:\/\//.test(paneUrl) ? paneUrl : "");
  const call = url
    ? { browser: { url, search: "", click: "", next_chunk: false, prev_chunk: false, back: false, forward: false, chunks: true } }
    : { search: { search: "", back: false, forward: false, chunks: false } };
  return F + "tool\n" + JSON.stringify(call) + "\n" + F + "\n";
}
