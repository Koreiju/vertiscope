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

import { ChunkPayload, ChunkPreview, EnactResult, Health, Interpreters,
         KernelReply, SearchResult, ShellReply } from "./types";

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

  /** Whether the sidecar answers at all, and what it will allow. */
  health(): Promise<Health | null> {
    return this.get<Health>("/health");
  }

  async alive(): Promise<boolean> {
    return (await this.health()) !== null;
  }

  /**
   * Drive the live page. The ONLY write this plugin makes.
   *
   * POST, and deliberately not routed through `get`: that retries once on a
   * thrown error, which is right for reading a chunk and wrong for an action.
   * A press that failed halfway may already have navigated, and pressing
   * again is not the same as pressing once.
   */
  async enact(address: string, action = "press",
              text?: string): Promise<EnactResult | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/enact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address, action, text }),
      });
      return (await res.json()) as EnactResult;
    } catch {
      return null;
    }
  }

  /**
   * Where the chunker would cut this text (`P-N8`).
   *
   * A POST because the body IS the note: newlines, and tens of kilobytes on a
   * long one, neither of which belongs in a query string. Not retried, not
   * because it acts -- it is a pure function of the text -- but because the
   * caller re-asks on the next idle anyway, and a retry would only delay a
   * mark the reader has already outrun by typing.
   */
  async chunkPreview(text: string, path: string,
                     vault = "vault"): Promise<ChunkPreview | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/chunk_preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, path, vault }),
      });
      if (!res.ok) return null;
      return (await res.json()) as ChunkPreview;
    } catch {
      return null;
    }
  }

  /** What this machine can run. A GET, so the retry in `get` is right here:
   *  discovery is idempotent and a burst can outrun the listen backlog. */
  interpreters(): Promise<Interpreters | null> {
    return this.get<Interpreters>("/interpreters");
  }

  /**
   * Run one command in a pane's shell.
   *
   * POST and not retried, for the reason `enact` is not: a command that failed
   * halfway may already have written a file or pushed a branch, and running it
   * again is not the same as running it once.
   */
  async runCommand(pane: string, command: string,
                   shell = ""): Promise<ShellReply | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/shell`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pane, command, shell }),
      });
      return (await res.json()) as ShellReply;
    } catch {
      return null;
    }
  }

  /** Drop a pane's shell. The next command starts a fresh one. */
  async restartShell(pane: string): Promise<boolean> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return false;
    try {
      const res = await fetch(`${base}/shell`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pane, op: "restart" }),
      });
      return !!(await res.json()).restarted;
    } catch {
      return false;
    }
  }

  /**
   * Run one notebook cell in its note's kernel.
   *
   * POST, and for the same reason `enact` is not routed through `get`: that
   * retries once on a thrown error, which is right for reading a chunk and
   * wrong for an ACTION. A cell that failed halfway may already have written a
   * file or mutated state, and running it again is not the same as running it
   * once.
   *
   * A non-ok response is returned rather than swallowed. The server answers 403
   * when the kernel is off and 400 when the request is wrong, and both carry a
   * `detail` the reader needs -- turning either into `null` would make "not
   * enabled" indistinguishable from "no sidecar".
   */
  async runCell(note: string, code: string,
                lang = "python"): Promise<KernelReply | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/kernel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note, code, lang }),
      });
      return (await res.json()) as KernelReply;
    } catch {
      return null;
    }
  }
}
