/**
 * Turning a passage's web links into vault edges.
 *
 * The `/` gesture inserts a chunk's markdown into a note, and that markdown
 * carries `[words](https://target)` for every link the distiller resolved.
 * Left alone those stay web links: the passage reads correctly and
 * contributes nothing to the graph, which is the same shape as the export's
 * first version and just as invisible.
 *
 * Two things have to line up, and neither is guessable from the passage.
 *
 * **Which chunk a link to a page lands on.** The store contributes ONE edge
 * per link, to the target page's first chunk, and the export follows that so
 * the two graphs can be compared. The sidecar's `/links` reports it rather
 * than the plugin reimplementing the rule -- a second implementation would
 * drift, and the symptom would be two edges for one link.
 *
 * **Which note holds that chunk.** Only the vault knows: the export may have
 * run against a different folder, or not at all, and notes get renamed. So
 * the map is built from the notes themselves, keyed on the `cid` the export
 * writes into frontmatter, which is the identity everything else is keyed on
 * too.
 */

import { App, TFile } from "obsidian";

import { Sidecar } from "./sidecar";

interface LinkTarget {
  url: string;
  canonical: string;
  cid: string;
}

/** `[words](target)` as the distiller draws it. */
const LINK = /\[([^\]]*)\]\(([^)\s]+)\)/g;

/**
 * A url in the one spelling both sides can agree on.
 *
 * A page is stored under the url it was scanned with, and that is not always
 * its canonical form -- matching on the stored spelling alone once dropped
 * three quarters of the store's own resolvable edges. The sidecar sends both,
 * and this normalises the passage's targets the same way: lower-case host, no
 * fragment, and a trailing slash on a bare host so `https://a.test` and
 * `https://a.test/` are one key.
 */
export function canonical(target: string, base?: string): string {
  try {
    const u = new URL(target, base);
    u.hash = "";
    u.host = u.host.toLowerCase();
    if (!u.pathname) u.pathname = "/";
    return u.toString();
  } catch {
    return "";
  }
}

export class VaultLinks {
  /** canonical url -> note basename. Rebuilt on demand, not cached stale. */
  private map = new Map<string, string>();

  constructor(private app: App, private sidecar: Sidecar) {}

  /**
   * Learn which exported note each page's links should point at.
   *
   * Returns how many pages resolved, so a caller can say "no notes exported
   * yet" rather than silently inserting web links and looking like it worked.
   */
  async refresh(): Promise<number> {
    this.map.clear();
    const answer = (await this.sidecar.links()) as
      { targets: LinkTarget[] } | null;
    if (!answer) return 0;

    // cid -> note, from the vault. The export writes `cid` into frontmatter
    // precisely so this lookup does not have to guess from a file name.
    const noteOf = new Map<string, string>();
    for (const file of this.app.vault.getMarkdownFiles()) {
      const cid = this.app.metadataCache.getFileCache(file)
        ?.frontmatter?.cid;
      if (typeof cid === "string" && cid) noteOf.set(cid, file.basename);
    }

    for (const target of answer.targets) {
      const note = noteOf.get(target.cid);
      if (!note) continue;             // that page was never exported
      for (const spelling of [target.canonical, target.url]) {
        const key = canonical(spelling);
        if (key) this.map.set(key, note);
      }
    }
    return this.map.size;
  }

  /**
   * Rewrite a passage's links into wikilinks where the target is in the vault.
   *
   * `[[note|words]]` rather than `[[note]]`: the sentence a reader sees is
   * unchanged and the edge becomes real. A target that was never exported is
   * left exactly as it was -- a web link that works is better than a wikilink
   * to a note that does not exist, which Obsidian draws as a dangling node
   * and puts in the graph as a dot nobody can open.
   */
  /** The exported note a page's url resolves to, by basename, if any. */
  noteFor(url: string): string | undefined {
    const key = canonical(url);
    return key ? this.map.get(key) : undefined;
  }

  rewrite(markdown: string, base: string): { text: string; edges: number } {
    let edges = 0;
    const text = markdown.replace(LINK, (whole, words: string, target: string) => {
      const note = this.map.get(canonical(target, base));
      if (!note) return whole;
      edges += 1;
      const label = words.trim();
      // Obsidian splits an alias on `|`, so a label containing one would cut
      // the link short. Rare, and silent when it happens.
      return label && !label.includes("|")
        ? `[[${note}|${label}]]`
        : `[[${note}]]`;
    });
    return { text, edges };
  }

  get size(): number {
    return this.map.size;
  }
}
