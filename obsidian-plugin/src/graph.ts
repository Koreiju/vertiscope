/**
 * The 3D view: chunks placed by both vector spaces, in their own pane.
 *
 * A separate scene, not an extension of Obsidian's graph. The core graph has
 * no plugin API -- the one community plugin that extends it patches
 * undocumented internals and warns in its own README that settings can be
 * lost -- and it draws NOTES, one dot per file, which is the wrong unit here:
 * a page is many chunks and the interesting structure is between them. So the
 * native graph keeps doing what it does with the wikilinks the exporter
 * writes, and this shows the other thing.
 *
 * The placement is not computed here. `domvec/obsidian/layout.py` fits it,
 * because the vectors, numpy and UMAP already live in Python and a projection
 * fitted twice in two languages is two projections. This asks for coordinates
 * and draws them.
 */

import { profiler } from "./profile";
import { ItemView, WorkspaceLeaf, requestUrl } from "obsidian";
import ForceGraph3D, { ForceGraph3DInstance } from "3d-force-graph";
// `d3-force-3d` is what `3d-force-graph` runs its simulation on, so this is
// the same module instance the graph already uses -- not a second copy whose
// forces the graph would ignore.
import { forceCenter, forceCollide, forceManyBody } from "d3-force-3d";
import type { ForceNodeDelta } from "./forcetree";
import * as THREE from "three";
import { NodeLook, SceneBatch } from "./scenebatch";
import { flushTiny, octreeVerdict } from "./octreeguard";
import { MotionRecorder } from "./motion";

import { Sidecar } from "./sidecar";
import { ChunkSurface, SurfaceHost } from "./surface";
import { faviconFor, getSnapshot, pictureFor, renderSnapshot } from "./snapshot";
import type { ActRecord, ActResult } from "./panelact";

export const GRAPH_VIEW = "domvec-graph-view";

export interface LayoutNode {
  cid: string;
  /** What this node stands for: "page", "path" (a branch part-way down a
   *  page's trie), or a chunk when absent. Decides what a click does. */
  level?: string;
  /** The xpath this node sits at, for the next unravelling step. */
  path?: string;
  /** The size the renderer should draw it at, when the layout has an
   *  opinion -- a page's is its chunk count, not its character count. */
  val?: number;
  /** How many chunks this node stands for, when stage two merged it with
   *  others (`G-26`). 1 for an ordinary chunk. */
  members?: number;
  url: string;
  title: string;
  rank: number;
  chars: number;
  tokens?: number;
  pos: number[];
  /**
   * Three MORE components of the same projection, as (hue, saturation,
   * value).
   *
   * Not a palette. The fit is six-dimensional: three axes stand the node in
   * space and three colour it, so hue carries a direction of the joint
   * frequency+semantic space the camera has no room for. Two nodes that look
   * alike ARE alike in that direction.
   */
  hsv?: number[];
  /** The chunk's first picture, absolutised, when it showed one. */
  image?: { src: string; alt: string };
}

interface Layout {
  nodes: LayoutNode[];
  edges: { source: string; target: string }[];
  spaces: string[];
  n: number;
  dims?: number;
  /** 6 when the colour came from the fit; 3 when it did not. */
  fitted_dims?: number;
  hsv?: boolean;
  images?: number;
  /** Half the width of the cube the coordinates are delivered in. */
  extent?: number;
  /** Nearest-neighbour distance quantiles over the placed nodes, from the
   *  fit itself. `p50` is the projection's own scale; see the sizing note. */
  spacing?: { p05: number; p25: number; p50: number; n: number };
  /** Which space the fit actually used. `semantic: false` means the workspace
   *  had no embeddings and the frequency FALLBACK drew this picture, which is
   *  not the projection the goal asks for — so the bar has to say so. */
  fitted_on?: { semantic: boolean };
  /** "page" when the fit is the collapsed view (`G-53`). */
  level?: string;
  /** How many chunks stand behind the pages, at page level. */
  chunks?: number;
  note?: string;
  /** Answered by the chunk projector: which fit, and how far its stream is. */
  source?: string;
  epoch?: number;
  seq?: number;
  fitting?: boolean;
  projector?: any;
}

/**
 * The colour the fit gave this node.
 *
 * `hsv` when the projection produced it, which is the whole point of fitting
 * six dimensions: the colour is three more directions of the same space, so
 * it MEASURES something. The host hash below is the fallback for a sidecar
 * that only fitted three, and it is a legend rather than a measurement -- it
 * says which site a node came from, which the node's own label already says.
 */
function colourOf(node: LayoutNode): string {
  if (node.hsv && node.hsv.length === 3) {
    const [h, s, v] = node.hsv;
    return `hsl(${h.toFixed(1)}, ${(s * 100).toFixed(0)}%, ` +
           `${(v * 100).toFixed(0)}%)`;
  }
  return hue(node.url);
}

/**
 * The largest picture worth turning into a billboard, in bytes.
 *
 * A base64 `data:` url is a third larger than the bytes it carries and is
 * held in memory for the life of the pane, so a corpus of full-resolution
 * photographs would be held twice over. Thumbnails and logos -- what a node
 * actually shows at this size -- are far under this.
 */
const MAX_TEXTURE_BYTES = 2 * 1024 * 1024;

/** The type a url implies, when the host did not say. */
function guessType(src: string): string {
  const m = /\.(png|jpe?g|gif|webp|svg)($|\?)/i.exec(src);
  if (!m) return "";
  const ext = m[1].toLowerCase();
  if (ext === "svg") return "image/svg+xml";
  if (ext === "jpg" || ext === "jpeg") return "image/jpeg";
  return `image/${ext}`;
}

/**
 * An SVG as a data url a WebGL texture can actually be made from.
 *
 * `TextureLoader` draws through an `<img>` onto a canvas, and an `<img>`
 * holding an SVG with no width/height has no intrinsic size -- so the draw
 * produces nothing and the texture never appears. Sites overwhelmingly ship
 * their logos that way, sizing them in CSS instead. Measured on this corpus:
 * 43 of the 110 billboards are SVG, which is very nearly the whole of what
 * was still failing after the CORS problem was solved.
 *
 * So a size is given when the file does not carry one, taken from `viewBox`
 * where there is one so the aspect ratio survives.
 *
 * Encoded with `encodeURIComponent` rather than base64: the bytes are text,
 * and this keeps the url readable when one has to be looked at.
 *
 * The markup never reaches the DOM as markup -- it goes into an `<img>`,
 * where browsers do not run scripts in SVG -- and from there into a texture.
 */
function svgDataUrl(markup: string): string | null {
  const open = /<svg\b[^>]*>/i.exec(markup);
  if (!open) return null;
  let tag = open[0];
  // The word boundaries are load-bearing: without them `stroke-width="2"`
  // reads as a width, so an SVG that sets a stroke and no size is
  // judged already sized and still draws nothing.
  if (!/\bwidth\s*=/i.test(tag) || !/\bheight\s*=/i.test(tag)) {
    const box = /viewBox\s*=\s*["']\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)/i
      .exec(tag);
    const w = box ? Math.round(parseFloat(box[1])) || 256 : 256;
    const h = box ? Math.round(parseFloat(box[2])) || 256 : 256;
    tag = tag.replace(/^<svg/i, `<svg width="${w}" height="${h}"`);
    markup = markup.replace(open[0], tag);
  }
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(markup);
}

/** One colour per host, so a site reads as a region without a legend. */
function hue(url: string): string {
  let host = url;
  try {
    host = new URL(url).host;
  } catch {
    /* keep the raw string; a stable hash is all this needs */
  }
  let h = 0;
  for (let i = 0; i < host.length; i++) h = (h * 31 + host.charCodeAt(i)) | 0;
  return `hsl(${Math.abs(h) % 360}, 65%, 62%)`;
}

/**
 * The collider of a projected node (`G-21`, amended by Addendum IX / `G-94`).
 *
 * Addendum IX: "collision boundaries defined as the diameter multiplied by
 * some safety factor for space between real nodes by some extra invisible
 * barrier length that I would argue is integer-valued in its safety
 * factors". It replaces the "quarter distance safety factor" (1.25) of
 * Addendum I, under which the collapsed picture still read as jumbled
 * (2026-09-27). The collider is the drawn radius times an INTEGER, plus an
 * invisible margin in scene units.
 */
/**
 * The fitted layout drawn as a THICK DISC facing the default camera
 * (2026-09-27, G-94): the camera looks down z, and a full-depth cloud stacked
 * page behind page -- 29 of 199 nodes buried on the working store. Depth is
 * kept, compressed; display only (the fit and the stored coordinates are
 * untouched).
 */
const DEPTH = 0.4;

const COLLIDER_SAFETY = 2;
const COLLIDER_MARGIN = 1;

/**
 * Streaming (force-directed) nodes, Addendum IX (`G-93`, `G-94`).
 *
 * "without an upper bound on link lengths and perhaps more lenient/relaxed
 * attractive forces (rather than strong repulsion)"; siblings kept apart by
 * "the diameter multiplied by some safety factor ... integer-valued", plus an
 * invisible margin. The spring rested every node 12 units from its parent
 * and pushed siblings apart only inside 8, so a 100-chunk drain packed into
 * one grey ball.
 */
export const STREAM = {
  /** Rest length of a link: BASE + PER * sqrt(nodes hanging below the child). Unbounded. */
  BASE: 18,
  PER: 7,
  /** Pull toward the rest length, per tick (it was 0.6). */
  PULL: 0.18,
  /** Sibling clearance: diameter x SAFETY (an integer) + MARGIN. */
  SAFETY: 3,
  MARGIN: 2,
  /** A streaming node's drawn radius, in scene units, and its opacity. */
  RADIUS: 2.2,
  OPACITY: 0.35,
  /** Planted by G-93's check: the spring this replaced (rest 12, pull 0.6,
   *  siblings apart inside 8, groups over 400 not spread). */
  LEGACY: false,
};

/**
 * How much wider a picture panel may be than the sphere it replaces (`G-21`).
 *
 * This is the one real trade in the relaxation, and it was measured rather
 * than chosen. A panel has to be given room, so the collider evicts whatever
 * the fit had put next to it; the bigger the panel, the more of the
 * embedding is spent buying it. Scored live as neighbourhood retention --
 * of a node's ten nearest neighbours in the fit, how many are still its ten
 * nearest afterwards -- over a 300-node sample, against a null arm that
 * shuffles the final positions between nodes and scores 0.001:
 *
 *     gain   edge   panels   spheres   extent
 *     1.00   2.73    0.841     0.937      305
 *     1.75   4.77    0.690     0.925      309
 *     2.50   6.82    0.547     0.914      328
 *     4.00  10.90    0.355     0.879      429
 *
 * Every one of those reaches zero overlapping pairs, so the gain does not buy
 * the `G-20` guarantee -- it buys picture size, and pays in embedding.
 *
 * 1.75 puts a panel's edge at 4.77 against this fit's median node spacing of
 * 4.19: a panel is as wide as the room the embedding allotted a node, and no
 * wider. Past that it is taking territory that belongs to other chunks, and
 * the reader can zoom for detail. Note the last column of the sphere score:
 * an oversized panel was displacing plain nodes too, and this wins 0.11 back
 * for the 4,510 chunks that never showed a picture at all.
 */
const PANEL_GAIN = 1.75;

/**
 * The edge of the square panel a picture node draws on, in world units.
 *
 * Sized from the fit, like `nodeRelSize` and for the same reason. This was
 * `clamp(sqrt(val) * 4, 6, 18)` -- an absolute world size that knew nothing
 * about the corpus it was drawing. `nodeRelSize` was 5.124 when those numbers
 * were picked and is 0.699 now, so every panel had grown to roughly 26 times
 * the sphere it stood in for, and the clamp had flattened them: nearly every
 * panel sat at the ceiling of 18, the same size whatever the chunk. That is
 * precisely the defect `relSize` already documents for spheres, left standing
 * one function away.
 *
 * A function rather than the same expression written at each place that needs
 * it. `billboard()` scales the sprite by this and the collider sizes its
 * sphere from it, and the two silently disagreeing is exactly the defect the
 * branch below exists to fix.
 */
function billboardEdge(node: { val?: number }, relSize: number): number {
  const sphere = Math.cbrt(Math.max(node.val ?? 1, 1e-9)) * relSize;
  // `* sqrt(2)` turns the circumradius the gain names back into an edge: the
  // panel's bounding sphere is what has to be `PANEL_GAIN` times the node's.
  return sphere * PANEL_GAIN * Math.SQRT2;
}

/**
 * The radius a node actually occupies -- which is not one formula, because
 * the pane does not draw one shape.
 *
 * A plain chunk is a sphere of `cbrt(val) * nodeRelSize`. A chunk that showed
 * a picture is a square PANEL instead, and a panel differs in both size and
 * kind: it is a `THREE.Sprite`, so it turns to face the camera, and across an
 * orbit it sweeps the sphere that circumscribes it. That radius is the
 * half-DIAGONAL, `edge / sqrt(2)` -- taking the half-edge would let two
 * panels rest corner into corner at every angle but the one facing them.
 *
 * Sizing every node as a sphere is not a small error here. Measured in the
 * app with the single-formula collider, on a 1,200-node sample: 96
 * overlapping pairs, and every one of them involved a panel -- 66
 * panel-on-panel, 30 panel-on-sphere, 0 sphere-on-sphere. The collider was
 * reserving 1.93 units for a node drawing at 12.73, a factor of 6.6, so the
 * simulation believed it had resolved a corpus it had never measured. The
 * sphere arm was already correct and stays untouched.
 */
function drawnRadius(node: any, relSize: number, media: boolean): number {
  if (media && node?.image?.src) {
    return billboardEdge(node, relSize) * Math.SQRT1_2;
  }
  return Math.cbrt(Math.max(node.val ?? 1, 1e-9)) * relSize;
}

export class GraphView extends ItemView {
  /** Put the camera back outside the cloud, looking at the middle. */
  private reframe: (() => void) | null = null;
  /** Frame what an expansion just opened. Set in `draw`. */
  private frameOn: ((subset: any[]) => void) | null = null;
  /**
   * Fetched pictures, shared across every instance of the view.
   *
   * Many nodes of one site point at the same avatar or logo, and reopening
   * the pane refits and rebuilds every sprite. Without this, closing and
   * reopening the graph re-downloads the corpus's images.
   */
  private static textures = new Map<string, string | null>();
  private graph: ForceGraph3DInstance | null = null;
  /** The projector fit this picture was drawn from, and how far into its
   *  stream the pane has applied. -1 when the layout did not come from it. */
  projEpoch = -1;
  projSeq = 0;
  /** The projector's last reported state, for the caption and the harness. */
  projStatus: any = null;
  /** What the stream has done to this pane, counted. */
  streamApplied = { deltas: 0, moved: 0, added: 0, gone: 0, pages: 0,
                    reloads: 0, lastAt: 0 };
  private pulling = false;
  /** Chunks the reader had open when a new fit was announced, kept until a
   *  picture in the NEW fit is actually drawn and they can be re-placed. */
  private reopen = new Set<string>();
  private retryLoad = 0;
  //: The caption is written on load and the picture changes afterwards.
  //  Unfolding took 96 nodes to 122 and the bar still said "96 pages", which
  //  is the one number on screen a reader uses to check the pane against the
  //  store. Keep the element and the invariant half of the text so the
  //  counts can be restated whenever the graph is mutated.
  private statusEl: HTMLElement | null = null;
  //: `G-57`. The chunk panel opens HERE, beside the node it belongs to,
  //  rather than taking over an Obsidian pane. Keyed by cid so clicking the
  //  same node twice does not stack two of them.
  private billboards = new Map<string, {
    el: HTMLElement; node: any; pinned: boolean;
    /** The mounted chunk surface, released when the billboard closes. */
    surface?: ChunkSurface | null;
    /** Opened by a right-click in the browser (`G-78`): it stays until the
     *  markdown side lets it go, and a click on the node does not close it. */
    fromBrowser?: boolean;
  }>();
  private billboardFrame = 0;
  private billboardLayer: HTMLElement | null = null;
  private canvasEl: HTMLElement | null = null;
  private captionTail = "";
  /** Which embedding space to ask the fit for: "" for the Euclidean one,
   *  "S3" for the quaternion metric (`G-18`). Empty by default, on the
   *  measurement recorded in `layout.py`. */
  private space = "";
  /** Which unit the fit draws: "" for the server's default, which is pages
   *  (`G-53`), or "chunk" for every chunk. */
  private level = "";
  /** Watches the canvas's box so the controls are recalibrated whenever
   *  it actually changes. Disconnected in `onClose`: an observer left on a
   *  detached canvas keeps the view, its WebGL context and its 5,337 node
   *  objects alive for as long as the app runs. */
  private resizeObserver: ResizeObserver | null = null;
  /** Where billboards fetch and enact from: the plugin. */
  private surfaceHost: SurfaceHost;
  /** Ask the browser's overlay to restrict its ranking to one page, or to
   *  release it (`G-70`). Set by the plugin, because a graph pane must work
   *  with no browser open. */
  onScope: (url: string) => void = () => {};
  //: Clicking a node takes the BROWSER to it (`G-40`). Set by the
  //  plugin, which is what knows whether a browser pane is open --
  //  neither pane may require the other, so this is brokered rather
  //  than held by either.
  onReveal: (url: string, xpath: string) => void = () => {};

  constructor(leaf: WorkspaceLeaf, private sidecar: Sidecar,
              surfaceHost: SurfaceHost,
              private media: () => boolean) {
    super(leaf);
    this.surfaceHost = surfaceHost;
  }

  getViewType() { return GRAPH_VIEW; }
  getDisplayText() { return "domvec 3D graph"; }
  getIcon() { return "git-fork"; }

  async onOpen() {
    const root = this.containerEl.children[1] as HTMLElement;
    root.empty();
    root.addClass("domvec-graph-root");

    const bar = root.createDiv({ cls: "domvec-graph-bar" });
    const status = bar.createSpan({ cls: "domvec-graph-status",
                                    text: "fitting…" });
    const again = bar.createEl("button", { text: "refit" });
    const recentre = bar.createEl("button", { text: "recentre" });
    recentre.onclick = () => this.reframe?.();
    // Which geometry the fit runs in (`G-18`). A switch rather than a
    // setting, because the two are a thing to compare: the quaternion fit
    // keeps about half as many of the encoder's neighbourhoods on the corpus
    // measured so far, and the only way that number moves is if someone can
    // look at both pictures of the same data.
    // Pages or chunks (`G-53`). A switch, because the collapsed view is the
    // one a reader can hold and the expanded one is where the detail is, and
    // neither is a setting you choose once.
    const unit = bar.createEl("button", { text: "pages" });
    unit.onclick = () => {
      this.level = this.level === "chunk" ? "" : "chunk";
      unit.setText(this.level === "chunk" ? "chunks" : "pages");
      void load();
    };
    const geometry = bar.createEl("button", { text: "euclidean" });
    geometry.onclick = () => {
      this.space = this.space ? "" : "S3";
      geometry.setText(this.space ? "S³" : "euclidean");
      void load();
    };

    const canvas = root.createDiv({ cls: "domvec-graph-canvas" });
    // The billboards hang off the CANVAS, not the pane.
    // `graph2ScreenCoords` answers in the canvas's own coordinates,
    // and the caption bar sits above it -- anchoring to the pane would
    // have drawn every panel one bar-height below its node.
    this.canvasEl = canvas;

    const load = async () => {
      // Not over the force tree's caption: a retry every 3 s wrote
      // "fitting…" across a pane that was drawing (`G-89`).
      if (this.layoutMode !== "force") status.setText("fitting…");
      const asked = this.space;
      const asking = this.level;
      const layout = (await this.sidecar.layout(3, asked, asking)) as
        Layout | null;
      if (!layout) {
        status.setText("no sidecar — start it to see the graph");
        return;
      }
      if (layout.fitting) {
        // The projector is making its fit. Say so and ask again; the old
        // separate fits are not a fallback, because the stream never places
        // into them.
        const ps = layout.projector || {};
        const fitting = `projector fitting · ${ps.chunks_now ?? "?"} chunks` +
                        ` · sample ≤ ${ps.fit_sample || 4000}`;
        // The force tree is what is drawn meanwhile (`G-89` C5): say both.
        status.setText(this.layoutMode === "force" ? `${forceText()} · ${fitting}` : fitting);
        // One pending retry, not one per caller: the stream also asks for a
        // reload while a fit is running, and each used to queue its own.
        window.clearTimeout(this.retryLoad);
        this.retryLoad = window.setTimeout(() => void load(), 3000);
        return;
      }
      if (!layout.nodes.length) {
        status.setText(this.layoutMode === "force"
          ? `${forceText()} · the projector has nothing to place yet`
          : (layout.note || "nothing to place yet"));
        // Ask again: a fresh store gets its first fit once enough chunks
        // have vectors, and nothing else would bring the pane to it.
        window.clearTimeout(this.retryLoad);
        this.retryLoad = window.setTimeout(() => void load(), 3000);
        return;
      }
      this.draw(canvas, layout);
      // The projector's page view is drawn; the pending diff stays drawn,
      // force-directed, hung from its pages, until the transform places it
      // (`G-89` C6, C8 -- and a refit must not drop it).
      this.setMode("projector", layout.source === "projector"
        ? `projector epoch ${layout.epoch ?? "?"}` : `layout from ${layout.source ?? "?"}`);
      if (this.forceSpecs.size) {
        // The fit covers what was scanned before it; only the page in the
        // browser keeps a pending diff, checked against the map as it comes.
        const keep = this.browsingUrl ? this.browsingUrl() : "";
        for (const [id, spec] of this.forceSpecs) {
          if (spec.url !== keep) this.forceSpecs.delete(id);
        }
        this.redrawForce();
        this.collapseCovered();
      }
      this.projEpoch = layout.source === "projector" ? (layout.epoch ?? -1) : -1;
      this.projSeq = layout.seq ?? 0;
      this.projStatus = layout.projector ?? null;
      // What the reader had open before a new fit, placed again in it.
      if (this.reopen.size && this.projEpoch >= 0) {
        const open = [...this.reopen];
        this.reopen.clear();
        void (async () => {
          for (let i = 0; i < open.length; i += 400) {
            const got: any = await this.sidecar.place(open.slice(i, i + 400));
            if (got?.nodes?.length) this.absorb(got.nodes, got.edges);
          }
        })();
      }
      // Composing the LABEL must not be able to break the PANE.
      //
      // The picture is already on screen by this line. Everything below is a
      // caption, and a caption that throws used to leave the status on
      // "fitting…" forever -- a working graph that read as a hung one. Each
      // field below is also read defensively, but the guard is what makes that
      // a belt rather than the only thing holding it up: the next field the
      // backend renames should cost a word of the caption, not the pane.
      try {
      // `fitted_on.semantic` rather than the space name alone. The projector
      // fits on the semantic space (D-1), and frequency survives only as the
      // fallback for a workspace with no embeddings. Those two produce
      // different pictures and look identical from the pane, so the pane says
      // which one it is looking at.
      //
      // Read defensively: this pane reads a report from a separately-running
      // sidecar, which may be an older build than the plugin. It previously
      // read `layout.halves.equalised` unguarded, and when the backend stopped
      // reporting `halves` the throw landed AFTER `draw()` -- so the canvas
      // painted, the status stayed on "fitting…" forever, and the pane looked
      // hung while working. A missing field must degrade to a weaker label,
      // never to an exception.
      const fit = layout.fitted_on
        ? (layout.fitted_on.semantic
            ? "semantic fit"
            : "FREQUENCY FALLBACK — no embeddings")
        : "fit unreported";
      // `fitted_dims`, not an assumption: a viewer colouring by hue is
      // showing three more dimensions of the projection, and one falling back
      // to a per-host palette is showing a legend. The two look identical
      // from the pane, so the pane says which it is.
      const colour = layout.hsv
        ? `${layout.fitted_dims ?? 6}D · colour from the fit`
        : "3D · colour by host";
      const pictures = layout.images
        ? ` · ${layout.images} with a picture` : "";
      // What the nodes ARE, not "chunks" regardless. The collapsed view drew
      // 96 pages over 14,169 chunks and the caption said "96 chunks", which
      // is the one number on screen a reader would use to check the pane
      // against the store -- and it disagreed with both.
      const unit = layout.level === "page"
        ? `${layout.n} pages · ${layout.chunks ?? "?"} chunks`
        : `${layout.n} chunks`;
      this.statusEl = status;
      // The fit's description only. The projector's state changes every
      // second and is composed in at display time -- never appended here,
      // or each refresh stacks another copy onto the last.
      this.captionTail =
        `${(layout.spaces ?? []).join(" + ")} · ${fit} · ${colour}${pictures}`;
      this.setStatus(`${unit} · ${this.captionTail}${this.projectorCaption()}`);
      } catch (err) {
        // Say the count, which is the one thing a reader needs to know the
        // pane is alive, and name the failure rather than swallowing it.
        status.setText(`${layout.nodes.length} nodes · caption failed: ` +
                       `${err instanceof Error ? err.message : String(err)}`);
      }
    };

    // "refit" asks the PROJECTOR to refit, in the background. The picture
    // stays until the new fit is complete; the stream then reports a new
    // epoch and `pullDelta` redraws once.
    again.onclick = async () => {
      status.setText("projector refitting in the background…");
      await this.sidecar.layout(3, this.space, this.level, true);
    };
    this.reload = load;
    const forceText = () => {
      const n = this.graph ? this.graph.graphData().nodes.length : 0;
      return `force layout · ${n} nodes from ${this.forceStats.drains} drains · ` +
             "no embedding needed";
    };
    this.forceCaption = () => status.setText(`${forceText()} · waiting for the projector's first fit`);
    await load();
    // The stream. Once a second: what the projector placed since the last
    // sequence number this pane applied. O(delta) -- a quiet corpus costs
    // one empty reply.
    this.registerInterval(window.setInterval(() => void this.pullDelta(load), 1000));
  }

  /**
   * Fetch the layout again from whichever sidecar the plugin points at, and
   * redraw. The in-app fresh-store run switches the sidecar and calls this,
   * so the pane shows the store the checks read -- without a plugin reload,
   * which would end the run that asked for it.
   */
  reload: () => Promise<void> = async () => {};

  // -- the force-directed tree, first and primary (`G-89`) ------------------

  /**
   * What the pane is drawing: nothing yet, the force-directed tree built in
   * the renderer from the drains, or the projector's layout. Read by the
   * harness; `phaseLog` is its history, which is what the phase contracts
   * are checked against.
   */
  layoutMode: "empty" | "force" | "projector" = "empty";
  phaseLog: { at: number; mode: string; nodes: number; why: string }[] = [];
  /** Per-drain renderer cost and counts, for C3. */
  forceStats = { drains: 0, added: 0, removed: 0, reparented: 0, ms: [] as number[],
                 toScene: [] as number[],
                 /** Mean movement of the already-drawn streaming nodes between updates. */
                 jitter: [] as number[],
                 /** [ms, nodes the drain touched] per drain: O(delta) is judged
                  *  per touched node, not per drain (a page's first drain
                  *  carries 500 chunks, later ones a handful). */
                 sized: [] as [number, number][] };

  private setMode(mode: "empty" | "force" | "projector", why: string): void {
    this.motion.event("mode", { mode, why: String(why).slice(0, 60) });
    if (mode === this.layoutMode) return;
    this.layoutMode = mode;
    const nodes = this.graph ? this.graph.graphData().nodes.length : 0;
    this.phaseLog.push({ at: Date.now(), mode, nodes, why });
    if (this.phaseLog.length > 200) this.phaseLog.shift();
  }

  /** The forces a TREE wants -- the ones a projector layout switches off. */
  private forceConfigure(): void {
    const g: any = this.graph;
    if (!g) return;
    g.d3Force("home", null);
    g.d3Force("contain", null);
    // Charge builds an octree every tick too: sanitised first (D-38).
    const charge: any = forceManyBody().strength(-60).distanceMax(220);
    let chargeNodes: any[] = [];
    const safeCharge: any = (alpha: number) => {
      this.sanitize(chargeNodes);
      if (this.octreeOk(chargeNodes, "charge", false)) charge(alpha);
    };
    safeCharge.initialize = (...a: any[]) => { chargeNodes = a[0] || []; return charge.initialize(...a); };
    g.d3Force("charge", safeCharge);
    g.d3Force("center", forceCenter());
    g.d3Force("link")?.strength(0.9).distance(18);
    g.d3AlphaDecay(0.0228).d3VelocityDecay(0.4);
    this.installHold();
    this.watchForces();
  }

  /**
   * CALM BETWEEN UPDATES (2026-09-28: "Force-directed scans in rapid fire on
   * the julia page are fast and responsive, but the force directed layout in
   * 3D is way too chaotic between scan updates"). Every drain hands the graph
   * a new node array, and that restarts the simulation at full heat: a burst
   * of drains re-shook the whole tree -- charge, springs, siblings -- for the
   * few nodes each one added. Now the nodes already drawn are HELD where they
   * are for 1.5 s after each update (renewed while updates keep coming); only
   * the newcomers are free to settle, and they start where they belong.
   */
  private installHold(): void {
    const g: any = this.graph;
    if (!g) return;
    let held: any[] = [];
    const hold: any = () => {
      const now = performance.now();
      for (const n of held) {
        const at = n.holdAt;
        if (!at) continue;
        if (now > n.holdUntil) { n.holdAt = undefined; continue; }
        n.vx = (n.vx ?? 0) * 0.2 + (at[0] - (n.x ?? 0)) * 0.5;
        n.vy = (n.vy ?? 0) * 0.2 + (at[1] - (n.y ?? 0)) * 0.5;
        n.vz = (n.vz ?? 0) * 0.2 + (at[2] - (n.z ?? 0)) * 0.5;
      }
    };
    hold.initialize = (nodes: any[]) => { held = nodes || []; };
    g.d3Force("hold", hold);
  }

  /** Planted by G-93's check: no hold -- every update re-shakes the whole tree. */
  plantNoHold = false;

  /** Hold every streaming node already drawn (not `fresh`), and measure how
   *  far the held ones moved since the last update (`forceStats.jitter`). */
  private holdAll(nodes: any[], fresh: Set<string>): void {
    const now = performance.now();
    let moved = 0, n = 0;
    for (const x of nodes) {
      if (!x.force || fresh.has(x.id) || !Number.isFinite(x.x)) continue;
      if (x.lastAt) {
        moved += Math.hypot(x.x - x.lastAt[0], x.y - x.lastAt[1], (x.z ?? 0) - x.lastAt[2]);
        n++;
      }
      x.lastAt = [x.x, x.y, x.z ?? 0];
      if (this.plantNoHold) continue;
      x.holdAt = [x.x, x.y, x.z ?? 0];
      x.holdUntil = now + 1500;
    }
    if (n) {
      this.forceStats.jitter.push(moved / n);
      if (this.forceStats.jitter.length > 500) this.forceStats.jitter.shift();
    }
  }

  /**
   * One drain's delta, applied to the force tree (`G-89` C2-C4).
   *
   * Called by the browser cell the moment a drain is decoded -- before the
   * capture's round trip, so nothing here waits on the sidecar, the store,
   * the embedder or the projector. O(delta): only what the drain added,
   * removed or re-parented is touched; every other node keeps its object,
   * so its position and velocity carry on (the tree grows, it is not
   * redrawn). Ignored once the projector draws the pane (C7): from then on
   * a drain reaches the picture through the stream.
   */
  forceDelta(d: ForceNodeDelta): void {
    if (!this.canvasEl) return;
    const t0 = performance.now();
    if (!this.graph) {
      this.draw(this.canvasEl, { nodes: [], edges: [] } as any);
    }
    if (!this.graph) return;
    if (this.layoutMode === "empty") this.forceConfigure();
    const data: any = this.graph.graphData();
    const gone = new Set(d.removed);
    const end = (x: any) => (typeof x === "object" && x ? x.id : x);
    const moving = new Map(d.reparented.map((r) => [r.id, r.parent]));
    let nodes = gone.size ? data.nodes.filter((n: any) => !gone.has(n.id)) : data.nodes.slice();
    let links = data.links.filter((l: any) =>
      !gone.has(end(l.source)) && !gone.has(end(l.target)) && !moving.has(end(l.target)));
    for (const id of gone) this.forceSpecs.delete(id);
    const byId = new Map<string, any>(nodes.map((n: any) => [n.id, n]));
    const pageNode = this.projectedPage(d.url, byId);
    for (const [id, parent] of moving) {
      const spec = this.forceSpecs.get(id);
      if (spec) spec.parent = parent;
      const to = this.parentFor(parent, d.url, byId, pageNode);
      if (byId.has(id) && to) links.push({ source: to, target: id, force: true });
    }
    // After the fit a page's pending diff is drawn only while the reader has
    // that page EXPANDED; collapsed, it is kept and not drawn (2026-09-26).
    // ... or while the page is new since the fit (no page node yet): its
    // force tree is the only immediate picture of the scan.
    const drawHere = this.layoutMode !== "projector" || !pageNode
      || this.expandedUrls(byId).has(d.url);
    for (const a of d.added) {
      if (byId.has(a.id)) continue;
      // A page the projector already draws needs no root of its own: the
      // pending diff hangs from its projected page node (C6, C8).
      if (!a.parent && pageNode) {
        this.forceSpecs.set(a.id, { parent: "", url: d.url, title: a.title, lines: 0 });
        continue;
      }
      const cid = d.covers ? d.covers[a.id] : undefined;
      // Stored before this visit and unchanged: already transformed.
      if (!a.again && d.settled && d.settled.includes(a.id)) { this.forceSpecs.delete(a.id); continue; }
      // Already drawn by the projector: not the diff, nothing to draw -- unless
      // its content just CHANGED (`again`), in which case what is drawn is the
      // old content and this stays pending until the new one is placed.
      if (cid && !a.again && byId.has(cid) && !byId.get(cid).force) { this.forceSpecs.delete(a.id); continue; }
      this.forceSpecs.set(a.id, { parent: a.parent, url: d.url, title: a.title, lines: a.lines,
                                  cid, stale: !!a.again, born: Date.now() });
      if (a.parent) {
        this.life.nodes.set(a.id, { url: d.url, drawnAt: Date.now(), cid });
        if (this.life.nodes.size > 20000) this.life.nodes.delete(this.life.nodes.keys().next().value as string);
      }
      if (!drawHere) continue;
      const to = a.parent ? this.parentFor(a.parent, d.url, byId, pageNode) : "";
      const p = to ? byId.get(to) : null;
      // Where it belongs, not a random jitter: a spring length from its
      // parent, in the next direction of a Fibonacci sphere of its siblings.
      const k = (this.childCount.get(to) || 0);
      this.childCount.set(to, k + 1);
      const zz = 1 - 2 * ((k % 32) + 0.5) / 32, rr = Math.sqrt(Math.max(0, 1 - zz * zz));
      const th = k * Math.PI * (3 - Math.sqrt(5));
      const off = [rr * Math.cos(th) * STREAM.BASE, rr * Math.sin(th) * STREAM.BASE, zz * STREAM.BASE];
      const jitter = (i: number) => (p ? off[i] : (Math.random() - 0.5) * 6);
      const page = !a.parent;
      const n: any = {
        id: a.id, level: page ? "page" : "chunk", name: a.title || a.id,
        url: d.url, members: 1, tokens: 0, force: true,
        val: page ? 3 : 1,
        color: page ? "#8ab4f8" : "#9aa0a6",
        x: (p?.x ?? 0) + jitter(0), y: (p?.y ?? 0) + jitter(1), z: (p?.z ?? 0) + jitter(2),
      };
      nodes.push(n);
      byId.set(n.id, n);
      if (p) links.push({ source: p.id, target: n.id, force: true });
    }
    this.holdAll(nodes, new Set(d.added.map((a) => a.id)));
    this.touchActive(d.url);
    this.motion.event("drain", { url: d.url.slice(-50), added: d.added.length, removed: d.removed.length,
                                 reparented: d.reparented.length });
    this.graph.graphData({ nodes, links });
    if (this.layoutMode === "projector") {
      this.treeSpring();
      this.graph.d3ReheatSimulation?.();
    }
    // Time to the SCREEN, not to the data: the next frame after the nodes
    // were handed over is when the renderer draws them (`G-90`).
    if (d.t0 && d.added.length) {
      const from = d.t0, traceId = d.trace;
      window.requestAnimationFrame(() => {
        const toScene = performance.now() - from;
        this.forceStats.toScene.push(toScene);
        if (this.forceStats.toScene.length > 500) this.forceStats.toScene.shift();
        const t = traceId ? profiler().get(traceId) : undefined;
        if (t) profiler().stage(t, "drain_to_3d", toScene);
      });
    }
    const ms = performance.now() - t0 + d.ms;
    this.forceStats.drains++;
    this.forceStats.added += d.added.length;
    this.forceStats.removed += d.removed.length;
    this.forceStats.reparented += d.reparented.length;
    this.forceStats.ms.push(ms);
    if (this.forceStats.ms.length > 500) this.forceStats.ms.shift();
    this.forceStats.sized.push([ms, d.added.length + d.removed.length + d.reparented.length]);
    if (this.forceStats.sized.length > 500) this.forceStats.sized.shift();
    if (this.layoutMode !== "projector") {
      this.setMode("force", `drain on ${d.url}`);
      this.forceCaption?.();
    }
  }

  /** Children placed under each parent so far, for the newcomers' directions. */
  private childCount = new Map<string, number>();

  /** Every force node drawn: what a redraw needs to put it back. */
  private forceSpecs = new Map<string, { parent: string; url: string; title: string;
                                          lines: number; cid?: string; stale?: boolean;
                                          born?: number }>();
  private settleTimer = 0;

  /** Set by the plugin: the url the browser cell is showing. */
  browsingUrl: (() => string) | null = null;

  /** Force nodes still waiting on a transform -- for the harness. */
  pendingState() {
    const drawn = this.graph ? this.graph.graphData().nodes.filter((n: any) => n.force).length : 0;
    return { force_nodes: this.forceSpecs.size, drawn,
             covered_known: [...this.forceSpecs.values()].filter((x) => x.cid).length,
             timed_out: this.forceTimedOut,
             expanded: [...this.expandedUrls()].length };
  }

  /** Pages the reader has EXPANDED: their chunks are drawn (not force ones). */
  private expandedUrls(byId?: Map<string, any>): Set<string> {
    const nodes: any[] = byId ? [...byId.values()]
      : (this.graph ? this.graph.graphData().nodes : []);
    return new Set(nodes.filter((n: any) => !n.force && n.level !== "page" && n.url)
      .map((n: any) => n.url));
  }

  /**
   * A projector layout switches the spring and repulsion forces off (the fit
   * IS the layout), so force nodes drawn inside an expanded page had nothing
   * but collision and piled up (2026-09-26: "way too jumbled"). This spring
   * acts on force nodes only: each is pulled to a rest distance from its
   * parent, and nothing the projector placed moves.
   */
  private treeSpring(): void {
    const g: any = this.graph;
    if (!g) return;
    let links: any[] = [];
    // How many nodes hang below each node, so a link's rest length grows
    // with what it carries: a big subtree is given room, a leaf stays close.
    let below = new Map<string, number>();
    let siblings = new Map<string, number>();
    const spring: any = (alpha: number) => {
      const bySource = new Map<string, any[]>();
      for (const l of links) {
        const s = l.source, t = l.target;
        if (!t || !t.force || typeof s !== "object") continue;
        const dx = (t.x ?? 0) - (s.x ?? 0), dy = (t.y ?? 0) - (s.y ?? 0), dz = (t.z ?? 0) - (s.z ?? 0);
        const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
        // Room for what hangs below this child AND for the siblings sharing
        // its shell: n siblings need a sphere of radius ~ clear*sqrt(n/4pi).
        // No upper bound (Addendum IX).
        const clearance = 2 * STREAM.RADIUS * STREAM.SAFETY + STREAM.MARGIN;
        const shell = clearance * Math.sqrt((siblings.get(typeof s === "object" ? s.id : s) || 1) / (4 * Math.PI)) * 1.2;
        const rest = STREAM.LEGACY ? 12 : Math.max(STREAM.BASE + STREAM.PER * Math.sqrt(below.get(t.id) || 0), shell);
        const k = ((d - rest) / d) * alpha * (STREAM.LEGACY ? 0.6 : STREAM.PULL);
        t.vx = (t.vx ?? 0) - dx * k; t.vy = (t.vy ?? 0) - dy * k; t.vz = (t.vz ?? 0) - dz * k;
        const kids = bySource.get(s.id) || [];
        kids.push(t);
        bySource.set(s.id, kids);
      }
      // SIBLINGS apart: with no charge and no collision room, the spring
      // alone let force nodes under one parent settle on one point (G-4
      // counted 8 coincident nodes). Short-range and among siblings only,
      // so nothing the projector placed is touched.
      const clear = STREAM.LEGACY ? 8 : 2 * STREAM.RADIUS * STREAM.SAFETY + STREAM.MARGIN;
      for (const kids of bySource.values()) {
        if (kids.length < 2 || (STREAM.LEGACY && kids.length > 400)) continue;
        // A grid of cells one clearance wide: each node is compared with the
        // 27 cells around it, so a 1,260-sibling drain costs O(n), not O(n^2)
        // -- the old pairwise loop skipped groups over 400, and exactly those
        // packed into one ball (G-93: nn p50 0.4 radii on a heavy page).
        const cell = new Map<string, any[]>();
        const key = (x: number, y: number, z: number) => `${Math.floor(x / clear)},${Math.floor(y / clear)},${Math.floor(z / clear)}`;
        for (const a of kids) {
          const k = key(a.x ?? 0, a.y ?? 0, a.z ?? 0);
          const list = cell.get(k); if (list) list.push(a); else cell.set(k, [a]);
        }
        const pairs: [any, any][] = [];
        for (const a of kids) {
          const cx = Math.floor((a.x ?? 0) / clear), cy = Math.floor((a.y ?? 0) / clear), cz = Math.floor((a.z ?? 0) / clear);
          for (let ox = -1; ox <= 1; ox++) for (let oy = -1; oy <= 1; oy++) for (let oz = -1; oz <= 1; oz++) {
            for (const b of cell.get(`${cx + ox},${cy + oy},${cz + oz}`) || []) if (a.id < b.id) pairs.push([a, b]);
          }
        }
        for (const [a, b] of pairs) {
          {
            let dx = (a.x ?? 0) - (b.x ?? 0), dy = (a.y ?? 0) - (b.y ?? 0), dz = (a.z ?? 0) - (b.z ?? 0);
            let d2 = dx * dx + dy * dy + dz * dz;
            if (d2 > clear * clear) continue;
            if (d2 < 1e-6) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; dz = Math.random() - 0.5; d2 = 0.25; }
            const d = Math.sqrt(d2), push = ((clear - d) / d) * alpha * 0.5;
            a.vx = (a.vx ?? 0) + dx * push; a.vy = (a.vy ?? 0) + dy * push; a.vz = (a.vz ?? 0) + dz * push;
            b.vx = (b.vx ?? 0) - dx * push; b.vy = (b.vy ?? 0) - dy * push; b.vz = (b.vz ?? 0) - dz * push;
          }
        }
      }
    };
    spring.initialize = () => {
      links = (g.graphData().links || []).filter((l: any) => l.force);
      const kids = new Map<string, string[]>();
      for (const l of links) {
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        const k = kids.get(sid) || [];
        k.push(tid);
        kids.set(sid, k);
      }
      below = new Map();
      siblings = new Map([...kids.entries()].map(([k, v]) => [k, v.length]));
      const count = (id: string, seen: Set<string>): number => {
        if (below.has(id)) return below.get(id)!;
        if (seen.has(id)) return 0;
        seen.add(id);
        let n = 0;
        for (const c of kids.get(id) || []) n += 1 + count(c, seen);
        below.set(id, n);
        return n;
      };
      for (const id of kids.keys()) count(id, new Set());
    };
    g.d3Force("treeSpring", spring);
    this.installHold();
    this.watchForces();
  }

  /** The projector's page node for `url`, if it draws one. */
  private projectedPage(url: string, byId?: Map<string, any>): any {
    const nodes: any[] = byId ? [...byId.values()]
      : (this.graph ? this.graph.graphData().nodes : []);
    return nodes.find((n: any) => !n.force && n.level === "page" && n.url === url) || null;
  }

  /** Where a force node hangs: its force parent, or -- for a page root --
   *  the page's projected node when the projector draws one. */
  private parentFor(parent: string, url: string, byId: Map<string, any>,
                    pageNode?: any): string {
    if (parent && byId.has(parent)) return parent;
    // The parent chunk already collapsed: hang from the projected chunk it
    // collapsed into, which is where its content is drawn now.
    const into = parent ? this.collapsedTo.get(parent) : undefined;
    if (into && byId.has(into)) return into;
    // The page node, looked up ONCE per drain by the caller: scanning the
    // graph for it per added node made a drain O(drain x graph) -- the
    // renderer's per-drain p95 went from 14 to 60 ms (G-89 C3).
    const page = pageNode !== undefined ? pageNode : this.projectedPage(url, byId);
    return page ? page.id : (byId.has(parent) ? parent : "");
  }

  /**
   * The browser's chunk map now names the stored chunk covering these force
   * nodes. Each collapses as soon as that chunk's projected node is drawn;
   * until then it stays the pending diff (`G-89` C7).
   */
  coverForce(url: string, covers: Record<string, string>, settled: string[] = []): void {
    // The capture's reply: the store has SAVED these (Addendum IX, stage 4:
    // "The moment the store confirms a node saved, THAT node collapses into
    // its page's root node -- before any vector, before any projection").
    // It used to wait for the projected node to be DRAWN -- G-89's older
    // order -- so a saved chunk stayed a streaming node through embedding
    // and placement, and on a collapsed page for good (2026-09-28).
    const now = Date.now();
    const saved = new Set<string>();
    for (const [id, cid] of Object.entries(covers)) {
      const spec = this.forceSpecs.get(id);
      if (!spec || !cid) continue;
      spec.cid = cid;
      spec.stale = false;
      saved.add(id);
      const l = this.life.nodes.get(id);
      if (l && !l.savedAt) l.savedAt = now;
    }
    for (const id of settled) if (this.forceSpecs.has(id)) saved.add(id);
    // Planted by G-92's check: the old order, collapse only once projected.
    if (this.plantLateCollapse) { this.collapseCovered(); return; }
    if (saved.size) this.foldIn(saved);
    this.collapseCovered();
  }

  /** Planted by G-92's check: a saved node waits for its projection (the old order). */
  plantLateCollapse = false;
  /**
   * D-38, found 2026-09-28 by pausing the frozen renderer: the stack was
   * `add3 <- addAll3 <- octree <- collide force <- tick`, heap 866 MB and
   * climbing. d3-octree skips a NaN coordinate but not +-Infinity: an infinite
   * extent makes `add`'s subdivision loop (and `cover`'s) never end, and each
   * turn allocates -- Chromium: "Renderer process oom", the whole window gone.
   * So no node reaches an octree with a non-finite (or runaway, > 1e7)
   * position: it goes back to its fit, still, and is RECORDED with everything
   * that moved it, so the force that produced it can be named.
   */
  nonFinite: any[] = [];
  nonFiniteCount = 0;
  /** Which FORCE first left a non-finite velocity, per tick it happened (D-38). */
  nanBy: { at: number; force: string; nodes: number; alpha: number; sample: any }[] = [];

  /**
   * Every force the pane runs, wrapped: after it acts, velocities are
   * checked, and the FIRST force to leave a non-finite one is named -- the
   * guard (`sanitize`) keeps the octree safe, this says where the NaN came
   * from. O(nodes) per force per tick.
   */
  private watchForces(): void {
    const g: any = this.graph;
    if (!g) return;
    for (const name of ["link", "center", "charge", "home", "contain", "collide", "treeSpring", "hold"]) {
      const f: any = g.d3Force(name);
      if (!f || f.__watched) continue;
      let nodes: any[] = [];
      const w: any = (alpha: number) => {
        const before = this.motion.forceBefore(nodes);
        f(alpha);
        this.motion.forceAfter(name, nodes, before, alpha);
        for (const n of nodes) {
          if (Number.isFinite(n.vx) && Number.isFinite(n.vy) && Number.isFinite(n.vz ?? 0)) continue;
          if (n.vx === undefined) continue;
          const bad = nodes.filter((m) => m.vx !== undefined && !(Number.isFinite(m.vx) && Number.isFinite(m.vy) && Number.isFinite(m.vz ?? 0)));
          if (this.nanBy.length < 40) this.nanBy.push({ at: Date.now(), force: name, nodes: bad.length, alpha,
            sample: { id: String(n.id).slice(0, 60), level: n.level, force: !!n.force, x: n.x, vx: String(n.vx), fitX: n.fitX, val: n.val,
                      anchor: n.anchorPos, room: n.room, hold: n.holdAt } });
          break;
        }
      };
      w.initialize = (...a: any[]) => { nodes = a[0] || []; return f.initialize ? f.initialize(...a) : undefined; };
      // The accessors the rest of the pane calls on these forces pass through.
      for (const k of ["strength", "distance", "radius", "iterations", "distanceMax", "links", "id", "x", "y", "z"]) {
        if (typeof f[k] === "function") w[k] = (...a: any[]) => { const r = f[k](...a); return a.length ? w : r; };
      }
      w.__watched = true;
      g.d3Force(name, w);
    }
  }
  /** Ticks an octree force sat out because a node could not be placed in
   *  one (octreeguard), and the last such, for the harness. */
  octreeSkips: { collide: number; charge: number; flushed: number; last: any } = { collide: 0, charge: 0, flushed: 0, last: null };

  private octreeOk(nodes: any[], force: "collide" | "charge", predicted: boolean): boolean {
    const v = octreeVerdict(nodes, predicted);
    if (v.ok) return true;
    this.octreeSkips[force]++;
    this.octreeSkips.last = { at: Date.now(), force, bad: v.bad, of: nodes.length, sample: v.sample };
    return false;
  }

  private sanitize(nodes: any[]): void {
    for (const n of nodes) {
      const x = n.x, y = n.y, z = n.z ?? 0;
      const vx = n.vx ?? 0, vy = n.vy ?? 0, vz = n.vz ?? 0;
      // Positions AND velocities: collision's octree is built on x + vx (the
      // predicted position), so an infinite velocity hangs it as surely --
      // finite positions passed this check and the renderer still froze.
      if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)
          && Math.abs(x) < 1e7 && Math.abs(y) < 1e7 && Math.abs(z) < 1e7
          && Number.isFinite(vx) && Number.isFinite(vy) && Number.isFinite(vz)
          && Math.abs(vx) < 1e6 && Math.abs(vy) < 1e6 && Math.abs(vz) < 1e6) continue;
      // Not placed yet: left for d3 to place. The octree does NOT skip it --
      // it inserts it at the origin -- so `octreeOk` keeps such a tick out
      // of the build instead.
      if (x === undefined) continue;
      this.nonFiniteCount++;
      if (this.nonFinite.length < 40) {
        const r = (v: any) => (typeof v === "number" ? (Number.isFinite(v) ? Math.round(v * 100) / 100 : String(v)) : v);
        this.nonFinite.push({ at: Date.now(), id: String(n.id).slice(0, 80), force: !!n.force, level: n.level,
          x: r(x), y: r(y), z: r(z), vx: r(n.vx), vy: r(n.vy), vz: r(n.vz), fx: r(n.fx),
          fit: [r(n.fitX), r(n.fitY), r(n.fitZ)], hold: n.holdAt ? n.holdAt.map(r) : null,
          anchor: n.anchorPos ? n.anchorPos.map(r) : null, room: r(n.room), val: r(n.val),
          folding: this.folding.has(n.id), mode: this.layoutMode });
      }
      const fit = [n.fitX, n.fitY, n.fitZ];
      const to = fit.every(Number.isFinite) ? fit : [0, 0, 0];
      n.x = to[0]; n.y = to[1]; n.z = to[2];
      n.vx = 0; n.vy = 0; n.vz = 0;
      if (n.fx != null && !(Number.isFinite(n.fx) && Number.isFinite(n.fy) && Number.isFinite(n.fz))) {
        n.fx = undefined; n.fy = undefined; n.fz = undefined;
      }
      if (n.holdAt && !n.holdAt.every(Number.isFinite)) n.holdAt = undefined;
    }
  }

  /** Collision runs until this time (performance.now); see `draw`. */
  collideUntil = 0;
  /** Planted by the host-load check: collision on every tick, as before. */
  plantAlwaysCollide = false;
  /** The projected layout changed: collision spaces it for the next 3 s. */
  private collideSoon(): void { this.collideUntil = performance.now() + 3000; }

  /** Planted by G-97's check: projected chunks drawn away from their fit, `home` off. */
  plantScatter = false;

  /**
   * The lifecycle of every diff node through the stream, for the checks and
   * the reader's corner: when it was drawn, saved, folded into its root, and
   * when its chunk was placed by the fit (Addendum IX's order, stage by stage).
   */
  life = {
    nodes: new Map<string, { url: string; drawnAt: number; savedAt?: number; foldedAt?: number; cid?: string }>(),
    placed: new Map<string, { at: number; drawn: boolean; url: string }>(),
    folded_unopened: 0, moved: 0, replaced_force: 0,
  };

  /** Force nodes folding into their page's root right now (a 250 ms tween). */
  private folding = new Map<string, { t0: number; from: number[]; to: any; node: any }>();

  /**
   * SAVED nodes fold into their page's root: the projected page node, or --
   * a page not projected yet -- its own force-directed root. Drawn, they
   * travel into it over 250 ms (what "folding in" looks like); not drawn,
   * they simply go.
   */
  private foldIn(ids: Set<string>): void {
    this.motion.event("fold", { nodes: ids.size });
    if (!this.graph) return;
    const data: any = this.graph.graphData();
    const byId = new Map<string, any>(data.nodes.map((n: any) => [n.id, n]));
    const now = performance.now(), wall = Date.now();
    const at = new Set<string>();
    for (const id of ids) {
      const spec = this.forceSpecs.get(id);
      const n = byId.get(id);
      const l = this.life.nodes.get(id);
      if (l) l.foldedAt = wall;
      if (!spec || !spec.parent) continue;              // a root folds into nothing
      const root = this.projectedPage(spec.url, byId) || byId.get(`f:${spec.url}`);
      if (!n || !root || this.folding.has(id)) { at.add(id); continue; }
      this.folding.set(id, { t0: now, from: [n.x ?? 0, n.y ?? 0, n.z ?? 0], to: root, node: n });
    }
    if (at.size) this.redrawForce(at);
    if (!this.folding.size) return;
    const step = () => {
      const t = performance.now();
      const done = new Set<string>();
      for (const [id, f] of this.folding) {
        // 450 ms, like a glide: at 250 a fold's peak step crossed 10 units a frame
        // and the flight recorder read the pane's own animation as a teleport.
        const k = Math.min(1, (t - f.t0) / 450);
        const e = k * k * (3 - 2 * k);
        f.node.fx = f.from[0] + ((f.to.x ?? 0) - f.from[0]) * e;
        f.node.fy = f.from[1] + ((f.to.y ?? 0) - f.from[1]) * e;
        f.node.fz = f.from[2] + ((f.to.z ?? 0) - f.from[2]) * e;
        if (k >= 1) done.add(id);
      }
      for (const id of done) this.folding.delete(id);
      if (done.size) this.redrawForce(done);
      if (this.folding.size) window.requestAnimationFrame(step);
    };
    window.requestAnimationFrame(step);
  }

  /**
   * The stream's lifecycle, measured: how long each stage took, how many
   * nodes skipped a stage or ran out of order, and whether projected chunks
   * sit where the fit put them (in collider units). For checks and the MCP.
   */
  lifecycleState(url = ""): any {
    const q = (xs: number[], p: number) => { if (!xs.length) return null; const s2 = xs.slice().sort((a, b) => a - b); return Math.round(s2[Math.min(s2.length - 1, Math.floor(p * s2.length))]); };
    const rows = [...this.life.nodes.values()].filter((l) => !url || l.url === url);
    const saved = rows.filter((l) => l.savedAt);
    const drawnToSaved = saved.map((l) => l.savedAt! - l.drawnAt);
    const savedToFolded = saved.filter((l) => l.foldedAt).map((l) => l.foldedAt! - l.savedAt!);
    const foldedBeforeSaved = rows.filter((l) => l.foldedAt && (!l.savedAt || l.foldedAt < l.savedAt)).length;
    const savedNotFolded = saved.filter((l) => !l.foldedAt && Date.now() - l.savedAt! > 2000).length;
    const savedToPlaced: number[] = [];
    let placedBeforeSaved = 0, alreadyStored = 0;
    for (const l of saved) {
      const pl = l.cid ? this.life.placed.get(l.cid) : undefined;
      if (!pl) continue;
      // Placed before the node was even DRAWN: content the store held from an
      // earlier visit, re-drained -- not a stage run out of order.
      if (pl.at <= l.drawnAt) { alreadyStored++; continue; }
      if (pl.at < l.savedAt!) placedBeforeSaved++;
      else savedToPlaced.push(pl.at - l.savedAt!);
    }
    // Projected chunks: how far from the fit's position, in colliders.
    const off: number[] = [];
    let duplicates = 0;
    if (this.graph) {
      const relSize = this.graph.nodeRelSize(), media = this.media();
      const nodes = this.graph.graphData().nodes as any[];
      const drawnCids = new Set<string>();
      for (const n of nodes) {
        if (n.force || n.level === "page" || (url && n.url !== url) || !Number.isFinite(n.fitX)) continue;
        drawnCids.add(n.id);
        const c = drawnRadius(n, relSize, media) * COLLIDER_SAFETY + COLLIDER_MARGIN;
        off.push(Math.hypot(n.x - n.fitX, n.y - n.fitY, (n.z || 0) - (n.fitZ || 0)) / Math.max(c, 1e-6));
      }
      // A force node still drawn beside the stored node it became.
      for (const n of nodes) {
        if (!n.force) continue;
        const spec = this.forceSpecs.get(n.id);
        if (spec && spec.cid && drawnCids.has(spec.cid)) duplicates++;
      }
    }
    const offQ = (p: number) => { if (!off.length) return null; const s2 = off.slice().sort((a, b) => a - b); return Math.round(s2[Math.min(s2.length - 1, Math.floor(p * s2.length))] * 100) / 100; };
    return {
      drawn: rows.length, saved: saved.length, folded: rows.filter((l) => l.foldedAt).length,
      drawn_to_saved_ms: { p50: q(drawnToSaved, 0.5), p95: q(drawnToSaved, 0.95) },
      saved_to_folded_ms: { n: savedToFolded.length, p50: q(savedToFolded, 0.5), p95: q(savedToFolded, 0.95) },
      saved_to_placed_ms: { n: savedToPlaced.length, p50: q(savedToPlaced, 0.5), p95: q(savedToPlaced, 0.95) },
      out_of_order: { folded_before_saved: foldedBeforeSaved, saved_not_folded: savedNotFolded, placed_before_saved: placedBeforeSaved },
      already_stored: alreadyStored,
      projected_drawn: off.length, off_fit_colliders: { p50: offQ(0.5), p90: offQ(0.9), max: offQ(1) },
      force_beside_stored: duplicates,
      folded_unopened: this.life.folded_unopened, fit_moves: this.life.moved,
    };
  }

  /**
   * Remove every force node whose covering chunk the projector now draws.
   * Called when chunks arrive (a capture, the stream, a placement) and on a
   * slow timer that also notices a page being expanded or collapsed.
   */
  collapseCovered(): void {
    if (!this.graph || !this.forceSpecs.size) return;
    const drawn = new Set<string>(this.graph.graphData().nodes
      .filter((n: any) => !n.force).map((n: any) => n.id));
    const done = new Set<string>();
    const now = Date.now();
    for (const [id, spec] of this.forceSpecs) {
      if (spec.cid && !spec.stale && drawn.has(spec.cid)) { done.add(id); continue; }
      // Not every sensor chunk is stored (the store drops what draws
      // nothing), and not every stored chunk gets a vector. A pending node
      // that nothing has covered in 20 s, or that was covered and never
      // placed in 90 s, is not coming: it goes, and is counted.
      const age = now - (spec.born ?? now);
      if (spec.parent && ((!spec.cid && age > 20000) || age > 90000)) {
        done.add(id);
        this.forceTimedOut++;
      }
    }
    const key = [...this.expandedUrls()].sort().join("\n");
    if (done.size || key !== this.lastExpanded) this.redrawForce(done);
    if (!this.settleTimer && this.forceSpecs.size) {
      this.settleTimer = window.setInterval(() => {
        if (!this.forceSpecs.size) { window.clearInterval(this.settleTimer); this.settleTimer = 0; return; }
        this.collapseCovered();
      }, 1500);
    }
  }

  /**
   * Drop `collapse` from the drawn force nodes, re-hang what remains on the
   * current page nodes, and put back any force node a redraw removed.
   */
  private redrawForce(collapse: Set<string> = new Set()): void {
    if (!this.graph) return;
    for (const id of collapse) {
      const cid = this.forceSpecs.get(id)?.cid;
      if (cid) this.collapsedTo.set(id, cid);
      this.forceSpecs.delete(id);
    }
    if (this.collapsedTo.size > 20000) this.collapsedTo.clear();
    const data: any = this.graph.graphData();
    const end = (x: any) => (typeof x === "object" && x ? x.id : x);
    let nodes = data.nodes.filter((n: any) => !(n.force && !this.forceSpecs.has(n.id)));
    let links = data.links.filter((l: any) => !l.force);
    const byId = new Map<string, any>(nodes.map((n: any) => [n.id, n]));
    // A page root is dropped once its page is drawn by the projector.
    for (const [id, spec] of this.forceSpecs) {
      if (!spec.parent && this.projectedPage(spec.url, byId) && byId.has(id)) {
        nodes = nodes.filter((n: any) => n.id !== id);
        byId.delete(id);
      }
    }
    const expanded = this.expandedUrls(byId);
    // A force ROOT whose chunks have all collapsed, on a page the projector
    // now draws chunks for, has nothing left to hold: it goes too (it was
    // left behind as a lone dot, "1 in the force tree").
    const pendingChunkUrls = new Set([...this.forceSpecs.values()]
      .filter((x) => x.parent).map((x) => x.url));
    for (const [id, spec] of [...this.forceSpecs]) {
      if (!spec.parent && !pendingChunkUrls.has(spec.url) && expanded.has(spec.url)) {
        this.forceSpecs.delete(id);
        nodes = nodes.filter((n: any) => n.id !== id);
        byId.delete(id);
      }
    }
    const visible = (url: string) => this.layoutMode !== "projector" || expanded.has(url)
      || !this.projectedPage(url, byId);
    // Force nodes of collapsed pages are not drawn after the fit.
    nodes = nodes.filter((n: any) => !n.force || visible(n.url));
    for (const id of [...byId.keys()]) {
      const n = byId.get(id);
      if (n.force && !visible(n.url)) byId.delete(id);
    }
    for (const [id, spec] of this.forceSpecs) {
      if (!spec.parent && this.projectedPage(spec.url, byId)) continue;
      if (!visible(spec.url)) continue;
      if (!byId.has(id)) {
        const n: any = { id, level: spec.parent ? "chunk" : "page", name: spec.title || id,
                         url: spec.url, members: 1, tokens: 0, force: true,
                         val: spec.parent ? 1 : 3,
                         color: spec.parent ? "#9aa0a6" : "#8ab4f8" };
        nodes.push(n);
        byId.set(id, n);
      }
    }
    // One page-node lookup per page, not one scan per force node.
    const pageByUrl = new Map<string, any>();
    for (const n of byId.values()) {
      if (!n.force && n.level === "page" && n.url && !pageByUrl.has(n.url)) pageByUrl.set(n.url, n);
    }
    for (const [id, spec] of this.forceSpecs) {
      if (!spec.parent || !byId.has(id)) continue;
      const to = this.parentFor(spec.parent, spec.url, byId, pageByUrl.get(spec.url) || null);
      if (to && to !== id) links.push({ source: to, target: id, force: true });
    }
    // Place a returning node beside its parent rather than at the origin.
    for (const l of links) {
      const t = byId.get(end(l.target)), s = byId.get(end(l.source));
      if (t && s && t.x === undefined) {
        t.x = (s.x ?? 0) + (Math.random() - 0.5) * 6;
        t.y = (s.y ?? 0) + (Math.random() - 0.5) * 6;
        t.z = (s.z ?? 0) + (Math.random() - 0.5) * 6;
      }
    }
    this.holdAll(nodes, new Set());
    this.graph.graphData({ nodes, links });
    if (this.layoutMode === "projector") this.treeSpring();
    this.graph.d3ReheatSimulation?.();
    this.lastExpanded = [...expanded].sort().join("\n");
  }

  /** Pending force nodes dropped because nothing ever covered or placed them. */
  forceTimedOut = 0;

  /** Pages the reader opened in the graph themselves -- never auto-collapsed. */
  openedByReader = new Set<string>();

  /**
   * The reader left `url` and its last diff is settled: its chunk nodes fold
   * back into its page node (S-6). Chunk nodes of pages browsed and left used
   * to stay drawn for good -- 52, then 122, then 280 of them after five pages.
   * A page the reader opened in the graph stays open, and a chunk held by an
   * open billboard (a pin) stays drawn.
   */
  collapsePage(url: string): void {
    this.touchActive(url);
    this.motion.event("collapse", { url: url.slice(-50) });
    if (!this.graph || !url || this.openedByReader.has(url)) return;
    if (this.layoutMode !== "projector") return;
    const data: any = this.graph.graphData();
    const keep = new Set<string>(this.billboards.keys() as any);
    const gone = new Set<string>(data.nodes
      .filter((n: any) => n.url === url && n.level !== "page" && !keep.has(n.id))
      .map((n: any) => n.id));
    if (!gone.size) return;
    const end = (x: any) => (typeof x === "object" && x ? x.id : x);
    const next = {
      nodes: data.nodes.filter((n: any) => !gone.has(n.id)),
      links: data.links.filter((l: any) => !gone.has(end(l.source)) && !gone.has(end(l.target))),
    };
    this.collideSoon();
    const pageNode = next.nodes.find((n: any) => !n.force && n.level === "page" && n.url === url);
    if (pageNode && pageNode.fullVal !== undefined && pageNode.val !== pageNode.fullVal) {
      const was = pageNode.val;
      pageNode.val = pageNode.fullVal;
      this.rescaleObject(pageNode, was);
    }
    this.graph.graphData(next);
    this.graph.d3ReheatSimulation?.();
    for (const [id, spec] of [...this.forceSpecs]) if (spec.url === url) this.forceSpecs.delete(id);
    this.collapsed.push({ at: Date.now(), url, nodes: gone.size });
    if (this.collapsed.length > 50) this.collapsed.shift();
  }

  /** The pending diff of a page the reader is leaving: gone at once. */
  dropForce(url: string): void {
    // Before the first fit the force trees ARE the picture of every page
    // scanned: leaving one must not wipe it (G-89 C4 saw one tree at a time).
    if (this.layoutMode !== "projector") return;
    let any = false;
    for (const [id, spec] of [...this.forceSpecs]) {
      if (spec.url === url) { this.forceSpecs.delete(id); any = true; }
    }
    if (any) this.redrawForce();
  }

  /** Force nodes known not to be pending (never stored): gone. */
  dropForceIds(ids: string[]): void {
    // Before the fit a never-stored chunk is still part of the scan's tree.
    if (this.layoutMode !== "projector") return;
    let any = false;
    for (const id of ids) if (this.forceSpecs.delete(id)) any = true;
    if (any) this.redrawForce();
  }

  /** Every collapse, for the harness: when, which page, how many nodes. */
  collapsed: { at: number; url: string; nodes: number }[] = [];

  /** A collapsed force node -> the projected chunk it collapsed into. */
  private collapsedTo = new Map<string, string>();

  /** Which pages were expanded at the last force redraw. */
  private lastExpanded = "";

  /**
   * The plugin now points at a DIFFERENT store: what is drawn belongs to the
   * old one. Emptied, and back to `empty`, so the next picture -- a force
   * tree from the first drain, or the new store's fit -- starts from nothing
   * (`G-89` C1). Open billboards belong to the old store too and go with it.
   */
  resetForStore(why: string): void {
    for (const id of [...this.billboards.keys()]) this.closeBillboard(id as string);
    if (this.graph) this.graph.graphData({ nodes: [], links: [] });
    this.projEpoch = -1;
    this.projSeq = 0;
    this.reopen.clear();
    this.forceStats = { drains: 0, added: 0, removed: 0, reparented: 0, ms: [], toScene: [],
                        jitter: [], sized: [] };
    this.forceSpecs.clear();
    this.layoutMode = "force";            // so setMode records the change
    this.setMode("empty", why);
  }

  /** Set by `onOpen`: the caption while the force tree is what is drawn. */
  private forceCaption: (() => void) | null = null;

  /** The projector's state, in the caption's words. */
  private projectorCaption(): string {
    const ps = this.projStatus;
    if (this.projEpoch < 0 || !ps) return " · legacy fit";
    const refit = ps.refit_at
      ? ` · refits at ${ps.refit_at} chunks` + (ps.chunks_now ? ` (now ${ps.chunks_now})` : "")
      : "";
    const queue = ps.queue ? ` · ${ps.queue} queued` : "";
    // The epoch is an identity (milliseconds), not a count; say WHEN.
    const when = new Date(this.projEpoch).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return ` · chunk projector: UMAP on a ${ps.fit_sample ?? "?"}-chunk sample (fit ${when}) · ` +
           `${ps.projected ?? "?"} chunks placed by transform` +
           `${refit}${queue}${ps.fitting ? " · refitting" : ""}`;
  }

  /**
   * Apply what the chunk projector placed since this pane last looked.
   *
   * * a chunk the pane draws that the stream re-placed moves to its new fit
   *   position (its text changed, so its meaning did);
   * * a chunk on a page the pane has OPEN that it does not draw yet is
   *   placed -- this is how a page's late-embedded chunks arrive without
   *   the reader doing anything;
   * * a chunk the stream says is gone is removed, with its links;
   * * a page whose chunks changed moves to the new transform of its mean;
   * * a new epoch -- the projector refit at 2x growth -- redraws once, and
   *   re-places every chunk that was open, so the reader keeps what they
   *   had unfolded, in the new fit's coordinates.
   */
  private async pullDelta(reload: () => Promise<void>): Promise<void> {
    if (!this.graph || this.projEpoch < 0 || this.pulling) return;
    this.pulling = true;
    try {
      const d: any = await this.sidecar.projectorDelta(this.projSeq, this.projEpoch);
      if (!d) return;
      if (d.status) this.projStatus = d.status;
      if (d.reload) {
        // Nothing to redraw INTO until the new fit is complete; asking for a
        // layout meanwhile is what produced a reload a second.
        if (d.status?.fitting || !d.status?.fitted_chunks) return;
        const before: any = this.graph.graphData();
        for (const n of before.nodes) {
          if (n.level !== "page" && !String(n.id).startsWith("path:")) {
            this.reopen.add(String(n.id));
          }
        }
        this.streamApplied.reloads++;
        await reload();                  // re-places `reopen` once it draws
        return;
      }
      if (typeof d.seq !== "number" || d.seq === this.projSeq) {
        this.refreshCaption();
        return;
      }
      this.projSeq = d.seq;
      const data: any = this.graph.graphData();
      const byId = new Map<string, any>(data.nodes.map((n: any) => [n.id, n]));
      const openUrls = new Set<string>(data.nodes
        .filter((n: any) => n.level !== "page").map((n: any) => n.url));
      let moved = 0, gone = 0, pages = 0, structural = false;
      const toPlace: string[] = [];
      for (const [cid, got] of Object.entries<any>(d.chunks || {})) {
        const node = byId.get(cid);
        if (node && got.pos) {
          // The fit's new coordinates ARE the node's place (stage 7: an
          // online update or a refit moves projected chunks; `home` carries
          // them there, collision only spacing them).
          node.fitX = got.pos[0]; node.fitY = got.pos[1]; node.fitZ = got.pos[2] * DEPTH;
          node.projX = node.fitX; node.projY = node.fitY; node.projZ = node.fitZ;
          this.glide(node, [node.fitX, node.fitY, node.fitZ]);
          this.life.moved++;
          moved++;
        } else if (!node && got.url && openUrls.has(got.url)) {
          toPlace.push(cid);
        }
      }
      const goneIds = new Set<string>((d.gone || []).filter((c: string) => byId.has(c)));
      if (goneIds.size) {
        data.nodes = data.nodes.filter((n: any) => !goneIds.has(n.id));
        data.links = data.links.filter((l: any) =>
          !goneIds.has(l.source?.id ?? l.source) && !goneIds.has(l.target?.id ?? l.target));
        gone = goneIds.size;
        structural = true;
      }
      for (const [url, got] of Object.entries<any>(d.pages || {})) {
        if (!got?.pos) continue;
        const node = byId.get("page:" + url);
        if (node) {
          node.fitX = got.pos[0]; node.fitY = got.pos[1]; node.fitZ = got.pos[2] * DEPTH;
          node.anchorPos = [got.pos[0], got.pos[1], got.pos[2] * DEPTH];
          this.glide(node, [node.fitX, node.fitY, node.fitZ]);
        } else {
          const members = got.projected ?? 1;
          const built = this.nodeFrom({ cid: "page:" + url, url, title: url,
            level: "page", pos: got.pos, members, rank: 0, chars: 0, tokens: 0,
            val: Math.max(1, Math.sqrt(Math.max(members, 1))),
            hsv: got.hsv } as any);
          built.anchorPos = [built.fitX, built.fitY, built.fitZ];
          built.room = Math.max(6, Math.cbrt(Math.max(built.val ?? 1, 1e-9)) * 2.5);
          // A new array, never pushed in place (D-38; see `addEdges`).
          data.nodes = data.nodes.concat([built]);
          structural = true;
        }
        pages++;
      }
      if (structural) this.graph.graphData(data);
      if (moved || gone || pages || structural) { this.collideSoon(); this.graph.d3ReheatSimulation(); }
      let added = 0;
      if (toPlace.length) {
        const trace = profiler().begin("stream", [...openUrls][0] || "");
        profiler().fact(trace, "stream_cids", toPlace.length);
        const got: any = await this.sidecar.place(toPlace);
        if (got?.nodes?.length) added = this.absorb(got.nodes, got.edges, trace.id).added;
        else profiler().finish(trace, "nothing_placed");
      }
      const a = this.streamApplied;
      a.deltas++; a.moved += moved; a.added += added; a.gone += gone;
      a.pages += pages; a.lastAt = Date.now();
      this.refreshCaption();
    } catch {
      // A missed delta is re-asked for next second from the same `since`.
    } finally {
      this.pulling = false;
    }
  }

  private refreshCaption(): void {
    if (!this.captionTail) return;
    this.sayCounts();
  }

  /**
   * One line, always. The caption is rebuilt from its parts on every
   * refresh; it used to be edited in place with a regex, and when the text
   * it looked for was renamed the regex stopped matching and a copy was
   * appended each second -- measured, a bar 12,620 px tall covering the
   * whole projector. The full text stays readable as a tooltip.
   */
  private setStatus(text: string): void {
    if (!this.statusEl) return;
    this.statusEl.setText(text);
    this.statusEl.setAttr("title", text);
  }

  async onClose() {
    // `_destructor` releases the WebGL context. Without it, reopening the
    // pane a few times exhausts the browser's context limit and every graph
    // after that renders black.
    // Before `_destructor`: the observer's callback touches `graph`, and a
    // resize landing between the teardown and the disconnect would call into a
    // destroyed renderer.
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.stopBatch();
    this.graph?._destructor?.();
    this.graph = null;
  }

  /**
   * A sprite carrying the chunk's first picture, or null for a plain node.
   *
   * Returning null rather than a blank sprite is what makes 3d-force-graph
   * fall back to its own sphere, so a chunk with no picture is still drawn --
   * and drawn in the colour the fit gave it, which a transparent sprite would
   * have replaced with nothing.
   *
   * The texture loads asynchronously and the sprite exists before it
   * arrives, which is why the material starts opaque and coloured. An image
   * that never loads leaves a tile rather than an invisible node, so a dead
   * asset host cannot silently empty the graph.
   */
  /** A streaming node: a small translucent sphere in its own colour. */
  /** One geometry for every streaming node, and one material per colour
   *  (G-90: a new geometry and material per node cost a 356-node drain its
   *  p95 of 52 ms in the graph). Scaled per node, not rebuilt. */
  private static streamGeo: any = null;
  private static streamMats = new Map<string, any>();
  private static ringMat: any = null;
  private streamingSphere(node: any): any {
    const r = node.level === "page" ? STREAM.RADIUS * 1.6 : STREAM.RADIUS;
    if (!GraphView.streamGeo) GraphView.streamGeo = new THREE.SphereGeometry(1, 12, 10);
    const colour = node.color || "#9aa0a6";
    let mat = GraphView.streamMats.get(colour);
    if (!mat) {
      mat = new THREE.MeshLambertMaterial({ color: new THREE.Color(colour), transparent: true,
                                            opacity: STREAM.OPACITY, depthWrite: false });
      GraphView.streamMats.set(colour, mat);
    }
    const mesh = new THREE.Mesh(GraphView.streamGeo, mat);
    mesh.scale.setScalar(r);
    (mesh as any).__streaming = true;
    return mesh;
  }

  private billboard(node: any, relSize: number): any {
    const src = node?.image?.src;
    if (!src) return null;
    const material = new THREE.SpriteMaterial({
      color: new THREE.Color(node.color || "#888"),
      transparent: true,
      opacity: 0.95,
    });
    const sprite = new THREE.Sprite(material);
    const size = billboardEdge(node, relSize);
    sprite.scale.set(size, size, 1);

    this.texture(src)
      .then((dataUrl) => {
        if (!dataUrl) return;
        // An `<img>` this method owns, rather than `THREE.TextureLoader`.
        //
        // The loader silently declined every SVG: 66 of 110 billboards had a
        // picture and the 44 without were exactly the 43 SVG sources plus one
        // video, while the very same data url loaded in an `<img>` at its
        // right size. Its error callback is a callback nobody was passing, so
        // the failure had no way to reach anyone.
        //
        // Building the texture from an image directly is what the loader does
        // anyway, and this way the failure path is one we can see.
        const img = new Image();
        img.onload = () => {
          const texture = new THREE.Texture(img);
          texture.colorSpace = THREE.SRGBColorSpace;
          texture.needsUpdate = true;
          material.map = texture;
          node.imgLoaded = true;           // for the harness: the picture is ON the node
          // White once a picture is on it: the colour was standing in for the
          // image, and leaving it would tint every photograph.
          material.color = new THREE.Color(0xffffff);
          material.needsUpdate = true;
        };
        img.onerror = () => {
          console.warn("domvec: billboard image would not decode", src);
        };
        img.src = dataUrl;
      })
      .catch(() => {
        // Left as the coloured tile it already is. A dead asset host and an
        // empty corpus must not look the same from the pane.
      });
    return sprite;
  }

  /**
   * The picture as a `data:` url, fetched the one way that works here.
   *
   * A WebGL texture has to be CORS-clean, and most hosts serve images without
   * an `Access-Control-Allow-Origin` header -- they were never expecting to
   * be read by a canvas. Measured against this corpus's own hosts: of eight,
   * two sent CORS and six served the picture happily to an `<img>` and
   * refused it to a texture. That is why 27 of 110 billboards had a picture
   * and the rest were coloured tiles, and no amount of retrying would have
   * fixed it -- the browser is enforcing a rule the host declined to waive.
   *
   * `requestUrl` is Obsidian's own HTTP client and runs outside the renderer,
   * so it is not subject to CORS at all. The bytes come back, become a
   * `data:` url, and a `data:` url is same-origin -- so the texture is clean
   * by construction.
   *
   * Only reached when the reader has remote media on. This does not widen
   * what gets fetched; it makes what was already being fetched usable.
   */
  private async texture(src: string): Promise<string | null> {
    const cached = GraphView.textures.get(src);
    if (cached !== undefined) return cached;
    let out: string | null = null;
    try {
      const res = await requestUrl({ url: src, method: "GET" });
      const bytes = new Uint8Array(res.arrayBuffer);
      const type = (res.headers?.["content-type"] || "").split(";")[0]
        || guessType(src);
      if (bytes.byteLength && bytes.byteLength <= MAX_TEXTURE_BYTES) {
        if (type === "image/svg+xml" || /\.svg($|\?)/i.test(src)) {
          out = svgDataUrl(new TextDecoder().decode(bytes));
        } else {
          let binary = "";
          for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
          }
          out = `data:${type || "image/png"};base64,${btoa(binary)}`;
        }
      }
    } catch {
      out = null;
    }
    // Negative results are cached too. A host that refuses once will refuse
    // for every node pointing at it, and a graph re-fit would otherwise ask
    // again for each.
    GraphView.textures.set(src, out);
    return out;
  }

  /**
   * Add edges the server supplied, resolving their endpoints ourselves.
   *
   * `forceLink` rewrites `source`/`target` from ids to node objects when it
   * initialises, and it has already initialised by the time anything is
   * added live -- so an edge handed in as a pair of strings after that is
   * never resolved and never drawn. Looking the nodes up here is what makes
   * a late edge behave like one that was there at boot.
   */
  /**
   * Say what is on screen NOW, after the picture has been mutated.
   *
   * The load-time caption describes the fit, which does not change; the
   * counts do, on every unfold, every hit list and every live capture. A bar
   * that keeps reporting the load-time numbers is worse than one with no
   * numbers, because it is the thing a reader checks the pane against.
   */
  private sayCounts(): void {
    if (!this.statusEl || !this.graph) return;
    const d: any = this.graph.graphData();
    const opened = d.nodes.filter((n: any) => n.unfolded).length;
    const parts = [`${d.nodes.length} nodes`, `${d.links.length} links`];
    if (opened) parts.push(`${opened} opened`);
    this.setStatus(`${parts.join(" · ")} · ${this.captionTail}${this.projectorCaption()}`);
  }

  private addEdges(data: any, edges?: { source: string; target: string }[]) {
    if (!edges || !edges.length) return 0;
    const byId = new Map<string, any>(data.nodes.map((n: any) => [n.id, n]));
    const have = new Set(data.links.map(
      (l: any) => `${l.source?.id ?? l.source} ${l.target?.id ?? l.target}`));
    let added = 0;
    const fresh: any[] = [];
    for (const edge of edges) {
      const source = byId.get(edge.source);
      const target = byId.get(edge.target);
      if (!source || !target || source === target) continue;
      const key = `${edge.source} ${edge.target}`;
      if (have.has(key)) continue;
      have.add(key);
      fresh.push({ source, target });
      added++;
    }
    // NEVER in place (D-38): the simulation iterates this very array, and its
    // forces' per-item arrays (link strengths and distances, collision radii)
    // are rebuilt only at the graph's deferred digest -- a frame ticked in
    // between read the grown array with the old weights, `l * undefined`
    // wrote NaN velocities, and collision's octree looped until the renderer
    // died of out-of-memory (paused in `add3 <- addAll3 <- octree <- collide`,
    // the NaN first written by the link force). A NEW array; the digest adopts it.
    if (added) data.links = data.links.concat(fresh);
    if (added) this.treeOnly(data);
    return added;
  }

  /** Planted by G-94's check: every containment edge kept (the web). */
  plantWeb = false;

  /**
   * A drawn page is a SIMPLE TREE (2026-09-27: "the densely packed maybe not
   * tree structures should be less interconnected and a simple tree").
   * Containment is transitive -- a chunk is contained by its parent, its
   * grandparent and its page -- and every one of those edges was drawn, so
   * each chunk hung from several nodes and an open page read as a web. Each
   * node keeps ONE incoming edge: from the deepest container drawn (one that
   * no other container of it contains), chunks preferred over the page.
   */
  private treeOnly(data: any): void {
    if (this.plantWeb) return;
    const end = (x: any) => (typeof x === "object" && x ? x.id : x);
    const byId = new Map<string, any>(data.nodes.map((n: any) => [n.id, n]));
    const into = new Map<string, any[]>();
    const outOf = new Map<string, Set<string>>();
    for (const l of data.links) {
      if (l.force) continue;
      const s = end(l.source), t = end(l.target);
      (into.get(t) || into.set(t, []).get(t)!).push(l);
      (outOf.get(s) || outOf.set(s, new Set()).get(s)!).add(t);
    }
    const drop = new Set<any>();
    for (const [t, links] of into) {
      if (links.length < 2) continue;
      const sources = links.map((l) => end(l.source));
      const isPage = (id: string) => (byId.get(id)?.level === "page");
      // Deepest: a source that no other source of t contains.
      const deepest = sources.filter((s) => !isPage(s) && !sources.some((o) => o !== s && outOf.get(s)?.has(o)));
      const keep = deepest[0] ?? sources.find((s) => !isPage(s)) ?? sources[0];
      for (const l of links) if (end(l.source) !== keep) drop.add(l);
    }
    if (drop.size) data.links = data.links.filter((l: any) => !drop.has(l));
  }

  /**
   * Open a page to exactly what the reader has scrolled to (`G-55`, `G-56`).
   *
   * The two requirements are one mechanism. `G-56` says only the chunks
   * matching the latest debounced query are drawn live inside their unfolded
   * page; `G-55` says how far a page unfolds follows how many results the
   * reader has scrolled through. The overlay's hit list is both of those
   * things at once -- it IS the matching set, and it grows as they scroll --
   * so the map opens where attention actually went rather than where someone
   * clicked once.
   *
   * Structural unravelling (`G-54`) is what a click does with no query
   * running. This is what it does with one.
   */
  async showHits(url: string, cids: string[]): Promise<void> {
    if (!this.graph || !url) return;
    const data: any = this.graph.graphData();
    const known = new Set(data.nodes.map((n: any) => n.id));
    const wanted = cids.filter((cid) => cid && !known.has(cid));
    // The page is OPEN whether or not its hits needed placing. Landing on a
    // page now places all of it, so a query scoped to the page being read
    // finds every hit already drawn -- and this returned before marking the
    // hub, leaving the page drawn as closed with its hits hanging off it.
    const openHub = data.nodes.find((n: any) => n.id === "page:" + url);
    if (openHub && cids.some((cid) => known.has(cid))) {
      openHub.unfolded = true;
      this.sayCounts();
    }
    if (!wanted.length) return;

    const placed = await this.sidecar.place(wanted);
    const nodes = (placed && (placed.nodes as LayoutNode[])) || [];
    if (!nodes.length) return;

    const fresh: any = this.graph.graphData();
    // The page node STAYS, and for the same reason `unfoldNode` keeps its
    // hub: it is what the hits hang from. Removing it left the matching
    // chunks as an unconnected scatter with no way to see which page they
    // came out of.
    const pageId = "page:" + url;
    const hub = fresh.nodes.find((n: any) => n.id === pageId);
    if (hub) hub.unfolded = true;
    const have = new Set(fresh.nodes.map((n: any) => n.id));
    const drawn: string[] = [];
    const built: any[] = [];
    for (const node of nodes) {
      if (!node || !node.cid || have.has(node.cid)) continue;
      built.push(this.nodeFrom(node));
      drawn.push(node.cid);
    }
    // A new array, never pushed in place (D-38; see `addEdges`).
    if (built.length) fresh.nodes = fresh.nodes.concat(built);
    const star = hub
      ? drawn.map((cid) => ({ source: pageId, target: cid }))
      : [];
    this.addEdges(fresh, [
      ...star,
      ...((placed?.edges as { source: string; target: string }[]) || []),
    ]);
    this.graph.graphData(fresh);
    this.graph.d3ReheatSimulation();
    this.sayCounts();
    void this.drawContainment();
  }

  /**
   * Unravel one node into what is under it (`G-54`), KEEPING it (`G-6`).
   *
   * It used to be removed, on the reasoning that it no longer stood for
   * anything a reader could not see. That reasoning cost the picture every
   * edge it had. Containment runs parent to child and the branches an
   * unfolding returns are disjoint subtrees, so the only containment edges
   * this step reveals are the ones from the parent to each branch -- and
   * removing the parent deletes all of them. Measured on RFC 9110 with the
   * parent gone: 26 nodes, **0 edges**, against the 31 and 30 the PRD
   * recorded when it was still there.
   *
   * So the unfolded node stays as the HUB of what it opened into. It is
   * marked `unfolded` so it draws as an opened container rather than as a
   * page still claiming to stand for its contents.
   */
  /**
   * Show which node the reader is hovering in the browser (`G-38`).
   *
   * A ring, not a recolour: colour is the fit's own six-dimensional
   * statement about the chunk (`D-1`), and overwriting it to signal a
   * transient hover would be destroying a measurement to draw a cursor. The
   * previous highlight is always cleared first, so the state is "at most one
   * node is hovered" rather than a trail of them.
   */
  highlightChunk(cid: string, url = ""): void {
    if (!this.graph) return;
    const data: any = this.graph.graphData();
    // The chunk's own node if it is drawn; otherwise the PAGE node standing
    // for it. At the default level the picture is 96 pages and no chunk node
    // exists at all, so ringing only exact ids would light nothing up for
    // every hover until the reader had already unfolded that page -- which
    // is the one case they least need the correspondence drawn.
    let target = cid ? data.nodes.find((n: any) => n.id === cid) : null;
    if (!target && cid && url) {
      target = data.nodes.find(
        (n: any) => n.level === "page" && n.url === url);
    }
    let changed = false;
    for (const n of data.nodes) {
      const want = !!target && n === target;
      if (!!n.hovered !== want) { n.hovered = want; changed = true; }
    }
    if (changed) this.graph.nodeColor(this.graph.nodeColor());
    // A streaming node is its own translucent mesh: ring it by its material.
    for (const n of data.nodes) {
      const obj: any = n.force ? (n as any).__threeObj : null;
      if (obj && obj.__streaming) {
        // Materials are shared: the ring swaps in its own, never recolours one.
        if (n.hovered) {
          if (!GraphView.ringMat) GraphView.ringMat = new THREE.MeshLambertMaterial({ color: new THREE.Color("#ffffff"),
            transparent: true, opacity: 0.9, depthWrite: false });
          obj.material = GraphView.ringMat;
        } else {
          obj.material = GraphView.streamMats.get(n.color || "#9aa0a6") || obj.material;
        }
      }
    }
  }

  /**
   * Open a chunk's panel as a billboard IN the projector (`G-57`).
   *
   * The panel is already generated and already in the store; what changes is
   * where it opens. Taking over an Obsidian pane put the thing a reader
   * clicked on the far side of the workspace from the picture they clicked
   * it in, and made the two representations compete for the same screen.
   *
   * **Anchored, then pinned.** It follows its node while the camera moves --
   * that is what makes it a billboard rather than a dialog -- until the
   * reader drags it, after which it stays where they put it. Dragging is how
   * a reader says "keep this where I can see it", and a panel that snapped
   * back would be arguing with them.
   */
  async openBillboard(node: any, fromBrowser = false): Promise<void> {
    if (!node || !node.id || !this.graph) return;
    const existing = this.billboards.get(node.id);
    if (existing) {
      // Asked for by the browser -- a pin, or a click on its card in the
      // side panel: shown, and expanded if it had been minimized.
      if (fromBrowser) { existing.fromBrowser = true; this.setMinimized(existing, false); return; }
      // A second click closes it -- unless the browser's markdown side is
      // holding it open, in which case that side is where it closes.
      if (existing.fromBrowser) return;
      this.closeBillboard(node.id);
      return;
    }
    if (!this.billboardLayer) {
      const host = this.canvasEl || this.contentEl;
      this.billboardLayer = host.createDiv({ cls: "domvec-bb-layer" });
    }
    const el = this.billboardLayer.createDiv({ cls: "domvec-bb" });
    const head = el.createDiv({ cls: "domvec-bb-head" });
    head.setText(String(node.name || node.id).slice(0, 44));
    // Minimize: down to the title bar, the chunk still open (2026-09-26).
    const min = head.createSpan({ cls: "domvec-bb-min" });
    min.setText("\u2013");
    min.setAttr("aria-label", "minimize");
    min.onpointerdown = (e: PointerEvent) => e.stopPropagation();
    min.onclick = (e: MouseEvent) => {
      e.stopPropagation();
      const en: any = this.billboards.get(node.id);
      if (en) this.setMinimized(en, !en.minimized);
    };
    const close = head.createSpan({ cls: "domvec-bb-close" });
    close.setText("\u00d7");
    close.onpointerdown = (e: PointerEvent) => e.stopPropagation();
    // The x takes the billboard out of the 3D view and nothing else: a
    // pinned chunk stays pinned -- its card in the browser's side panel and
    // its outline on the page -- and clicking that card brings the billboard
    // back (2026-09-26; it used to let go of all three).
    close.onclick = (e: MouseEvent) => {
      e.stopPropagation();
      this.closeBillboard(node.id);
    };
    const body = el.createDiv({ cls: "domvec-bb-body" });
    body.setText("\u2026");

    const entry: any = { el, node, pinned: false, surface: null, fromBrowser, minimized: false };
    this.billboards.set(node.id, entry);
    this.positionBillboard(entry);
    this.startBillboardLoop();

    // Dragging pins it. Pointer events rather than mouse, so a drag that
    // leaves the pane still ends.
    head.onpointerdown = (down: PointerEvent) => {
      down.preventDefault();
      head.setPointerCapture(down.pointerId);
      const box = el.getBoundingClientRect();
      const host = (this.billboardLayer as HTMLElement).getBoundingClientRect();
      const dx = down.clientX - box.left;
      const dy = down.clientY - box.top;
      const move = (m: PointerEvent) => {
        entry.pinned = true;
        el.style.left = `${m.clientX - host.left - dx}px`;
        el.style.top = `${m.clientY - host.top - dy}px`;
      };
      const up = () => {
        head.removeEventListener("pointermove", move);
        head.removeEventListener("pointerup", up);
      };
      head.addEventListener("pointermove", move);
      head.addEventListener("pointerup", up);
    };

    // **The chunk's rendered shadow-DOM form (`G-77`)** -- the same
    // `ChunkSurface` a note fence mounts, forced to its interactive form: the
    // distilled HTML in an open shadow root. It replaced both a text-only
    // list of lines here and the separate chunk pane; the markdown form is
    // the browser's markdown side.
    body.empty();
    if (node.level === "page" || node.level === "path") {
      body.setText("a page stands for its chunks -- click to unravel it");
      return;
    }
    // The chunk as the browser draws it (D-36), when the page gave one --
    // asked for NOW if its page is the one open in the browser cell.
    const ask = this.snapshotFor || ((cid: string, url: string) => {
      const b: any = this.app.workspace.getLeavesOfType("domvec-browser-view")[0]?.view;
      return b && typeof b.snapshotChunk === "function" ? b.snapshotChunk(cid, url) : Promise.resolve(false);
    });
    if (!getSnapshot(node.id)) {
      try { await ask(node.id, node.url || ""); } catch { /* keep the distilled form */ }
    }
    if (this.mountSnapshot(entry, body)) return;
    const surface = new ChunkSurface(body, node.id, this.surfaceHost,
                                     { interactive: true });
    entry.surface = surface;
    this.addChild(surface);
  }

  /**
   * An open page's chunk nodes sized to FIT its neighbourhood (2026-09-27:
   * "a lot of it is way too far from the original set of nodes"). The
   * projector draws a page's chunks within 0.45x the distance to the nearest
   * other page; drawn at full size, 88 chunks and their colliders could not
   * fit there, the collision pushed them out to 1.1-1.8x that distance, and
   * each page became a ball engulfing its neighbours. n spheres of radius r
   * pack a sphere of radius R when r ~ R * (0.6 / n)^(1/3), and the collider
   * is the drawn radius x COLLIDER_SAFETY plus its margin.
   *
   * **Sizes only.** Where a projected chunk is drawn is its UMAP position
   * (Addendum IX, stage 5: "a projection REPLACES the force position; a light
   * force pass afterwards only keeps collision spacing"). A geometric layout
   * here -- a sunflower disc, then a radial tree, then a force-seeded tree --
   * replaced the fit for every open page, and "I'm honestly unsure if the UMAP
   * layouts are being followed at all" (2026-09-28) was right: they were not.
   */
  private fitChunkSizes(data: any): void {
    if (!this.graph || this.plantBigChunks) return;
    this.collideSoon();
    const relSize = this.graph.nodeRelSize(), media = this.media();
    const pages = data.nodes.filter((n: any) => !n.force && n.level === "page" && Number.isFinite(n.fitX ?? n.x));
    // A page an earlier open page had moved aside goes back to its fit.
    for (const q of pages) {
      if (q.homeFit) {
        [q.fitX, q.fitY, q.fitZ] = q.homeFit;
        if (q.homeAnchor) q.anchorPos = q.homeAnchor;
        q.homeFit = undefined; q.homeAnchor = undefined;
      }
    }
    const at = (n: any) => [n.fitX ?? n.x, n.fitY ?? n.y, n.fitZ ?? n.z ?? 0];
    const byUrl = new Map<string, any[]>();
    for (const n of data.nodes) {
      if (n.force || n.level === "page" || !n.url) continue;
      (byUrl.get(n.url) || byUrl.set(n.url, []).get(n.url)!).push(n);
    }
    for (const [url, chunks] of byUrl) {
      const page = pages.find((p: any) => p.url === url);
      if (!page) continue;
      const [px, py, pz] = at(page);
      let nearest = Infinity;
      for (const q of pages) {
        if (q === page) continue;
        const [qx, qy, qz] = at(q);
        nearest = Math.min(nearest, Math.hypot(px - qx, py - qy, pz - qz));
      }
      if (!Number.isFinite(nearest)) continue;
      const R = 0.45 * nearest;                 // the projector's NEIGHBOURHOOD
      // A floor, so a crowded page's chunks stay visible: the fixed collider
      // margin could eat the whole room and leave specks (val ~ 0).
      const floor = 0.35 * relSize;
      const room = Math.max(floor, (R * Math.cbrt(0.6 / chunks.length) - COLLIDER_MARGIN) / COLLIDER_SAFETY);
      for (const c of chunks) {
        if (c.fullVal === undefined) c.fullVal = c.val ?? 1;
        const r = drawnRadius({ ...c, val: c.fullVal }, relSize, media);
        const was = c.val;
        c.val = r > room ? c.fullVal * Math.pow(room / r, 3) : c.fullVal;
        if (!(Math.abs((was ?? 0) - c.val) <= 0.05 * c.val)) c.__freeUntil = performance.now() + 3000;
      }
      // The OPEN page's own node, too: drawn at full size its billboard's
      // collider was larger than the room the fit gives its chunks, and it
      // shoved every one out to a shell beyond it -- the forum's chunks sat at
      // 299 from their page where the fit put them at 75, 5 colliders off
      // (2026-09-28, in the app). Its collider may reach at most to its
      // nearest chunk's fit position; back to full size when it collapses.
      const fitD = chunks.map((c: any) => Math.hypot((c.fitX ?? c.x) - px, (c.fitY ?? c.y) - py, (c.fitZ ?? c.z ?? 0) - pz))
        .filter(Number.isFinite).sort((a: number, b: number) => a - b);
      if (fitD.length) {
        if (page.fullVal === undefined) page.fullVal = page.val ?? 1;
        const reach = Math.max(floor, (fitD[Math.floor(fitD.length * 0.1)] - COLLIDER_MARGIN) / COLLIDER_SAFETY);
        const rp = drawnRadius({ ...page, val: page.fullVal }, relSize, media);
        const was = page.val;
        page.val = rp > reach ? page.fullVal * Math.pow(reach / rp, 3) : page.fullVal;
        if (was && Math.abs(was - page.val) > 0.05 * page.val) this.rescaleObject(page, was);
      }
    }
    // A page with no chunks drawn is closed: its node back to full size.
    for (const q of pages) {
      if (byUrl.has(q.url) || q.fullVal === undefined || q.val === q.fullVal) continue;
      const was = q.val;
      q.val = q.fullVal;
      this.rescaleObject(q, was);
    }
  }

  // ---- G-107: the scene batch ------------------------------------------

  /** What draws every node and edge (`scenebatch.ts`). */
  private batch: SceneBatch | null = null;
  private batchRaf = 0;
  /** Read once per draw, like the collider's: the two must agree. */
  private drawnMedia = false;
  /** Planted by G-107's check: the per-node spheres, sprites and per-link
   *  cylinders the batch replaced -- one draw call each. */
  plantPerNode = false;
  // ---- calm: what the stream is not changing holds still -------------------

  /**
   * Pages the stream is changing, until when (performance.now). The flight
   * recorder, 2026-09-29, 20 s of scrolling on the forum: 210 teleports and
   * 257 vibrating nodes, and the worst were page nodes of pages nobody was
   * touching (DuckDuckGo searches, ja.wikipedia) reversing ~18 times a second
   * with 40-46 unit jumps -- collide shoving, contain and home hauling back,
   * re-energised by the 21 reheats the drains triggered. Scrolling one page
   * must not shake the corpus.
   */
  private activeUntil = new Map<string, number>();
  /** No calm pin before this (performance.now): the first settle is free. */
  private calmFrom = 0;
  /** Planted by the calm check: nothing pinned, every node free, as before. */
  plantNoCalm = false;
  calmStats = { pinned: 0, released: 0 };

  /**
   * A fit move is a GLIDE, not a jump (2026-09-29, the flight recorder: 31
   * stored chunks of a page being built up moved 190-256 units in ONE frame,
   * 7 ms after a placement reported `moved: 31` -- the page's centroid shifts
   * as its chunks arrive, the online UMAP re-places it, and the node was
   * assigned its new coordinates outright). The user's step is "changing to
   * UMAP coordinates after a re-fit": a transition. 450 ms, smoothstep, driven
   * from the render loop so it finishes even when the simulation has cooled;
   * the node is held where it lands.
   */
  private glides = new Set<any>();
  /** Planted by the glide check: fit moves assigned outright, as before. */
  plantTeleport = false;
  glideStats = { started: 0, done: 0 };

  private glide(n: any, to: number[], ms = 450): void {
    if (!to.every(Number.isFinite)) return;
    if (this.plantTeleport || !Number.isFinite(n.x)) {
      n.x = to[0]; n.y = to[1]; n.z = to[2];
      if (n.__calm) { n.fx = n.x; n.fy = n.y; n.fz = n.z; n.__calmFit = [n.fitX, n.fitY, n.fitZ]; }
      return;
    }
    if (Math.hypot(to[0] - n.x, to[1] - n.y, to[2] - (n.z ?? 0)) < 1e-6) return;
    n.__glide = { from: [n.x, n.y, n.z ?? 0], to, t0: performance.now(), ms };
    n.fx = n.x; n.fy = n.y; n.fz = n.z ?? 0; n.__calm = false;
    this.glides.add(n);
    this.glideStats.started++;
  }

  private stepGlides(): void {
    if (!this.glides.size) return;
    const now = performance.now();
    for (const n of this.glides) {
      const g = n.__glide;
      if (!g) { this.glides.delete(n); continue; }
      const e = Math.min(1, (now - g.t0) / g.ms), k = e * e * (3 - 2 * e);
      n.fx = n.x = g.from[0] + (g.to[0] - g.from[0]) * k;
      n.fy = n.y = g.from[1] + (g.to[1] - g.from[1]) * k;
      n.fz = n.z = g.from[2] + (g.to[2] - g.from[2]) * k;
      n.vx = 0; n.vy = 0; n.vz = 0;
      if (e >= 1) {
        delete n.__glide;
        this.glides.delete(n);
        this.glideStats.done++;
        n.__calm = true; n.__calmFit = [n.fitX, n.fitY, n.fitZ];   // held where it landed
      }
    }
  }

  /**
   * The governor: no free node moves further than this in one tick, whatever
   * the forces add up to (2026-09-29, the flight recorder: stored chunks
   * jumped 70-90 units in a frame -- collide resolving a whole overlap at
   * once after a resize, home yanking a node 400 units from its fit back at
   * alpha * 0.55 of the distance). A glide or a pin sets its own position and
   * is not governed. Applied after the tick, so the order forces run in
   * cannot let one escape it.
   */
  static GOVERNOR = 2.5;
  /** Planted by the governor check: forces move nodes as far as they like. */
  plantNoGovernor = false;
  governorStats = { clamped: 0, ticks: 0 };

  private govern(): void {
    const g: any = this.graph;
    if (!g) return;
    this.governorStats.ticks++;
    const cap = GraphView.GOVERNOR;
    for (const n of g.graphData().nodes as any[]) {
      const x = n.x, y = n.y, z = n.z ?? 0;
      if (!Number.isFinite(x)) continue;
      if (!this.plantNoGovernor && n.__px !== undefined && n.fx == null && !n.__glide) {
        const dx = x - n.__px, dy = y - n.__py, dz = z - n.__pz;
        const d = Math.hypot(dx, dy, dz);
        if (d > cap) {
          const k = cap / d;
          n.x = n.__px + dx * k; n.y = n.__py + dy * k; n.z = n.__pz + dz * k;
          n.vx = (n.vx ?? 0) * k; n.vy = (n.vy ?? 0) * k; n.vz = (n.vz ?? 0) * k;
          this.governorStats.clamped++;
        }
      }
      n.__px = n.x; n.__py = n.y; n.__pz = n.z ?? 0;
    }
  }

  private touchActive(url: string, ms = 4000): void {
    if (url) this.activeUntil.set(String(url).split("#")[0], performance.now() + ms);
  }

  /**
   * Every stored node on a page the stream is NOT changing is held where it
   * settled (fx/fy/fz); the page browsed, and any page a drain, placement,
   * fold or collapse touched in the last 4 s, stays free. A held node whose
   * own fit moves (an online UMAP update) is let go to follow it.
   */
  private calm(nodes: any[]): void {
    const now = performance.now();
    if (now < this.calmFrom) return;
    const browsing = String(this.browsingUrl ? this.browsingUrl() : "").split("#")[0];
    for (const n of nodes) {
      if (n.force || n.x === undefined || n.__glide) continue;
      const u = String(n.url || "").split("#")[0];
      // Per NODE, as Addendum IX reads: "what is drawn holds still, only the
      // newcomers settle". A stored node is free for 3 s after it is placed,
      // moved by its fit or resized -- the page it is on being streamed does
      // not free the rest of it (the first, page-level version left the
      // browsed page's own 98 nodes vibrating).
      const active = this.plantNoCalm || (n.__freeUntil || 0) > now;
      if (active) {
        if (n.__calm) { n.fx = undefined; n.fy = undefined; n.fz = undefined; n.__calm = false; }
        continue;
      }
      if (n.__calm) {
        const f = n.__calmFit;
        if (f && (n.fitX !== f[0] || n.fitY !== f[1] || n.fitZ !== f[2])) {
          n.fx = undefined; n.fy = undefined; n.fz = undefined; n.__calm = false;
          n.__freeUntil = now + 3000;
          this.calmStats.released++;
        }
        continue;
      }
      if (n.fx != null || !Number.isFinite(n.x)) continue;     // held by something else
      n.fx = n.x; n.fy = n.y; n.fz = n.z ?? 0;
      n.vx = 0; n.vy = 0; n.vz = 0;
      n.__calm = true; n.__calmFit = [n.fitX, n.fitY, n.fitZ];
      this.calmStats.pinned++;
    }
  }

  /** The 3D view's flight recorder (`motion.ts`): read by the harness. */
  motion = new MotionRecorder();
  /** Planted by G-107's check: pick proxies the raycaster cannot hit. */
  plantNoPick = false;
  /** Planted by G-81's check: chunk pictures kept on the node, never drawn. */
  plantNoPicture = false;
  /** Main-thread frame gaps (ms) and draw calls per frame, newest last. */
  private frameGaps: number[] = [];
  private callsPerFrame: number[] = [];
  private lastFrameAt = 0;
  private lastFrameNo = 0;
  /** CPU ms inside `renderer.render` per call: the draw-call cost itself,
   *  which a throttled background window does not hide (its frame GAPS read
   *  1,000 ms whatever is drawn). */
  private renderMs: number[] = [];
  private static proxyGeo: any = null;
  private static proxyMat: any = null;

  /**
   * The radius a node's pick proxy answers for: what the reader SEES, which
   * is the drawn half-extent -- not the collider's radius. For a picture the
   * collider reserves the half-DIAGONAL (the sphere a panel sweeps across an
   * orbit), and a proxy that size reached past the drawn square into its
   * neighbours: G-107 found a pointer on a fixture page's node naming the
   * B-tree page beside it, 8 of 10 picks against the per-node sprites' 10.
   */
  private proxyRadius(n: any): number {
    return this.graph ? this.lookOf(n, this.graph.nodeRelSize(), this.drawnMedia).half : 1;
  }

  /**
   * A node's own three.js object, now: an invisible sphere the raycaster
   * still hits (three tests layers, not visibility) and the renderer skips
   * (an invisible material is never queued). Shared geometry and material.
   */
  private pickProxy(n: any, relSize: number, media: boolean): any {
    if (!GraphView.proxyGeo) {
      GraphView.proxyGeo = new THREE.SphereGeometry(1, 8, 6);
      GraphView.proxyMat = new THREE.MeshBasicMaterial({ visible: false });
    }
    const m = new THREE.Mesh(GraphView.proxyGeo, GraphView.proxyMat);
    m.scale.setScalar(this.lookOf(n, relSize, media).half);
    (m as any).__proxy = true;
    if (this.plantNoPick) m.raycast = () => {};
    return m;
  }

  /**
   * How one node looks, for the batch -- the same choices the per-node
   * objects made: a translucent sphere while streaming (white when hovered),
   * a picture panel when media is on and it has one, a sphere otherwise.
   * READS the node; writes nothing the layout uses.
   */
  private lookOf(n: any, relSize: number, media: boolean): NodeLook {
    if (n.force) {
      return { half: n.level === "page" ? STREAM.RADIUS * 1.6 : STREAM.RADIUS, translucent: true,
               alpha: n.hovered ? 0.9 : STREAM.OPACITY, color: n.hovered ? "#ffffff" : (n.color || "#9aa0a6") };
    }
    const src = media && !(this.plantNoPicture && n.level !== "page") ? n.image?.src : undefined;
    if (src) return { half: billboardEdge(n, relSize) / 2, translucent: false, alpha: 0.95,
                      color: n.color || "#888888", picture: src };
    return { half: Math.cbrt(Math.max(n.val ?? 1, 1e-9)) * relSize, translucent: false, alpha: 1,
             color: n.hovered ? "#ffffff" : (n.color || "#9aa0a6") };
  }

  /** A picture decoded to an `<img>`, through the same CORS-free fetch. */
  private decoded(src: string): Promise<HTMLImageElement | null> {
    return this.texture(src).then((url) => new Promise<HTMLImageElement | null>((resolve) => {
      if (!url) { resolve(null); return; }
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => { console.warn("domvec: picture would not decode", src); resolve(null); };
      img.src = url;
    }), () => null);
  }

  private startBatch(graph: any, media: boolean): void {
    this.stopBatch();
    this.batch = new SceneBatch(graph.scene(), graph.renderer(), (src) => this.decoded(src));
    this.frameGaps = [];
    this.callsPerFrame = [];
    this.lastFrameAt = 0;
    const info = graph.renderer().info;
    // Counted across the whole frame, however many passes it takes.
    info.autoReset = false;
    info.reset();
    this.lastFrameNo = info.render.frame;
    this.renderMs = [];
    const renderer: any = graph.renderer();
    if (!renderer.__domvecTimed) {
      const draw = renderer.render.bind(renderer);
      renderer.__domvecDraw = draw;
      renderer.render = (scene: any, camera: any) => {
        const t = performance.now();
        draw(scene, camera);
        this.renderMs.push(performance.now() - t);
        if (this.renderMs.length > 600) this.renderMs.splice(0, 100);
      };
      renderer.__domvecTimed = true;
    }
    // Every graphData swap and reheat on the recorder's clock.
    const gd = graph.graphData.bind(graph), reheat = graph.d3ReheatSimulation?.bind(graph);
    graph.graphData = (...a: any[]) => {
      if (a.length) this.motion.event("graphData", { nodes: a[0]?.nodes?.length, links: a[0]?.links?.length });
      return gd(...a);
    };
    if (reheat) graph.d3ReheatSimulation = (...a: any[]) => { this.motion.event("reheat"); return reheat(...a); };
    const V3 = new THREE.Vector3();
    const tick = (t: number) => {
      this.batchRaf = requestAnimationFrame(tick);
      const g: any = this.graph;
      if (!g || !this.batch) return;
      this.stepGlides();
      if (this.motion.recording) {
        const cam = g.camera(), el = g.renderer().domElement;
        const W = el.clientWidth || 1, H = el.clientHeight || 1;
        this.motion.box = { w: W, h: H };
        cam.updateMatrixWorld();
        const tanHalf = Math.tan(((cam.fov || 50) * Math.PI) / 360);
        const rs0 = g.nodeRelSize();
        const cp = cam.position, cq = cam.quaternion;
        this.motion.camera([cp.x, cp.y, cp.z, cq.x, cq.y, cq.z, cq.w]);
        this.motion.linksNow = () => g.graphData().links;
        this.motion.frame(g.graphData().nodes,
          (x, y, z) => {
            V3.set(x, y, z).applyMatrix4(cam.matrixWorldInverse);
            const depth = -V3.z;
            V3.set(x, y, z).project(cam);
            return [(V3.x + 1) / 2 * W, (1 - V3.y) / 2 * H, depth];
          },
          (n) => this.lookOf(n, rs0, media).half,
          (depth) => (H / 2) / (depth * tanHalf));
      }
      if (this.lastFrameAt) {
        this.frameGaps.push(t - this.lastFrameAt);
        if (this.frameGaps.length > 600) this.frameGaps.splice(0, 100);
      }
      this.lastFrameAt = t;
      const frames = info.render.frame - this.lastFrameNo;
      if (frames > 0) {
        this.callsPerFrame.push(info.render.calls / frames);
        if (this.callsPerFrame.length > 600) this.callsPerFrame.splice(0, 100);
        this.lastFrameNo = info.render.frame;
        info.reset();
      }
      this.batch.setVisible(!this.plantPerNode);
      if (this.plantPerNode) return;
      const d = g.graphData();
      const rs = g.nodeRelSize();
      this.batch.sync(d.nodes, d.links, (n) => this.lookOf(n, rs, media));
    };
    this.batchRaf = requestAnimationFrame(tick);
  }

  private inspectRT: any = null;
  private inspectCanvas: HTMLCanvasElement | null = null;

  /**
   * A second camera on ONE page, rendered off-screen: what the reader would
   * see zoomed onto it, without moving the reader's camera (2026-09-29: the
   * glitches live at the page's scale, and at the default zoom an open page's
   * 1,109 chunks are a 9-pixel dot). Same scene, same batch, the reader's
   * viewing direction; framed on the page's nodes. Returns a PNG data URL.
   */
  inspect(url = "", size = 480, pad = 1.25): any {
    const g: any = this.graph;
    if (!g) return { error: "no graph" };
    const d = g.graphData();
    const u = url || (this.browsingUrl ? this.browsingUrl() : "");
    const members = d.nodes.filter((n: any) => n.url === u && Number.isFinite(n.x));
    if (!members.length) return { error: "nothing drawn for " + u };
    const c = [0, 0, 0];
    for (const n of members) { c[0] += n.x; c[1] += n.y; c[2] += n.z || 0; }
    c[0] /= members.length; c[1] /= members.length; c[2] /= members.length;
    const dist = members.map((n: any) => Math.hypot(n.x - c[0], n.y - c[1], (n.z || 0) - c[2])).sort((a: number, b: number) => a - b);
    const r = Math.max(1, dist[Math.floor(0.95 * (dist.length - 1))]);
    const main = g.camera();
    const back0 = pad * r / Math.tan((20 * Math.PI) / 180);
    // The near plane just in front of the page: a node between this camera
    // and the page (another page's, say) otherwise fills the frame -- the
    // first inspection film was dominated by exactly that.
    const cam = new THREE.PerspectiveCamera(40, 1, Math.max(r / 200, back0 - 1.3 * r), back0 + 1.3 * r);
    cam.quaternion.copy(main.quaternion);
    const back = new THREE.Vector3(0, 0, 1).applyQuaternion(main.quaternion).multiplyScalar(back0);
    cam.position.set(c[0], c[1], c[2]).add(back);
    cam.updateMatrixWorld();
    const renderer: any = g.renderer();
    if (!this.inspectRT || this.inspectRT.width !== size) {
      this.inspectRT?.dispose();
      this.inspectRT = new THREE.WebGLRenderTarget(size, size);
      this.inspectRT.texture.colorSpace = THREE.SRGBColorSpace;
    }
    const prevTarget = renderer.getRenderTarget();
    const prevColor = new THREE.Color(); renderer.getClearColor(prevColor);
    const prevAlpha = renderer.getClearAlpha();
    renderer.setRenderTarget(this.inspectRT);
    renderer.setClearColor(0x1e1e1e, 1);
    renderer.clear();
    (renderer.__domvecDraw || renderer.render.bind(renderer))(g.scene(), cam);
    const px = new Uint8Array(size * size * 4);
    renderer.readRenderTargetPixels(this.inspectRT, 0, 0, size, size, px);
    renderer.setRenderTarget(prevTarget);
    renderer.setClearColor(prevColor, prevAlpha);
    if (!this.inspectCanvas) this.inspectCanvas = document.createElement("canvas");
    const cv = this.inspectCanvas;
    cv.width = size; cv.height = size;
    const ctx = cv.getContext("2d")!;
    const img = ctx.createImageData(size, size);
    for (let y = 0; y < size; y++) img.data.set(px.subarray((size - 1 - y) * size * 4, (size - y) * size * 4), y * size * 4);
    ctx.putImageData(img, 0, 0);
    // Where each node of the page lands in THIS image, for annotation.
    const at = (n: any) => { const v = new THREE.Vector3(n.x, n.y, n.z || 0).project(cam); return [Math.round((v.x + 1) / 2 * size), Math.round((1 - v.y) / 2 * size)]; };
    return { png: cv.toDataURL("image/png"), url: u, nodes: members.length, radius: Math.round(r * 100) / 100,
             center: c.map((v) => Math.round(v * 100) / 100), at_ms: Math.round(performance.now()),
             streaming: members.filter((n: any) => n.force).length,
             points: members.slice(0, 1500).map((n: any) => [String(n.id).slice(0, 24), n.force ? 1 : 0, ...at(n)]) };
  }

  /** One sync now, outside the frame loop: a check reads the stats and the
   *  graph in the same turn, so neither is a frame older than the other. */
  batchSync(): any {
    const g: any = this.graph;
    if (!g || !this.batch || this.plantPerNode) return null;
    const d = g.graphData(), rs = g.nodeRelSize();
    this.batch.sync(d.nodes, d.links, (n) => this.lookOf(n, rs, this.drawnMedia));
    return { ...this.batch.lastStats };
  }

  private stopBatch(): void {
    if (this.batchRaf) cancelAnimationFrame(this.batchRaf);
    this.batchRaf = 0;
    this.batch?.dispose();
    this.batch = null;
  }

  /** G-107's plant: the per-node objects and per-link cylinders, or the batch. */
  setPerNode(on: boolean): void {
    const leaving = this.plantPerNode && !on;
    this.plantPerNode = on;
    const g: any = this.graph;
    if (!g) return;
    // Leaving the planted arm frees its pictures. 3d-force-graph disposes a
    // replaced object's material but not the material's TEXTURE, and three
    // keeps every undisposed texture's source image referenced -- so each
    // per-node arm left one decoded picture per node in this renderer and
    // one GL texture in the GPU process. Two arms in the working store
    // (2,283 and 1,805 textures) were followed by "Renderer process oom".
    const maps: any[] = leaving ? g.graphData().nodes
      .map((n: any) => n.__threeObj?.material?.map).filter(Boolean) : [];
    g.linkVisibility(on);
    g.nodeThreeObject(g.nodeThreeObject());
    for (const m of new Set(maps)) { try { m.dispose(); } catch { /* already gone */ } }
    this.frameGaps = [];
    this.callsPerFrame = [];
    this.renderMs = [];
  }

  /** How a node is drawn right now -- checks ask this, never the objects. */
  drawnAs(n: any): { batched: boolean; kind: "picture" | "sphere"; translucent: boolean; alpha: number; half: number } {
    if (this.plantPerNode || !this.graph) {
      const o: any = n.__threeObj, mat: any = o?.material;
      const sprite = o?.type === "Sprite";
      return { batched: false, kind: sprite ? "picture" : "sphere",
               translucent: !!mat?.transparent, alpha: mat?.opacity ?? 1,
               half: sprite ? o.scale.x / 2 : (o?.scale?.x ?? 0) };
    }
    const lk = this.lookOf(n, this.graph.nodeRelSize(), this.drawnMedia);
    return { batched: true, kind: lk.picture ? "picture" : "sphere", translucent: lk.translucent,
             alpha: lk.alpha, half: lk.half };
  }

  /** The render stage, for the harness: draw calls and frame gaps, measured. */
  renderStats(): any {
    const g: any = this.graph;
    if (!g) return null;
    const q = (xs: number[], p: number) => {
      if (!xs.length) return null;
      const s = [...xs].sort((a, b) => a - b);
      return Math.round(s[Math.min(s.length - 1, Math.floor(p * s.length))] * 10) / 10;
    };
    const info = g.renderer().info, d = g.graphData();
    return {
      mode: this.plantPerNode ? "per-node" : "batch",
      nodes: d.nodes.length, links: d.links.length,
      draw_calls_p50: q(this.callsPerFrame, 0.5), draw_calls_max: q(this.callsPerFrame, 1),
      frame_gap_p50: q(this.frameGaps, 0.5), frame_gap_p95: q(this.frameGaps, 0.95),
      frames: this.frameGaps.length,
      render_ms_p50: q(this.renderMs, 0.5), render_ms_p95: q(this.renderMs, 0.95), renders: this.renderMs.length,
      hidden: document.hidden,
      textures: info.memory.textures, geometries: info.memory.geometries,
      batch: this.batch ? { ...this.batch.lastStats } : null,
    };
  }

  /**
   * A node's size changed after its object was built: scale THAT object by
   * the drawn radius's ratio (cbrt of val). Rebuilding every object for one
   * page re-uploaded every picture's texture (0.4 s of a 13 s profile).
   */
  private rescaleObject(n: any, wasVal: number): void {
    const obj = n.__threeObj;
    if (!obj || !(wasVal > 0) || !(n.val > 0)) return;
    obj.scale.multiplyScalar(Math.cbrt(n.val / wasVal));
  }

  /**
   * Chunks get their most relevant picture (largest rendered in the page):
   * set on the nodes drawn now; later redraws read it back from the table.
   */
  setPictures(byCid: Record<string, string>): void {
    if (!this.graph) return;
    let any = false;
    for (const n of this.graph.graphData().nodes as any[]) {
      const src = byCid[n.id];
      if (!src || n.force || (n.image && n.image.src === src)) continue;
      n.image = { src, alt: "" };
      n.imgLoaded = false;
      any = true;
      // A picture changes what the node occupies (a panel's half-diagonal):
      // the proxy follows. The batch reads `n.image` on its next frame.
      if (!this.plantPerNode) (n as any).__threeObj?.scale.setScalar(this.proxyRadius(n));
    }
    if (any && this.plantPerNode) this.graph.nodeThreeObject(this.graph.nodeThreeObject());
  }

  /** Planted by G-81's check: page nodes get no favicon. */
  plantNoIcons = false;

  /** Planted by G-94's check: chunks drawn at full size, whatever the room. */
  plantBigChunks = false;

  /** The radius a node is DRAWN at, the pane's own number, for checks. */
  drawnRadiusOf(n: any): number {
    return this.graph ? drawnRadius(n, this.graph.nodeRelSize(), this.media()) : 0;
  }


  /** Planted by G-94's check: no collision room for projected nodes. */
  plantNoCollide = false;
  /** The collider's parameters, for checks that must use the pane's own numbers. */
  collider = { safety: COLLIDER_SAFETY, margin: COLLIDER_MARGIN };

  /**
   * The collapsed picture AS SEEN (G-94): every drawn node projected to the
   * screen with its drawn radius in pixels, and how much of it other nodes
   * cover. What "jumbled" means to a reader -- discs on top of discs --
   * rather than distances in the fit's own space.
   */
  seenLayout(): any {
    const g: any = this.graph;
    if (!g) return null;
    const cam = g.camera();
    const e = cam.matrixWorld.elements;          // column 0: the camera's right
    const right = [e[0], e[1], e[2]];
    const relSize = g.nodeRelSize(), media = this.media();
    const w = this.canvasEl ? this.canvasEl.clientWidth : 0, h = this.canvasEl ? this.canvasEl.clientHeight : 0;
    const drawn: any[] = [];
    for (const n of g.graphData().nodes) {
      if (n.force || typeof n.x !== "number") continue;
      const r = drawnRadius(n, relSize, media);
      const c = g.graph2ScreenCoords(n.x, n.y, n.z || 0);
      const q = g.graph2ScreenCoords(n.x + right[0] * r, n.y + right[1] * r, (n.z || 0) + right[2] * r);
      const rp = Math.hypot(q.x - c.x, q.y - c.y);
      if (c.x < -rp || c.y < -rp || c.x > w + rp || c.y > h + rp) continue;
      drawn.push({ id: n.id, level: n.level, x: c.x, y: c.y, r: Math.max(0.5, rp) });
    }
    // Nearest neighbour in units of "touching" (r_a + r_b): < 1 overlaps.
    const cell = 40, grid = new Map<string, any[]>();
    for (const d of drawn) {
      const k = `${Math.floor(d.x / cell)},${Math.floor(d.y / cell)}`;
      (grid.get(k) || grid.set(k, []).get(k)!).push(d);
    }
    const ratio: number[] = [];
    for (const a of drawn) {
      let best = Infinity;
      const cx = Math.floor(a.x / cell), cy = Math.floor(a.y / cell);
      const reach = Math.ceil((a.r * 4) / cell) + 1;
      for (let ox = -reach; ox <= reach; ox++) for (let oy = -reach; oy <= reach; oy++) {
        for (const b of grid.get(`${cx + ox},${cy + oy}`) || []) {
          if (b === a) continue;
          best = Math.min(best, Math.hypot(a.x - b.x, a.y - b.y) / (a.r + b.r));
        }
      }
      ratio.push(best);
    }
    const sorted = ratio.filter(Number.isFinite).sort((x, y) => x - y);
    const q = (p: number) => sorted.length ? Math.round(sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))] * 100) / 100 : null;
    return {
      drawn: drawn.length, pages: drawn.filter((d) => d.level === "page").length,
      overlapping: ratio.filter((x) => x < 1).length,
      buried: ratio.filter((x) => x < 0.5).length,
      nn_touch_p10: q(0.1), nn_touch_p50: q(0.5),
      radius_px_p50: drawn.length ? Math.round(drawn.map((d) => d.r).sort((x, y) => x - y)[Math.floor(drawn.length / 2)] * 10) / 10 : null,
      canvas: [w, h],
    };
  }

  /** The streaming layout's parameters, live -- a check plants the old ones (G-93). */
  streamParams = STREAM;

  /** Asks the browser cell for a chunk's page snapshot (set by the plugin). */
  snapshotFor: ((cid: string, url: string) => Promise<boolean>) | null = null;

  /** Where a link clicked inside a billboard's snapshot goes: the browser cell. */
  onNavigate: (href: string) => void = () => {};

  /**
   * A gesture on a control in a billboard's snapshot (`G-111`): carried out in
   * the browser cell on the live page, which then re-reads the chunk. Brokered
   * by the plugin like `onNavigate`; null (no cell) leaves the controls inert.
   */
  onAct: (cid: string, rec: ActRecord) => Promise<ActResult | null> = async () => null;

  /**
   * Mount the page-faithful snapshot of a chunk into a billboard body, with a
   * toggle to the distilled form. False when there is none to show.
   */
  private mountSnapshot(entry: any, body: HTMLElement): boolean {
    const snap = getSnapshot(entry.node.id);
    if (!snap) return false;
    body.empty();
    entry.snapshot = true;
    renderSnapshot(body, snap, {
      maxHeight: 420, onLink: (h) => this.onNavigate(h), cid: entry.node.id,
      onAct: (rec) => this.onAct(entry.node.id, rec),
    });
    const toggle = entry.el.querySelector(".domvec-bb-head") as HTMLElement | null;
    if (toggle && !toggle.querySelector(".domvec-bb-form")) {
      const t = toggle.createSpan({ cls: "domvec-bb-form", text: "md" });
      t.setAttr("aria-label", "distilled form");
      t.onpointerdown = (e: PointerEvent) => e.stopPropagation();
      t.onclick = (e: MouseEvent) => {
        e.stopPropagation();
        const b = entry.el.querySelector(".domvec-bb-body") as HTMLElement;
        if (entry.snapshot) {
          b.empty();
          entry.snapshot = false;
          entry.surface = new ChunkSurface(b, entry.node.id, this.surfaceHost, { interactive: true });
          this.addChild(entry.surface);
          t.setText("page");
        } else {
          if (entry.surface) { this.removeChild(entry.surface); entry.surface = null; }
          this.mountSnapshot(entry, b);
          t.setText("md");
        }
      };
    }
    return true;
  }

  /**
   * A capture rewrote some chunks: redraw the billboards showing them, so an
   * open shadow-DOM form never shows what the page used to say (`S-12`; it
   * was the chunk pane's `refreshIf`, and the pane is gone).
   */
  refreshBillboards(cids: string[]): void {
    const changed = new Set(cids);
    for (const [id, entry] of this.billboards.entries() as any) {
      if (!changed.has(id)) continue;
      const body = entry.el.querySelector(".domvec-bb-body") as HTMLElement | null;
      if (!body) continue;
      if (entry.snapshot) { this.mountSnapshot(entry, body); continue; }
      if (!entry.surface) continue;
      this.removeChild(entry.surface);
      body.empty();
      entry.surface = new ChunkSurface(body, id, this.surfaceHost,
                                       { interactive: true });
      this.addChild(entry.surface);
    }
  }

  /** Collapse a billboard to its title bar, or open it back up. */
  private setMinimized(entry: any, on: boolean): void {
    entry.minimized = on;
    entry.el.toggleClass("is-min", on);
  }

  /** Close one billboard and release its surface. */
  closeBillboard(id: string): void {
    const entry: any = this.billboards.get(id);
    if (!entry) return;
    if (entry.surface) this.removeChild(entry.surface);
    entry.el.remove();
    this.billboards.delete(id);
    this.stopBillboardLoop();
  }

  /** Told when the reader closes a billboard with its x, so the browser can
   *  drop the matching pin and markdown (`G-78`). Assigned by the plugin. */
  onBillboardClosed: (id: string) => void = () => {};

  /**
   * Open a chunk's billboard because the browser pinned it (`G-78`).
   *
   * Placed first if the graph does not draw it yet -- a right-click on a
   * page whose chunks are not in the picture still gets its billboard.
   */
  async pinChunk(cid: string): Promise<boolean> {
    if (!this.graph || !cid) return false;
    let node = this.graph.graphData().nodes.find((n: any) => n.id === cid);
    if (!node) {
      const got: any = await this.sidecar.place([cid]);
      if (got?.nodes?.length) this.absorb(got.nodes, got.edges);
      node = this.graph.graphData().nodes.find((n: any) => n.id === cid);
    }
    if (!node) return false;
    await this.openBillboard(node, true);
    return true;
  }

  /** The browser let a chunk go: close its billboard. */
  unpinChunk(cid: string): void {
    const entry: any = this.billboards.get(cid);
    if (entry && entry.fromBrowser) this.closeBillboard(cid);
  }

  /** Which billboards are open, and which the browser holds -- for the
   *  harness, so a check reads the pane rather than re-deriving it. */
  billboardState(): { id: string; fromBrowser: boolean; shadow: boolean; form: string; elements: number }[] {
    return [...this.billboards.entries()].map(([id, e]: [string, any]) => {
      const host = e.el.querySelector(".domvec-html-host");
      const frame = e.el.querySelector("iframe.domvec-snapshot") as HTMLIFrameElement | null;
      let elements = 0;
      try {
        elements = frame ? (frame.contentDocument?.querySelectorAll("#domvec-root *").length || 0)
          : (host?.shadowRoot?.querySelectorAll("*").length || 0);
      } catch { /* not readable yet */ }
      // Two forms (D-36): the chunk as the PAGE draws it, when the page gave
      // one, else the distilled shadow-DOM form. Both are rendered HTML.
      return {
        id, fromBrowser: !!e.fromBrowser, minimized: !!e.minimized,
        shadow: !!host?.shadowRoot || !!frame,
        form: frame ? "page" : (host?.shadowRoot ? "distilled" : "none"),
        elements,
      };
    });
  }

  /** Put a billboard where its node is, in screen coordinates. */
  private positionBillboard(entry: { el: HTMLElement; node: any; pinned: boolean }): void {
    if (entry.pinned || !this.graph) return;
    const n = entry.node;
    if (!Number.isFinite(n.x)) return;
    const at: any = (this.graph as any).graph2ScreenCoords(n.x, n.y, n.z);
    if (!at) return;
    entry.el.style.left = `${Math.round(at.x) + 12}px`;
    entry.el.style.top = `${Math.round(at.y) + 12}px`;
  }

  /**
   * Follow the nodes while anything is open.
   *
   * Its own frame loop rather than `onEngineTick`: the simulation stops
   * ticking as soon as it settles, and the camera keeps moving after that --
   * so a panel anchored on ticks alone detaches from its node the moment the
   * reader orbits, which is exactly when they are looking at it.
   */
  private startBillboardLoop(): void {
    if (this.billboardFrame) return;
    const step = () => {
      if (!this.billboards.size) { this.billboardFrame = 0; return; }
      for (const entry of this.billboards.values()) this.positionBillboard(entry);
      this.billboardFrame = window.requestAnimationFrame(step);
    };
    this.billboardFrame = window.requestAnimationFrame(step);
  }

  private stopBillboardLoop(): void {
    if (this.billboards.size || !this.billboardFrame) return;
    window.cancelAnimationFrame(this.billboardFrame);
    this.billboardFrame = 0;
  }

  /**
   * Draw the containment the trie holds among everything on screen (`G-6`).
   *
   * **Asked for the whole drawn set, not per arrival.** Every route computed
   * edges only among the nodes it was producing: `unfold` for its branches,
   * `place_into` for one drain's chunks. An edge has two ends and they
   * routinely arrive from different calls, so a chunk placed by a live
   * capture that contains one an unfolding drew earlier got no edge from
   * either. Measured: 9,257 `Contains` edges in the store, 99 drawn, and
   * 110 of 189 nodes isolated.
   */
  private async drawContainment(): Promise<number> {
    if (!this.graph) return 0;
    const data: any = this.graph.graphData();
    const cids = data.nodes
      .filter((n: any) => n.level && n.level !== "page")
      .map((n: any) => n.id)
      .filter((id: string) => !String(id).startsWith("path:"));
    if (cids.length < 2) return 0;
    const urls = [...new Set(data.nodes
      .filter((n: any) => n.url).map((n: any) => n.url))] as string[];
    const got: any = await this.sidecar.edgesAmong(cids, urls);
    const edges = (got && got.edges) || [];
    if (!edges.length) return 0;
    const fresh: any = this.graph.graphData();
    const added = this.addEdges(fresh, edges);
    if (added) {
      this.graph.graphData(fresh);
      this.graph.d3ReheatSimulation();
      this.sayCounts();
    }
    return added;
  }

  /**
   * How deep one expansion opens, and how much of the tree it may draw.
   *
   * Depth rather than breadth is the bounded quantity because that is what
   * patricia compression makes cheap: a chain of single-child wrappers
   * costs one step, so four steps reach much further into a real document
   * than four levels of a naive tree would. The node budget is the backstop
   * for a page whose top fork is very wide.
   */
  private static readonly UNFOLD_DEPTH = 3;
  private static readonly UNFOLD_BUDGET = 160;

  /**
   * Open a node into the SHAPE of the trie beneath it, not just its first
   * fork (`G-54`, and the reader's "this is not a DAG").
   *
   * Each branch a step reveals is itself a place the trie forks, and
   * stopping at the first one draws a star: measured at 31 edges from the
   * hub, 30 between branches, every branch at degree 2, depth 1. Recursing
   * turns the same calls into a tree with levels, which is the structure
   * the patricia trie actually holds.
   *
   * Breadth-first, so the budget spends itself on the widest part of the
   * tree nearest the reader rather than on one deep chain.
   */
  private async unfoldNode(node: any): Promise<void> {
    // Opened by the READER: stays open when they browse away (S-6).
    if (node && node.url) this.openedByReader.add(node.url);
    const added = await this.unfoldStep(node);
    if (!added.length) return;
    let frontier = added.filter((n: any) => n.level === "path");
    let drawn = added.length;
    for (let depth = 1;
         depth < GraphView.UNFOLD_DEPTH
           && frontier.length
           && drawn < GraphView.UNFOLD_BUDGET;
         depth++) {
      const next: any[] = [];
      for (const branch of frontier) {
        if (drawn >= GraphView.UNFOLD_BUDGET) break;
        const more = await this.unfoldStep(branch);
        drawn += more.length;
        for (const m of more) if (m.level === "path") next.push(m);
      }
      frontier = next;
    }
    // Containment across everything now drawn, which is where the edges
    // BETWEEN levels come from: a parent and a grandchild are never in the
    // same step's result, so no single step could draw that edge.
    await this.drawContainment();
    // **Not reframed on the expansion, and the reason is worth recording.**
    //
    // I added that, on the argument that 161 nodes inside a 48-unit ball
    // are about 40 screen pixels and the reader needs to be closer. Moving
    // the camera in made every node bigger by exactly the same factor as it
    // made the gaps bigger: in a perspective projection the drawn radius
    // and the distance between two centres both scale as 1/d, so the ratio
    // between them -- which is what "overlapping" means -- is invariant
    // under any camera move. Measured after zooming in: radius 23.2px, gap
    // p50 -36.2px, 159 of 162 touching, and 98 nodes pushed off screen.
    //
    // Overlap is a property of the LAYOUT in world units and has to be
    // fixed there. `fitRadiiToSpacing` is that fix.
    this.fitRadiiToSpacing();
  }

  /**
   * No node may be drawn wider than the room its neighbours leave it.
   *
   * **The invariant a readable picture actually needs**, and the one thing
   * that was never enforced. `nodeRelSize` is global and computed from the
   * page-level spread, so when an expansion drops 161 nodes into a 48-unit
   * ball they keep the size that suited 97 pages across 900 units. Measured
   * there: drawn radius about 14 world units against a nearest-neighbour
   * spacing of about 14 -- diameters twice the spacing, so more than half
   * the picture necessarily overlaps, at every zoom level.
   *
   * Zooming cannot help. In a perspective projection the drawn radius and
   * the gap between two centres both scale as 1/distance, so their ratio is
   * invariant under camera moves; a node that overlaps its neighbour does so
   * at every magnification. That is why this is a layout pass and not a
   * camera one.
   *
   * Each node is capped at 0.45 of its own nearest-neighbour distance, so a
   * pair always shows a visible gap. Only ever SHRINKS: a node with room to
   * spare keeps the size its `val` asked for, which is the statement about
   * how many chunks it stands for, and that statement survives wherever the
   * picture can afford it.
   */
  private fitRadiiToSpacing(): boolean {
    if (!this.graph) return false;
    const data: any = this.graph.graphData();
    const nodes = data.nodes as any[];
    if (nodes.length < 2) return false;
    const relSize = (this.graph as any).nodeRelSize?.() ?? 1;
    const media = this.media();
    let changed = false;
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      let nearest = Infinity;
      for (let j = 0; j < nodes.length; j++) {
        if (i === j) continue;
        const b = nodes[j];
        const d = Math.hypot((a.x ?? 0) - (b.x ?? 0),
                             (a.y ?? 0) - (b.y ?? 0),
                             (a.z ?? 0) - (b.z ?? 0));
        if (d > 1e-6 && d < nearest) nearest = d;
      }
      if (!Number.isFinite(nearest)) continue;
      const allowed = nearest * 0.45;
      const drawn = drawnRadius(a, relSize, media);
      if (drawn <= allowed || drawn <= 0) continue;
      // `val` is radius cubed, so a radius scale of k is k^3 on val.
      if (a.valFull === undefined) a.valFull = a.val;
      a.val = Math.max((a.val ?? 1) * Math.pow(allowed / drawn, 3), 1e-4);
      changed = true;
    }
    if (changed) {
      // **Refresh the SIZES, not the graph.** `graphData(data)` re-feeds the
      // layout engine and resets the cooldown, so calling this when the
      // simulation settles would restart it and call this again -- a loop
      // that never cools. Re-setting the accessor redraws the spheres and
      // leaves the engine alone.
      this.graph.nodeVal(this.graph.nodeVal());
      this.sayCounts();
    }
    return changed;
  }

  /** One patricia step, returning what it added. */
  private async unfoldStep(node: any): Promise<any[]> {
    if (!this.graph || !node || !node.url) return [];
    // A branch opened inside another branch inherits its territory: its
    // anchor is that branch's own position and its room a share of that
    // branch's room. `1/sqrt(siblings)` because children fill an AREA
    // inside their parent's ball, not a length; dividing the radius by
    // the count shrinks deep levels to dots far faster than the geometry
    // requires.
    // **Only a BRANCH passes down a territory.** A page node carries a
    // small `room` too, but that is the leash holding it at its fit
    // position (`D-27`), not a region its contents live in -- and reading
    // it as one handed the very first step a territory of 8 world units
    // instead of 48, which drew every node in the expansion at 2px.
    const parentRoom = node.level === "page" ? 0 : (node as any).room;
    let inherit: { anchor: number[]; room: number } | null =
      parentRoom && (node as any).anchorPos
      ? {
          anchor: [node.x ?? 0, node.y ?? 0, node.z ?? 0],
          // **Half the parent's radius, floored.** The first version
          // divided by `sqrt(members)` -- the chunks a branch STANDS for,
          // routinely hundreds -- so a depth-2 territory came out at 0.1
          // world units and every node drew as a 0.5px speck. `members` is
          // a statement about the subtree's size, not about how many
          // siblings have to share a ball. Halving per level is the
          // geometric relation that actually holds: children with their own
          // contents fit inside their parent with room to spare, and three
          // levels still leave a quarter of the page's territory.
          room: Math.max(parentRoom * 0.5, 8),
        }
      : null;
    // **A page anchors its own unfolding.** The sidecar answers from
    // `_PAGE_POS`, an in-process table written by whichever fit ran last,
    // while `/layout` can serve a STORED layout built by an earlier one.
    // Measured inside a single process: the layout and the pane agreed the
    // page sat at [-203.5, -192.5, -111.5] and the unfold anchored at
    // [-178.8, 248.8, 130.7] -- 504 units away, so every branch hung in the
    // middle of the corpus rather than on its page. That is the whole of
    // "nodes way too jumbled": the expansion measured 553 units across
    // against a territory of 52.7, and only 10 of 161 nodes read as
    // outside "their" room because the room was centred somewhere else.
    //
    // `D-22`'s family -- a stale fit answering for the wrong corpus -- and
    // the fix that closes the family rather than the instance is to stop
    // keeping two answers. The pane cannot drift from itself.
    if (node.level === "page") {
      const at = [node.fitX ?? node.x ?? 0,
                  node.fitY ?? node.y ?? 0,
                  node.fitZ ?? node.z ?? 0];
      // `_room_around`'s own rule, against the pages actually on screen:
      // 0.45 of the way to the nearest one is the largest radius that
      // cannot reach a neighbour's centre.
      let gap = Infinity;
      for (const other of (this.graph.graphData() as any).nodes) {
        if (other === node || other.level !== "page") continue;
        const d = Math.hypot((other.fitX ?? 0) - at[0],
                             (other.fitY ?? 0) - at[1],
                             (other.fitZ ?? 0) - at[2]);
        if (d > 1e-6 && d < gap) gap = d;
      }
      inherit = {
        anchor: at,
        room: Number.isFinite(gap) ? Math.max(gap * 0.45, 12) : 90,
      };
    }
    const got = await this.sidecar.unfold(
      node.url, node.path || "", this.space,
      inherit?.anchor, inherit?.room);
    const nodes = (got && (got.nodes as LayoutNode[])) || [];
    if (!nodes.length) return [];

    const data: any = this.graph.graphData();
    const hub = data.nodes.find((n: any) => n.id === node.id);
    const known = new Set(data.nodes.map((n: any) => n.id));
    const opened: any[] = [];
    for (const incoming of nodes) {
      if (!incoming || !incoming.cid || known.has(incoming.cid)) continue;
      const built = this.nodeFrom(incoming);
      opened.push(built);
    }
    // A new array, never pushed in place (D-38; see `addEdges`).
    if (opened.length) data.nodes = data.nodes.concat(opened);
    // An opened container is still a CONTAINER, and this used to shrink it
    // to the smallest thing it revealed.
    //
    // The reasoning was that an open page no longer stands for its chunks
    // because they are on screen, so a full-size sphere would be a lid over
    // them. True of the lid; false of the size. Measured in the live pane
    // with two pages open: the hubs sat at `val` 1, a drawn radius of
    // **5.78** world units, while the chunks they had just opened into drew
    // at **17.24** at the median -- three times larger. The container was
    // the smallest object in its own neighbourhood, which is the nesting
    // the goal asks for turned inside out.
    //
    // So the lid is what goes, not the size: `image` is dropped, and the
    // branches now arrive sized in the page's OWN unit (sqrt of the chunks
    // each stands for, see `layout._room_around`), so a branch cannot
    // exceed the page it came out of -- `members <= chunks` is a property
    // of the trie, not a number anyone tuned.
    // **Scaled to fit the territory, keeping the trie's proportions.**
    //
    // `layout._room_around` gives this unfolding a ball; the branches have
    // to pack into it. Thirty-one branches at their natural size needed
    // roughly 47 units of radius against the 19 they were given, so the
    // collider pushed them out to 275 -- past a neighbouring page 80 units
    // away. A boundary and a collider that disagree do not negotiate.
    //
    // The packing estimate is the usual one: n spheres of radius r occupy
    // about `1.6 * r * cbrt(n)` of radius once loosely packed. Solving for r
    // gives the largest a branch may be drawn. Only ever shrinks -- a small
    // unfolding with room to spare keeps the size the trie asked for, so
    // this cannot inflate anything.
    //
    // Relative size is preserved because every branch is scaled by the same
    // factor: a branch covering 400 chunks still draws larger than one
    // covering 4, which is the statement `val` is making.
    if (opened.length > 1) {
      const room = opened[0]?.room;
      const relSize = (this.graph as any).nodeRelSize?.() ?? 1;
      // **The application's own radius function, not a reimplementation.**
      // `cbrt(val) * relSize` is the radius of a PLAIN node; one showing a
      // picture is drawn at 1.75x that, and sizing against the smaller
      // number left every image-bearing branch overlapping its neighbour --
      // 12 pairs, enough for the collider to shove the interior outward and
      // turn the fit's uniform ball (cv 0.289) into a shell (cv 0.153).
      // `G-21` was filed for exactly this mistake in a live check, which
      // wrote its own `drawnRadius` and invented 49 overlaps.
      const media = this.media();
      const radiusOf = (n: any) => drawnRadius(n, relSize, media);
      // **The smallest gap the fit actually left**, not an estimate of how
      // many spheres would pack into the territory. These nodes are placed,
      // not packed: the only question is whether each is small enough to sit
      // where the projection put it without touching its neighbour.
      let closest = Infinity;
      for (let i = 0; i < opened.length; i++) {
        for (let j = i + 1; j < opened.length; j++) {
          const a = opened[i];
          const b = opened[j];
          const d = Math.hypot((a.x ?? 0) - (b.x ?? 0),
                               (a.y ?? 0) - (b.y ?? 0),
                               (a.z ?? 0) - (b.z ?? 0));
          if (d > 1e-6 && d < closest) closest = d;
        }
      }
      const biggest = opened.reduce(
        (m: number, n: any) => Math.max(m, radiusOf(n)), 0);
      // Half the gap, less the margin the collider adds on each side.
      let allowed = Number.isFinite(closest)
        ? closest / (2 * COLLIDER_SAFETY) : biggest;
      // Never shrink to nothing because one pair landed on top of each
      // other; there the collider should act, and separating one pair is a
      // better outcome than an unfolding nobody can see.
      if (room && room > 0) allowed = Math.max(allowed, room * 0.06);
      if (biggest > allowed && biggest > 0) {
        // `val` is radius cubed, so a radius scale of `k` is `k^3` on val.
        const k = Math.pow(allowed / biggest, 3);
        for (const n of opened) n.val = Math.max((n.val ?? 1) * k, 1e-3);
      }
    }
    if (hub) {
      hub.unfolded = true;
      if (hub.valFull === undefined) hub.valFull = hub.val;
      // **Bound to the territory it is the centre of.** Without this the
      // branches stayed put and the page walked: 18.1 units of reach from
      // the anchor, 283.8 from the hub, on the same unfolding. A quarter of
      // the branches' own room leaves the collider enough slack to separate
      // it from a neighbour without letting it leave.
      if (opened.length && opened[0]?.room) {
        hub.anchorPos = [hub.fitX, hub.fitY, hub.fitZ];
        hub.room = opened[0].room * 0.25;
      }
      // A billboard is drawn at the panel edge rather than at `val`, so
      // leaving the image would leave exactly the lid this removes.
      delete hub.image;
    }
    this.addEdges(data, got?.edges);
    this.graph.graphData(data);
    this.graph.d3ReheatSimulation();
    this.sayCounts();
    return opened;
  }

  /**
   * Take chunks captured after the fit into the picture already on screen.
   *
   * `G-34`: a reader browsing with the sensor running produces chunks
   * continuously, and the pane has to show them without rebuilding. The
   * sidecar places them with `Projection.transform` -- the same fit, not a
   * new one -- so what arrives here is already in this cloud's coordinates.
   *
   * **Reheating is cheap here, and that is a property of the design rather
   * than luck.** Collision is the only force running (`G-20`), and collision
   * acts on a node only when something is inside its radius. Measured cold:
   * 2,302 of 5,337 nodes sit exactly where the fit put them, feeling nothing.
   * So a reheat after three new nodes arrive settles those three and their
   * immediate neighbours, and leaves the rest of the cloud untouched -- where
   * a charge or a link force would have shaken all 5,337.
   *
   * A chunk that was REWRITTEN moves. Its text changed, so its embedding
   * changed, so the fit puts it somewhere else, and pretending otherwise
   * would leave a node standing where its old meaning used to be.
   */
  absorb(incoming: LayoutNode[],
         edges?: { source: string; target: string }[],
         traceId?: string, opts: { pagesOnly?: boolean } = {}):
      { added: number; moved: number; edges: number } {
    if (this.forceSpecs.size) {
      // Chunks placed just now carry their NEW content: a force node pending
      // on a changed chunk may collapse into it from here on.
      const placed = new Set((incoming || []).map((n) => n.cid));
      for (const spec of this.forceSpecs.values()) {
        if (spec.stale && spec.cid && placed.has(spec.cid)) spec.stale = false;
      }
      window.setTimeout(() => this.collapseCovered(), 0);
    }
    // A capture's chunks join their page node rather than the picture,
    // unless the reader has that page open (its chunks drawn) -- `G-89`.
    if (opts.pagesOnly && this.graph && incoming && incoming.length) {
      const open = new Set<string>(this.graph.graphData().nodes
        .filter((n: any) => !n.force && n.level !== "page").map((n: any) => n.url));
      incoming = incoming.filter((n) => (n.level ?? "chunk") === "page" || open.has(n.url));
    }
    // A projected chunk is DRAWN only while its page is open -- the page the
    // reader is on, or one they opened; any other page holds it folded in its
    // root (Addendum IX: chunks of a collapsed page are not drawn). A late
    // placement -- vectors trail the store by seconds -- used to reopen a page
    // the reader had already left.
    if (this.graph && incoming && incoming.length) {
      const data0: any = this.graph.graphData();
      const openNow = new Set<string>(data0.nodes.filter((n: any) => !n.force && n.level !== "page").map((n: any) => n.url));
      const browsing = this.browsingUrl ? this.browsingUrl() : "";
      const open = (u: string) => !!u && (openNow.has(u) || this.openedByReader.has(u)
        || (!!browsing && u.split("#")[0] === browsing.split("#")[0]));
      const t = Date.now();
      incoming = incoming.filter((n) => {
        if ((n.level ?? "chunk") === "page") return true;
        const shown = open(n.url || "");
        if (n.cid && !this.life.placed.has(n.cid)) this.life.placed.set(n.cid, { at: t, drawn: shown, url: n.url || "" });
        if (!shown) this.life.folded_unopened++;
        return shown;
      });
      if (this.life.placed.size > 40000) this.life.placed.clear();
    }
    const out = { added: 0, moved: 0, edges: 0 };
    const prof = profiler();
    const trace = traceId ? prof.get(traceId) : undefined;
    const absorbStart = performance.now();
    if (!this.graph || !incoming || !incoming.length) {
      if (trace) prof.finish(trace, this.graph ? "nothing_placed" : "no_graph");
      return out;
    }
    const data: any = this.graph.graphData();
    const byId = new Map<string, any>(data.nodes.map((n: any) => [n.id, n]));
    const arrived: any[] = [];

    for (const node of incoming) {
      if (!node || !node.cid || !node.pos) continue;
      this.touchActive(node.url || "");
      const built = this.nodeFrom(node);
      if (this.plantScatter && node.level !== "page") {
        const j = () => (Math.random() - 0.5) * 60;
        built.x = (built.x ?? 0) + j(); built.y = (built.y ?? 0) + j(); built.z = (built.z ?? 0) + j();
      }
      const existing = byId.get(node.cid);
      if (existing) {
        // Fields the render reads, and the fit's own coordinates. `x/y/z` is
        // set too: the simulation owns those, but a chunk whose meaning moved
        // should not be left drawing at its old meaning's address.
        Object.assign(existing, {
          name: built.name, url: built.url, val: built.val, fullVal: built.val,
          projX: built.fitX, projY: built.fitY, projZ: built.fitZ,
          tokens: built.tokens, image: built.image, color: built.color,
          fitX: built.fitX, fitY: built.fitY, fitZ: built.fitZ,
        });
        // To its new place by a glide, not a jump.
        this.glide(existing, [built.x, built.y, built.z]);
        out.moved++;
      } else {
        built.__freeUntil = performance.now() + 3000;
        arrived.push(built);
        byId.set(node.cid, built);
        out.added++;
      }
    }
    // A new array, never pushed in place (D-38; see `addEdges`).
    if (arrived.length) data.nodes = data.nodes.concat(arrived);
    if (!out.added && !out.moved) return out;
    // The links array is handed back unchanged. `forceLink` resolved its
    // endpoints in place at boot, so rebuilding it here would hand d3 a list
    // of node OBJECTS where it expects to re-resolve, and the edges would
    // stop drawing -- which is exactly the failure that removing the link
    // force caused.
    // **The trie's own edges, which were computed and then dropped.**
    //
    // `place_into` returns the containment edges among what it placed --
    // `G-6` -- and the pane's callback chain passed only the nodes, so a
    // live capture drew its chunks as loose dots. Measured before this:
    // 921 nodes, 84 links, and of 793 chunk nodes exactly 16 had an edge of
    // any kind. A patricia trie that is not drawn has no structure for a
    // force to act on, which is most of why the picture reads as a clump.
    // The projection REPLACES the force position: a force node still drawn
    // for a chunk now placed (not yet saved-and-folded) goes.
    if (this.forceSpecs.size) {
      const placedCids = new Set((incoming || []).map((n) => n.cid));
      const replaced = new Set<string>();
      for (const [id, spec] of this.forceSpecs) if (spec.cid && placedCids.has(spec.cid) && !this.plantLateCollapse) replaced.add(id);
      if (replaced.size) {
        this.life.replaced_force += replaced.size;
        for (const id of replaced) this.forceSpecs.delete(id);
        data.nodes = data.nodes.filter((n: any) => !(n.force && replaced.has(n.id)));
        data.links = data.links.filter((l: any) => !(l.force && (replaced.has(l.target?.id ?? l.target) || replaced.has(l.source?.id ?? l.source))));
      }
    }
    out.edges = this.addEdges(data, edges);
    this.motion.event("placed", { added: out.added, moved: out.moved, edges: out.edges });
    this.fitChunkSizes(data);
    this.graph.graphData(data);
    void this.drawContainment();
    // `absorb` ends here; the listener takes it from the scene.
    if (trace) {
      const absorbEnd = performance.now();
      prof.stage(trace, "absorb", absorbEnd - absorbStart);
      prof.fact(trace, "absorbed", out.added);
      prof.fact(trace, "moved", out.moved);
      prof.watch(trace, incoming.map((n) => n.cid).filter(Boolean), absorbEnd);
    }
    this.graph.d3ReheatSimulation();
    this.sayCounts();
    return out;
  }

  /**
   * One layout node as the object the renderer holds.
   *
   * Factored out because live capture needs the SAME mapping: a node placed
   * by `transform` a minute after the fit has to arrive identical in shape to
   * one the fit produced, or the two kinds of node drift apart and the
   * collider starts sizing half the cloud differently from the other half.
   */
  private nodeFrom(n: LayoutNode): any {
    return {
      id: n.cid,
      members: n.members ?? 1,
      level: n.level ?? "chunk",
      path: n.path ?? "",
      name: n.title || n.url,
      url: n.url,
      // The fitted position as a SEEDING, not a pin (`G-20`).
      //
      // These were `fx/fy/fz`, which hold a node exactly where the projection
      // put it, and the reason given was sound: "running the force simulation
      // on top would drift the points off the embedding and quietly turn a
      // UMAP of two vector spaces into a spring layout that happened to start
      // there." That danger is real and it is not what the simulation here
      // does. Every force that WOULD do it -- charge, links, centring -- is
      // removed below, leaving collision alone. A node with no neighbour
      // inside its radius feels nothing and does not move, so the embedding
      // survives everywhere it is not degenerate, and the only places it gives
      // is where two points were drawn on top of each other anyway.
      //
      // Used as delivered. This multiplied by 40, which was a constant chosen
      // when the coordinates were whatever UMAP happened to emit -- so the
      // world size of the cloud moved with the corpus. `layout.py` centres
      // and scales to a known cube now, and a second scale here would only
      // put the guesswork back.
      x: n.pos[0],
      y: n.pos[1],
      z: (n.pos[2] ?? 0) * DEPTH,
      //: Where the FIT put this node, kept so drift off the embedding can be
      //: measured rather than assumed. Nothing reads it to draw.
      fitX: n.pos[0],
      fitY: n.pos[1],
      fitZ: (n.pos[2] ?? 0) * DEPTH,
      // The payload's own `val` when it has one, because a page node's size
      // is its CHUNK COUNT and it has no characters of its own. Deriving it
      // from `chars` gave every one of 96 pages the same radius -- a
      // 1,173-chunk reference index drawn as the same dot as a one-chunk
      // stub -- and the `val` the layout computed was simply discarded here.
      val: n.val ?? Math.max(1, Math.sqrt(n.chars)),
      //: The territory this node must stay inside, and the point it is
      //: measured from (`D-27`). Present only on what an unfolding
      //: produced; a page node owns the whole cloud and is bounded by
      //: nothing. `containWithin` is what enforces it.
      room: (n as any).room,
      anchorPos: (n as any).anchor,
      rank: n.rank,
      tokens: n.tokens ?? 0,
      // A page with no picture of its own shows its site's icon (G-81).
      // Planted (G-81): a page has NO picture, whatever supplies one -- the
      // layout's own image included, which the plant once left standing
      // and so removed nothing.
      image: (n.level === "page" && this.plantNoIcons) ? null
        : (n.level !== "page" && pictureFor(n.cid) ? { src: pictureFor(n.cid), alt: "" } : null)
        ?? n.image ?? ((n.level === "page" && n.url && !this.plantNoIcons) ? (() => {
        const src = faviconFor(n.url);
        return src ? { src, alt: "icon" } : undefined;
      })() : undefined),
      color: colourOf(n),
    };
  }

  private draw(canvas: HTMLElement, layout: Layout) {
    // **The previous graph is destroyed, not just unmounted.** `canvas.empty()`
    // removes its DOM, but a `ForceGraph3D` keeps its animation loop, its
    // hover raycasting and its WebGL context running on the detached canvas.
    // Every redraw -- a refit, a new projector epoch, a level or space toggle
    // -- leaked one. Measured after a day of them: the renderer held above a
    // full core with the pane showing an empty graph, profiled as WebGL draws
    // and `checkGeometryIntersection` from graphs nobody could see.
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.stopBatch();
    this.graph?._destructor?.();
    this.graph = null;
    canvas.empty();
    const nodes = layout.nodes.map((n) => this.nodeFrom(n));

    // **A page node is held at the position the fit gave it.**
    //
    // Where a page sits IS the corpus's statement about it -- that is the
    // whole of layer 1 -- so no force may relocate it. That was free while
    // the link force contributed nothing; with links pulling at 0.25 a hub
    // was measured **757.6 units** from its own anchor, dragging its open
    // page across the cloud and taking the meaning of its position with it.
    //
    // The allowance is a small multiple of the node's own size rather than
    // zero, so collision can still separate two pages the fit placed on top
    // of each other. Layer 2 does its fanning out INSIDE these territories;
    // layer 1 does not move.
    for (const n of nodes) {
      if (n.level !== "page" || (n as any).room) continue;
      (n as any).anchorPos = [n.fitX, n.fitY, n.fitZ];
      (n as any).room = Math.max(6, Math.cbrt(Math.max(n.val ?? 1, 1e-9)) * 2.5);
    }

    // How big a node should be, from the span it is drawn in and how many
    // there are -- not from a constant.
    //
    // This is why the pane looked empty at 3,136 chunks. Node radius is
    // `cbrt(val) * nodeRelSize`, `val` comes from a chunk's length, and the
    // 512-token window made every chunk shorter at the same time as the
    // record rule made them four times more numerous. So the cloud grew and
    // each node shrank, twice over: the renderer was drawing 390,000
    // triangles and lighting 1.5% of the pixels.
    //
    // Spacing comes from the FIT now, not from a formula about the cube.
    //
    // `2 * extent / cbrt(n)` is the spacing of a UNIFORM cloud, and UMAP does
    // not deliver one. Measured over the 3,135-node corpus: that formula says
    // 41.0 units and the real median nearest-neighbour distance is 0.76 --
    // a factor of 54 -- so every node was drawn overlapping dozens of others
    // and the pane read as a blob. The extent was already normalised; the
    // extent was never the problem.
    //
    // `layout.spacing.p50` is the projection's own scale. Sizing the median
    // node to just clear it means half the nodes clear their nearest
    // neighbour, which is the acceptance criterion R-J1 states. The median
    // and not p05: p05 is near-duplicate chunks off one page sitting on top
    // of each other, which is the projection being right, and sizing against
    // it would shrink every node on the page to hide a chunker problem.
    //
    // `cbrt(val)` runs about 2 to 4 across a corpus, so a diameter of
    // `2 * cbrt(val) * relSize` clears `p50` at the middle of that range when
    // relSize is `p50 / 6`. The old formula is the fallback for a sidecar too
    // old to send `spacing`, and for a fit so degenerate it reports zero.
    // Sized from the fit's OWN spacing, not from a formula about the cube.
    //
    // `2 * extent / cbrt(n)` is the spacing of a UNIFORM cloud, and UMAP does
    // not deliver one: over this corpus that formula says 41.0 units while
    // the real median nearest-neighbour distance is 0.76, a factor of 54. So
    // every node was drawn overlapping dozens of others. Rescaling the extent
    // cannot fix it -- `_framed` already normalises the extent, and the cloud
    // is still clumped inside it.
    //
    // The MEDIAN, not p05: p05 is near-duplicate chunks off one page landing
    // on each other, which is the projection being correct, and sizing against
    // it would shrink every node to hide a chunker problem (R-J3).
    //
    // Sized from the fit's OWN spacing, not from a formula about the cube.
    //
    // The camera no longer blocks it -- `frameDistance` below decoupled that,
    // and with both changes in place 100% of nodes are on screen AND the R-J1
    // ratio is 1.000. The blocker is that the honest size is INVISIBLE. At a
    // camera distance of 1529 framing a cloud of radius 380, one world unit
    // is 1.70 px, so a median node of 0.757 units draws at **0.45 px**.
    //
    // Legibility is two-sided and the renderer can only satisfy one side: the
    // node must clear its neighbour (diameter <= nn_p50) AND be visible
    // (diameter >= ~2 px). Neither held while the fit delivered a median
    // separation of 0.757 units -- an honest node drew at 0.44 px. It holds
    // now because `layout.py::_spread` equalises the axes: p50 is 5.657, so
    // the honest node draws at 2.46 px. Both sides, measured in the app.
    //
    // `cbrt(val)` runs about 2 to 4 across a corpus, so a diameter of
    // `2 * cbrt(val) * relSize` clears p50 at the middle of that range when
    // relSize is `p50 / 6`. The uniform-cloud formula stays as the fallback
    // for a sidecar too old to send `spacing`.
    const extent = layout.extent ?? 300;
    const uniform = (2 * extent) / Math.cbrt(Math.max(1, nodes.length));
    const measured = layout.spacing?.p50 ?? 0;
    // **/12, not /6, and the old number was self-defeating by arithmetic.**
    //
    // `cbrt(val)` runs about 2 to 4, so at /6 the diameter
    // `2*cbrt(val)*relSize` came out at 2*3*(p50/6) = p50 exactly: nodes
    // sized to TOUCH at the median spacing, which means every node closer
    // than the median overlaps, and half of them are closer than the median
    // by definition. Measured through the harness at page level: a drawn
    // radius of 39.3 px against a nearest-neighbour gap of 34.3 px, with
    // 86 of 97 nodes overlapping a neighbour.
    //
    // At /12 the median diameter is half the median gap, which leaves a
    // space a reader can see between things the projection says are
    // distinct -- which is what `G-4` and `G-21` actually ask for.
    const relSize = measured > 0
      ? Math.max(0.05, measured / 12)
      : Math.max(0.5, uniform / 8);

    const graph = new ForceGraph3D(canvas)
      .graphData({ nodes, links: layout.edges.map((e) => ({ ...e })) })
      .nodeLabel((n: any) => {
        // A merged node says how many chunks it stands for. Without it the
        // pane silently shows one node where the store holds eight, and a
        // reader comparing the two counts has no way to account for the
        // difference.
        const parts = n.members > 1 ? ` · ${n.members} chunks merged` : "";
        return `${n.name}${parts}<br><small>${n.url}</small>`;
      })
      // A hovered node is ringed white and keeps its own colour
      // underneath (`G-38`): the colour is a measurement, not a slot
      // to put a cursor in.
      .nodeColor((n: any) => (n.hovered ? "#ffffff" : n.color))
      .nodeRelSize(relSize)
      .nodeVal((n: any) => n.val)
      .linkOpacity(0.25)
      .linkWidth(0.5)
      // Edges are drawn by the batch's one line-segment set (`G-107`); the
      // per-link cylinders come back only under the planted arm.
      .linkVisibility(this.plantPerNode)
      .backgroundColor("rgba(0,0,0,0)")
      .onNodeClick((n: any) => {
        // A page or a branch unravels; a chunk opens (`G-54`). One gesture,
        // and which it means is a property of the node rather than of a mode
        // the reader has to remember they are in.
        if (n.level === "page" || n.level === "path") {
          // And it scopes the ranking to that shadow DOM (`G-70`). Clicking
          // a page is a statement about where the reader is looking, and the
          // overlay is the other half of that statement.
          if (n.level === "page" && n.url) this.onScope(n.url);
          // And the browser follows the click (`G-40`, `G-58`). A page node
          // navigates; a branch or chunk node also scrolls to its address.
          if (n.url) this.onReveal(n.url, n.path || "");
          void this.unfoldNode(n);
          return;
        }
        if (n.url) this.onReveal(n.url, n.path || "");
        // `G-57`: the panel opens HERE, beside the node, rather than taking
        // over an Obsidian pane. The pane remains what the structures look
        // like offline (`G-59`); it is no longer what a click in the
        // projector reaches for.
        void this.openBillboard(n);
      })
      // Right-click releases the scope (`G-70`): back to the corpus, from
      // wherever the reader had narrowed to.
      .onNodeRightClick(() => this.onScope(""));

    // A chunk that showed a picture looks like the thing it showed.
    //
    // Only when the reader has remote media on, and for the reason the
    // surface asks: fetching a page's assets from a vault tells those
    // hosts the page was read again, at a new time, from a new address.
    // A graph that quietly fetched a few hundred images the moment it
    // opened would be the loudest version of that.
    //: Read once and shared with the collider below. Asking twice invites the
    //: two to answer differently -- and a collider sizing spheres while the
    //: renderer draws panels is the defect `drawnRadius` documents.
    const media = this.media();
    // Streaming nodes are TRANSLUCENT (Addendum IX): "simple translucent
    // nodes to signify chunks that are part of a stream through the diff".
    //
    // `G-107`: every node is DRAWN by the scene batch (three draw calls for
    // the whole graph) and keeps only an invisible pick proxy here, so hover,
    // click and right-click still land on it. The per-node spheres, sprites
    // and cylinders it replaced -- ~1,800 draw calls at 2,467 nodes -- come
    // back only when G-107's check plants them.
    this.drawnMedia = media;
    graph.nodeThreeObject((n: any) => !this.plantPerNode ? this.pickProxy(n, relSize, media)
      : n.force ? this.streamingSphere(n)
      : (media ? this.billboard(n, relSize) : null));

    // Relax overlaps, and nothing else (`G-20`, `G-21`).
    //
    // This used to freeze the simulation outright -- `d3AlphaDecay(1)` with
    // `d3VelocityDecay(1)` -- on the ground that "the coordinates are already
    // the answer". They are, and they can still put two nodes in the same
    // place: a projection has no notion of how big a node is drawn, so any
    // embedding will overlap somewhere. Measured before this change, on a
    // 1,200-node sample of the live graph: 750 overlapping pairs, the worst
    // pair penetrating 3.72 world units and the closest two centres 0.195
    // apart when their radii together needed 2.6.
    //
    // The forces that would REWRITE the embedding are switched off rather
    // than tuned down. `charge` pushes every node from every other and would
    // inflate the cloud; `link` pulls edge-joined nodes together and would
    // draw a spring layout; `center` drags the whole cloud at once. With all
    // three contributing nothing the only force left is collision, which acts
    // on a node only when something is inside its radius -- so a node with
    // room keeps exactly the coordinates the fit gave it.
    graph.d3Force("charge", null);
    graph.d3Force("center", null);

    // The link force is NEUTERED, not removed -- and the difference is the
    // whole of whether edges draw at all.
    //
    // `d3-force-3d` documents link endpoints as "resolved to node object
    // references when the force is initialized", which makes `forceLink` the
    // id resolver as well as the spring. Removing it left all 2,961 links
    // holding their source and target as the strings the sidecar sent, so the
    // renderer had no coordinates to draw between and put zero line objects in
    // the scene: every patricia edge and every inter-note link silently
    // vanished, with no error anywhere, because nothing failed -- a string is
    // a perfectly good value to hold.
    //
    // Zero strength is the spring the goal forbids, turned off, while
    // initialization still runs and still resolves the endpoints.
    // **The link force pulls now, and the boundary is what makes that safe.**
    //
    // It was `strength(0)` -- initialized so endpoints resolve, contributing
    // nothing -- on the reasoning that a spring layout would rewrite the
    // embedding the fit computed. That reasoning was right while nothing
    // bounded a node: a spring could drag a chunk anywhere. `contain` now
    // holds every chunk inside its own page's territory however hard its
    // edges pull, so the spring can only arrange nodes WITHIN the region the
    // fit assigned them -- which is exactly the force-directed unfold the
    // goal asks for, and no longer a threat to the semantic placement.
    //
    // Distance from the two nodes' drawn radii rather than a constant: a
    // link between two big nodes needs more room than one between two small
    // ones, and a fixed length packed the large ones on top of each other.
    // Strength is modest and capped so a node with many children is not
    // torn apart by them.
    // **Reverted to zero, and the reason is worth keeping.**
    //
    // I turned this up to 0.25 with a radius-derived distance, reasoning
    // that `contain` now made a spring safe. It is safe -- nothing left its
    // territory -- and it is still wrong. A spring pulls every child to the
    // SAME distance from its parent, so a 31-branch unfolding was drawn to
    // a shell of equal radius around its hub: a cloud of nodes around one
    // url, which is what the reader saw and reported. Bounding the spring
    // stopped it escaping; it did not stop it flattening the structure
    // inside the bound.
    //
    // The local UMAP already says where these nodes go relative to each
    // other, and that statement is the thing worth drawing. A spring
    // overwrites it with "equidistant from the parent", which carries no
    // information at all. So the force contributes nothing and the edges
    // are drawn as lines over the fit -- which is what `strength(0)` meant
    // the first time, and the comment that survived this round trip should
    // now be read as load-bearing rather than cautious.
    graph.d3Force("link")?.strength(0);
    // The live node array, handed over by d3 at `initialize`.
    let containNodes: any[] = [];

    /**
     * **Home: the fit is an attractor, not just a starting point (`G-20`).**
     *
     * Measured on the sidecar's own unfold output, 31 branches: mean radius
     * 0.714 of the territory with sd 0.206, a coefficient of variation of
     * 0.289 -- a uniform ball, against the 0.259 a uniform ball gives. The
     * same unfolding in the pane read cv 0.13, so the ball was being turned
     * into a shell here.
     *
     * Nothing was holding a node anywhere. `forceCollide` pushes a node off
     * whatever it overlaps and has no opinion about the result; `contain`
     * pushes it back at the boundary. So a node shoved out of the interior
     * never came back and the equilibrium was every branch resting against
     * the inside of its territory.
     *
     * Weak on purpose. It has to yield to collision locally or two nodes the
     * projection put in the same place would stay there; it only has to win
     * over many ticks of aimless shoving. Applied to every node that carries
     * a fit coordinate, which is every node the sidecar placed.
     */
    const home: any = (alpha: number) => {
      // **Floored, for the same reason `contain` is, and it is the whole
      // point of this force.**
      //
      // `forceCollide` is a positional constraint: it acts at full strength
      // on every tick regardless of alpha. An alpha-scaled restoring force
      // therefore loses by construction -- it fades to nothing while the
      // thing it is meant to balance keeps shoving. Measured with it
      // alpha-scaled: the fit's uniform ball (mean/R 0.714, cv 0.289)
      // settled at 0.778 and cv 0.153, with a median node not moving at all
      // and the p90 moving 10.25 units. The median is blind to this, which
      // is why `fit_drift_p50` read 0 through the whole defect.
      // Tried floored, like `contain`, on the argument that collision is
      // alpha-independent and an alpha-scaled restoring force must lose to
      // it. Measured: the distribution did not move (cv 0.153 -> 0.149)
      // and 37 of 133 nodes went off screen, because a force that never
      // cools keeps feeding the camera a cloud that is still moving when it
      // frames. The argument may still be right; this implementation of it
      // is not, and a regression that big is not worth a 0.004 improvement.
      const k = this.plantScatter ? 0 : alpha * 0.55;
      for (const n of containNodes) {
        if (n.fitX === undefined) continue;
        n.vx = (n.vx ?? 0) + (n.fitX - (n.x ?? 0)) * k;
        n.vy = (n.vy ?? 0) + (n.fitY - (n.y ?? 0)) * k;
        n.vz = (n.vz ?? 0) + (n.fitZ - (n.z ?? 0)) * k;
      }
    };
    home.initialize = (nodes: any[]) => { containNodes = nodes || []; };
    graph.d3Force("home", home);
    // **The nested layer is bounded, and that is what makes it nested.**
    //
    // `layout._room_around` gives every unfolding a territory -- 0.45 of the
    // distance to the nearest other page -- and placing inside it was not
    // enough, because relaxation runs afterwards. Measured on RFC 9110, 31
    // branches placed inside a 33-unit ball: the collider pushed them out to
    // **102 units** against a 74-unit gap to the next page, so the unfolding
    // ended up on top of a page it has nothing to do with. Placement is a
    // starting condition; a boundary has to be a force.
    //
    // Radial and one-sided: a node inside its territory feels nothing at
    // all, so this cannot flatten the structure the local fit produced. A
    // node outside is pulled back to the surface, proportionally to how far
    // out it is, which resolves against the collider instead of fighting it
    // -- the two settle at a packing that fits rather than at a standoff.
    //
    // In trie terms: layer 1 gives every root a territory, and a patricia
    // step down from that root stays in it while the forces run.
    // **A d3 force, not a callback.** d3 calls `force.initialize(nodes)`
    // once when the simulation binds it and `force(alpha)` every tick, and
    // the node array it hands over is the live one. The first version of
    // this reached for `graph.graphData()` inside the tick instead, which
    // threw and took the whole projector down -- the pane drew nothing and
    // every check below reported "no projector", which reads exactly like a
    // dead plugin and was a dead force.
    const contain: any = (alpha: number) => {
      for (const n of containNodes) {
        const room = n.room;
        const at = n.anchorPos;
        if (!room || !at) continue;
        const dx = (n.x ?? 0) - at[0];
        const dy = (n.y ?? 0) - at[1];
        const dz = (n.z ?? 0) - at[2];
        const d = Math.hypot(dx, dy, dz);
        if (d <= room || d < 1e-6) continue;
        // Back to the SURFACE, not to the centre: pulling to the anchor
        // would collapse an unfolding into its own hub.
        // **Floored, not alpha-scaled.** A boundary that fades as the
        // simulation cools is a boundary only while nothing is settled,
        // which is the opposite of what it is for; the collider keeps
        // acting at every alpha and would walk a node out unopposed.
        const pull = ((d - room) / d) * Math.max(alpha, 0.35);
        n.vx = (n.vx ?? 0) - dx * pull;
        n.vy = (n.vy ?? 0) - dy * pull;
        n.vz = (n.vz ?? 0) - dz * pull;
      }
    };
    contain.initialize = (nodes: any[]) => { containNodes = nodes || []; };
    graph.d3Force("contain", contain);
    // Registered after `home` so both share the node array d3 hands over;
    // either one's `initialize` sets it and they are called with the same
    // list, but leaving that to registration order would be a trap for the
    // next change.


    const collideForce: any = forceCollide()
      // `G-21`: the drawn radius, plus a quarter of it as clearance. A
      // collider exactly the size of the sphere lets two nodes rest touching,
      // which reads as one shape; the margin makes a gap a reader can see
      // between things the projection says are distinct.
      // Force nodes (the pending diff) take no room: they must not shove
      // projected chunks off their transform positions, which pushed them
      // up to 23 units away with spikes past 300 while a diff was drawn
      // (S-7). The tree's own spring and charge space the force nodes.
      // A chunk on an open page's disc is PLACED, not collided: the disc is
      // already evenly spaced, and colliding with its own large page node at
      // the centre pushed the inner ring out to 1.46x the nearest page's
      // distance (G-94, 2026-09-27).
      .radius((n: any) => {
        if (n.force || this.plantNoCollide) return 0;
        const r = drawnRadius(n, relSize, media) * COLLIDER_SAFETY + COLLIDER_MARGIN;
        // A non-finite or absurd radius makes collision's first pass push by
        // Infinity and its second pass's octree hang (D-38): refused, recorded.
        if (Number.isFinite(r) && r >= 0 && r < 1e4) return r;
        this.nonFiniteCount++;
        if (this.nonFinite.length < 40) this.nonFinite.push({ at: Date.now(), radius: String(r), id: String(n.id).slice(0, 80),
          level: n.level, val: String(n.val), fullVal: String(n.fullVal), image: !!(n.image && n.image.src), mode: this.layoutMode });
        return COLLIDER_MARGIN;
      })
      // Soft and iterated rather than hard and once. `d3-force-3d` documents
      // collision as "by default a soft constraint with a configurable
      // strength and iteration count" to reduce jitter; a hard shove would
      // trade overlap for nodes visibly vibrating against each other.
      .strength(0.7)
      // ONE iteration per call; `gated` runs the iterations itself so the
      // octree check stands between them (D-38: the first iteration can throw
      // a coincident pair to Infinity, and the second builds its octree on it).
      .iterations(1);
    let collideIterations = 2;
    // **Only while the PROJECTED layout is changing.** Profiled on the reader's
    // store while the forum streamed (2026-09-28): the 3D loop held Obsidian's
    // main thread 11.4 s of 13 -- collision 5.0 s of it, every tick, over
    // ~1,000 nodes -- because each streaming update reheats the simulation and
    // collision ran through every one. Streaming nodes take no collision room,
    // and projected nodes already spaced do not need it again: it runs for 3 s
    // after a placement, a move by the fit, a resize or a collapse.
    let gatedNodes: any[] = [];
    const gated: any = (alpha: number) => {
      // What the stream is not changing holds still (calm, above).
      this.calm(gatedNodes);
      // EVERY tick, gate open or not: a non-finite position must never reach
      // an octree (D-38, below).
      this.sanitize(gatedNodes);
      // Vanishing velocities to exactly zero, so a coincident pair meets d3's
      // jiggle instead of a squared distance that underflows to 0 and a
      // divide that throws both to Infinity (octreeguard.flushTiny).
      this.octreeSkips.flushed += flushTiny(gatedNodes);
      if (!(this.plantAlwaysCollide || performance.now() < this.collideUntil)) return;
      // And never an octree over a node whose predicted position is not a
      // number -- one the simulation has not placed yet included, which
      // d3-octree inserts at the origin and then cannot separate -- checked
      // before EVERY iteration, not once per tick.
      for (let k = 0; k < collideIterations; k++) {
        if (!this.octreeOk(gatedNodes, "collide", true)) { this.sanitize(gatedNodes); break; }
        collideForce(alpha);
      }
    };
    gated.initialize = (...a: any[]) => { gatedNodes = a[0] || []; return collideForce.initialize(...a); };
    gated.radius = (...a: any[]) => { const r = collideForce.radius(...a); return a.length ? gated : r; };
    gated.strength = (...a: any[]) => { const r = collideForce.strength(...a); return a.length ? gated : r; };
    gated.iterations = (...a: any[]) => {
      if (!a.length) return collideIterations;
      collideIterations = Math.max(1, Math.floor(+a[0] || 1));
      return gated;
    };
    this.collideUntil = performance.now() + 3000;
    graph.d3Force("collide", gated);
    window.setTimeout(() => this.watchForces(), 0);

    // It has to be allowed to run, having been frozen. These are d3's own
    // defaults: the simulation cools over a few hundred ticks and stops.
    graph.d3AlphaDecay(0.0228).d3VelocityDecay(0.4);

    // **And it has to be REHEATED, or the collider never acts.**
    //
    // A layout arrives with every node at its fit coordinate and the
    // simulation already cool, so `forceCollide` -- the one force this
    // projector keeps -- had nothing to spend and separated nothing.
    // Measured: fit-to-drawn drift of exactly 0 with 57 of 97 nodes
    // overlapping a neighbour, which is a collider that is present, correct,
    // and asleep. The seeding the row asks for is the fit as a STARTING
    // point; without a reheat it was the finishing point too.
    graph.d3ReheatSimulation();
    this.graph = graph;
    this.calmFrom = performance.now() + 6000;
    graph.onEngineTick(() => this.govern());
    this.startBatch(graph, media);
    // The profiler's listener reads the scene through this, so "visible"
    // is decided by what is drawn and not by what `absorb` returned.
    profiler().graphSource = () => this.graph;
    profiler().graphView = () => this;

    // **And again when the forces settle.** The cap is measured against
    // where nodes ARE, and on insertion that is where the fit put them --
    // then collision and containment move them and the spacing it was
    // computed from is gone. Measured: applied once, world-space overlap
    // was 143 pairs of 92,235 with the median node still 1.3px inside its
    // neighbour.
    //
    // Bounded, so a node that shrinks and thereby lets its neighbour come
    // closer cannot start a cascade: it only ever shrinks, it has a floor,
    // and `settles` stops it re-running more than a few times per layout.
    let settles = 0;
    graph.onEngineStop(() => {
      if (settles >= 3) return;
      settles += 1;
      if (this.fitRadiiToSpacing()) settles += 0;
    });

    // Resizing the RENDERER is not resizing the CONTROLS, and missing the
    // second one leaves the graph unrotatable.
    //
    // `width`/`height` resize the canvas, the renderer and the camera frustum,
    // and that is all they do. `TrackballControls` keeps its own `screen` --
    // the box it maps pointer positions into -- captured when it was
    // constructed, which here is before the pane has been laid out at full
    // size. Measured on load: the canvas was 915x856 and `controls().screen`
    // was 450x225.
    //
    // The consequence is not a miscalibration, it is a dead control. The
    // trackball maps a pointer to a point on a unit circle by
    // `(x - screen.width/2 - screen.left) / (screen.width/2)`; with the width
    // roughly half of true, both ends of a drag map outside that circle and the
    // rotation between them comes out as nothing. Proved both ways against the
    // live view: with `screen` corrected a drag emitted 62 `change` events and
    // moved the camera from (-595,192,151) to (485,-135,401); with the stale
    // value planted back, the same drag emitted ZERO and the camera did not
    // move at all.
    //
    // So `handleResize` belongs in `fit`, where every other size-dependent
    // thing already is.
    // `controls()` is typed `object` by 3d-force-graph, because which control
    // class it returns depends on the `controlType` the graph was built with.
    // Narrowed to the one method needed, and guarded, rather than cast to
    // `any`: a future `controlType` without `handleResize` should skip it, not
    // throw on every resize.
    const trackball = () =>
      graph.controls() as { handleResize?: () => void };

    const fit = () => {
      graph.width(canvas.clientWidth).height(canvas.clientHeight);
      trackball().handleResize?.();
    };
    fit();
    this.registerEvent(this.app.workspace.on("resize", fit));

    // A `ResizeObserver` on the canvas, because `fit()` at construction is too
    // EARLY and the workspace event is too narrow.
    //
    // Called from here the first time, `handleResize` measures a canvas the
    // pane has not laid out yet: it read 1707x1019 against a box that settled
    // at 903x844 a moment later, so the controls were calibrated to the window
    // rather than to the canvas and rotation was dead for the same reason the
    // 450x225 value killed it. Calling it again later fixes it -- which is the
    // proof that the value is right and the MOMENT was wrong.
    //
    // `workspace.on("resize")` does not close the gap either. It fires for the
    // window, not for the things that actually change this canvas most often:
    // collapsing a sidebar, splitting a pane, dragging the divider between two
    // leaves. A ResizeObserver fires on the box itself, including the first
    // time it gets one, which is exactly the event that was missing.
    // Where the camera was last PUT, as opposed to where it is. The
    // difference is how the observer below tells "this pane has not been
    // looked at yet" from "the reader has orbited somewhere".
    let placed: { x: number; y: number; z: number } | null = null;
    const place = () => {
      try {
        const z = frameDistance();
        graph.cameraPosition({ x: 0, y: 0, z }, { x: 0, y: 0, z: 0 }, 0);
        placed = { x: 0, y: 0, z };
      } catch {
        /* an empty scene has nothing to fit */
      }
    };
    const untouched = () => {
      if (!placed) return true;
      const c: any = graph.cameraPosition();
      return Math.abs((c?.x ?? 0) - placed.x) < 1
          && Math.abs((c?.y ?? 0) - placed.y) < 1
          && Math.abs((c?.z ?? 0) - placed.z) < 1;
    };

    const observer = new ResizeObserver(() => {
      fit();
      // **Restart the animation loop, or the pane stays on its last frame.**
      //
      // Obsidian gives a background tab a 0x0 box, and the renderer's loop
      // does not come back when the box does: measured through the harness,
      // `renderer.info.render.frame` sat at 1 across 1.5 seconds -- zero
      // frames -- on a pane reporting 97 nodes on screen, 97 in frustum and
      // 98 visible scene objects. A render forced by hand drew all of them,
      // 98 calls and 1,758 triangles, so the scene and the camera were
      // never the problem. The canvas was simply never painted again after
      // being resized to nothing and back, which is the blank projector.
      //
      // It is also why `forceCollide` never separated anything: d3's tick
      // runs inside this same loop, so a dead loop is a frozen simulation,
      // and the drift off the fit measured exactly 0 every time.
      // `resumeAnimation()` ALONE IS A NO-OP here: the library still
      // believes its cycle is running and returns without scheduling one.
      // Pausing first gives the resume something to undo. Measured through
      // the harness -- frames 1 -> 1 over 1.5s with resume alone, and
      // 1 -> 208 with the pair.
      try {
        const gg = graph as any;
        gg.pauseAnimation?.();
        gg.resumeAnimation?.();
        // And the simulation cooled to nothing while the loop was dead, so
        // the collider has no energy to spend separating anything. This is
        // what made `fit_drift` measure exactly 0 on every sample.
        gg.d3ReheatSimulation?.();
      } catch { /* older build */ }
      // Re-frame, but only while the reader has not moved the camera. The
      // first placement runs on a timer against a canvas the pane may not
      // have laid out, so the box that matters usually arrives AFTER it --
      // and re-framing a view someone has orbited into would take their
      // position away every time a sidebar moved.
      if (untouched()) place();
    });
    observer.observe(canvas);
    this.resizeObserver = observer;

    // Frame the cloud once it exists.
    //
    // The camera is PLACED first, then fitted, and the order is the fix.
    // `zoomToFit` only moves the camera along the direction it is already
    // looking -- it changes distance, never position relative to the scene --
    // so a camera that has ended up inside the cloud is "fitted" from inside
    // it and stays there. Measured: the camera sat at z = -230 with the cloud
    // spanning +/-249, and fitting again at four different node sizes left it
    // at -230, -232, -234, -239. From inside a sparse cloud a viewer sees
    // essentially nothing, which is exactly the report this fixes.
    //
    // Placing it on the +z axis at a distance set by the cube the layout
    // delivers -- which `layout.py` now guarantees -- means the fit always
    // starts from outside, looking at the centre.
    //
    // And then NOT calling `zoomToFit`, which undid it.
    //
    // `zoomToFit` frames node bounding SPHERES, so the distance it picks is a
    // function of node RADIUS, not of where the nodes are. Measured over CDP
    // on this corpus: at `nodeRelSize` 5.124 it settled the camera at 148.9,
    // and at 0.126 it settled at 3.67 -- 40.6x apart, the same 40.6x as the
    // radii, and in both cases the rendered node came out at 278.9 px. It is
    // a servo that holds apparent node size constant, which is the wrong
    // invariant for framing a cloud: with the cloud spanning +/-300 it put
    // the camera INSIDE, and nodes projected to (1076, 1029) and (1323, 1718)
    // against a 518 x 840 canvas -- 0 of 3,135 on screen. That is the "3D
    // projector has no viewable nodes" report, still true.
    //
    // Framed from the DATA instead. The layout centres on the origin, so the
    // cloud's radius is the furthest node from it, and the distance that puts
    // a sphere of that radius inside the frustum is `R / sin(half-angle)`.
    // The binding angle is the smaller of the two: the vertical fov is what
    // three.js stores, and the horizontal one is narrower whenever the pane
    // is taller than it is wide, which in a sidebar it usually is.
    const frameDistance = () => {
      const pts = graph.graphData().nodes as any[];
      // The bounding BOX, not the bounding sphere.
      //
      // This measured `hypot(x, y, z)` -- the radius of the sphere that
      // contains everything -- and placed the camera to fit that sphere. It
      // is correct and it wastes most of the frame: a cloud filling a cube of
      // half-width 316 has a bounding sphere of radius 511, √3 larger, so the
      // picture occupied about a third of the pane by area and read as a
      // small clump in a large empty canvas.
      //
      // The box fits by axis instead. A point at (x, y, z) seen from (0, 0, d)
      // is `d - z` along the view axis, so it is inside horizontally when
      // `|x| <= (d - z)·tan(hfov/2)`. Taking the worst case on each axis
      // gives the distance below, which cannot clip and does not over-frame.
      let mx = 0;
      let my = 0;
      let mz = 0;
      for (const p of pts) {
        mx = Math.max(mx, Math.abs(p.x ?? 0));
        my = Math.max(my, Math.abs(p.y ?? 0));
        mz = Math.max(mz, Math.abs(p.z ?? 0));
      }
      let r = Math.max(mx, my, mz);
      if (!(r > 0)) { r = extent; mx = my = mz = extent; }
      const cam: any = graph.camera();
      const vfov = ((cam?.fov ?? 50) * Math.PI) / 180;
      const aspect = Math.max(0.01, canvas.clientWidth / Math.max(1, canvas.clientHeight));
      const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
      // A canvas with no size yet gives a degenerate aspect, and a
      // degenerate aspect gives a tiny horizontal fov, and a tiny fov puts
      // the camera absurdly far away. Measured: a cloud of radius 317 framed
      // at 1,989 -- six times the right distance -- because the placement ran
      // 250ms after construction, before the pane had laid the canvas out.
      // Below a usable box the aspect is treated as square, which is wrong by
      // a little rather than by a factor of six, and the observer below
      // re-frames as soon as the real box arrives.
      const usable = canvas.clientWidth > 2 && canvas.clientHeight > 2;
      const half = usable
        ? Math.max(0.01, Math.min(vfov, hfov) / 2)
        : Math.max(0.01, vfov / 2);
      // 1.12 leaves a margin so the outermost nodes are not clipped by their
      // own radius, which this calculation deliberately does not know about.
      const horizontal = mx / Math.tan(usable ? hfov / 2 : vfov / 2);
      const vertical = my / Math.tan(vfov / 2);
      return (Math.max(horizontal, vertical) + mz) * 1.12;
    };

    /**
     * How much of the canvas the cloud actually covers, at the camera's
     * current position. Fraction of width and of height, 0..1.
     *
     * Only nodes in FRONT of the camera count. One behind it projects to a
     * perfectly ordinary screen point, and including those is how the live
     * checks once reported 97 of 97 nodes on screen while the pane was
     * blank.
     */
    const screenCoverage = (): { w: number; h: number } | null => {
      const g: any = graph;
      const cam: any = g.camera?.();
      const pts = g.graphData().nodes as any[];
      if (!cam || !pts.length) return null;
      const W = canvas.clientWidth;
      const H = canvas.clientHeight;
      if (!(W > 2 && H > 2)) return null;
      cam.updateMatrixWorld?.();
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      let seen = 0;
      for (const n of pts) {
        const v = new (cam.position.constructor as any)(
          n.x ?? 0, n.y ?? 0, n.z ?? 0);
        v.project(cam);
        // `project` divides by w; a point behind the camera comes back with
        // z outside [-1, 1], which is the cheap form of the same test.
        if (!(v.z > -1 && v.z < 1)) continue;
        seen += 1;
        const sx = (v.x * 0.5 + 0.5) * W;
        const sy = (-v.y * 0.5 + 0.5) * H;
        if (sx < minX) minX = sx;
        if (sx > maxX) maxX = sx;
        if (sy < minY) minY = sy;
        if (sy > maxY) maxY = sy;
      }
      if (seen < 2 || !isFinite(minX)) return null;
      return { w: (maxX - minX) / W, h: (maxY - minY) / H };
    };

    /**
     * Close the gap between the framing the formula predicted and the
     * picture it produced.
     *
     * `target` is how much of the smaller canvas dimension the cloud should
     * fill. Not 1.0: a node is drawn with a radius the projection does not
     * know about, and a billboard is drawn wider still.
     */
    const tighten = (target = 0.88, steps = 2) => {
      const g: any = graph;
      for (let i = 0; i < steps; i++) {
        const cover = screenCoverage();
        if (!cover) return;
        const filled = Math.max(cover.w, cover.h);
        if (!(filled > 0.01)) return;
        const ratio = filled / target;
        // Already close enough; another step would only jitter the camera.
        if (ratio > 0.92 && ratio < 1.08) return;
        const cam: any = g.cameraPosition();
        const d = Math.hypot(cam.x ?? 0, cam.y ?? 0, cam.z ?? 0);
        if (!(d > 0)) return;
        // Screen span goes as 1/d, so scaling the distance by the shortfall
        // is the step that lands on target.
        let next = d * Math.min(1.6, Math.max(0.55, ratio));
        // **Never inside the cloud.** This is the guard the previous attempt
        // at this did not have, and it is why the pane went empty.
        const pts = g.graphData().nodes as any[];
        let frontmost = 0;
        for (const n of pts) frontmost = Math.max(frontmost, n.z ?? 0);
        const floor = frontmost + Math.max(20, frontmost * 0.15);
        if (next < floor) next = floor;
        g.cameraPosition({ x: 0, y: 0, z: next }, { x: 0, y: 0, z: 0 }, 0);
      }
    };

    window.setTimeout(() => { place(); window.setTimeout(tighten, 120); }, 250);

    // The same thing, on demand. A reader who has orbited into the middle of
    // the cloud has no way back otherwise, and "the graph went blank" is not
    // a state anyone should have to recognise.
    /**
     * Frame a SUBSET -- what an expansion just opened (`G-54`, `G-4`).
     *
     * **Why an expansion has to move the camera.** The nesting is
     * scale-wise on purpose: a page's contents live inside that page's
     * territory, which is a small part of the corpus by construction.
     * Measured with eight pages open: 430 nodes, and `rfc9110`'s 161 of
     * them inside a 48.6-unit ball while the cloud's radius is 472 -- about
     * 40 screen pixels for 161 nodes. The median node overlapped its nearest
     * neighbour by 3.3px and 333 of 430 touched one. No layout change fixes
     * that, because the layout is right: the picture was showing the whole
     * corpus while the reader was asking about one page.
     *
     * So opening a page frames it. `reframe` remains the way back out.
     */
    const frameOn = (subset: any[]) => {
      if (!subset || subset.length < 2) return;
      let cx = 0, cy = 0, cz = 0;
      for (const n of subset) { cx += n.x ?? 0; cy += n.y ?? 0; cz += n.z ?? 0; }
      cx /= subset.length; cy /= subset.length; cz /= subset.length;
      let mx = 0, my = 0, mz = 0;
      for (const n of subset) {
        mx = Math.max(mx, Math.abs((n.x ?? 0) - cx));
        my = Math.max(my, Math.abs((n.y ?? 0) - cy));
        mz = Math.max(mz, Math.abs((n.z ?? 0) - cz));
      }
      const cam: any = graph.camera();
      const vfov = ((cam?.fov ?? 50) * Math.PI) / 180;
      const aspect = Math.max(0.01,
        canvas.clientWidth / Math.max(1, canvas.clientHeight));
      const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
      const d = (Math.max(mx / Math.tan(hfov / 2),
                          my / Math.tan(vfov / 2)) + mz) * 1.18;
      // **Never inside the subset.** The guard that was missing the first
      // time a camera change emptied this pane.
      const safe = Math.max(d, mz + Math.max(20, mz * 0.2));
      graph.cameraPosition({ x: cx, y: cy, z: cz + safe },
                           { x: cx, y: cy, z: cz }, 600);
    };
    this.frameOn = frameOn;

    this.reframe = () => {
      placed = null;              // an explicit reframe is always wanted
      graph.cameraPosition({ x: 0, y: 0, z: frameDistance() },
                           { x: 0, y: 0, z: 0 }, 400);
      // After the flight, not during it: the camera is animating for 400ms
      // and a measurement taken mid-flight frames the halfway point.
      window.setTimeout(() => {
        // Open pages' discs face the camera again (G-94).
        const d: any = graph.graphData();
        this.fitChunkSizes(d);
        graph.d3ReheatSimulation?.();
        tighten();
      }, 450);
    };
    this.keepBillboards(canvas);
  }

  /**
   * Open billboards SURVIVE a redraw (`G-78`: a pinned chunk's billboard
   * "persists with" its pin).
   *
   * `draw()` empties the canvas, and the billboard layer is a child of it.
   * The view kept its reference to the detached layer, so after any redraw --
   * a refit, a new epoch, a level toggle, a store switch -- every billboard
   * already open vanished and every one opened afterwards was built off
   * screen: the entry existed, `inDom` was false, and there was no x to
   * press (G-78 read pins 1 / billboards 1 after "closing" it, 2026-09-26).
   * The layer goes back on top of the new canvas, and each billboard is
   * re-pointed at its node in the new graph -- a node object from the old
   * one no longer moves.
   */
  private keepBillboards(canvas: HTMLElement): void {
    if (!this.billboardLayer) return;
    canvas.appendChild(this.billboardLayer);
    const byId = new Map<string, any>(
      (this.graph?.graphData().nodes || []).map((n: any) => [n.id, n]));
    for (const [id, entry] of this.billboards.entries() as any) {
      const fresh = byId.get(id);
      if (fresh) entry.node = fresh;
    }
    if (this.billboards.size) this.startBillboardLoop();
  }
}
