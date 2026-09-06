/**
 * The client for the domvec sidecar.
 *
 * Every method answers `null` rather than throwing when the sidecar is not
 * there. Offline is a supported mode for this plugin, not a failure: the
 * exported notes are complete markdown and a vault has to keep working with
 * no process running and no network. Callers say so on the surface instead of
 * rendering an empty chunk, because an unreachable sidecar and a chunk with
 * nothing in it look identical otherwise, and that is how a dead pipeline
 * goes unnoticed.
 */

import { ChunkPayload, SearchResult } from "./types";

export class Sidecar {
  constructor(private base: () => string) {}

  private url(path: string): string | null {
    const base = this.base().trim().replace(/\/+$/, "");
    return base ? `${base}${path}` : null;
  }

  private async get<T>(path: string): Promise<T | null> {
    const url = this.url(path);
    if (!url) return null;
    // Retried once, and only on a THROWN error.
    //
    // A thrown fetch is a connection that never happened -- refused, reset,
    // the socket gone -- and those are transient here: a vault opens many
    // chunks at once and a burst can outrun the server's listen backlog. One
    // refused connection used to make that surface say "sidecar unreachable"
    // and keep saying it until the note was edited, while every other surface
    // on screen worked. Measured: one refusal in a burst of nine.
    //
    // A RESPONSE that is not ok is not retried. A 404 for a cid the store does
    // not have is an answer, and asking twice makes it no truer.
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const res = await fetch(url);
        if (!res.ok) return null;
        return (await res.json()) as T;
      } catch {
        if (attempt === 0) continue;
        return null;
      }
    }
    return null;
  }

  chunk(cid: string): Promise<ChunkPayload | null> {
    return this.get<ChunkPayload>(`/chunk/${encodeURIComponent(cid)}`);
  }

  search(query: string, limit: number): Promise<SearchResult | null> {
    return this.get<SearchResult>(
      `/search?q=${encodeURIComponent(query)}&k=${limit}`,
    );
  }

  /**
   * Where a link to each stored page should land.
   *
   * The rule lives in `export.py` next to the export that established it, so
   * the gesture and the export write the SAME edge for one link rather than
   * two implementations drifting apart.
   */
  links(): Promise<unknown | null> {
    return this.get("/links");
  }

  /**
   * The fitted 3D placement. Seconds on a first call, cached after.
   *
   * Fitted in Python, where the vectors, numpy and UMAP already are. A
   * projection fitted twice in two languages is two projections.
   */
  layout(dims = 3): Promise<unknown | null> {
    return this.get(`/layout?dims=${dims}`);
  }

  /** Whether the sidecar answers at all. Used only to report status. */
  async alive(): Promise<boolean> {
    return (await this.get<unknown>("/health")) !== null;
  }
}
