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
 * The placement is not computed here. `vertiscope/obsidian/layout.py` fits it,
 * because the vectors, numpy and UMAP already live in Python and a projection
 * fitted twice in two languages is two projections. This asks for coordinates
 * and draws them.
 */

import { spreadFactor } from "./spread.ts";
import { unitOf, lineAddr, inUnit } from "./address.ts";
import { centredTelescope, relaxCloud, zoomFor, similarityFit, similarityInverse, rotateInverse, type V3 } from "./camera";
import { profiler } from "./profile";
import { ItemView, MarkdownRenderer, WorkspaceLeaf, requestUrl } from "obsidian";
import ForceGraph3D, { ForceGraph3DInstance } from "3d-force-graph";
// `d3-force-3d` is what `3d-force-graph` runs its simulation on, so this is
// the same module instance the graph already uses -- not a second copy whose
// forces the graph would ignore.
import { forceCenter, forceCollide, forceManyBody } from "d3-force-3d";
import type { ForceNodeDelta } from "./forcetree";
import type { CentralDiff } from "./types";
import * as THREE from "three";
import { NodeLook, Picture, SceneBatch } from "./scenebatch";
import { flushTiny, octreeVerdict } from "./octreeguard";
import { MotionRecorder } from "./motion";

import { Sidecar } from "./sidecar";
import { ChunkSurface, SurfaceHost } from "./surface";
import { baseFor, faviconFor, getSnapshot, pictureFor, putSnapshot, renderSnapshot } from "./snapshot";
import type { ActRecord, ActResult } from "./panelact";
import { PANEL_VIEW, PanelView } from "./panelview";
import { SearchField, brightness, fade, holdStep, type FieldHit, type FieldAnswer } from "./searchfield";

export const GRAPH_VIEW = "vertiscope-graph-view";

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

/** Pictures drawn at once: the nodes nearest the pointer's ray (`refreshDetail`). */
const DETAIL_PICTURES = 64;
/** The least share of its drawn radius a node keeps when spacing shrinks it. */
const MIN_SPACING_SHARE = 0.3;

export class GraphView extends ItemView {
  /** Put the camera back outside the cloud, looking at the middle. */
  private reframe: (() => void) | null = null;
  /** Planted (item 116): every framing aims at the origin, as before. */
  plantOriginFrame = false;
  /** How much of the pane the cloud fills and how far off-centre it sits. */
  screenCoverage: (() => { w: number; h: number; dx: number; dy: number } | null) | null = null;
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
    /** Opened by a hover (a preview): it passes the pointer through (`G-243`). */
    fromHover?: boolean;
    minimized?: boolean;
    openedAt?: number;
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
  getDisplayText() { return "vertiscope 3D graph"; }
  getIcon() { return "git-fork"; }

  async onOpen() {
    const root = this.containerEl.children[1] as HTMLElement;
    root.empty();
    root.addClass("vertiscope-graph-root");

    const bar = root.createDiv({ cls: "vertiscope-graph-bar" });
    const status = bar.createSpan({ cls: "vertiscope-graph-status",
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
    // G-196 (2026-10-17: "a toggle to switch on and off the panels always
    // opening on fly-to nodes and instead opening when a right-click action
    // is made"). Remembered per viewer; the fly itself is unchanged.
    const panels = bar.createEl("button", { text: this.panelsOn === "rightclick" ? "panels: right-click" : "panels: fly-to" });
    panels.onclick = () => {
      this.setPanelsOn(this.panelsOn === "rightclick" ? "flyto" : "rightclick");
      panels.setText(this.panelsOn === "rightclick" ? "panels: right-click" : "panels: fly-to");
    };
    // G-241: the code graph's edges, drawn between the chunks of an open
    // code page -- each kind its own colour and its own switch.
    // Shown only while a code page is open: on web pages they switch nothing
    // (2026-10-18: "what are the inherits and calls buttons for?").
    for (const kind of ["CALLS", "INHERITS"] as const) {
      const b = bar.createEl("button", { text: (this.codeEdgeKinds[kind] ? "" : "no ") + kind.toLowerCase() });
      b.setAttr("title", kind === "CALLS"
        ? "Code graph: draw a function's calls (orange) between the chunks of an open code page"
        : "Code graph: draw a class's base classes (green) between the chunks of an open code page");
      b.style.display = "none";
      this.codeEdgeButtons.push(b);
      b.onclick = () => {
        this.codeEdgeKinds[kind] = !this.codeEdgeKinds[kind];
        b.setText((this.codeEdgeKinds[kind] ? "" : "no ") + kind.toLowerCase());
        this.batchDirty = true;
      };
    }
    const geometry = bar.createEl("button", { text: "euclidean" });
    geometry.onclick = () => {
      this.space = this.space ? "" : "S3";
      geometry.setText(this.space ? "S³" : "euclidean");
      void load();
    };

    const canvas = root.createDiv({ cls: "vertiscope-graph-canvas" });
    // The billboards hang off the CANVAS, not the pane.
    // `graph2ScreenCoords` answers in the canvas's own coordinates,
    // and the caption bar sits above it -- anchoring to the pane would
    // have drawn every panel one bar-height below its node.
    this.canvasEl = canvas;
    // The reader moving the camera, for holding stream deltas (G-227).
    const moved = () => { this.camMovedAt = performance.now(); };
    canvas.addEventListener("wheel", moved, { passive: true, capture: true });
    canvas.addEventListener("pointermove", (e) => { if (e.buttons) moved(); }, { passive: true, capture: true });
    // Arrow keys pan, precisely, while the pointer is over the 3D view and no
    // text field has the keyboard (2026-10-12, PLUGIN_GOAL 114). A held key
    // steps faster the longer it is held, as the k/n fields do (item 109).
    canvas.addEventListener("pointerenter", () => { this.pointerOver = true; });
    canvas.addEventListener("pointerleave", () => { this.pointerOver = false; });
    this.registerDomEvent(window, "keydown", (e: KeyboardEvent) => this.arrowPan(e));
    this.registerDomEvent(window, "keyup", (e: KeyboardEvent) => { if (e.key.startsWith("Arrow")) this.panHeldSince = 0; });
    // The naked search field, middle-bottom of the 3D panel (PLUGIN_GOAL 84).
    this.searchField = new SearchField(canvas, (q, k) => this.searchAsk(q, k),
                                       (hits, d, soft) => this.showSearch(hits, d, soft), () => this.clearSearch());
    // The web half on the search BUTTON (and Enter) only -- typing never
    // reaches the browser cell (item 107).
    this.searchField.onSubmit = (q) => { this.searchStats.web_asked++; this.onWebSearch(q); this.followStore(q); };
    // The results strip (G-222): each item named as its node is, and a hover
    // on one takes the hover's own path -- the stored node placed if it is
    // not drawn, flown to, its panel opened (PLUGIN_GOAL 151: "hovering scroll
    // results includes the fly-to-node feature").
    this.searchField.labelOf = (h) => {
      // The result's OWN words first: a url names its page, and two pages
      // held every result -- each item read "duckduckgo.com/" (2026-10-18).
      const line = String(h.preview || "").split(String.fromCharCode(10)).map((x) => x.replace(/[#*>`_\[\]]/g, "").trim()).find((x) => x.length >= 3);
      if (line) return line.slice(0, 60);
      const n: any = this.graph ? (this.graph.graphData() as any).nodes.find((x: any) => x.id === h.cid) : null;
      const t = n && (n.name || n.title);
      if (t) return String(t).slice(0, 60);
      try { const u = new URL(h.url); return (u.hostname + u.pathname).slice(0, 60); } catch { return h.url.slice(0, 60); }
    };
    this.searchField.onHoverHit = (h) => {
      if (!h) { this.focusOn(null); this.hoverPanel(null); this.unspread(); return; }
      this.searchStats.strip_hovers++;
      this.spreadUrl(h.url);
      // The node the search lit for this hit -- its chunk when drawn, else
      // its page (`resolveSearch`) -- flown to as the top result is; a chunk
      // also opens its panel. `highlightChunk` flies only to a DRAWN chunk,
      // and in url view a result's chunk is not drawn: no flight at all.
      const st = this.searchState;
      const i = st ? st.hits.findIndex((x) => x.cid === h.cid) : -1;
      const n = i >= 0 ? st!.targets[i] : null;
      if (!n) { this.highlightChunk(h.cid, h.url, h.cid); return; }
      this.focusOn(n);
      // The panels toggle governs the strip as it governs the browser hover
      // (G-232, PLUGIN_GOAL 161): right-click mode flies without a panel.
      if (this.panelsOn === "rightclick" && !this.plantStripIgnoresToggle) { this.panelModeStats.strip_flown++; return; }
      // Planted: the hover opens its panel whatever the toggle, as before.
      // Straight to the panel: `hoverPanel` checks the mode too, and the
      // planted arm went through it and could never fail (2026-10-18).
      if (this.plantStripIgnoresToggle && this.panelsOn === "rightclick") { void this.openBillboard(this.stripTarget(h, n), false, true); return; }
      this.hoverPanel(this.stripTarget(h, n));
    };
    this.searchField.onRightHit = (h) => {
      const st = this.searchState;
      const i = st ? st.hits.findIndex((x) => x.cid === h.cid) : -1;
      const n = i >= 0 ? st!.targets[i] : null;
      if (!n) return;
      this.panelModeStats.strip_right++;
      void this.openBillboard(this.stripTarget(h, n));
    };
    // Tiered retrieval (G-210): url nodes first, then each url's chunks.
    this.searchField.tiers = {
      pages: async (q, k) => {
        const got: any = (await this.sidecar.searchPages(q, k)) || { pages: null };
        this.tierMatching = { q, n: typeof got.matching === "number" ? got.matching : null };
        return got.pages;
      },
      matching: (q) => (this.tierMatching && this.tierMatching.q === q ? this.tierMatching.n : null),
      page: async (q, url, k) => {
        const got: any = await this.sidecar.search(q, { k, url });
        return got ? { hits: (got.hits || []).map((h: any) => ({ cid: String(h.cid), url: String(h.url || ""), score: Number(h.score) || 0,
                                                                  preview: String(h.preview || "") })),
                       n: Number(got.n) || 0 } : null;
      },
    };

    const load = async () => {
      // Not over the force tree's caption: a retry every 3 s wrote
      // "fitting…" across a pane that was drawing (`G-89`).
      // "loading", not "fitting": this reads stored positions; a fit is
      // reported only when the sidecar says one is running (PLUGIN_GOAL 108).
      if (this.layoutMode !== "force") status.setText("loading…");
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
      const epochWas = this.projEpoch;
      this.projEpoch = layout.source === "projector" ? (layout.epoch ?? -1) : -1;
      // A full refit landed (a new epoch, not the first): the stage of the page
      // being browsed, with the fit's own identity as provenance.
      if (epochWas > 0 && this.projEpoch > 0 && this.projEpoch !== epochWas && this.browsingUrl) {
        profiler().mark(this.browsingUrl(), "refit", { epoch: this.projEpoch, fit_sample: (layout as any).projector?.fit_sample ?? null });
      }
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
                 /** `jitter` without each node's ONE move to its fit (G-93 calm). */
                 jitterHeld: [] as number[],
                 /** That one move, per update: how far projected nodes glided (radii x RADIUS). */
                 glide: [] as number[],
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
    g.d3AlphaDecay(0.0228).d3VelocityDecay(0.4).d3AlphaMin(this.plantNoAlphaMin ? 0 : 0.001);
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
    let moved = 0, n = 0, movedHeld = 0, nHeld = 0, glided = 0, nGlided = 0;
    for (const x of nodes) {
      if (!x.force || fresh.has(x.id) || !Number.isFinite(x.x)) continue;
      if (x.lastAt) {
        const d = Math.hypot(x.x - x.lastAt[0], x.y - x.lastAt[1], (x.z ?? 0) - x.lastAt[2]);
        moved += d;
        n++;
        // A node whose projection landed since the last update made its one
        // designed move -- grey force place to its fit (PLUGIN_GOAL 48). G-93's
        // "too chaotic between scan updates" is the OTHER motion: re-shaking.
        // Both are kept; the calm bar reads the second.
        if (x.projectedAt && x.projectedAt > (x.lastAtT ?? 0)) { glided += d; nGlided++; }
        else { movedHeld += d; nHeld++; }
      }
      x.lastAt = [x.x, x.y, x.z ?? 0];
      x.lastAtT = now;
      if (this.plantNoHold) continue;
      x.holdAt = [x.x, x.y, x.z ?? 0];
      x.holdUntil = now + 1500;
    }
    if (n) {
      this.forceStats.jitter.push(moved / n);
      if (this.forceStats.jitter.length > 500) this.forceStats.jitter.shift();
    }
    if (nHeld) {
      this.forceStats.jitterHeld.push(movedHeld / nHeld);
      if (this.forceStats.jitterHeld.length > 500) this.forceStats.jitterHeld.shift();
    }
    if (nGlided) {
      this.forceStats.glide.push(glided / nGlided);
      if (this.forceStats.glide.length > 500) this.forceStats.glide.shift();
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
  /**
   * A drain's delta, held while the reader's camera is MOVING and applied in
   * one batch when it rests (2026-10-17, PLUGIN_GOAL 156: "zooming lags
   * heavily for throughput streams (maybe some throttling here)"): each delta
   * rebuilds the graph's data, and one per drain landed between zoom frames.
   * Held at most `DELTA_DEFER_MAX_MS`, so the stream never waits on a zoom
   * that does not end. Planted `plantNoDeltaDefer`: every delta at once.
   */
  forceDelta(d: ForceNodeDelta): void {
    if (this.plantNoDeltaDefer) { this.applyForceDelta(d); return; }
    if (!this.deltaQueue.length) this.deltaQueuedAt = performance.now();
    this.deltaQueue.push(d);
    if (this.deltaTimer) return;
    const flush = () => {
      this.deltaTimer = 0;
      const now = performance.now();
      if (now - this.camMovedAt < 250 && now - this.deltaQueuedAt < GraphView.DELTA_DEFER_MAX_MS) {
        this.deltaStats.deferred++;
        this.deltaTimer = window.setTimeout(flush, 120);
        return;
      }
      const q = this.deltaQueue;
      this.deltaQueue = [];
      if (q.length > 1) this.deltaStats.batched += q.length - 1;
      for (const x of q) this.applyForceDelta(x);
    };
    this.deltaTimer = window.setTimeout(flush, 0);
  }
  static DELTA_DEFER_MAX_MS = 1500;
  private deltaQueue: ForceNodeDelta[] = [];
  private deltaQueuedAt = 0;
  private deltaTimer = 0;
  /** When the READER last moved the camera (wheel, drag) -- not the idle turn. */
  camMovedAt = 0;
  deltaStats = { deferred: 0, batched: 0 };
  plantNoDeltaDefer = false;

  private applyForceDelta(d: ForceNodeDelta): void {
    if (d && d.url && d.added && d.added.length) profiler().mark(d.url, "grey", { nodes: d.added.length });
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
                                  cid, stale: !!a.again, born: Date.now(), branch: !!(a as any).branch } as any);
      if (a.parent) {
        this.life.nodes.set(a.id, { url: d.url, drawnAt: Date.now(), cid });
        if (this.life.nodes.size > 20000) this.life.nodes.delete(this.life.nodes.keys().next().value as string);
      }
      // A page the reader folded by right-click keeps its diff pending, not
      // drawn: the page node alone stands for it (`collapsedByReader`).
      if (!drawHere || (a.parent && this.readerCollapsed(d.url))) continue;
      // The chunk's trie parent, drawn with its missing ancestors (G-116):
      // a branch announced while the page was folded, or pruned since, was
      // not drawn, and the chunk fell back to the page node -- johnwick's
      // stream read 13/13 on the page with the skeleton built.
      const ensure = (id: string, depth = 0): string => {
        if (!id || depth > 40) return "";
        if (byId.has(id)) return id;
        const br = d.branches ? d.branches[id] : undefined;
        if (!br) return "";
        const up = ensure(br.parent, depth + 1) || (pageNode ? pageNode.id : "");
        const pu = up ? byId.get(up) : null;
        const bn: any = { id, level: "path", name: br.title || id, url: d.url, members: 1, tokens: 0,
                          force: true, branch: true, val: 0.35, color: "#5f6368",
                          x: (pu?.x ?? 0) + (Math.random() - 0.5) * 8, y: (pu?.y ?? 0) + (Math.random() - 0.5) * 8,
                          z: (pu?.z ?? 0) + (Math.random() - 0.5) * 8 };
        nodes.push(bn);
        byId.set(id, bn);
        if (up) links.push({ source: up, target: id, force: true });
        this.forceSpecs.set(id, { parent: br.parent, url: d.url, title: br.title, lines: 0, branch: true } as any);
        return id;
      };
      const to = a.parent ? (ensure(a.parent) || this.parentFor(a.parent, d.url, byId, pageNode)) : "";
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
      // A branch of the page's patricia trie: a small interior node the
      // stream's chunks hang from (`ForceTree.skeleton`, G-116).
      const branch = !!(a as any).branch;
      const n: any = {
        id: a.id, level: page ? "page" : branch ? "path" : "chunk", name: a.title || a.id,
        url: d.url, members: 1, tokens: 0, force: true, branch,
        val: page ? 3 : branch ? 0.35 : 1,
        color: page ? "#8ab4f8" : branch ? "#5f6368" : "#9aa0a6",
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
      const bySource = new Map<string, Set<any>>();
      for (const l of links) {
        const s = l.source, t = l.target;
        if (!t || !t.force || typeof s !== "object") continue;
        // A streamed chunk the fit has already placed is not sprung back
        // toward its parent: the fit says where it goes (PLUGIN_GOAL 48).
        if (t.projected) continue;
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
        // Grouped by PAGE, not by parent: since the stream draws the trie's
        // branches (G-116) a page's chunks hang under many parents, and
        // cousins under neighbouring branches were never kept apart -- G-93
        // measured 82 of 126 streamed nodes overlapping, nn p10 0.1 radii
        // (2026-10-07), where it passed with every chunk a sibling.
        const group = STREAM.LEGACY ? s.id : (t.url || s.id);
        let kids = bySource.get(group);
        if (!kids) { kids = new Set(); bySource.set(group, kids); }
        kids.add(t);
        if (!STREAM.LEGACY && s.force && s.url === t.url) kids.add(s);
      }
      // A PAGE's streamed nodes apart: with no charge and no collision room,
      // the spring alone let force nodes under one parent settle on one point
      // (G-4 counted 8 coincident nodes). Short-range and among force nodes
      // only, so nothing the projector placed is touched.
      const clear = STREAM.LEGACY ? 8 : 2 * STREAM.RADIUS * STREAM.SAFETY + STREAM.MARGIN;
      for (const kidSet of bySource.values()) {
        const kids = [...kidSet];
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
    // A chunk the store already held before this visit (the central diff's
    // `known`) is drawn from the store, never a new streaming node.
    for (const [id, cid] of Object.entries(covers)) {
      if (cid && this.knownCids.has(cid) && this.forceSpecs.has(id)) saved.add(id);
    }
    // Planted by G-92's check: the old order, collapse only once projected.
    if (this.plantLateCollapse) { this.collapseCovered(); return; }
    if (saved.size) this.foldIn(saved);
    this.collapseCovered();
  }

  /** Planted by G-92's check: a saved node waits for its projection (the old order). */
  plantLateCollapse = false;

  /** What the central diff has done to this view, counted (`G-109`). */
  diffStats = { applied: 0, retired_removed: 0, renamed: 0, carried: 0, known: 0 };
  /** Planted by G-109's check: the view ignores the central diff (the old
   *  behaviour: a retired chunk's node stays drawn for good). */
  plantNoDiff = false;
  /** Cids the store held before the visit that rendered them (the diff's `known`). */
  private knownCids = new Set<string>();
  /** A renamed chunk's NEW cid -> where the retired node stood, so the node
   *  absorb places next starts there and glides to its fit. */
  private renamedFrom = new Map<string, { at: number[]; t: number }>();

  /**
   * Apply the central diff (`_page_diff` in the sidecar) to this view.
   *
   * The diff is a diff of the patricia trie's rendered chunks, keyed on the
   * cid the 3D node, the store row and the projector all share. This READS
   * `retired` / `renamed` / `known` and WRITES the drawn node set and the
   * pending force specs; nothing is inferred from the page or the stream:
   *
   * * `retired` -- the store dropped the chunk, so its node and links go
   *   (new arrays, never spliced in place: D-38, see `addEdges`). Before
   *   this a chunk retired at a settle stayed drawn for good: 24 of 65
   *   stored nodes had no chunk in the store after one search.
   * * `renamed` -- same content, new address (a shift): the old node's
   *   position is carried to the new cid, so when `absorb` places it the node
   *   starts where the old one stood and glides to its fit, not from nowhere.
   *   A force spec pointing at the retired cid is re-pointed at the new one.
   * * `known` -- stored before this visit: a force node covering one is
   *   settled, never drawn as a new streaming node.
   */
  applyDiff(diff: CentralDiff | null | undefined): void {
    if (this.plantNoDiff || !diff || !Array.isArray(diff.retired)) return;
    const st = this.diffStats;
    st.applied++;
    const renamed = diff.renamed || {};
    const retired = new Set<string>(diff.retired);
    st.renamed += Object.keys(renamed).length;
    st.known += (diff.known || []).length;
    for (const c of diff.known || []) this.knownCids.add(c);
    if (this.knownCids.size > 40000) this.knownCids = new Set(diff.known || []);

    // The pending force tree: specs that named a retired cid.
    const settledNow = new Set<string>();
    for (const [id, spec] of this.forceSpecs) {
      if (spec.cid && retired.has(spec.cid)) spec.cid = renamed[spec.cid];   // re-point, or drop
      else if (spec.cid && !spec.stale && this.knownCids.has(spec.cid)) settledNow.add(id);
    }
    if (settledNow.size) this.coverForce(diff.url, {}, [...settledNow]);

    if (!this.graph || !retired.size) return;
    const data: any = this.graph.graphData();
    const byId = new Map<string, any>(data.nodes.map((n: any) => [n.id, n]));
    const hold = new Set<string>(this.billboards.keys() as any);
    const gone = new Set<string>();
    const now = Date.now();
    for (const old of retired) {
      const n = byId.get(old);
      if (!n || n.force || n.level === "page" || String(old).startsWith("path:")) continue;
      if (hold.has(old)) continue;                      // an open billboard keeps its node
      gone.add(old);
      const to = renamed[old];
      if (to && !byId.has(to) && [n.x, n.y, n.z ?? 0].every(Number.isFinite)) {
        this.renamedFrom.set(to, { at: [n.x, n.y, n.z ?? 0], t: now });
      }
      if (n.__glide) { delete n.__glide; this.glides.delete(n); }
    }
    if (this.renamedFrom.size > 5000) {
      for (const [k, v] of this.renamedFrom) if (now - v.t > 60000) this.renamedFrom.delete(k);
    }
    if (!gone.size) return;
    const end = (x: any) => (typeof x === "object" && x ? x.id : x);
    this.graph.graphData({
      nodes: data.nodes.filter((n: any) => !gone.has(n.id)),
      links: data.links.filter((l: any) => !gone.has(end(l.source)) && !gone.has(end(l.target))),
    });
    st.retired_removed += gone.size;
    this.collideSoon();
    this.graph.d3ReheatSimulation?.();
    this.sayCounts();
  }

  /**
   * Drawn stored-chunk nodes whose chunk the store no longer has (`G-109`).
   *
   * A stored-chunk node is non-force, non-page, not a `path:` fork. The store's
   * cids for each url come from `/page_map` (the chunks anchored in the page's
   * trie); a drawn node whose cid is not among them is a retirement some view
   * missed. Zero is the invariant; the planted arm (`plantNoDiff`) must read
   * more than zero or this measures nothing. A node held by an open billboard
   * is counted separately in `staleDetail`, not hidden.
   */
  staleDetail: { stale: number; held: number; urls: number; sample: string[] } | null = null;
  async staleStored(): Promise<number> {
    if (!this.graph) return 0;
    const nodes: any[] = this.graph.graphData().nodes.filter((n: any) =>
      !n.force && n.level !== "page" && n.url && !String(n.id).startsWith("path:"));
    const urls = [...new Set<string>(nodes.map((n: any) => n.url))];
    const have = new Map<string, Set<string> | null>();
    await Promise.all(urls.map(async (u) => {
      const got: any = await this.sidecar.pageMap(u).catch(() => null);
      have.set(u, got && got.chunks ? new Set(Object.keys(got.chunks)) : null);
    }));
    const hold = new Set<string>(this.billboards.keys() as any);
    let stale = 0, held = 0;
    const sample: string[] = [];
    for (const n of nodes) {
      const cids = have.get(n.url);
      if (!cids || cids.has(n.id)) continue;          // no answer is not a verdict
      stale++;
      if (hold.has(n.id)) held++;
      if (sample.length < 5) sample.push(String(n.id));
    }
    this.staleDetail = { stale, held, urls: urls.length, sample };
    return stale;
  }
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
      let calls = 0;
      const w: any = (alpha: number) => {
        const before = this.motion.forceBefore(nodes);
        f(alpha);
        this.motion.forceAfter(name, nodes, before, alpha);
        // Which force made a velocity non-finite: a diagnosis, read every
        // fourth call -- per force per tick it was 8 passes over 23k nodes.
        // `sanitize` repairs every tick regardless.
        if ((++calls & 3) !== 0) return;
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
      // nothing), and not every stored chunk gets a vector. A capture's reply
      // drops the ones it did not store (`onUnstored` -> `dropForceIds`), so
      // an uncovered node waits for ITS capture, not a clock: under a slow
      // store (captures p90 15 s, 55 s seen, 2026-10-18) a flat 20 s threw
      // away grey nodes a capture was about to save -- 2,060 in one session,
      // read as "a lot of diff scans not yet at least projected after
      // vectorization". 120 s is the net for a page that never captures;
      // covered and never placed, 90 s as before. Planted
      // `plantUncoveredClock`: 20 s, as before.
      const age = now - (spec.born ?? now);
      const uncoveredMs = this.plantUncoveredClock ? 20000 : 120000;
      if (spec.parent && ((!spec.cid && age > uncoveredMs) || (spec.cid && age > 90000))) {
        done.add(id);
        this.forceTimedOut++;
      }
    }
    const key = [...this.expandedUrls()].sort().join("\n");
    if (done.size || key !== this.lastExpanded) this.redrawForce(done);
    if (!this.settleTimer && this.forceSpecs.size) {
      this.settleTimer = window.setInterval(() => {
        if (this.closed) { GraphView.closedTick(); return; }
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
    // A trie branch with nothing left under it goes too, bottom-up: its
    // chunks folded into stored nodes and it would hang as scaffolding.
    for (let changed = true; changed;) {
      changed = false;
      const parents = new Set<string>([...this.forceSpecs.values()].map((x: any) => x.parent));
      for (const [id, spec] of [...this.forceSpecs] as any) {
        if (spec.branch && !parents.has(id)) { this.forceSpecs.delete(id); changed = true; }
      }
    }
    if (this.collapsedTo.size > 20000) this.collapsedTo.clear();
    const data: any = this.graph.graphData();
    const end = (x: any) => (typeof x === "object" && x ? x.id : x);
    let nodes = data.nodes.filter((n: any) => !(n.force && !n.unit && !this.forceSpecs.has(n.id)));
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
      .filter((x: any) => x.parent && !x.branch).map((x) => x.url));
    for (const [id, spec] of [...this.forceSpecs]) {
      if (!spec.parent && !pendingChunkUrls.has(spec.url) && expanded.has(spec.url)) {
        this.forceSpecs.delete(id);
        nodes = nodes.filter((n: any) => n.id !== id);
        byId.delete(id);
      }
    }
    const visible = (url: string) => this.layoutMode !== "projector" || expanded.has(url)
      || !this.projectedPage(url, byId);
    // Force nodes of collapsed pages are not drawn after the fit; nor are the
    // chunks of a page the reader folded by right-click, whatever the layout
    // mode (its root, if it has no page node yet, still is).
    const shown = (url: string, chunk: boolean) => visible(url) && !(chunk && this.readerCollapsed(url));
    nodes = nodes.filter((n: any) => !n.force || n.unit || shown(n.url, n.level !== "page"));
    for (const id of [...byId.keys()]) {
      const n = byId.get(id);
      if (n.force && !n.unit && !shown(n.url, n.level !== "page")) byId.delete(id);
    }
    for (const [id, spec] of this.forceSpecs) {
      if (!spec.parent && this.projectedPage(spec.url, byId)) continue;
      if (!shown(spec.url, !!spec.parent)) continue;
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
    this.keepUnits(nodes, links, byId);
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

  /** Planted: an uncovered grey node goes after 20 s whatever its capture is doing. */
  plantUncoveredClock = false;
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
    this.foldChunks(url);
  }

  /**
   * Pages whose chunks the reader folded into the page node themselves, by
   * right-click on it (2026-10-04). The mirror of `openedByReader`: that set
   * keeps a page's chunks drawn when the reader browses away, this one keeps
   * them folded when the reader browses TO the page -- `absorb` draws the page
   * being browsed, and without this a late placement redrew a page the reader
   * had just collapsed. Read by `absorb` (nothing of a url in here is drawn
   * from a placement) and cleared by an explicit expand.
   */
  collapsedByReader = new Set<string>();

  /** `url` is held folded by the reader (fragment-insensitive, like browsing). */
  private readerCollapsed(url: string): boolean {
    return !!url && this.collapsedByReader.size > 0
      && (this.collapsedByReader.has(url) || this.collapsedByReader.has(url.split("#")[0]));
  }

  /** Planted (G-110): right-click does what it did before -- release the scope. */
  plantNoToggle = false;

  /** Every toggle, for the harness. */
  toggled: { at: number; url: string; action: string; nodes: number }[] = [];

  /**
   * Right-click on a PAGE node (2026-10-04: "no right-click on central url
   * nodes collapsing the chunks into the node and expanding the full UMAPped
   * chunk set"). A toggle on one url's subtree of the trie:
   *
   * * chunk nodes of the url are drawn -> they fold into the page node (its
   *   root in the trie); the url joins `collapsedByReader`, leaves
   *   `openedByReader`, and a pending force diff for it stays folded too;
   * * none are drawn -> EVERY chunk the store holds under the url is read
   *   (`pageCids`, the trie's leaves for that url), placed by the projector's
   *   transform and drawn at its UMAP position -- not the page's first
   *   unfold step, the whole set.
   *
   * Anything that is not a page node keeps its old meaning (release the
   * scope). Returns what was done, for the harness.
   */
  /** Planted: a right-click folds whenever anything of the page is drawn. */
  plantToggleByDrawn = false;

  async togglePage(node: any): Promise<{ action: string; url: string; nodes: number }> {
    if (this.plantNoToggle || !node || node.level !== "page" || !node.url) {
      this.onScope("");
      return { action: "scope", url: String(node?.url || ""), nodes: 0 };
    }
    const url: string = node.url;
    const out = (action: string, nodes: number) => {
      this.toggled.push({ at: Date.now(), url, action, nodes });
      if (this.toggled.length > 50) this.toggled.shift();
      this.motion.event("toggle", { url: url.slice(-50), action, nodes });
      return { action, url, nodes };
    };
    if (!this.graph) return out("none", 0);
    const drawn = this.graph.graphData().nodes
      // Force chunks count: the page being browsed is drawn by the stream.
      .some((n: any) => n.url === url && n.level !== "page");
    // The READER's last gesture decides first (2026-10-11: "re-right clicking
    // doesn't open chunks back up in chunk view"). A page the reader folded
    // opens on the next right-click even while something of it is still drawn
    // -- the page being browsed keeps drawing its stream's pending nodes, and
    // a pinned chunk stays -- which made every right-click a fold of nothing.
    // Planted: decided by what is drawn alone, as before.
    const folded = !this.plantToggleByDrawn && this.collapsedByReader.has(url);
    if (drawn && !folded) {
      this.openedByReader.delete(url);
      this.collapsedByReader.add(url);
      return out("collapse", this.foldChunks(url));
    }
    this.collapsedByReader.delete(url);
    this.openedByReader.add(url);
    void this.loadCodeEdges(url);                  // G-241: a code page's calls and bases
    void this.loadFiles(url);                      // 186k: the special files it links to
    const cids = await this.sidecar.pageCids(url).catch(() => [] as string[]);
    let placed = 0;
    // 400 a request, as the reopen after a refit does: a 1,109-chunk page is
    // three placements, each absorbed as it lands.
    for (let i = 0; i < cids.length; i += 400) {
      // The reader folded it again while the placements were in flight.
      if (this.collapsedByReader.has(url)) break;
      const got: any = await this.sidecar.place(cids.slice(i, i + 400));
      if (got?.nodes?.length) placed += this.absorb(got.nodes, got.edges).added;
    }
    // ONE containment pass over the whole page once every slice is in. Each
    // slice's placement hung from the url node every chunk whose parent was
    // in ANOTHER slice, and the per-slice passes ran before the later slices
    // landed: RFC 9110 kept 269 of 1,172 chunks on its url node, where the
    // trie has one (2026-10-11, "all the recursive chunks linked to their
    // root URL node"). Planted: the per-slice passes only.
    if (placed && !this.plantSliceContainment) await this.drawContainment();
    // The page's streamed chunks come back with its stored ones (G-199).
    if (!this.plantFoldForgets) { const before = this.graph.graphData().nodes.length; this.redrawForce(); placed += Math.max(0, this.graph.graphData().nodes.length - before); }
    return out("expand", placed);
  }

  /**
   * Fold every chunk node of `url` into its page node, in any layout mode;
   * a chunk held by an open billboard (a pin) stays. Returns how many went.
   */
  private foldChunks(url: string): number {
    if (!this.graph) return 0;
    const data: any = this.graph.graphData();
    const keep = new Set<string>(this.billboards.keys() as any);
    const gone = new Set<string>(data.nodes
      .filter((n: any) => n.url === url && n.level !== "page" && !keep.has(n.id))
      .map((n: any) => n.id));
    if (!gone.size) return 0;
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
    // A fold HIDES the page's streamed (grey) chunks -- `collapsedByReader`
    // keeps them undrawn -- it does not forget them: deleting their specs
    // here made a scanned page's unfold bring back only what the store held
    // (Bluesky, 2026-10-17: 339 grey nodes folded, 1 chunk on unfold; "right/
    // left clicking on the url nodes don't explode/collapse as I would
    // anticipate for scanned nodes"). Planted: forgotten, as before.
    if (this.plantFoldForgets) for (const [id, spec] of [...this.forceSpecs]) if (spec.url === url) this.forceSpecs.delete(id);
    this.collapsed.push({ at: Date.now(), url, nodes: gone.size });
    if (this.collapsed.length > 50) this.collapsed.shift();
    return gone.size;
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
    this.collapsedByReader.clear();
    this.forceStats = { drains: 0, added: 0, removed: 0, reparented: 0, ms: [], toScene: [],
                        jitter: [], jitterHeld: [], glide: [], sized: [] };
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
        this.capturePose();              // G-194: the camera comes back registered, not reframed
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
      // G-109's plant removes EVERY retirement path, this one included: the
      // projector reports a retired chunk gone as well as the central diff
      // naming it, and a plant that left this open measured nothing (the
      // planted arm read stale 0 in the Verifier, 2026-10-06).
      const goneIds = new Set<string>(this.plantNoDiff ? [] : (d.gone || []).filter((c: string) => byId.has(c)));
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
      // The fit's new coordinates are the PHANTOM, not the drawn place: an
      // online update, a url's local refit or a streamed placement moved
      // these, and they glided to the raw fit -- off-centre, packed, onto
      // their url node -- until some other change re-ran the telescope
      // (2026-10-10: 2,069 overlapping pairs and 68 chunks inside the url
      // node on ko.wikipedia, gone the moment the pass ran by hand; "Weird
      // phantom open-links": a page node moved without its cloud). The pass
      // runs NOW and every moved node glides to its relaxed target.
      if ((moved || pages) && !this.plantRawMoves) {
        this.fitChunkSizes(data);
        for (const [cid] of Object.entries<any>(d.chunks || {})) {
          const node = byId.get(cid);
          if (node && Number.isFinite(node.fitX)) this.glide(node, [node.fitX, node.fitY, node.fitZ ?? 0]);
        }
        for (const [url] of Object.entries<any>(d.pages || {})) {
          const node = byId.get("page:" + url);
          if (node && Number.isFinite(node.fitX)) this.glide(node, [node.fitX, node.fitY, node.fitZ ?? 0]);
        }
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
    // Every timer this view started that the plugin did not register: left
    // running, a closed view's code kept firing after a plugin RELOAD -- the
    // old build's profiler replaced the new one's, and the two thrashed
    // (2026-10-11). A relax in flight is abandoned by its sequence number.
    if (!(window as any).__vertiscopePlantLeakTimers) {
      window.clearInterval(this.settleTimer); this.settleTimer = 0 as any;
      window.clearInterval(this.hoverSweep); this.hoverSweep = 0;
      window.clearInterval(this.webTimer); this.webTimer = 0;
      window.clearTimeout(this.hoverBbTimer); this.hoverBbTimer = 0;
    }
    this.relaxSeq++;
    this.closed = true;
    this.graph?._destructor?.();
    this.graph = null;
  }
  /** Set by `onClose`: a timer that outlived it has nothing to do. */
  closed = false;
  /** A timer firing on a CLOSED view, counted on the window, which outlives
   *  the plugin (planted by `__vertiscopePlantLeakTimers`: the timers left on). */
  static closedTick(): void { const w = window as any; w.__vertiscopeClosedTicks = (w.__vertiscopeClosedTicks || 0) + 1; }

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
          console.warn("vertiscope: billboard image would not decode", src);
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
          // In 32 KB slices: one character at a time was the slowest thing
          // on the main thread while a corpus's pictures loaded.
          let binary = "";
          for (let i = 0; i < bytes.length; i += 0x8000) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000) as any);
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
  /** Planted (2026-10-11): an opened page gets only its per-slice containment passes. */
  plantSliceContainment = false;

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
  highlightChunk(cid: string, url = "", stored = ""): void {
    if (!this.graph) return;
    // The hovered url spreads; off every chunk, it goes back (G-230).
    if (cid && url) this.spreadUrl(url); else if (!cid) this.unspread();
    if (cid && url) void this.loadFiles(url);
    const data: any = this.graph.graphData();
    const seq = ++this.hoverSeq;
    // The stored chunk under the pointer, placed if it is not drawn yet, so
    // the camera and its panel go to THAT chunk (2026-10-06: "the camera
    // doesn't 'fly' for hovering over different chunks ... this also opens
    // the panels on the 3D side, but closes them when the hovering stops").
    if (cid && stored && !data.nodes.some((n: any) => n.id === stored) && !this.readerCollapsed(url)) {
      void this.sidecar.place([stored]).then((got: any) => {
        if (seq !== this.hoverSeq || !got || !got.nodes || !got.nodes.length) return;
        this.absorb(got.nodes, got.edges);
        this.highlightChunk(cid, url, stored);
      }).catch(() => undefined);
    }
    // The chunk's own node if it is drawn; otherwise the PAGE node standing
    // for it. At the default level the picture is 96 pages and no chunk node
    // exists at all, so ringing only exact ids would light nothing up for
    // every hover until the reader had already unfolded that page -- which
    // is the one case they least need the correspondence drawn.
    let target = cid ? data.nodes.find((n: any) => n.id === cid) : null;
    if (!target && stored) target = data.nodes.find((n: any) => n.id === stored) || null;
    // A streamed chunk already folded into a stored one: that one.
    if (!target && cid) {
      const into = this.collapsedTo.get(cid) || this.forceSpecs.get(cid)?.cid;
      if (into) target = data.nodes.find((n: any) => n.id === into) || null;
    }
    if (!target && cid && url) {
      target = data.nodes.find(
        (n: any) => n.level === "page" && n.url === url);
    }
    let changed = false;
    for (const n of data.nodes) {
      const want = !!target && n === target;
      if (!!n.hovered !== want) { n.hovered = want; changed = true; this.batchDirty = true; }
    }
    if (changed) this.graph.nodeColor(this.graph.nodeColor());
    // Only a CHUNK moves the camera and opens a panel: a page node is the
    // fallback when the hovered chunk is not drawn, and flying to it made the
    // camera alternate between the chunk and its page on every poll
    // (measured 4-6 flights per hover, ending on the page).
    // No drawn node for the hovered chunk, only its page: a STREAMED chunk
    // still shows its own content, at its page's place (PLUGIN_GOAL 125:
    // "view the base-content extracted/detected on the diff tree in just
    // their markdown form") -- not the page, and not a stored ancestor.
    if (target && target.level === "page" && cid && cid.startsWith("f:") && !this.plantNoVirtualPanel
        && this.forcePayloadFor(cid)) {
      target = { id: cid, url, level: "chunk", virtual: true, x: target.x, y: target.y, z: target.z ?? 0 };
    }
    // A grey chunk hovered at an ELEMENT: the panel is that element's (a tile
    // in a container chunk several tiles share), keyed `cid|element` so each
    // tile opens its own, placed where the chunk is drawn.
    // The panel is the hovered ELEMENT's unit, for a grey or a stored chunk:
    // `base|element`, turned into `base|unit` when the panel opens.
    const el = cid && target && target.level !== "page" && target.level !== "path" && !this.plantNoVirtualPanel
      ? this.hoverElementOf(cid) : "";
    // A GREY chunk: the unit's own chunk, found among the page's live chunks
    // (the sensor's hovered chunk may not hold the tile at all).
    const gu = cid && cid.startsWith("f:") && target && (target.force || target.virtual) && !this.plantNoVirtualPanel
      ? this.greyUnitFor(cid) : null;
    if (gu) {
      target = { id: `${gu.id}|${gu.at}`, url, level: "chunk", virtual: true, x: target.x, y: target.y, z: target.z ?? 0 };
    } else if (el && !String(target.id).includes("|")) {
      target = { id: `${target.id}|${el}`, url, level: "chunk", virtual: true, base: target, hoverCid: cid, x: target.x, y: target.y, z: target.z ?? 0 };
    }
    const isChunk = !!target && target.level !== "page" && target.level !== "path";
    if (cid && url) { this.hoverAskAt = performance.now(); this.hoverAskUrl = url; }
    if (!cid || isChunk) {
      this.focusOn(cid ? target : null);
      this.hoverPanel(cid ? target : null);
    } else {
      // Off every drawn chunk (the page node is only the fallback): the
      // hover panel closes -- it stayed open until the pointer left the page
      // (2026-10-06: "Billboards are slow to close when not hovered").
      this.hoverPanel(null);
    }
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

  /** The dwell before a hover opens its panel: long enough that sweeping the
   *  pointer across a page does not open one per chunk passed, short enough to
   *  read as immediate (2026-10-11, item 91: hover-to-panel was 209 ms at the
   *  stored stage, 150 of them this dwell). Was 150. */
  hoverDwellMs = 60;
  /** How long the first paint waits for the page form before drawing the markdown (was 80). */
  pageFormWaitMs = 30;
  private hoverSeq = 0;
  /** When the last hover reached the 3D view, and on which page (item 91). */
  private hoverAskAt = 0;
  private hoverAskUrl = "";
  private hoverBbTimer = 0;
  private hoverBbPending = "";
  /** The billboard a hover opened (closed when the hover moves on or ends). */
  private hoverBb = "";

  /**
   * A hovered CHUNK opens its panel in 3D, after the same dwell as the
   * camera; the panel a hover opened closes when the hover moves on or stops
   * -- unless the reader pinned it (dragged it, or the browser holds it).
   */
  /**
   * Panels opened by hovering in the browser PERSIST after the hover ends and
   * close themselves a minute after their chunk was last hovered (2026-10-10:
   * "showing hovered panels in the 3D gui when hovered on the 2D browser
   * should persist, but disappear after a minute maybe" -- replacing
   * 2026-10-06's "closes them when the hovering stops"). Hovering it again
   * renews the minute; at most `hoverPanelCap` stay open, oldest first out.
   */
  hoverPanelTtlMs = 60000;
  /** ONE: only the most recently hovered panel persists (2026-10-10: "I should
   *  only see a single most recently hovered and flown to panel persist its
   *  billboard rendering, not multiple"). */
  hoverPanelCap = 1;
  /** Planted: the old close-on-hover-end behaviour. */
  plantCloseOnLeave = false;
  hoverStats: { empty_skipped: number; units?: number; stale_stored?: number } = { empty_skipped: 0 };
  private hoverSweep = 0;

  private expireHoverPanels(): void {
    const now = performance.now();
    const open = [...this.billboards.entries()].filter(([, e]: [string, any]) => e.fromHover && !e.pinned && !e.fromBrowser);
    for (const [id, e] of open as [string, any][]) {
      if (id === this.hoverBb) continue;
      if (now - (e.hoverAt ?? e.openedAt ?? now) > this.hoverPanelTtlMs) {
        this.closeBillboard(id);
        this.panelTimes.close.push(now - (e.hoverAt ?? now));
        if (this.panelTimes.close.length > 200) this.panelTimes.close.shift();
      }
    }
    const left = [...this.billboards.entries()].filter(([, e]: [string, any]) => e.fromHover && !e.pinned && !e.fromBrowser)
      .sort((a: any, b: any) => (a[1].hoverAt ?? 0) - (b[1].hoverAt ?? 0));
    while (left.length > this.hoverPanelCap) {
      const [id] = left.shift() as [string, any];
      if (id !== this.hoverBb) this.closeBillboard(id);
    }
    if (!this.hoverSweep && left.length) this.hoverSweep = window.setInterval(() => {
      if (this.closed) { GraphView.closedTick(); return; }
      this.expireHoverPanels();
      if (![...this.billboards.values()].some((e: any) => e.fromHover)) { window.clearInterval(this.hoverSweep); this.hoverSweep = 0; }
    }, 1000);
  }

  /** G-196: billboards open on a fly-to ("flyto", the default) or only on a right-click. */
  panelsOn: "flyto" | "rightclick" = (() => {
    try { return window.localStorage.getItem("vertiscope.panelsOn") === "rightclick" ? "rightclick" : "flyto"; }
    catch { return "flyto"; }
  })();
  panelModeStats = { hover_skipped: 0, right_opened: 0, strip_flown: 0, strip_right: 0 };
  /** A right-click over the browser on a hovered chunk (G-215): in
   *  right-click mode its panel opens, as a hover's would in fly-to mode. */
  rightPanel(cid: string, url: string, stored: string): void {
    if (this.panelsOn !== "rightclick" || !this.graph) return;
    const nodes = this.graph.graphData().nodes;
    const target = (stored && nodes.find((n: any) => String(n.id) === stored))
      || nodes.find((n: any) => String(n.id) === cid);
    if (!target) return;
    this.panelModeStats.right_opened++;
    void this.openBillboard(target, false, true);
  }
  setPanelsOn(mode: "flyto" | "rightclick"): void {
    this.panelsOn = mode;
    try { window.localStorage.setItem("vertiscope.panelsOn", mode); } catch { /* a convenience only */ }
  }

  private hoverPanel(target: any): void {
    if (this.plantNoFocus) return;
    if (this.panelsOn === "rightclick") { this.panelModeStats.hover_skipped++; return; }
    const isChunk = !!target && target.level !== "page" && target.level !== "path";
    const close = () => {
      const e: any = this.hoverBb ? this.billboards.get(this.hoverBb) : null;
      if (e && e.fromHover && !e.pinned && !e.fromBrowser) {
        if (this.plantCloseOnLeave) this.closeBillboard(this.hoverBb);
        else e.hoverAt = performance.now();          // its minute starts now
      }
      this.hoverBb = "";
      if (!this.plantCloseOnLeave) this.expireHoverPanels();
    };
    if (!isChunk) {
      if (this.hoverBbPending === "-" || !this.hoverBb) return;
      window.clearTimeout(this.hoverBbTimer);
      this.hoverBbPending = "-";
      this.hoverBbTimer = window.setTimeout(() => { this.hoverBbPending = ""; close(); }, 250);
      return;
    }
    // The open chunk asserted again CANCELS a pending close: without this a
    // momentary off-chunk hover closed the panel and the next ask reopened
    // it -- open, close, open (2026-10-06: "flickering on the billboards").
    if (this.hoverBb === target.id) {
      if (this.hoverBbPending === "-") { window.clearTimeout(this.hoverBbTimer); this.hoverBbPending = ""; }
      return;
    }
    if (this.hoverBbPending === target.id) return;
    window.clearTimeout(this.hoverBbTimer);
    this.hoverBbPending = target.id;
    // Fetched NOW, during the dwell, so the panel draws from the cache.
    void this.chunkPayload(target.id);
    this.hoverBbTimer = window.setTimeout(async () => {
      this.hoverBbPending = "";
      // `base|element` -> `base|unit`: the element's tile within the chunk.
      // A move inside one tile lands on the same unit and renews its panel.
      if (String(target.id).includes("|")) {
        const bar = String(target.id).indexOf("|");
        const base = String(target.id).slice(0, bar), el = String(target.id).slice(bar + 1);
        const bp: any = await this.chunkPayload(base);
        const u = bp && bp.lines ? unitOf(bp.lines, el) : null;
        let id = u ? `${base}|${u.at}` : base;
        // A STORED chunk is a recording of what each address held when it was
        // captured; a virtual list (archive.org's tiles) reuses addresses for
        // other items, so the record can name a different tile than the page
        // draws now -- every tile opened its slot's former occupant
        // (2026-10-17, PLUGIN_GOAL 149). When the page's live tree holds
        // the unit and its lines are not all in the stored unit, the live
        // unit is the truth. Planted: `plantTrustStored`.
        if (!base.startsWith("f:") && target.hoverCid && !this.plantTrustStored) {
          const gu = this.greyUnitFor(target.hoverCid);
          if (gu) {
            const live: any = await this.chunkPayload(`${gu.id}|${gu.at}`);
            const have = new Set((u ? u.lines : []).map((l: any) => String(l.text || "").trim()));
            const fresh = (live && live.lines ? live.lines : []).map((l: any) => String(l.text || "").trim()).filter(Boolean);
            if (fresh.length && fresh.some((t: string) => !have.has(t))) {
              id = `${gu.id}|${gu.at}`;
              this.hoverStats.stale_stored = (this.hoverStats.stale_stored || 0) + 1;
            }
          }
        }
        if (id !== target.id) target = { ...target, id };
        if (u) this.hoverStats.units = (this.hoverStats.units || 0) + 1;
      }
      close();
      const had: any = this.billboards.get(target.id);
      // Already open (an earlier hover's panel, still within its minute):
      // renewed, not reopened.
      if (had) { this.hoverBb = target.id; had.hoverAt = performance.now(); this.expireHoverPanels(); return; }
      // Nothing to show -- no stored lines and no page form: a hover opens
      // no panel ("(no lines stored for this chunk)", 2026-10-10).
      const pay: any = await this.chunkPayload(target.id);
      if (!(pay && pay.lines && pay.lines.length) && !getSnapshot(target.id)) { this.hoverStats.empty_skipped++; return; }
      if (this.hoverBbPending) return;              // the pointer moved on meanwhile
      this.hoverBb = target.id;
      await this.openBillboard(target, false, true);
      const e: any = this.billboards.get(target.id);
      if (e) e.hoverAt = performance.now();
      this.expireHoverPanels();
    }, this.hoverDwellMs);
  }

  /**
   * **Unit nodes** (G-251, 2026-10-18: "hovering over sub-components of the
   * same overall chunk only renders those components in the same node ...
   * each panel comes from the same node"). A hovered unit -- a tile, a track
   * row, a list -- is a node of its own, grey (no vector yet: it is drawn
   * from the sensor's tree before anything is embedded, PLUGIN_GOAL 48/125),
   * one level BELOW its chunk: hung from the chunk's node, or from the
   * page's when the chunk is not drawn. Units of one chunk sit on a shell
   * around it, so their panels leave from distinct places. Kept through
   * redraws (they are not in `forceSpecs`, whose drain owns streamed
   * chunks); the oldest beyond `unitNodeCap` go, never one with a panel
   * open. Planted `plantSharedAnchor`: the panel hangs from a copy of the
   * chunk's position, as before.
   */
  plantSharedAnchor = false;
  unitNodeCap = 96;
  unitStats = { made: 0, reused: 0, dropped: 0 };
  private unitNodes = new Map<string, { base: string; url: string; at: number }>();
  private unitParent(base: string, url: string, byId: Map<string, any>): any {
    if (base && byId.has(base)) return byId.get(base);
    const into = base ? (this.collapsedTo.get(base) || this.forceSpecs.get(base)?.cid) : undefined;
    if (into && byId.has(into)) return byId.get(into);
    const key = String(url || "").split("#")[0];
    return [...byId.values()].find((n: any) => n.level === "page" && !n.force && String(n.url || "").split("#")[0] === key)
      || [...byId.values()].find((n: any) => n.level === "page" && String(n.url || "").split("#")[0] === key) || null;
  }
  ensureUnitNode(v: any): any {
    if (!this.graph || !v || !v.id) return v;
    const id = String(v.id);
    const data: any = this.graph.graphData();
    const byId = new Map<string, any>(data.nodes.map((n: any) => [String(n.id), n]));
    const had = byId.get(id);
    if (had) {
      const r = this.unitNodes.get(id);
      if (r) r.at = performance.now();
      this.unitStats.reused++;
      return had;
    }
    const bar = id.indexOf("|");
    const base = v.parentId ? String(v.parentId) : bar > 0 ? id.slice(0, bar) : (v.base && v.base.id ? String(v.base.id) : "");
    const p = this.unitParent(base === id ? "" : base, v.url, byId);
    const pid = p ? String(p.id) : "";
    const k = this.childCount.get(pid || id) || 0;
    this.childCount.set(pid || id, k + 1);
    // The next direction of a Fibonacci sphere about the parent, as a
    // streamed chunk is placed about its trie parent.
    const zz = 1 - 2 * ((k % 24) + 0.5) / 24, rr = Math.sqrt(Math.max(0, 1 - zz * zz));
    const th = k * Math.PI * (3 - Math.sqrt(5));
    const R = STREAM.BASE * (p && p.level === "page" ? 1 : 0.7);
    const cx = p && Number.isFinite(p.x) ? p.x : (v.x ?? 0), cy = p && Number.isFinite(p.y) ? p.y : (v.y ?? 0);
    const cz = p && Number.isFinite(p.z) ? p.z : (v.z ?? 0);
    // A unit of a chunk the projector placed is a part of THAT chunk and
    // takes its colour; only a unit of a grey (streamed) chunk is grey.
    const color = v.color ? v.color : p && !p.force && p.level !== "page" && p.color ? p.color : "#9aa0a6";
    const n: any = { id, level: "chunk", name: v.name || id, url: v.url, members: 1, tokens: 0,
                     force: true, unit: true, val: v.kgEntity ? 0.45 : 0.6, color, fileRef: v.fileRef, kgEntity: v.kgEntity,
                     x: cx + rr * Math.cos(th) * R, y: cy + rr * Math.sin(th) * R, z: cz + zz * R };
    const nodes = data.nodes.slice();
    const links = data.links.slice();
    nodes.push(n);
    if (pid) links.push({ source: pid, target: id, force: true, unit: true });
    this.unitNodes.set(id, { base, url: String(v.url || ""), at: performance.now() });
    this.unitStats.made++;
    // The oldest units beyond the cap go -- never one a panel holds.
    if (this.unitNodes.size > this.unitNodeCap) {
      const old = [...this.unitNodes.entries()].filter(([u]) => !this.billboards.has(u) && u !== id && !u.startsWith("file:") && !u.startsWith("kg:"))
        .sort((a, b) => a[1].at - b[1].at).slice(0, this.unitNodes.size - this.unitNodeCap).map(([u]) => u);
      const drop = new Set(old);
      for (const u of old) this.unitNodes.delete(u);
      this.unitStats.dropped += old.length;
      const end = (x: any) => String(typeof x === "object" && x ? x.id : x);
      const keepN = nodes.filter((m: any) => !drop.has(String(m.id)));
      const keepL = links.filter((l: any) => !drop.has(end(l.source)) && !drop.has(end(l.target)));
      this.graph.graphData({ nodes: keepN, links: keepL });
    } else {
      this.graph.graphData({ nodes, links });
    }
    if (this.layoutMode === "projector") this.treeSpring();
    this.graph.d3ReheatSimulation?.();
    this.batchDirty = true;
    return n;
  }
  /** The unit nodes put back after a redraw that rebuilt the force picture. */
  private keepUnits(nodes: any[], links: any[], byId: Map<string, any>): void {
    if (!this.unitNodes.size) return;
    const was: any[] = this.graph ? (this.graph.graphData() as any).nodes : [];
    const prior = new Map<string, any>(was.filter((n: any) => n.unit).map((n: any) => [String(n.id), n]));
    for (const [id, r] of this.unitNodes) {
      let n = byId.get(id);
      if (!n) {
        n = prior.get(id);
        if (!n) continue;                       // dropped by a fold: made again when hovered
        nodes.push(n);
        byId.set(id, n);
      }
      const p = this.unitParent(r.base, r.url, byId);
      if (p && String(p.id) !== id) links.push({ source: String(p.id), target: id, force: true, unit: true });
    }
  }

  /** Planted (item 91): payloads held 10 s and never prefetched, as before. */
  plantShortPayloadCache = false;
  prefetchStats = { pages: 0, asked: 0, done: 0 };
  private prefetching = new Set<string>();
  /** Every drawn chunk of a page, its payload fetched ahead: 400 at most, 4 at a time. */
  private prefetchPayloads(url: string): void {
    if (this.plantShortPayloadCache || !this.graph || this.prefetching.has(url)) return;
    this.prefetching.add(url);
    this.prefetchStats.pages++;
    const cids = ((this.graph.graphData() as any).nodes as any[])
      .filter((n) => n.url === url && !n.force && n.level !== "page" && !String(n.id).startsWith("path:"))
      .map((n) => String(n.id)).filter((c) => !this.payloadCache.has(c)).slice(0, 400);
    let next = 0;
    const worker = async () => {
      while (next < cids.length) {
        const c = cids[next++];
        this.prefetchStats.asked++;
        await this.chunkPayload(c).catch(() => null);
        this.prefetchStats.done++;
      }
    };
    void Promise.all([worker(), worker(), worker(), worker()]).finally(() => {
      // Again on the next landing: a page's chunks change as it streams.
      window.setTimeout(() => this.prefetching.delete(url), 5000);
    });
  }

  /** Open/close timings of hover panels, for the harness (`app_anomalies`). */
  panelTimes = { first_paint: [] as number[], page_paint: [] as number[], close: [] as number[] };
  private payloadCache = new Map<string, { at: number; p: Promise<any> }>();
  /** A chunk's payload, shared by the hover prefetch and the panel (10 s). */
  /** Is a node with this id drawn? */
  hasNode(id: string): boolean {
    return !!this.graph && this.graph.graphData().nodes.some((n: any) => String(n.id) === id);
  }
  /** The chunk holding a hovered grey element's unit, and the unit. */
  /** Tier 1's corpus-wide match count for the query it answered. */
  private tierMatching: { q: string; n: number | null } | null = null;
  greyUnitFor: (cid: string) => { id: string; at: string } | null = () => null;
  /** Planted: a stored chunk's unit is shown even where the live page draws other content there. */
  plantTrustStored = false;
  /** Planted: the speck clamp pulls in a kept-zoom flight too (the reader's zoom-out lost). */
  plantClampKeptZoom = false;
  /** Planted: a strip hover opens its panel in right-click mode too. */
  plantStripIgnoresToggle = false;
  /** Planted: a hover preview takes the pointer (and blocks the nodes beneath). */
  plantPreviewBlocks = false;
  /** A strip result's panel target: its chunk node, or -- standing in its
   *  page (url view) -- the CHUNK's panel at the page's place. */
  private stripTarget(h: { cid: string; url: string }, n: any): any {
    return n.level !== "page" && n.level !== "path" ? n
      : { id: h.cid, url: h.url, level: "chunk", virtual: true, x: n.x, y: n.y, z: n.z ?? 0 };
  }
  /** The hovered element for a grey chunk (the browser's pipebox). */
  hoverElementOf: (cid: string) => string = () => "";
  /** Planted: a hovered undrawn grey chunk opens no panel (its page stands for it). */
  plantNoVirtualPanel = false;
  /** A grey node's provisional payload, from the browser's drain (G-198). */
  forcePayloadFor: (id: string) => any = () => null;
  chunkPayload(cid: string): Promise<any> {
    // `base|unit`: the base chunk's lines under that unit (a tile's).
    const bar = String(cid).indexOf("|");
    if (bar > 0) {
      const base = String(cid).slice(0, bar), at = String(cid).slice(bar + 1);
      return this.chunkPayload(base).then((p: any) => {
        if (!p || !p.lines) return p;
        const pick = p.lines.filter((l: any) => inUnit(lineAddr(l), at));
        return pick.length ? { ...p, cid, lines: pick } : p;
      });
    }
    // A grey node: its streamed markdown, now -- never cached, it is still
    // being rewritten (PLUGIN_GOAL 125).
    if (String(cid).startsWith("f:")) return Promise.resolve(this.forcePayloadFor(cid));
    const now = performance.now();
    const hit = this.payloadCache.get(cid);
    // Held for a minute, not ten seconds: a chunk the stream rewrites is
    // dropped from here the moment it is reported (`refreshBillboards`), so
    // the age limit only guards against a change nothing reported.
    if (hit && now - hit.at < (this.plantShortPayloadCache ? 10000 : 60000)) return hit.p;
    const p = this.sidecar.chunk(cid).catch(() => null);
    this.payloadCache.set(cid, { at: now, p });
    if (this.payloadCache.size > 1200) this.payloadCache.delete(this.payloadCache.keys().next().value as string);
    return p;
  }

  /** Planted by the focus check: hover rings only, the camera stays. */
  plantNoFocus = false;
  focusStats = { asked: 0, flown: 0, followed: 0, released: 0, last: "", zoomed: 0, kept_zoom: 0, last_d: 0, clamped: 0 };
  /** A flight never ends with its target smaller than this radius on screen (px). */
  minTargetPx = 6;
  /** Planted: the reader's zoom kept whatever the target's size (the speck flights). */
  plantSpeckFlights = false;
  /** The navigation the camera last zoomed for, and when (performance.now). */
  private zoomState = { zoomedFor: "", zoomedAt: -1e9 };
  /** Planted: every flight re-zooms (the old behaviour), and tracking copies every jitter. */
  plantAlwaysZoom = false;
  plantNoSmooth = false;
  private focusTimer = 0;
  private focusPending: any = null;
  /** What the hover currently asks for, so a deferred flight can tell it is still wanted. */
  private focusWant: any = null;
  private focusFrame = 0;
  private focusNode: any = null;
  private focusLast: number[] | null = null;
  private focusHooked = false;

  /**
   * The camera goes to the chunk the reader hovers in the browser, and stays
   * on it while the forces move it (2026-10-06: "hovering overlays should
   * zoom-focus the camera in the 3D editor on the specific chunk, no matter
   * placement in the diff, with focus persisting on force-directed
   * updates"). After a 200 ms dwell on one chunk -- a pointer sweeping the
   * page must not throw the camera about -- it flies there (400 ms), then
   * follows the node frame by frame by the node's own displacement. The
   * reader's own camera gesture releases it.
   */
  private focusOn(target: any): void {
    if (this.plantNoFocus || !this.graph) return;
    this.focusWant = target || null;
    if (!target) { window.clearTimeout(this.focusTimer); this.focusPending = null; return; }
    // The SAME target asked again (every pushed and every polled hover asks)
    // leaves its dwell alone: resetting it on each ask meant it never ran --
    // measured 23 asks, 0 flights (2026-10-06).
    if (this.focusNode === target || this.focusPending === target) return;
    window.clearTimeout(this.focusTimer);
    this.focusPending = target;
    this.focusStats.asked++;
    this.focusTimer = window.setTimeout(() => { this.focusPending = null; this.flyTo(target); }, 200);
  }

  private flyTo(n: any, waited = 0): void {
    const g: any = this.graph;
    if (!g) return;
    // A node just placed from the store has no position until the forces
    // tick it, and the hover that asked for it has already stopped asking:
    // returning here left the camera where it was, with the panel open
    // (G-113 on the working store, 2026-10-07: panel yes, flights 0). Wait
    // for the position for as long as this node is still what is hovered.
    if (!Number.isFinite(n.x)) {
      if (waited < 3000 && this.focusWant === n && !this.plantNoFocus) {
        this.focusTimer = window.setTimeout(() => this.flyTo(n, waited + 100), 100);
      }
      return;
    }
    if (!this.focusHooked) {
      const c: any = g.controls();
      if (c && c.addEventListener) {
        c.addEventListener("start", () => {
          if (!this.focusNode) return;
          this.focusNode = null; this.focusStats.released++;
        });
        this.focusHooked = true;
      }
    }
    const cam = g.camera().position;
    const r = drawnRadius(n, g.nodeRelSize(), this.media());
    // ZOOM on a new navigation only; after that the reader's own zoom is kept
    // and the camera just re-aims (2026-10-10: "fly-to-node should zoom
    // initially, but preserve user zoom while still tracking during
    // fly-throughs"; "some kind of debounce on ... re-setting the zoom action
    // for 'new navigations'"). A navigation is the browser cell's page; two
    // within 1.5 s zoom once.
    const bv: any = this.app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
    const nav = String((bv && bv.session) || n.url || "");
    const ctl: any = g.controls();
    const tgt = ctl && ctl.target ? ctl.target : null;
    const userD = tgt ? Math.hypot(cam.x - tgt.x, cam.y - tgt.y, cam.z - tgt.z) : NaN;
    const decided = zoomFor(this.zoomState, nav, performance.now(), userD, Math.max(45, 10 * r),
                            { always: this.plantAlwaysZoom });
    let D = decided.distance;
    if (decided.zoom) this.focusStats.zoomed++; else this.focusStats.kept_zoom++;
    // The reader's zoom is kept -- but never so far out that the target is a
    // speck: a flight landed on a chunk a pixel or two wide, its links running
    // off-screen, and read as "an empty nodes problem" (2026-10-10). The
    // target keeps at least `minTargetPx` of radius on screen.
    const camObj: any = g.camera();
    const fov = ((camObj && camObj.fov) || 50) * Math.PI / 180;
    const H = (g.renderer && g.renderer().domElement && g.renderer().domElement.clientHeight) || 800;
    const Dvisible = r * (H / 2) / (this.minTargetPx * Math.tan(fov / 2));
    // ...on a flight that ZOOMS only. Applied to every flight, it pulled the
    // camera in on each hover the search scroll made onto a small result, and
    // the reader's zoom-out was lost (2026-10-17, PLUGIN_GOAL 158: "zooming
    // out while scanning doesn't persist over later node hovers"). A kept
    // zoom is the reader's. Planted `plantClampKeptZoom`: as before.
    if (!this.plantSpeckFlights && (decided.zoom || this.plantClampKeptZoom)
        && Number.isFinite(Dvisible) && Dvisible > 0 && D > Dvisible) {
      D = Dvisible; this.focusStats.clamped++;
    }
    let dx = cam.x - n.x, dy = cam.y - n.y, dz = cam.z - (n.z || 0);
    const len = Math.hypot(dx, dy, dz) || 1;
    dx /= len; dy /= len; dz /= len;
    const to = { x: n.x + dx * D, y: n.y + dy * D, z: (n.z || 0) + dz * D };
    g.cameraPosition(to, { x: n.x, y: n.y, z: n.z || 0 }, 400);
    this.focusStats.flown++;
    this.focusStats.last_d = Math.round(D * 10) / 10;
    this.focusStats.last = String(n.id).slice(0, 60);
    this.focusNode = null;
    window.setTimeout(() => {
      this.focusNode = n;
      this.focusLast = [n.x, n.y, n.z || 0];
      if (!this.focusFrame) this.followFocus();
    }, 420);
  }

  private followFocus(): void {
    const step = () => {
      const g: any = this.graph, n = this.focusNode;
      if (!g || !n || !this.focusLast) { this.focusFrame = 0; return; }
      const ids = g.graphData().nodes;
      if (!ids.includes(n)) { this.focusNode = null; this.focusFrame = 0; return; }
      const [lx, ly, lz] = this.focusLast;
      // Debounced: a dead-band ignores the collider's sub-0.05 wobble, and
      // the camera closes a quarter of the gap a frame -- it glides after the
      // node instead of copying every jitter (2026-10-10: "some kind of
      // debounce on continuous tracking"). The reader's distance is kept: the
      // camera and its target move by the same step.
      const ex = n.x - lx, ey = n.y - ly, ez = (n.z || 0) - lz;
      if (Math.abs(ex) + Math.abs(ey) + Math.abs(ez) > (this.plantNoSmooth ? 1e-3 : 0.05)) {
        const k = this.plantNoSmooth ? 1 : 0.25;
        const ddx = ex * k, ddy = ey * k, ddz = ez * k;
        const cam = g.camera().position;
        const to = [lx + ddx, ly + ddy, lz + ddz];
        g.cameraPosition({ x: cam.x + ddx, y: cam.y + ddy, z: cam.z + ddz }, { x: to[0], y: to[1], z: to[2] }, 0);
        this.focusLast = to;
        this.focusStats.followed++;
      }
      this.focusFrame = window.requestAnimationFrame(step);
    };
    this.focusFrame = window.requestAnimationFrame(step);
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
  async openBillboard(node: any, fromBrowser = false, fromHover = false): Promise<void> {
    if (!node || !node.id || !this.graph) return;
    this.batchDirty = true;
    const existing = this.billboards.get(node.id);
    if (existing) {
      // Asked for by the browser -- a pin, or a click on its card in the
      // side panel: shown, and expanded if it had been minimized.
      if (fromBrowser) { existing.fromBrowser = true; existing.el.removeClass("is-preview"); this.setMinimized(existing, false); return; }
      // A click on a node whose HOVER preview is open keeps it: the preview
      // becomes an ordinary panel the pointer can use (G-243).
      if (existing.fromHover && !fromHover && !existing.pinned) {
        existing.fromHover = false; existing.pinned = true; existing.el.removeClass("is-preview"); return;
      }
      // A second click closes it -- unless the browser's markdown side is
      // holding it open, in which case that side is where it closes.
      if (existing.fromBrowser) return;
      this.closeBillboard(node.id);
      return;
    }
    if (!this.billboardLayer) {
      const host = this.canvasEl || this.contentEl;
      this.billboardLayer = host.createDiv({ cls: "vertiscope-bb-layer" });
    }
    const el = this.billboardLayer.createDiv({ cls: "vertiscope-bb" });
    // A HOVER preview passes the pointer through to the graph: an open
    // preview stood over the nodes beneath it and they could not be hovered
    // (2026-10-18, PLUGIN_GOAL 172). A click keeps it (see above), and it is
    // an ordinary panel from then on. Planted `plantPreviewBlocks`.
    if (fromHover && !this.plantPreviewBlocks) el.addClass("is-preview");
    // Which chunk this panel is, readable without the view: a hover panel and
    // a pinned one can be open at once, and "the first .vertiscope-bb" read the
    // wrong one (D-36, 2026-10-07).
    el.dataset.cid = String(node.id);
    const head = el.createDiv({ cls: "vertiscope-bb-head" });
    // The chunk's full patricia-trie address (2026-10-06: "the header of the
    // panel should show the full patricia trie address"): `url : xpath`,
    // filled in when the store answers; the url alone until then.
    const addr = head.createDiv({ cls: "vertiscope-bb-addr" });
    addr.setText(String(node.url || node.name || node.id));
    // Minimize: down to the title bar, the chunk still open (2026-09-26).
    const min = head.createSpan({ cls: "vertiscope-bb-min" });
    min.setText("\u2013");
    min.setAttr("aria-label", "minimize");
    min.onpointerdown = (e: PointerEvent) => e.stopPropagation();
    min.onclick = (e: MouseEvent) => {
      e.stopPropagation();
      const en: any = this.billboards.get(node.id);
      if (en) this.setMinimized(en, !en.minimized);
    };
    const close = head.createSpan({ cls: "vertiscope-bb-close" });
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
    const body = el.createDiv({ cls: "vertiscope-bb-body" });
    body.setText("\u2026");

    // `fromHover` is set NOW, not after the forms load: a hover that ended
    // while the panel was still loading found it unmarked and left it open
    // (2026-10-06: "Billboards don't close").
    // A panel with no drawn node of its own -- a unit (`chunk|unit`) of a
    // chunk several share, or a chunk whose page is not unfolded -- hangs
    // from its OWN grey node, made now (G-251). It hung from a copy of its
    // chunk's (or page's) position, so every track of a bandcamp list opened
    // from one node (2026-10-18: "each panel comes from the same node").
    if (node.virtual && !this.plantSharedAnchor) node = this.ensureUnitNode(node);
    const entry: any = { el, node, pinned: false, surface: null, fromBrowser, minimized: false,
                         fromHover, openedAt: performance.now() };
    this.billboards.set(node.id, entry);
    this.positionBillboard(entry);
    // Offline the panel is a MAIN pane, not a billboard (`G-59`).
    if (this.offlineNow()) void this.dockPanel(entry);
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
        el.removeClass("is-preview");
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

    // **Two forms (2026-10-06)**: the PAGE -- the live page's own rendering
    // of the chunk, read from the browser cell -- and MARKDOWN, drawn by
    // Obsidian's own renderer. "our webpage rendering view is basically the
    // correct result", so the distilled shadow-DOM form and its switch are
    // gone from the panel. The page form is the default whenever the chunk's
    // page is the one open in the cell.
    body.empty();
    if (node.level === "page" || node.level === "path") {
      body.setText("a page stands for its chunks -- click to unravel it");
      return;
    }
    if (node.fileRef) { this.renderFilePanel(node, body, addr); return; }
    if (node.kgEntity) { this.renderKgPanel(node, body, addr); return; }
    // The header's address fills in when the store answers -- NOT awaited:
    // the first paint must not wait for the sidecar (it queued behind
    // capture writes for 1.8 s at p90).
    void this.chunkPayload(node.id).then(async (payload: any) => {
      if (!payload) return;
      if (!entry.payload) entry.payload = payload;
      // The fast page form carried no addresses (its controls inert): now
      // that the store answered, re-read it addressed and redraw (G-111).
      if (entry.form === "page" && this.billboards.has(node.id)) {
        const b: any = this.app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
        if (b && typeof b.snapshotAddressed === "function" && await b.snapshotAddressed(node.id, payload.lines || [])) {
          if (this.billboards.has(node.id) && entry.form === "page") await this.renderForm(entry, "page", false);
        }
      }
      if (payload.url) {
        const full = `${payload.url} : ${payload.xpath || "/"}`;
        addr.setText(full);
        addr.setAttr("title", full);
      }
    });
    // A chunk's knowledge-graph triples, drawn as nodes hung from it (G-264,
    // G-260): Triplex over a web chunk's prose, the compact code KG for a
    // `code://` chunk. A field in the panel, not a verb typed anywhere.
    if (!this.plantNoKg && !String(node.id).includes("|") && !String(node.id).startsWith("f:")) {
      const kg = head.createSpan({ cls: "vertiscope-bb-kg", text: "triples" });
      kg.setAttr("aria-label", "extract this chunk's knowledge-graph triples and draw them");
      kg.onpointerdown = (e: PointerEvent) => e.stopPropagation();
      kg.onclick = (e: MouseEvent) => { e.stopPropagation(); void this.chunkTriples(node, kg); };
    }
    const toggle = head.createSpan({ cls: "vertiscope-bb-form" });
    toggle.onpointerdown = (e: PointerEvent) => e.stopPropagation();
    toggle.onclick = (e: MouseEvent) => {
      e.stopPropagation();
      entry.userForm = true;
      void this.switchForm(entry, entry.form === "page" ? "markdown" : "page");
    };
    entry.toggle = toggle;
    // FAST first: the markdown form from the store, at once; the PAGE form
    // replaces it only when its snapshot shows something -- visible text or
    // a picture (2026-10-06: panels "very slow to render, and don't show
    // anything at all" -- a chunk spanning johnwick's full-page backgrounds
    // snapshotted to an empty frame, and the panel waited for it).
    // The PAGE form first when the chunk's page is the one in the cell: it is
    // read from the live page through the browser's chunk map in a few ms.
    // Otherwise (or if it shows nothing) the markdown form from the store.
    // First paint NEVER waits on the page form: it gets 80 ms (the live
    // page's clone from the in-memory map is a few ms when the page draws the
    // chunk); otherwise the markdown paints now and the page form replaces it
    // the moment it arrives. ONE attempt per panel -- it is also the upgrade
    // (2026-10-11: the attempt ran twice and first paint took 222-763 ms).
    const pageAttempt = this.plantSerialPanel ? null : this.tryPageForm(entry);
    const quick = this.plantSerialPanel
      ? await this.tryPageForm(entry)
      : await Promise.race([pageAttempt!, new Promise<string>((r) => window.setTimeout(() => r("slow"), this.pageFormWaitMs))]);
    if (quick !== true && entry.form !== "page") await this.renderForm(entry, "markdown", false, true);
    entry.firstPaintMs = Math.round(performance.now() - entry.openedAt);
    if (fromHover && this.hoverAskAt) {
      profiler().hover(this.hoverAskUrl || node.url || "", performance.now() - this.hoverAskAt, entry.firstPaintMs);
      this.hoverAskAt = 0;
    }
    this.panelTimes.first_paint.push(entry.firstPaintMs);
    if (this.panelTimes.first_paint.length > 200) this.panelTimes.first_paint.shift();
    const settle = this.plantSerialPanel ? this.upgradeToPage(entry) : pageAttempt!.then((ok: boolean) => {
      if (ok && entry.form === "page") {
        entry.pagePaintMs = Math.round(performance.now() - entry.openedAt);
        this.panelTimes.page_paint.push(entry.pagePaintMs);
        if (this.panelTimes.page_paint.length > 200) this.panelTimes.page_paint.shift();
      }
    });
    void Promise.resolve(settle).then(() => this.noteBillboard(node, body, entry.form || "none"));
  }

  /**
   * The chunk's page form: read from the live page, else the one SAVED when
   * it was scanned (`snapshots.py`, 2026-10-10: "I should also never see the
   * notification that something that we have already chunked and tracked is
   * inaccessible"). "live", "saved", or null when neither exists.
   */
  private async pageFormFor(entry: any, live = true): Promise<"live" | "saved" | null> {
    const id = entry.node.id;
    const ask = this.snapshotFor || ((cid: string, url: string, again?: boolean) => {
      const b: any = this.app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
      return b && typeof b.snapshotChunk === "function" ? b.snapshotChunk(cid, url, again) : Promise.resolve(false);
    });
    let fresh = false;
    if (live) { try { fresh = !!(await ask(id, entry.node.url || "", true)); } catch { /* not on the page */ } }
    if (fresh || (live && getSnapshot(id) && this.lastSnapOk(id))) return "live";
    if (this.plantNoSaved) return null;            // nothing kept from the scan
    const saved: any = await this.sidecar.savedSnapshot(id).catch(() => null);
    if (saved && saved.html) { putSnapshot(id, saved); entry.savedForm = true; this.formStats.saved++; return "saved"; }
    return getSnapshot(id) ? "live" : null;
  }

  private lastSnapOk(id: string): boolean {
    const b: any = this.app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
    const last = b && b.lastSnapshot;
    return !!last && last.cid === id && !!last.ok;
  }

  /** How much of the chunk the page form shows: the share of the markdown's
   *  words in its text (link targets excluded -- a rendered link shows its
   *  text). A page HIDES collapsed menus and language lists, and their page
   *  form showed 5-25% of chunks the store holds whole (Monarch butterfly,
   *  2026-10-10, 21 of 36 panels below 98%). */
  private async pageCoverage(entry: any): Promise<number> {
    const snap = getSnapshot(entry.node.id);
    if (!snap) return 0;
    const payload: any = await this.chunkPayload(entry.node.id);
    const md = payload && payload.lines ? payload.lines.map((l: any) => l.text).join("\n") : "";
    const words = (t: string) => (String(t || "")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, " ").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/<[^>]+>/g, " ").replace(/https?:\/\/\S+/g, " ").toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || []);
    const want = words(md);
    if (!want.length) return 1;
    const text = String(snap.html || "").replace(/<style[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " ");
    const have = new Set(words(text));
    return want.filter((w) => have.has(w)).length / want.length;
  }

  /** The page form at once, if it exists and shows the chunk; false otherwise, nothing drawn. */
  private async tryPageForm(entry: any): Promise<boolean> {
    const got = await this.pageFormFor(entry);
    const snap = got ? getSnapshot(entry.node.id) : null;
    if (!snap || !this.billboards.has(entry.node.id)) return false;
    const html = String(snap.html || "");
    const text = html.replace(/<style[\s\S]*?<\/style>/gi, "").replace(/<[^>]+>/g, " ").replace(/&[a-z#0-9]+;/gi, " ").trim();
    if (text.length < 3 && !/<(img|video|svg|canvas|picture)/i.test(html)) return false;
    return this.renderForm(entry, "page", false);
  }

  /** The page form, if it exists and shows the chunk; else the markdown stays. */
  private async upgradeToPage(entry: any): Promise<void> {
    if (!this.billboards.has(entry.node.id) || entry.form !== "markdown" || entry.userForm) return;
    const got = await this.pageFormFor(entry);
    const snap = got ? getSnapshot(entry.node.id) : null;
    if (!snap || !this.billboards.has(entry.node.id) || entry.form !== "markdown" || entry.userForm) return;
    const html = String(snap.html || "");
    const text = html.replace(/<style[\s\S]*?<\/style>/gi, "").replace(/<[^>]+>/g, " ").replace(/&[a-z#0-9]+;/gi, " ").trim();
    if (text.length < 3 && !/<(img|video|svg|canvas|picture)\b/i.test(html)) { entry.pageEmpty = true; return; }
    await this.renderForm(entry, "page", false);
    entry.pagePaintMs = Math.round(performance.now() - entry.openedAt);
    this.panelTimes.page_paint.push(entry.pagePaintMs);
    if (this.panelTimes.page_paint.length > 200) this.panelTimes.page_paint.shift();
  }

  /** A panel OPENS in page form only when the page draws this share of the chunk. */
  PAGE_FORM_COVERAGE = 0.9;
  /** Planted: page form whatever share of the chunk it shows (the Monarch chrome panels). */
  plantAnyCoverage = false;
  /** Planted: no saved page form is ever read (the banner's world). */
  plantNoSaved = false;

  /** The chunk's markdown, as Obsidian renders a note: one line per detection,
   *  its structural indent dropped (four spaces would make a code block). */
  private chunkMarkdown(payload: any): string {
    const lines: any[] = (payload && payload.lines) || [];
    // ONE image per element (2026-10-06: "many images for nodes seem
    // duplicative"). The live sensor gives an <img> two detections -- its
    // source accessor and its alt -- and each rendered a picture; measured on
    // an allrecipes card: the same jpg twice. Keyed on the element's address
    // (`url|xpath`), keeping the line that carries the alt.
    const imgAt = new Map<string, number>();
    const keep = lines.map(() => true);
    lines.forEach((l, i) => {
      const t = String(l.text || "").trim();
      if (!/^!\[/.test(t)) return;
      const el = String(l.key || "").split("|").slice(0, 2).join("|");
      if (!el) return;
      const j = imgAt.get(el);
      if (j === undefined) { imgAt.set(el, i); return; }
      const hasAlt = (s: string) => !/^!\[\]/.test(String(s || "").trim());
      if (hasAlt(t) && !hasAlt(lines[j].text)) { keep[j] = false; imgAt.set(el, i); }
      else keep[i] = false;
    });
    // Destinations are the PAGE's own (johnwick.movie stores
    // `assets/img/...`): absolutised against the chunk's url, or Obsidian
    // resolves them against the vault and every picture breaks. A video or
    // an audio file is a player, not a broken <img> (2026-10-06: "a lot of
    // rich video, audio, and images ... not registering").
    const base = baseFor(String((payload && payload.url) || ""));
    const abs = (u: string) => { try { return new URL(u, base).href; } catch { return u; } };
    const DEST = /(!?)\[([^\]]*)\]\(((?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))*)\)/g;
    const esc = (u: string) => u.replace(/"/g, "&quot;");
    return lines.filter((_l, i) => keep[i]).map((l) => {
      // In-page footnote jumps (`[[32]](#cite_note-...)`) are drawn by the
      // page as superscript marks; their nested brackets defeated the link
      // pattern and the markdown form showed "32(#cite_note-...)" as text
      // (Monarch_butterfly, 2026-10-11). The two forms match.
      const t = String(l.text || "").replace(/^\s+/, "")
        .replace(/\[\[([^\]]*)\]\]\(#[^)]*\)/g, (_m: string, n: string) => `<sup>[${n.trim()}]</sup>`)
        .replace(/\[([^\]\[]*)\]\(#[^)]*\)/g, (_m: string, txt: string) => txt);
      return t.replace(DEST, (_m, bang: string, label: string, dest: string) => {
        const u = dest ? abs(dest) : dest;
        if (bang && /\.(mp4|webm|mov|m4v|ogv)(\?|#|$)/i.test(u)) {
          return `<video controls preload="metadata" src="${esc(u)}" style="max-width:100%"></video>`;
        }
        if (bang && /\.(mp3|m4a|ogg|oga|wav|flac|aac)(\?|#|$)/i.test(u)) {
          return `<audio controls preload="metadata" src="${esc(u)}"></audio>`;
        }
        // `<...>` keeps a destination whole whatever it contains (CommonMark).
        return `${bang}[${label}](<${u}>)`;
      });
    }).reduce((out: string[], line: string, i: number, all: string[]) => {
      // A table's separator row, drawn here for the reader's renderer: the
      // stored lines pair one-to-one with addresses and hold none (`D-5`,
      // `markdown.py` `with_table_separators`).
      const row = (t: string) => /^\s*\|.*\|\s*$/.test(t || "");
      const cols = (t: string) => Math.max(1, (String(t).trim().match(/(?<!\\)\|/g) || []).length - 1);
      // A row of another width is another table (a nested one -- Wikipedia's
      // infobox "Time complexity"): one delimiter for both dropped the cells
      // past the first table's width (2026-10-18). Planted `plantOneTableRun`.
      const newTable = row(line) && row(all[i - 1]) && cols(line) !== cols(all[i - 1]) && !GraphView.plantOneTableRun;
      if (newTable) out.push("");
      // A table cannot interrupt a paragraph, and a plain line after one is
      // read as its next row: a blank line on each side (the panel drew the
      // rows as one paragraph of "| a | b |" text, 2026-10-18).
      else if (row(line) && !row(all[i - 1]) && out.length && String(out[out.length - 1]).trim()) out.push("");
      if (!row(line) && row(all[i - 1]) && String(line).trim()) out.push("");
      out.push(line);
      if (row(line) && (!row(all[i - 1]) || newTable)) {
        out.push("|" + Array(cols(line)).fill(" --- ").join("|") + "|");
      }
      return out;
    }, []).join("\n");
  }

  /**
   * Draw one form into the billboard's body. `page` re-reads the live page
   * every time it is asked (a held snapshot was served forever, so a chunk the
   * diff had rewritten showed its old rendering: "The html-side of the chunk
   * also doesn't update"). False when that form cannot be drawn.
   */
  /**
   * The page form, COMPLETE (2026-10-10: "The following method of feature
   * degradation on the dual panel representation shall be deprecated, with
   * full rendering, completeness, and matching guarantees as appropriate for
   * both panel views"). What the page DREW -- live, or as saved at scan time --
   * and beneath it every line of the chunk the page did not draw (a hidden
   * menu, a collapsed list), so the page form holds everything the markdown
   * form does. With nothing drawn or saved, the store's own HTML of the chunk.
   * Null only when the store holds no lines at all.
   */
  private async completePageSnapshot(entry: any): Promise<any | null> {
    const id = entry.node.id;
    const payload: any = entry.payload || (await this.chunkPayload(id));
    if (payload) entry.payload = payload;
    const lines: any[] = (payload && payload.lines) || [];
    const base = baseFor(String((payload && payload.url) || entry.node.url || ""));
    const abs = (u: string) => { try { return new URL(u, base).href; } catch { return u; } };
    const esc = (t: string) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    const DEST = /(!?)\[([^\]]*)\]\(((?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))*)\)/g;
    const lineHtml = (t: string) => {
      let txt = String(t || "").replace(/^\s+/, "").replace(/^#+\s*/, "").replace(/^[-*]\s+/, "");
      // A control's GLYPHS are the distilled view's, not the page's: the
      // complement drew DuckDuckGo's hidden result menu as `( Only include
      // results for this site )` in a panel that must read like the page
      // (D-36, 2026-10-19). Its words stay; the marks go. Planted
      // `plantComplementGlyphs`.
      if (!this.plantComplementGlyphs) {
        const ctl = /^\(\s(.+)\s\)$/.exec(txt);
        if (ctl) txt = ctl[1];
        txt = txt.replace(/^\[[ xX]\]\s+/, "").replace(/^===\s*(.*?)\s*===$/, "$1");
      }
      let out = "", last = 0, m: RegExpExecArray | null;
      DEST.lastIndex = 0;
      while ((m = DEST.exec(txt))) {
        out += esc(txt.slice(last, m.index));
        const u = abs(m[3] || "");
        if (m[1]) out += /^https?:/.test(u) ? `<img src="${esc(u)}" alt="${esc(m[2])}" style="max-width:100%;height:auto">` : "";
        else out += /^https?:/.test(u) && !/^#/.test(m[3] || "") ? `<a href="${esc(u)}" data-href="${esc(u)}">${esc(m[2] || u)}</a>` : esc(m[2]);
        last = m.index + m[0].length;
      }
      out += esc(txt.slice(last));
      return out.trim() ? `<div style="margin:2px 0">${out}</div>` : "";
    };
    // Destinations are never content: `](dest)` is dropped whatever the
    // brackets before it hold -- a footnote `[[ 77 ]](#cite_note-...)` nests
    // them, and its "cite note" counted as undrawn words (ko.wikipedia, Higgs
    // boson, 2026-10-10: the complement repeated what the page had drawn).
    const words = (t: string) => (String(t || "").replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
      .replace(/\]\([^)]*\)/g, "] ").replace(/<[^>]+>/g, " ").replace(/https?:\/\/\S+/g, " ")
      .toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || []);
    // A picture is the same picture at any size: a page draws the thumbnail
    // (`/thumb/.../250px-X.jpg`) of the file a line names (`X.jpg`).
    const picName = (u: string) => {
      let n = String(u || "").split("#")[0].split("?")[0];
      try { n = decodeURIComponent(n); } catch { /* as is */ }
      n = (n.split("/").pop() || "").toLowerCase().replace(/^\d+px-/, "");
      return n.replace(/\.(png|jpe?g|gif|webp|svg)\.(png|jpe?g|gif|webp)$/, ".$1");
    };
    let snap: any = getSnapshot(id);
    if (!snap) {
      const html = String((payload && payload.html) || "");
      const body = html.trim() ? html : lines.map((l) => lineHtml(l.text)).join("");
      if (!body.trim()) return null;
      this.formStats.from_store++;
      return { html: body, bg: "", color: "", font: "", elements: 0, found: 0,
               url: String((payload && payload.url) || entry.node.url || ""), at: Date.now() };
    }
    if (this.plantNoComplement || !lines.length) return snap;
    const drawn = new Set(words(String(snap.html || "").replace(/<style[\s\S]*?<\/style>/gi, " ")));
    const drawnPics = new Set<string>();
    String(snap.html || "").replace(/<img[^>]*\bsrc="([^"]+)"/gi, (_m: string, u: string) => { drawnPics.add(picName(u)); return ""; });
    const missing = lines.filter((l) => {
      const t = String(l.text || "");
      const img = /!\[[^\]]*\]\(([^)\s]+)/.exec(t);
      if (img) return !drawnPics.has(picName(abs(img[1])));
      // Only footnote MARKS (`[[ 33 ]](#cite_note-...)`, `[a](#...)`): the page
      // drew them as superscripts. An in-page link that NAMES something is
      // content -- a hidden menu or a table of contents of `#` anchors was
      // read as all marks and never complemented (G-130, 2026-10-11: 0 of 5
      // menu items shown). Planted with the complement (`plantNoComplement`).
      const rest = t.replace(/\[(\[?[^\]]*\]?)\]\((#[^)]*)\)/g, (m0: string, label: string, dest: string) => {
        const inner = String(label || "").replace(/[\[\]\s]/g, "");
        return /^#cite/i.test(dest) || /^[\p{L}\p{N}]{0,3}$/u.test(inner) ? " " : m0;
      }).replace(/[\[\]\s,;.]/g, "");
      if (!rest) return false;
      const w = words(t);
      return w.length > 0 && w.filter((x) => !drawn.has(x)).length / w.length > 0.5;
    });
    if (!missing.length) return snap;
    this.formStats.complemented++;
    entry.complemented = missing.length;
    return { ...snap, html: String(snap.html) +
      '<div class="vertiscope-complement" style="border-top:1px dashed rgba(128,128,128,.6);margin-top:8px;padding-top:6px">' +
      missing.map((l) => lineHtml(l.text)).join("") + "</div>" };
  }
  /** Planted: the page form shows only what the page drew (the incomplete one). */
  plantNoComplement = false;
  /** Planted (D-36): the complement keeps the distilled control glyphs. */
  plantComplementGlyphs = false;

  /** Planted (D-36): the fallback markdown overwrites a page form that landed while it waited. */
  plantPanelRace = false;
  private async renderForm(entry: any, form: "page" | "markdown", fresh = true, fallback = false): Promise<boolean> {
    const body = entry.el.querySelector(".vertiscope-bb-body") as HTMLElement | null;
    if (!body) return false;
    const id = entry.node.id;
    if (form === "page") {
      const ask = this.snapshotFor || ((cid: string, url: string, again?: boolean) => {
        const b: any = this.app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
        return b && typeof b.snapshotChunk === "function" ? b.snapshotChunk(cid, url, again) : Promise.resolve(false);
      });
      try { await ask(id, entry.node.url || "", fresh); } catch { /* not open in the cell */ }
      const snap = await this.completePageSnapshot(entry);
      if (!snap) return false;
      body.empty();
      renderSnapshot(body, snap, {
        maxHeight: 420, onLink: (h) => this.onNavigate(h), cid: id,
        onAct: (rec) => this.onAct(id, rec),
        onFieldDone: () => this.releaseHeld(entry),
      });
    } else {
      if (fresh || !entry.payload) entry.payload = (await this.chunkPayload(id)) || entry.payload;
      // The FALLBACK paint, while the page form was given its head start:
      // if the page form landed while the payload was fetched, it stays. The
      // markdown emptied the body after it and replaced a page form of 77
      // elements with its own half a second after the panel opened (D-36,
      // 2026-10-19: "form none" from the graph).
      if (fallback && entry.form === "page" && !this.plantPanelRace) return true;
      body.empty();
      const host = body.createDiv({ cls: "vertiscope-bb-md markdown-rendered" });
      const md = this.chunkMarkdown(entry.payload);
      if (!md.trim()) host.setText("(no lines stored for this chunk)");
      else await MarkdownRenderer.render(this.app, md, host, "", this);
      // A link goes to the browser cell, never the vault's own router.
      host.querySelectorAll("a").forEach((a: HTMLAnchorElement) => {
        a.onclick = (e: MouseEvent) => {
          e.preventDefault(); e.stopPropagation();
          const h = a.getAttribute("href") || a.getAttribute("data-href") || "";
          if (/^https?:/.test(h)) this.onNavigate(h);
        };
      });
    }
    entry.form = form;
    entry.snapshot = form === "page";
    entry.el.toggleClass("is-md", form === "markdown");
    if (entry.toggle) entry.toggle.setText(form === "page" ? "markdown" : "page");
    return true;
  }

  /**
   * The top-right button: the other form, at that form's own size, resized
   * about the panel's CENTRE (2026-10-06: "resizing centered by the button
   * clicked at the top right corner of the panel to get the page and markdown
   * sizing unique").
   */
  /** The page button's outcomes, for the harness: asked, shown, unavailable (with why). */
  formStats = { asked: 0, shown: 0, unavailable: 0, saved: 0, from_store: 0, complemented: 0, last_why: "" };

  private async switchForm(entry: any, form: "page" | "markdown"): Promise<void> {
    const before = entry.el.getBoundingClientRect();
    const host = (this.billboardLayer as HTMLElement).getBoundingClientRect();
    const cx = before.left + before.width / 2 - host.left;
    const cy = before.top + before.height / 2 - host.top;
    if (form === "page") {
      // A FRESH read of the live page, else the form SAVED at scan time: the
      // snapshot taken when the panel opened may have failed (the chunk
      // scrolled out of a list since) and the button rendered only that
      // cached one -- it did nothing (2026-10-10: "'Page' button doesn't
      // work"), then said "scroll to where it was" ("I should also never see
      // the notification ...").
      this.formStats.asked++;
      if (!this.plantDeadPageButton) await this.pageFormFor(entry);
    }
    const ok = await this.renderForm(entry, form);
    if (!ok) {
      // Only a chunk with NO stored lines lands here; the button is never
      // shown as degraded (2026-10-10: that state "shall be deprecated").
      if (form === "page") { this.formStats.unavailable++; this.formStats.last_why = "no lines stored"; }
      return;
    }
    if (form === "page") this.formStats.shown++;
    const after = entry.el.getBoundingClientRect();
    const left = cx - after.width / 2, top = cy - after.height / 2;
    if (entry.pinned) {
      entry.el.style.left = `${Math.round(left)}px`;
      entry.el.style.top = `${Math.round(top)}px`;
      return;
    }
    // Following its node: keep the new offset from the node, so the centre
    // stays where it was and the panel goes on following.
    const at: any = this.graph ? (this.graph as any).graph2ScreenCoords(entry.node.x, entry.node.y, entry.node.z) : null;
    if (at) { entry.dx = Math.round(left - at.x); entry.dy = Math.round(top - at.y); }
  }

  /**
   * Every billboard opened, and what its body actually SHOWED 1.5 s later
   * (2026-10-06: "a clicked panel not rendering. This has begun to happen
   * quite a bit now"). Text and shadow-root content are measured where the
   * reader sees them; an empty body is recorded with what the node was.
   */
  billboardLog: { at: number; id: string; level: string; force: boolean; url: string;
                  via: string; text: number; shadow: number; frame: number; empty: boolean }[] = [];
  private noteBillboard(node: any, body: HTMLElement, via: string): void {
    window.setTimeout(() => {
      let shadow = 0, frame = 0;
      body.querySelectorAll("*").forEach((el: any) => {
        if (el.shadowRoot) shadow += (el.shadowRoot.textContent || "").trim().length
          + el.shadowRoot.querySelectorAll("img,svg,input,button,a").length;
        if (el.tagName === "IFRAME") {
          try { frame += ((el.contentDocument && el.contentDocument.body && el.contentDocument.body.textContent) || "").trim().length; }
          catch { frame += 1; }
        }
      });
      const text = (body.innerText || "").trim().length;
      const e: any = this.billboards.get(node.id);
      this.billboardLog.push({ at: Date.now(), id: String(node.id), level: String(node.level || ""),
        force: !!node.force, url: String(node.url || ""), via, text, shadow, frame,
        empty: text + shadow + frame === 0, first_paint_ms: e?.firstPaintMs ?? null,
        page_paint_ms: e?.pagePaintMs ?? null, page_empty: !!e?.pageEmpty, from_hover: !!e?.fromHover } as any);
      if (this.billboardLog.length > 100) this.billboardLog.shift();
    }, 1500);
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
  /** Telescope passes run and skipped (their inputs unchanged), for the harness. */
  teleRan = 0;
  teleSkipped = 0;
  /** Planted (D-40): every open page re-telescoped on every pass, as before. */
  plantRetelescopeAll = false;
  private fitChunkSizes(data: any): void {
    if (!this.graph || this.plantBigChunks) return;
    // Url view's pass (an OPEN page's chunks sized and relaxed around its
    // node), never chunk view's: there every chunk has a page, so every page
    // read as open and the telescope and relaxCloud ran over all 26k chunks,
    // synchronously, on every projector update and absorb -- frames of 5-7 s,
    // 53% of the CPU (2026-10-12: "significant lag experienced here"). Chunk
    // view has its own one size and its own bounded, time-sliced relax.
    // Planted (`plantFitInChunkView`): the pass runs there too, as it did.
    if (this.level === "chunk" && !this.plantFitInChunkView) { this.fitSkipped++; return; }
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
    // The scene's radius: the 90th percentile page distance from the pages'
    // centroid -- what an open page's telescope is allowed a share of.
    let sceneR = 0;
    if (pages.length) {
      const c = [0, 1, 2].map((k) => pages.reduce((a: number, q: any) => a + at(q)[k], 0) / pages.length);
      const ds = pages.map((q: any) => { const [x, y, z] = at(q); return Math.hypot(x - c[0], y - c[1], z - c[2]); })
        .filter(Number.isFinite).sort((a: number, b: number) => a - b);
      sceneR = ds.length ? ds[Math.min(ds.length - 1, Math.floor(ds.length * 0.9))] : 0;
    }
    const byUrl = new Map<string, any[]>();
    for (const n of data.nodes) {
      if ((n.force && !n.projected) || n.level === "page" || !n.url) continue;
      (byUrl.get(n.url) || byUrl.set(n.url, []).get(n.url)!).push(n);
    }
    // Each open page's bound, from the FIT (before anything is moved aside).
    const bounds = new Map<string, { B: number; R: number }>();
    for (const [url] of byUrl) {
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
      // The telescope's bound is the larger of that and a share of the
      // SCENE (2026-10-06, measured: on johnwick.movie the neighbourhood was
      // 37 units against a raw p90 chunk distance of 31.5, so telescoping
      // could only shrink -- k 0.65 -- and the cluster stayed a small dense
      // ball; pages sit close in the page fit, and 0.45 x the gap is little).
      bounds.set(url, { B: Math.max(R, 0.35 * sceneR), R });
    }
    // ROOM for each open page, made by moving its NEIGHBOURS, never its own
    // chunks (2026-10-10: "get umapped within their url domain node's scope";
    // "force-directed post-umap ... with the original residual coordinates as
    // phantom coordinates to keep the nodes closer to their original
    // locations while enforcing collision ... with a radius/diameter safety
    // factor on collision spheres"). Measured on Monarch_butterfly: 26 of 192
    // chunks were nearer their own url node than any other. An open page
    // claims a sphere of its bound B; a closed page inside it is pushed out
    // radially to 2B + its radius (so every chunk within B of the open page
    // is nearer it than the neighbour), two open pages until their spheres
    // part. The moved page keeps its fit as `homeFit` -- the phantom it goes
    // back to when the open page closes (the restore at the top of this pass).
    // REMOVED 2026-10-12 (the reader, asked "should the room-pass ring be
    // removed?": "Remove it"): pushed out to 2B, the closed neighbours stood
    // on a shell around every open page -- the ring. Pages stay at their fit;
    // pages moved before glide home (the restore at the top of this pass).
    // Planted (`plantRoomRing`): the push, as it was.
    if (this.plantRoomRing && !this.plantNoRoom && bounds.size) {
      const open = [...bounds.entries()].sort((a, b) => b[1].B - a[1].B);
      for (const [url, { B }] of open) {
        const page = pages.find((p: any) => p.url === url);
        if (!page) continue;
        const [px, py, pz] = at(page);
        for (const q of pages) {
          if (q === page) continue;
          const qb = bounds.get(q.url);
          const rq = qb ? qb.B : drawnRadius({ ...q, val: q.fullVal ?? q.val }, relSize, media) * COLLIDER_SAFETY;
          const want = (qb ? B + qb.B : this.roomFactor * B + rq) * 1.02;
          const [qx, qy, qz] = at(q);
          let dx = qx - px, dy = qy - py, dz = qz - pz;
          let d = Math.hypot(dx, dy, dz);
          if (d >= want) continue;
          if (d < 1e-6) { dx = 1; dy = 0; dz = 0; d = 1; }
          if (!q.homeFit) { q.homeFit = [q.fitX ?? q.x, q.fitY ?? q.y, q.fitZ ?? q.z ?? 0]; q.homeAnchor = q.anchorPos; }
          const f = want / d;
          q.fitX = px + dx * f; q.fitY = py + dy * f; q.fitZ = pz + dz * f;
          // Its territory moves with it: `contain` holds a page near its
          // anchor, and an anchor left at the fit pulled every moved page
          // straight back (Monarch, 2026-10-11: targets ~288 out, drawn at
          // 57-111). The fit's own anchor is kept in `homeAnchor`.
          if (q.anchorPos) q.anchorPos = [q.fitX, q.fitY, q.fitZ];
          q.__freeUntil = performance.now() + 3000;
          this.roomStats.moved++;
        }
      }
    }
    // Url nodes the fit put ON each other -- identical content lands at one
    // point (2026-10-11: 30 coincident pairs, all copies of a fixture page
    // from two ports; the same article on two mirrors would do it) -- and,
    // pinned at rest, the collider never parts them (`G-21`). Their targets
    // are relaxed like a page's chunks: spheres at the safety factor, each
    // anchored to its fit. Planted: left where the fit put them.
    if (!this.plantPagesTogether && pages.length > 1) {
      const pos = pages.map((q: any) => at(q) as V3);
      const radii = pages.map((q: any) => drawnRadius({ ...q, val: q.fullVal ?? q.val }, relSize, media));
      // No root sphere here: a root out of reach, so only the collisions act.
      const rel = relaxCloud([1e12, 1e12, 1e12], pos, radii, 0, Infinity, { safety: COLLIDER_SAFETY, anchor: 0 });
      pages.forEach((q: any, i: number) => {
        const [x, y, z] = rel.pos[i];
        if (Math.hypot(x - pos[i][0], y - pos[i][1], z - pos[i][2]) < 1e-6) return;
        if (!q.homeFit) { q.homeFit = [q.fitX ?? q.x, q.fitY ?? q.y, q.fitZ ?? q.z ?? 0]; q.homeAnchor = q.anchorPos; }
        q.fitX = x; q.fitY = y; q.fitZ = z;
        if (q.anchorPos) q.anchorPos = [x, y, z];
        this.roomStats.parted++;
      });
    }
    // A page at rest is calm-pinned, and the home force does not move a pinned
    // node: a target moved aside (or back to its phantom) was never reached --
    // Monarch's 669 chunks, 48 nearer their own url node (2026-10-11). Every
    // page whose drawn place is off its target GLIDES there.
    if (!this.plantNoRoom) {
      for (const q of pages) {
        if (!Number.isFinite(q.x) || !Number.isFinite(q.fitX)) continue;
        if (Math.hypot(q.x - q.fitX, q.y - q.fitY, (q.z || 0) - (q.fitZ || 0)) > 1) {
          this.glide(q, [q.fitX, q.fitY, q.fitZ ?? 0]);
          this.roomStats.glided++;
        }
      }
    }
    for (const [url, chunks] of byUrl) {
      const page = pages.find((p: any) => p.url === url);
      if (!page) continue;
      const bd = bounds.get(url);
      if (!bd) continue;
      const R = bd.R;
      const B = bd.B;
      const [px, py, pz] = at(page);
      // No exclusion sphere around the url node (2026-10-11: "Remove the
      // repulsion sphere entirely please", then "Giant clumping problem").
      // It was a third of the distance to the nearest url node, and it WIDENED
      // the page's bound to make room outside itself -- a wider bound is a
      // wider room per chunk, so chunks were no longer shrunk and drew at full
      // size, packed into a cloud. The chunks keep clear of the url node's
      // DRAWN body only, as any two nodes do (`telescope`, `relaxCloud`).
      // **Only a cloud whose inputs moved is telescoped again.** The pass runs
      // on every projection of ANY url, and re-telescoping (and relaxing)
      // every open page each time held the main thread: 5.2 s of 40 s on the
      // Julia forum went to `relaxCloud` under `applyProjected` while one
      // page streamed, and a hover's outline waited behind it (D-40: ours
      // p95 347 ms, 2026-10-19). The targets are a function of the url
      // node's place and drawn size, the bound, the scale, and each chunk's
      // fit and size -- all in the signature, a chunk's fit by whether it
      // still holds what the last pass gave it (`__tele`). Planted
      // `plantRetelescopeAll`: every open page, every time, as before.
      let vals = 0;
      for (const c of chunks) vals += c.val ?? 0;
      const sig = [B, px, py, pz, page.val, relSize, media ? 1 : 0, chunks.length, Math.round(vals * 1000)].join("|");
      const still = chunks.every((c: any) => c.__tele && c.__tele[0] === c.fitX && c.__tele[1] === c.fitY && c.__tele[2] === c.fitZ);
      if (!this.plantRetelescopeAll && page.__teleSig === sig && still) this.teleSkipped++;
      else { this.telescope(page, chunks, B, relSize, media); page.__teleSig = sig; this.teleRan++; }
      // A floor, so a crowded page's chunks stay visible: the fixed collider
      // margin could eat the whole room and leave specks (val ~ 0).
      const floor = 0.35 * relSize;
      const room = Math.max(floor, ((this.plantNoTelescope ? R : B) * Math.cbrt(0.6 / chunks.length) - COLLIDER_MARGIN) / COLLIDER_SAFETY);
      for (const c of chunks) {
        if (c.fullVal === undefined) c.fullVal = c.val ?? 1;
        const r = drawnRadius({ ...c, val: c.fullVal }, relSize, media);
        const was = c.val;
        // Shrunk to the room when crowded; GROWN into it when the room is
        // larger, up to 2.5x the radius (2026-10-06, measured on
        // johnwick.movie: chunks drawn at 2.7 units with 6.9 of room each --
        // an open page read as a knot of specks).
        // Growth REVERTED (2026-10-06): up to 2.5x made johnwick's picture
        // billboards overlap ("Nodes are way too closely packed together
        // now"). Shrink-to-room only, as before.
        const grow = 1;
        c.val = r > room ? c.fullVal * Math.pow(room / r, 3) : c.fullVal * Math.pow(Math.max(1, grow), 3);
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

  /** Planted: projector moves glide to the raw fit, never re-telescoped (the drift after every update). */
  plantRawMoves = false;
  /** Planted: the fit's raw radii (a dense core), and no relaxation (overlaps, chunks inside the url node). */
  plantNoUniform = false;
  plantNoRelax = false;
  /** Planted: open pages make no room -- their clouds reach into their neighbours (D-49). */
  plantNoRoom = false;
  plantFitInChunkView = false;
  /** Planted (G-94 with G-188): spacing measured without the node scale. */
  plantUnscaledSpacing = false;
  /** Planted (G-82): a pin on a chunk drawn through another finds no node, as before. */
  plantNoPinAlias = false;
  /** Planted (G-95): a page click unfolds step-wise and never collapses, as before. */
  plantUnfoldOnClick = false;
  fitSkipped = 0;
  /** Planted: the room pass pushes closed neighbours out to a shell -- the ring (removed 2026-10-12). */
  plantRoomRing = false;
  /** How far a closed neighbour is moved from an open page, in its bound B:
   *  2 guarantees every chunk is nearer its own url node than the neighbour. */
  roomFactor = 2;
  roomStats = { moved: 0, glided: 0, parted: 0 };

  /** Planted by the telescope's check: chunks at their raw fit (the packed ball). */
  plantNoTelescope = false;
  // ---- G-241: the code property graph's edges in the view ----------------
  /** Which code edge kinds are drawn. */
  codeEdgeKinds: Record<"CALLS" | "INHERITS", boolean> = { CALLS: true, INHERITS: true };
  static CODE_EDGE_COLOR: Record<string, string> = { CALLS: "#f5a623", INHERITS: "#7ed321" };
  /** Per open code page, its edges by node id (from `/cpg_edges`). */
  private codeEdges = new Map<string, { source: string; target: string; kind: string }[]>();
  codeEdgeStats = { pages: 0, fetched: 0, drawn: { CALLS: 0, INHERITS: 0 } as Record<string, number> };
  private codeEdgeButtons: HTMLElement[] = [];
  private showCodeButtons(on: boolean): void {
    for (const b of this.codeEdgeButtons) { const d = on ? "" : "none"; if (b.style.display !== d) b.style.display = d; }
  }
  /**
   * **Special files as nodes** (PLUGIN_GOAL 186k, 2026-10-18). A file a page
   * links to -- a model (.gguf), a table (.csv), JSON, an archive, a PDF --
   * is drawn as its own node hung from the chunk whose line links it, in its
   * kind's colour; its panel shows the file and a download field that ASKS
   * before it fetches anything ("prompt the user before applying a download
   * on-click"). Planted `plantNoFileNodes`: no file is drawn.
   */
  plantNoFileNodes = false;
  fileStats = { pages: 0, drawn: 0, downloads_asked: 0, downloads_confirmed: 0, downloads_cancelled: 0 };
  private filesLoadedAt = new Map<string, number>();
  static FILE_COLOURS: Record<string, string> = { model: "#c58af9", weights: "#c58af9", table: "#81c995",
                                                  json: "#fdd663", archive: "#f28b82", pdf: "#78d9ec" };
  private async loadFiles(url: string): Promise<void> {
    if (this.plantNoFileNodes || !url || /^(code|vault):\/\//.test(url)) return;
    const k = url.split("#")[0];
    const at = this.filesLoadedAt.get(k) || 0;
    if (performance.now() - at < 60000) return;
    this.filesLoadedAt.set(k, performance.now());
    const got: any = await this.sidecar.files(k).catch(() => null);
    const files: any[] = (got && Array.isArray(got.files)) ? got.files : [];
    if (!files.length || !this.graph) return;
    this.fileStats.pages++;
    for (const f of files) {
      this.ensureUnitNode({ id: "file:" + f.key, url: f.url, virtual: true, parentId: f.cid, name: f.name,
                            color: GraphView.FILE_COLOURS[f.kind] || "#e8eaed", fileRef: f });
      this.fileStats.drawn++;
    }
  }
  /** A file node's panel: what the file is, and a download that asks first. */
  private renderFilePanel(node: any, body: HTMLElement, addr: HTMLElement): void {
    const f = node.fileRef;
    addr.setText(`${f.url} : ${f.xpath || "/"}`);
    addr.setAttr("title", `${f.url} : ${f.xpath || "/"}`);
    const box = body.createDiv({ cls: "vertiscope-file" });
    box.createDiv({ cls: "vertiscope-file-kind", text: `${f.kind} \u00b7 ${f.ext}` });
    box.createDiv({ cls: "vertiscope-file-name", text: f.label && f.label !== f.name ? `${f.name} \u2014 ${f.label}` : f.name });
    const link = box.createEl("a", { cls: "vertiscope-file-href", text: f.href, href: f.href });
    link.setAttr("target", "_blank");
    const size = box.createDiv({ cls: "vertiscope-file-size", text: "size: asking the server\u2026" });
    let bytes: number | null = null;
    void this.sidecar.fileHead(f.href).then((h: any) => {
      bytes = h && typeof h.size === "number" ? h.size : null;
      size.setText(bytes !== null ? `size: ${GraphView.fmtBytes(bytes)}` : `size: unknown${h && h.error ? " (" + h.error + ")" : ""}`);
    });
    const dest = f.kind === "model" ? "the model directory (~/.cache/gpt4all), installed as a model"
      : f.kind === "pdf" ? "the workspace, then chunked into the store like a page" : "the workspace's downloads/ folder";
    const row = box.createDiv({ cls: "vertiscope-file-actions" });
    const field = row.createSpan({ cls: "vertiscope-file-dl", text: "download" });
    const status = box.createDiv({ cls: "vertiscope-file-status" });
    field.onpointerdown = (e: PointerEvent) => e.stopPropagation();
    field.onclick = (e: MouseEvent) => {
      e.stopPropagation();
      // ASK first: name, size, destination -- and nothing is sent until the
      // reader confirms.
      this.fileStats.downloads_asked++;
      row.empty();
      row.createSpan({ cls: "vertiscope-file-ask",
        text: `Download ${f.name}${bytes !== null ? " (" + GraphView.fmtBytes(bytes) + ")" : ""} to ${dest}?` });
      const yes = row.createSpan({ cls: "vertiscope-file-dl", text: "confirm" });
      const no = row.createSpan({ cls: "vertiscope-file-dl", text: "cancel" });
      for (const b of [yes, no]) b.onpointerdown = (ev: PointerEvent) => ev.stopPropagation();
      no.onclick = (ev: MouseEvent) => {
        ev.stopPropagation();
        this.fileStats.downloads_cancelled++;
        row.empty(); row.appendChild(field);
      };
      yes.onclick = async (ev: MouseEvent) => {
        ev.stopPropagation();
        this.fileStats.downloads_confirmed++;
        row.empty();
        const started: any = await this.sidecar.download(f.href, f.kind, f.name);
        if (!started || started.error) { status.setText(`not started: ${started ? started.error : "the sidecar did not answer"}`); return; }
        const tick = async () => {
          const st: any = await this.sidecar.downloadStatus(f.href);
          if (!st) return;
          if (st.state === "running") {
            status.setText(`downloading ${GraphView.fmtBytes(st.bytes || 0)}${st.total ? " of " + GraphView.fmtBytes(st.total) : ""}`);
            window.setTimeout(tick, 1000);
          } else if (st.state === "done") {
            status.setText(`saved: ${st.path}` + (st.indexed ? ` -- chunked: ${st.indexed.chunks} chunks` : ""));
          } else if (st.state === "error") {
            status.setText(`failed: ${st.error}`);
          }
        };
        void tick();
      };
    };
  }
  static fmtBytes(n: number): string {
    return n >= 1e9 ? (n / 1e9).toFixed(2) + " GB" : n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : n >= 1e3 ? (n / 1e3).toFixed(0) + " KB" : n + " B";
  }

  /**
   * **A chunk's knowledge graph, drawn** (G-264, G-260; PLUGIN_GOAL 186h,
   * 186l): its entities as small nodes hung from the chunk -- force-directed
   * about it, no embedding of their own -- and its triples as lines between
   * them (drawn, never forces, like G-241's code edges). Planted `plantNoKg`.
   */
  plantNoKg = false;
  kgStats = { asked: 0, done: 0, entities: 0, triples_drawn: 0, last_error: "", last_s: 0 };
  private kgEdges = new Map<string, { source: string; target: string; p: string }[]>();
  static KG_COLOUR = "#ffb86c";
  async chunkTriples(node: any, button?: HTMLElement): Promise<any> {
    const cid = String(node.id), url = String(node.url || "");
    this.kgStats.asked++;
    const say = (t: string) => { if (button) button.setText(t); };
    let triples: { s: string; p: string; o: string }[] = [];
    let entities: Record<string, { type: string; name: string }> = {};
    if (url.startsWith("code://")) {
      say("triples\u2026");
      const got: any = await this.sidecar.codeKg(url).catch(() => null);
      const payload: any = await this.chunkPayload(cid);
      // The chunk's SCOPE: a code chunk sits on an element under its class or
      // function (`/module/class/code`), the triples at the scope's own
      // address and below (`/module/class/function[2]`). Cut back to the last
      // module / class / function step; `[1]` dropped as the CPG spells it.
      const steps = String((payload && payload.xpath) || "").replace(/\[1\](?=\/|$)/g, "").split("/");
      while (steps.length > 1 && !/^(module|class|function)(\[\d+\])?$/.test(steps[steps.length - 1])) steps.pop();
      const xp = steps.join("/");
      const mine = ((got && got.triples) || []).filter((t: any) => {
        const at = String(t.at || "").split("|")[1] || "";
        return !xp || at === xp || at.startsWith(xp + "/");
      }).slice(0, 120);
      for (const t of mine) {
        entities[t.s] = entities[t.s] || { type: "code", name: t.s };
        entities[t.o] = entities[t.o] || { type: "code", name: t.o };
        triples.push({ s: t.s, p: t.p, o: t.o });
      }
    } else {
      say("triples: reading\u2026");
      const job: any = await this.sidecar.modelRun({ role: "triplex", cid });
      if (!job || !job.id) { this.kgStats.last_error = "not started"; say("triples: not started"); return null; }
      let st: any = null;
      for (let i = 0; i < 180; i++) {
        await new Promise((r) => window.setTimeout(r, 1000));
        st = await this.sidecar.modelJob(job.id);
        if (st && st.state !== "running") break;
        say(`triples: reading ${i + 1}s`);
      }
      const v = st && st.result && st.result.value;
      if (!v) { this.kgStats.last_error = (st && st.error) || "no answer"; say("triples: " + this.kgStats.last_error.slice(0, 40)); return st; }
      this.kgStats.last_s = st.s || 0;
      for (const [k, e] of Object.entries(v.entities || {})) entities[(e as any).name] = { type: (e as any).type, name: (e as any).name };
      triples = (v.triples || []).map((t: any) => ({ s: t.s, p: t.p, o: t.o }));
    }
    const ids: Record<string, string> = {};
    for (const [name, e] of Object.entries(entities)) {
      const id = `kg:${cid}:${name}`;
      ids[name] = id;
      this.ensureUnitNode({ id, url, virtual: true, parentId: cid, name: `${e.type}: ${name}`, color: GraphView.KG_COLOUR,
                            kgEntity: { cid, name, type: e.type, triples: triples.filter((t) => t.s === name || t.o === name) } });
    }
    this.kgEdges.set(cid, triples.filter((t) => ids[t.s] && ids[t.o] && t.s !== t.o).map((t) => ({ source: ids[t.s], target: ids[t.o], p: t.p })));
    this.kgStats.done++;
    this.kgStats.entities += Object.keys(entities).length;
    this.batchDirty = true;
    say(`triples: ${Object.keys(entities).length} entities, ${triples.length} triples`);
    return { entities: Object.keys(entities).length, triples: triples.length };
  }
  private drawableKgEdges(nodes: any[]): any[] {
    if (this.plantNoKg || !this.kgEdges.size) { this.kgStats.triples_drawn = 0; return []; }
    const byId = new Map<string, any>();
    for (const n of nodes) byId.set(String(n.id), n);
    const out: any[] = [];
    for (const edges of this.kgEdges.values()) {
      for (const e of edges) {
        const s = byId.get(e.source), t = byId.get(e.target);
        if (s && t) out.push({ source: s, target: t, color: GraphView.KG_COLOUR, alpha: 0.9, kg: e.p });
      }
    }
    this.kgStats.triples_drawn = out.length;
    return out;
  }
  private renderKgPanel(node: any, body: HTMLElement, addr: HTMLElement): void {
    const k = node.kgEntity;
    addr.setText(`${k.type}: ${k.name}`);
    const box = body.createDiv({ cls: "vertiscope-file" });
    box.createDiv({ cls: "vertiscope-file-kind", text: `entity \u00b7 ${k.type}` });
    box.createDiv({ cls: "vertiscope-file-name", text: k.name });
    if (!k.triples.length) box.createDiv({ cls: "vertiscope-file-status", text: "no triple names it" });
    for (const t of k.triples) box.createDiv({ cls: "vertiscope-file-href", text: `${t.s} \u2014 ${t.p} \u2192 ${t.o}` });
  }

  /**
   * **Panel content-completeness** (G-197, PLUGIN_GOAL 124: "a development MCP
   * tool ... to check the content-completeness on rendering to streamed
   * interactive chunk diffs"). Opens a chunk's panel, draws each form, and
   * compares it with the stored chunk: every picture the chunk's lines name --
   * rendered? loaded? broken? -- and how much of its text the form shows.
   * The MCP tool `panel_completeness` calls this. Closes what it opened.
   */
  async panelCompleteness(cid: string, url = ""): Promise<any> {
    const payload: any = await this.chunkPayload(cid);
    const lines: any[] = (payload && payload.lines) || [];
    const base = baseFor(String((payload && payload.url) || url || ""));
    const abs = (u: string) => { try { return new URL(u, base).href; } catch { return u; } };
    const tail = (u: string) => { try { const x = new URL(u); return (x.hostname + x.pathname).split("/").slice(-2).join("/").toLowerCase(); } catch { return String(u).toLowerCase(); } };
    const IMG = /!\[[^\]]*\]\(<?([^)\s>]+)>?\)/g;
    const expected = [...new Set(lines.flatMap((l: any) => [...String(l.text || "").matchAll(IMG)].map((m) => abs(m[1]))))];
    const words = lines.map((l: any) => String(l.text || "").replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[`*_#>|]/g, " ").replace(/\s+/g, " ").trim())
      .filter((t: string) => t.length > 3);
    const had = this.billboards.get(cid);
    const node = this.graph?.graphData().nodes.find((n: any) => String(n.id) === cid)
      || { id: cid, url: (payload && payload.url) || url, level: "chunk", virtual: true, x: 0, y: 0, z: 0 };
    if (!had) await this.openBillboard(node, false, false);
    const e: any = this.billboards.get(cid);
    const out: any = { cid, url: (payload && payload.url) || url, lines: lines.length, images_expected: expected.length, forms: {} };
    if (!e) return { ...out, error: "no panel" };
    for (const form of ["markdown", "page"] as const) {
      for (let i = 0; i < 6 && e.form !== form; i++) { await this.switchForm(e, form); await new Promise((r) => window.setTimeout(r, 300)); }
      if (e.form !== form) { out.forms[form] = { drawn: false }; continue; }
      // Read a render that has FINISHED, of the stored chunk as it is now: a
      // panel that opened in this form may still be drawing an older payload
      // (a fresh capture's check saw 3 of 4 pictures that way).
      if (form === "markdown") await this.renderForm(e, "markdown", true);
      const body: HTMLElement | null = e.el.querySelector(".vertiscope-bb-body");
      // The page form draws its snapshot in an iframe (`vertiscope-snapshot`):
      // its pictures and text are in THAT document, not the panel's.
      const roots = (): HTMLElement[] => {
        const out: HTMLElement[] = body ? [body] : [];
        const frames: HTMLIFrameElement[] = body ? Array.from(body.querySelectorAll("iframe")) : [];
        for (const f of frames) {
          try { if (f.contentDocument?.body) out.push(f.contentDocument.body); } catch { /* cross-origin */ }
        }
        return out;
      };
      const imgsNow = (): HTMLImageElement[] => roots().flatMap((r) => Array.from(r.querySelectorAll("img")));
      const deadline = performance.now() + 4000;
      while (performance.now() < deadline) {
        if (imgsNow().every((im) => im.complete)) break;
        await new Promise((r) => window.setTimeout(r, 200));
      }
      const imgs = imgsNow();
      const srcs = imgs.map((im) => im.currentSrc || im.src);
      const rendered = new Set(srcs.map(tail));
      const text = roots().map((r) => r.textContent || "").join(" ").replace(/\s+/g, " ");
      const shown = words.filter((w: string) => text.includes(w.slice(0, 40))).length;
      out.forms[form] = { drawn: true, images_rendered: imgs.length,
                          images_loaded: imgs.filter((im) => im.complete && im.naturalWidth > 0).length,
                          images_broken: imgs.filter((im) => im.complete && im.naturalWidth === 0).length,
                          missing: expected.filter((u) => !rendered.has(tail(u))).slice(0, 12),
                          // A lazy loader's stand-in -- an empty SVG the size of the
                          // picture -- "loads" and shows nothing.
                          placeholders: srcs.filter((u) => /^data:image\/svg\+xml/.test(u)
                            && !/(<|%3C)(path|image|circle|ellipse|rect|polygon|polyline|line|g|text|use)\b/i.test(u)
                            && !/<(path|image|circle|ellipse|rect|polygon|polyline|line|g|text|use)\b/i.test((() => { try { return decodeURIComponent(u); } catch { return u; } })())).length,
                          text_cover: words.length ? Math.round((shown / words.length) * 1000) / 1000 : null };
    }
    if (!had) this.closeBillboard(cid);
    return out;
  }

  /** Planted: table rows of different widths share one table run, as before. */
  static plantOneTableRun = false;
  /** Planted: code edges are never fetched or drawn, as before. */
  plantNoCodeEdges = false;
  private async loadCodeEdges(url: string): Promise<void> {
    if (this.plantNoCodeEdges || !url.startsWith("code://") || this.codeEdges.has(url)) return;
    this.codeEdges.set(url, []);
    const got: any = await this.sidecar.cpgEdges(url).catch(() => null);
    const edges = (got && Array.isArray(got.edges)) ? got.edges : [];
    this.codeEdges.set(url, edges);
    this.codeEdgeStats.pages = this.codeEdges.size; this.codeEdgeStats.fetched += edges.length;
    this.batchDirty = true;
  }
  /** The code edges to DRAW now: both ends drawn, the kind switched on.
   *  Never in the graph's links -- drawn, not forces (G-241's measurement). */
  private drawableCodeEdges(nodes: any[]): any[] {
    // The switches appear while a code page's chunks are drawn.
    this.showCodeButtons(!this.plantNoCodeEdges && nodes.some((n) => n.level !== "page" && String(n.url || "").startsWith("code://")));
    if (this.plantNoCodeEdges || !this.codeEdges.size) { this.codeEdgeStats.drawn = { CALLS: 0, INHERITS: 0 }; return []; }
    const byId = new Map<string, any>();
    for (const n of nodes) byId.set(String(n.id), n);
    const out: any[] = [], drawn: Record<string, number> = { CALLS: 0, INHERITS: 0 };
    for (const [url, edges] of this.codeEdges) {
      if (!nodes.some((n) => n.url === url && n.level !== "page")) continue;      // the page is not open
      for (const e of edges) {
        if (!(this.codeEdgeKinds as any)[e.kind]) continue;
        const s = byId.get(String(e.source)), t = byId.get(String(e.target));
        if (!s || !t || s === t) continue;
        out.push({ source: s, target: t, color: GraphView.CODE_EDGE_COLOR[e.kind] || "#ffffff", alpha: 0.85, code: e.kind });
        drawn[e.kind] = (drawn[e.kind] || 0) + 1;
      }
    }
    this.codeEdgeStats.drawn = drawn;
    return out;
  }

  /** Planted (G-245): the cloud left where the rank radii put its mass, off its url node. */
  plantNoRecentre = false;
  /** Planted (G-245): a telescoped target is reached by the forces alone, as before. */
  plantTeleByForce = false;
  /** Chunks glided to a telescoped target (G-245). */
  teleGlides = 0;
  /** Per open page, what the last telescope did (for the harness). */
  teleStats = new Map<string, { n: number; raw_p90: number; bound: number; inner: number; k: number; clamped: number; centre_off?: number; relax?: any; root_r?: number; recentred?: number }>();

  /**
   * A page's chunks TELESCOPED radially about its node (2026-10-06: "the umap
   * clusters are still quite small, and still quite closely packed for each
   * URL ... a max bound distance that telescopes the chunk distances from
   * their centroid url node radially within some bounds, which still
   * preserves the UMAP geometries").
   *
   * Each chunk keeps its DIRECTION from the page node and the ORDER and RATIO
   * of its distance: d' = inner + k * d, with k chosen so the page's 90th
   * percentile chunk lands at 0.85 of the bound, and anything beyond clamped
   * at the bound -- the neighbourhood the projector gives the page (0.45 x
   * the nearest other page). Computed from the RAW fit each time, so a
   * second pass never telescopes a telescoped position; a fit that changed
   * underneath (`fitX` no longer what was written) is taken as the new raw.
   */
  /** Planted: the page button renders only the cached snapshot (the dead button). */
  plantDeadPageButton = false;
  /**
   * Streamed chunks placed by the fit before the store holds them (2026-10-10,
   * PLUGIN_GOAL 48: "so that we don't wait with grey force-directed while
   * hierarchical fits are happening"). Each takes the fit's colour and glides
   * to where the fit put it -- telescoped with its page's stored chunks, so it
   * does not jump when the stored chunk replaces it -- and the stream's spring
   * leaves it alone.
   */
  projectStats = { batches: 0, nodes: 0, provisional_pages: 0, roots_placed: 0 };
  /** Planted (item 91): projected nodes never reach the graph -- the stage clock must show the gap. */
  plantNoProjected = false;
  /**
   * **A refit does not snap the camera** (G-194, 2026-10-17: "when we
   * currently call a re-fit on the full set of UMAP chunks, our camera snaps
   * to the 're-center view'. Perhaps we could apply efficient scale-aware ICP
   * over the URL nodes so that we render the 3D coordinates from their
   * closest most previous registered camera pose"). Before a new epoch's
   * redraw the url nodes' places and the camera's pose are kept; after it,
   * the similarity carrying the new url nodes onto the old ones
   * (`similarityFit`, matched by url, so one closed-form solve) carries the
   * camera BACK into the new frame. Nothing in the cloud moves -- the camera
   * is put where it sees the new fit as it saw the old. Planted:
   * `plantSnapOnRefit` (the reframe, as before).
   */
  plantSnapOnRefit = false;
  private priorPose: { pages: Map<string, V3>; cam: V3; target: V3; up: V3; fullViewDist: number } | null = null;
  refitStats = { captured: 0, registered: 0, reframed: 0, last_rms: 0, last_matched: 0, last_scale: 0 };
  capturePose(): void {
    const g: any = this.graph;
    if (!g) return;
    const pages = new Map<string, V3>();
    for (const n of g.graphData().nodes) {
      if (n.level === "page" && !n.force && n.url && Number.isFinite(n.x)) pages.set(String(n.url), [n.x, n.y, n.z ?? 0]);
    }
    const c = g.camera(), t = g.controls()?.target;
    if (!c || !t) return;
    this.priorPose = { pages, cam: [c.position.x, c.position.y, c.position.z], target: [t.x, t.y, t.z],
                       up: [c.up.x, c.up.y, c.up.z], fullViewDist: this.fullViewDist };
    this.refitStats.captured++;
  }
  private registeredPose(): { x: number; y: number; z: number } | null {
    const prior = this.priorPose;
    this.priorPose = null;
    const g: any = this.graph;
    if (!prior || !g || this.plantSnapOnRefit) { if (prior) this.refitStats.reframed++; return null; }
    const src: V3[] = [], dst: V3[] = [];
    for (const n of g.graphData().nodes) {
      if (n.level !== "page" || n.force || !Number.isFinite(n.x)) continue;
      const o = prior.pages.get(String(n.url));
      if (o) { src.push([n.x, n.y, n.z ?? 0]); dst.push(o); }
    }
    const f = similarityFit(src, dst);
    if (!f || !(f.s > 0)) { this.refitStats.reframed++; return null; }
    const p = similarityInverse(f, prior.cam), t = similarityInverse(f, prior.target), up = rotateInverse(f, prior.up);
    g.camera().up.set(up[0], up[1], up[2]);
    g.cameraPosition({ x: p[0], y: p[1], z: p[2] }, { x: t[0], y: t[1], z: t[2] }, 0);
    if (prior.fullViewDist > 0) this.fullViewDist = prior.fullViewDist / f.s;
    this.refitStats.registered++;
    this.refitStats.last_rms = Math.round(f.rms * 100) / 100;
    this.refitStats.last_matched = f.n;
    this.refitStats.last_scale = Math.round(f.s * 1000) / 1000;
    return { x: p[0], y: p[1], z: p[2] };
  }

  /** Planted (G-93/G-94): the force root keeps its arbitrary birthplace. */
  plantRootUnplaced = false;
  applyProjected(url: string, got: any): void {
    if (!this.graph || !got || !got.pos || this.plantNoProjected) return;
    const data: any = this.graph.graphData();
    // **The root takes its projection, and its tree comes with it** (G-94:
    // "a root that is not yet projected is itself force-directed; when a
    // projection arrives it REPLACES the force position"). A new page's
    // force root is born at an arbitrary point -- near the origin -- while
    // its chunks' projections land where their meaning is, ~320 units away
    // on the Julia forum; every chunk then glided across the cloud and the
    // children of each collapsed parent were dragged after it: 37 of 42
    // held nodes moved 131 radii in one update (G-93 calm p90 94 radii,
    // 2026-10-17). `/project` answers with the page's position (provisional
    // for a page the fit has not met). The first time it does, the root is
    // pinned there and the part of its tree not yet projected moves with it
    // rigidly, its shape kept; everything spawned after is born there. It
    // lands within a few hundred ms of the first drain -- before any of
    // that batch is held -- so it reads as the tree appearing in its place.
    const page = got.page;
    if (!this.plantRootUnplaced && Array.isArray(page) && page.length >= 3 && page.every(Number.isFinite)) {
      const root = data.nodes.find((n: any) => n.force && n.url === url && n.level === "page");
      if (root && !root.rootPlaced && Number.isFinite(root.x)) {
        const dv = [page[0] - root.x, page[1] - root.y, page[2] - (root.z ?? 0)];
        for (const n of data.nodes) {
          if (!n.force || n.url !== url || n.projected || !Number.isFinite(n.x)) continue;
          n.x += dv[0]; n.y += dv[1]; n.z = (n.z ?? 0) + dv[2];
          if (n.holdAt) n.holdAt = [n.holdAt[0] + dv[0], n.holdAt[1] + dv[1], n.holdAt[2] + dv[2]];
        }
        root.fx = page[0]; root.fy = page[1]; root.fz = page[2];
        root.rootPlaced = true;
        this.projectStats.roots_placed++;
      }
    }
    let n0 = 0;
    const touched: any[] = [];
    for (const n of data.nodes) {
      if (!n.force || n.url !== url) continue;
      const p = got.pos[n.id];
      if (!p || !p.every(Number.isFinite)) continue;
      n.projected = true;
      n.projectedAt = performance.now();
      const hsv = got.hsv ? got.hsv[n.id] : null;
      if (hsv) { n.hsv = hsv; n.color = colourOf({ hsv } as any); }
      n.fitX = p[0]; n.fitY = p[1]; n.fitZ = p[2];
      n.__tele = undefined; n.__raw = undefined;
      touched.push(n);
      n0++;
    }
    if (!n0) return;
    profiler().mark(url, "projected", { nodes: n0, provisional_page: !!got.provisional_page });
    this.projectStats.batches++; this.projectStats.nodes += n0;
    if (got.provisional_page) this.projectStats.provisional_pages++;
    this.fitChunkSizes(data);
    for (const n of touched) this.glide(n, [n.fitX, n.fitY, n.fitZ ?? 0]);
    this.graph.nodeColor(this.graph.nodeColor());
  }

  /** Planted: first paint waits for the page form, then upgrades again (the slow panel). */
  plantSerialPanel = false;
  /** Planted: telescope from the page point, as before -- the cloud off-centre. */
  plantOffCentre = false;

  /** Planted (2026-10-11): url nodes the fit put on each other stay there. */
  plantPagesTogether = false;
  private telescope(page: any, chunks: any[], bound: number, relSize: number, media: boolean): void {
    if (this.plantNoTelescope || !chunks.length || !(bound > 0)) return;
    const px = page.fitX ?? page.x, py = page.fitY ?? page.y, pz = page.fitZ ?? page.z ?? 0;
    if (![px, py, pz].every(Number.isFinite)) return;
    const raw: V3[] = [];
    for (const c of chunks) {
      const tf = c.__tele;
      const moved = !tf || tf[0] !== c.fitX || tf[1] !== c.fitY || tf[2] !== c.fitZ;
      if (moved || !c.__raw) c.__raw = [c.fitX ?? c.x, c.fitY ?? c.y, c.fitZ ?? c.z ?? 0];
      raw.push(c.__raw);
    }
    // Centred on the chunks' own centroid (`centredTelescope`, camera.ts):
    // the forum's 186 chunks drew as a ball 95 units off their url node when
    // offsets were taken from the page point (2026-10-10).
    // The url node's drawn body, at the collider's safety -- the only room it
    // keeps; no hole beyond it (the repulsion sphere is gone, 2026-10-11).
    const rootR = drawnRadius({ ...page, val: page.val }, relSize, media) * COLLIDER_SAFETY;
    const inner = rootR;
    const t = centredTelescope([px, py, pz], raw, bound, inner, this.plantOffCentre, !this.plantNoUniform);
    // The targets RELAXED: collision spheres at the safety factor, the url
    // node's own sphere kept clear, each anchored to its fit (`relaxCloud`,
    // 2026-10-10: "the central URL node collision radius boundary was not
    // enforced" -- ko.wikipedia/물리학 drew 285 chunks with 2,069 overlapping
    // pairs and 68 inside its url node).
    let rel: any = null;
    if (!this.plantNoRelax) {
      const idx = t.pos.map((q, i) => (q ? i : -1)).filter((i) => i >= 0);
      const radii = idx.map((i) => drawnRadius(chunks[i], relSize, media));
      rel = relaxCloud([px, py, pz], idx.map((i) => t.pos[i] as V3), radii, rootR, bound, { safety: COLLIDER_SAFETY });
      idx.forEach((i, j) => { t.pos[i] = rel.pos[j]; });
    }
    // The url node AT the centroid of what is drawn (2026-10-18, PLUGIN_GOAL
    // 174; Addendum IX's "centroid computed directly from the chunk
    // coordinates that sets the url node placements"). Centring the RAW
    // cloud is not enough: the radii are equalised by rank, so a lopsided
    // fit -- a few far chunks on one side, the rest packed on the other --
    // drew its mass to one side and the url node at the edge of its own fan
    // (a new page: 0.59-0.71 of the cloud's radius off, until the projector
    // compacted the raw positions). The whole cloud is shifted by what is
    // left over; the shapes and distances among chunks are unchanged.
    // Planted `plantNoRecentre`.
    let recentred = 0;
    if (!this.plantNoRecentre) {
      const live = t.pos.filter(Boolean) as V3[];
      if (live.length >= 2) {
        const m = [0, 1, 2].map((k) => live.reduce((a, q) => a + q[k], 0) / live.length);
        const d = [px - m[0], py - m[1], pz - m[2]];
        recentred = Math.hypot(d[0], d[1], d[2]);
        if (recentred > 1e-6) t.pos = t.pos.map((q) => (q ? [q[0] + d[0], q[1] + d[1], q[2] + d[2]] as V3 : q));
      }
    }
    chunks.forEach((c, i) => {
      const p = t.pos[i];
      if (!p) return;
      const [nx, ny, nz] = p;
      if (c.fitX !== nx || c.fitY !== ny || c.fitZ !== nz) {
        c.fitX = nx; c.fitY = ny; c.fitZ = nz;
        c.__freeUntil = performance.now() + 3000;
      }
      // A chunk DRAWN far from its target glides there -- whoever set the
      // target, and whether or not it changed now. Left to the home force a
      // move is held to 2.5 units a tick under a cooling alpha, and a calm
      // pin stops it outright: a new page's chunks drew 142-184 units from
      // targets centred on their url node, pinned, for 25 s (2026-10-18,
      // PLUGIN_GOAL 174: "url node centroids seem off in many cases"). Not
      // while the hover spread holds the url apart, nor mid-glide. Planted
      // `plantTeleByForce`: left to the forces, as before.
      if (!this.plantTeleByForce && !c.__spreadHome && !c.__glide && Number.isFinite(c.x)
          && Math.hypot(c.x - nx, c.y - ny, (c.z || 0) - nz) > Math.max(2, 0.05 * bound)) {
        this.glide(c, [nx, ny, nz]);
        this.teleGlides++;
      }
      c.__tele = [nx, ny, nz];
    });
    this.teleStats.set(page.url, { n: chunks.length, raw_p90: Math.round(t.p90 * 10) / 10, bound: Math.round(bound),
                                   centre_off: Math.round(t.centreOff * 10) / 10,
                                   inner: Math.round(inner), k: Math.round(t.k * 100) / 100, clamped: t.clamped,
                                   root_r: Math.round(rootR * 10) / 10, recentred: Math.round(recentred * 10) / 10,
                                   relax: rel ? { overlaps: [rel.overlapsBefore, rel.overlapsAfter], inside_root: [rel.insideBefore, rel.insideAfter], iterations: rel.iterations } : null });
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

  /** Planted: collision over the whole graph on every pass, as before. */
  plantFullCollide = false;
  collideStats = { passes: 0, idle: 0, scoped: 0, whole: 0 };

  /** The nodes a collision pass must see: the free ones, and all within reach. */
  private collideScope(nodes: any[], force: any, maxRadius: number): any[] {
    const free: any[] = [];
    let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity, rFree = 0;
    const radius = force.radius();
    for (const n of nodes) {
      if (n.fx != null || n.force) continue;
      free.push(n);
      const x = n.x, y = n.y, z = n.z || 0;
      if (x < x0) x0 = x; if (x > x1) x1 = x;
      if (y < y0) y0 = y; if (y > y1) y1 = y;
      if (z < z0) z0 = z; if (z > z1) z1 = z;
      const r = +radius(n) || 0; if (r > rFree) rFree = r;
    }
    if (!free.length) return free;
    if (free.length * 2 > nodes.length) return nodes;
    // A step's worth of travel too: a free node moves before the next pass.
    const reach = rFree + maxRadius + 4;
    x0 -= reach; y0 -= reach; z0 -= reach; x1 += reach; y1 += reach; z1 += reach;
    const scope = free;
    for (const n of nodes) {
      if (n.fx == null || n.force) continue;
      const z = n.z || 0;
      if (n.x >= x0 && n.x <= x1 && n.y >= y0 && n.y <= y1 && z >= z0 && z <= z1) scope.push(n);
    }
    return scope;
  }

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

  /**
   * **Per-hover spread** (G-230, PLUGIN_GOAL 159): the hovered url's drawn
   * nodes are scaled out about the page so their pictures and panels do not
   * overlap; when the hover leaves the url they glide back to the place the
   * fit gave them (`__spreadHome`). Planted `plantNoHoverSpread`.
   */
  private spread: { url: string; nodes: any[]; k: number } | null = null;
  spreadStats = { spread: 0, restored: 0, last_k: 1, last_n: 0 };
  plantNoHoverSpread = false;
  spreadUrl(url: string): void {
    if (this.plantNoHoverSpread || !this.graph) return;
    const key = String(url || "").split("#")[0];
    if (this.spread && this.spread.url === key) return;
    this.unspread();
    if (!key) return;
    const all: any[] = (this.graph.graphData() as any).nodes;
    const page = all.find((n: any) => n.level === "page" && !n.force && String(n.url || "").split("#")[0] === key);
    const members = all.filter((n: any) => n !== page && n.level !== "page" && Number.isFinite(n.x)
      && String(n.url || "").split("#")[0] === key);
    if (members.length < 2 || members.length > 400) return;
    const C = page && Number.isFinite(page.x) ? [page.x, page.y, page.z ?? 0]
      : [0, 1, 2].map((a) => members.reduce((s: number, n: any) => s + ([n.x, n.y, n.z ?? 0][a]), 0) / members.length);
    const homes = members.map((n: any) => n.__spreadHome || [n.x, n.y, n.z ?? 0]);
    const rs = this.graph.nodeRelSize(), media = this.media();
    const k = spreadFactor(homes, members.map((n: any) => drawnRadius(n, rs, media)));
    this.spreadStats.last_k = Math.round(k * 100) / 100; this.spreadStats.last_n = members.length;
    if (k <= 1.01) return;
    members.forEach((n: any, i: number) => {
      n.__spreadHome = homes[i];
      this.glide(n, [0, 1, 2].map((a) => C[a] + (homes[i][a] - C[a]) * k), 300);
    });
    this.spread = { url: key, nodes: members, k };
    this.spreadStats.spread++;
  }
  /** The spread url's nodes back where the fit put them. */
  unspread(): void {
    const sp = this.spread;
    if (!sp) return;
    this.spread = null;
    for (const n of sp.nodes) {
      const h = n.__spreadHome;
      if (!h) continue;
      delete n.__spreadHome;
      this.glide(n, h, 300);
    }
    this.spreadStats.restored++;
  }
  /** Planted by the glide check: fit moves assigned outright, as before. */
  plantTeleport = false;
  glideStats: { started: number; done: number; retargeted?: number } = { started: 0, done: 0 };

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
        // Its TARGET moved while it flew (a telescope pass skips a node
        // mid-glide): on to where it is wanted now, or the calm pin holds it
        // at a stale place -- a new page's chunks sat 53-80 units off their
        // centred targets 35 s after landing (2026-10-18, G-245). Not under
        // the hover spread, whose glides are to its own homes.
        if (!this.plantTeleByForce && !n.__spreadHome && [n.fitX, n.fitY].every(Number.isFinite)
            && Math.hypot(n.x - n.fitX, n.y - n.fitY, (n.z || 0) - (n.fitZ || 0)) > 2) {
          this.glide(n, [n.fitX, n.fitY, n.fitZ || 0]);
          this.glideStats.retargeted = (this.glideStats.retargeted || 0) + 1;
        }
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
  /** Planted (2026-10-11): the simulation never stops on its own (alphaMin 0). */
  plantNoAlphaMin = false;
  /** Planted (2026-10-11): pick proxies visible to the renderer's walk. */
  plantVisibleProxies = false;
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
  /** Planted: a chunk click reveals with the node's own `path` only, as before. */
  plantRevealPathOnly = false;
  revealStats = { clicks: 0, with_xpath: 0, from_payload: 0 };
  /**
   * A chunk's click takes the browser cell to the chunk: its page, scrolled to
   * the element its FIRST line draws (2026-10-12: "clicking on a node after
   * clicking on another node gives no response in the browser"). Chunk nodes
   * carry no xpath -- 7 of 22,220 did -- so a click on a chunk of the page
   * already open had nothing to scroll to. The first line's element, not the
   * chunk's root: a merged chunk is rooted at the container of its run.
   */
  private async revealChunk(n: any): Promise<void> {
    this.revealStats.clicks++;
    let xpath = n.path || "";
    if (!xpath && !this.plantRevealPathOnly) {
      const pay: any = await Promise.race([
        this.chunkPayload(String(n.id)).catch(() => null),
        new Promise((r) => setTimeout(() => r(null), 1500)),
      ]);
      const key = String(pay?.lines?.find((l: any) => l && l.key)?.key || "");
      const at = key.split("|")[1] || pay?.xpath || "";
      xpath = at.replace(/\/(text\(\)|comment\(\))(\[\d+\])?$/, "").replace(/\/@[^/]+$/, "");
      if (xpath) this.revealStats.from_payload++;
    }
    if (xpath) this.revealStats.with_xpath++;
    this.onReveal(n.url, xpath);
  }

  /** Planted: proxies keep the size they were made at, as before. */
  plantStaleProxies = false;
  proxyStats = { resized: 0 };
  /**
   * Every pick proxy at its node's DRAWN size, on each sync. A proxy was
   * sized only when made (and when a picture arrived), so a change of how a
   * node is drawn -- chunk view's one size, a reveal, a plant flipped -- left
   * invisible spheres up to 21.5x the drawn node: 21,808 of 22,229 stale, and
   * a drag on empty space grabbed a node near the camera (2026-10-12).
   */
  private fitProxyAt = 0;
  private fitProxies(nodes: any[], rs: number, media: boolean): void {
    if (this.plantPerNode) return;
    // At most once a second: a second look pass over every node on every
    // sync was a tenth of the CPU in chunk view (2026-10-12, "significant
    // lag"), and a proxy a second stale picks within its old size, briefly.
    const now = performance.now();
    if (now - this.fitProxyAt < 1000) return;
    this.fitProxyAt = now;
    for (const n of nodes) {
      const o = n.__threeObj;
      if (!o || !o.__proxy) continue;
      const want = this.lookOf(n, rs, media).half * this.zoomScale;
      if (Math.abs(o.scale.x - want) <= 1e-6 * Math.max(1, want)) continue;
      o.scale.setScalar(want);
      o.updateMatrix();
      if (o.parent) o.matrixWorld.multiplyMatrices(o.parent.matrixWorld, o.matrix);
      else o.matrixWorld.copy(o.matrix);
      this.proxyStats.resized++;
    }
  }

  private proxyRadius(n: any): number {
    return this.graph ? this.lookOf(n, this.graph.nodeRelSize(), this.drawnMedia).half * this.zoomScale : 1;
  }

  /**
   * A node's own three.js object, now: an invisible sphere the raycaster
   * still hits (three tests layers, not visibility) and the renderer skips
   * (an invisible material is never queued). Shared geometry and material.
   */
  private pickProxy(n: any, relSize: number, media: boolean): any {
    // For the harness: a ray cast as the pane's own picking casts it (G-174).
    (window as any).__vertiscopeRaycaster = THREE.Raycaster;
    if (!GraphView.proxyGeo) {
      GraphView.proxyGeo = new THREE.SphereGeometry(1, 8, 6);
      GraphView.proxyMat = new THREE.MeshBasicMaterial({ visible: false });
    }
    const m = new THREE.Mesh(GraphView.proxyGeo, GraphView.proxyMat);
    // Hidden as an OBJECT, not only by its material: the renderer walked all
    // 23k proxies every frame to find each one drew nothing (0.7 s in 7).
    // Raycasting ignores `visible`, so hover, click and drag still land.
    if (!this.plantVisibleProxies) m.visible = false;
    // Its matrix is composed when it MOVES (`nodePositionUpdate`), not by the
    // renderer every frame for 23k proxies that mostly hold still.
    if (!this.plantProxyAutoMatrix) m.matrixAutoUpdate = false;
    // And its WORLD matrix is written when it moves, never by the per-frame
    // pass: three.js calls every child's updateMatrixWorld each frame, and an
    // ancestor flagged changed made all 22k proxies multiply matrices --
    // 21.7% of the CPU in chunk view with no input at all (2026-10-11).
    if (!this.plantProxyWorldPass) m.updateMatrixWorld = () => {};
    m.scale.setScalar(this.lookOf(n, relSize, media).half);
    m.updateMatrix();
    (m as any).__proxy = true;
    if (this.plantNoPick) m.raycast = () => {};
    else {
      // Exact picking for the nodes near the pointer's ray only (2026-10-11:
      // three.js's hover raycast tested all 22k proxies on every pointer move,
      // ~28% of the CPU in chunk view). `glowNear` is the per-frame ranking of
      // the nodes nearest that same ray; anything outside it cannot be under
      // the pointer, so it declines before any matrix or sphere test. Empty
      // (no ranking yet): every proxy is tested, as before. Planted: always.
      const exact = THREE.Mesh.prototype.raycast;
      m.raycast = (rc: any, out: any[]) => {
        if (!this.plantFullPick && this.pickStamp && n.__pk !== this.pickStamp) return;
        exact.call(m, rc, out);
      };
    }
    return m;
  }

  /**
   * How one node looks, for the batch -- the same choices the per-node
   * objects made: a translucent sphere while streaming (white when hovered),
   * a picture panel when media is on and it has one, a sphere otherwise.
   * READS the node; writes nothing the layout uses.
   */
  private lookOf(n: any, relSize: number, media: boolean): NodeLook {
    const base = this.baseLook(n, relSize, media);
    const st = this.searchState;
    if (!st || this.plantNoGlass) {
      // The DEFAULT look: a glowing glass orb in the node's own colour
      // (2026-10-11: "standardize the latent glowing glass orbs as the
      // default"). Pictures stay pictures; a streaming node keeps its grey
      // translucence, so streaming still reads as streaming. Planted: the old
      // opaque spheres.
      const hg = this.plantNoHoverGlow ? 0 : (n.hovered ? 1 : (this.glowNear.get(n) || 0));
      if (this.plantOpaqueOrbs) return base;
      if (this.dimFront.has(n) && !base.picture) return { half: base.half, translucent: true, alpha: 0.12, color: base.color, glass: true };
      if (n.hovered && !base.picture) return { half: base.half, translucent: true, alpha: 2.5, color: n.color || base.color, glass: true };
      // A REVEALED picture is the picture alone; unrevealed, the node is its
      // orb -- the old switch between node and image (2026-10-11: "we dont need
      // spheres over images ... we can switch between node and image reveals as
      // was the same as the older functionality"). A streaming node is an orb
      // with a dimmer glow, so streaming still reads (item 99: "some nodes are
      // not the same level of glass and translucent").
      if (base.picture) return hg > 0 ? { ...base, glow: hg } : base;
      if (base.translucent) return { half: base.half, translucent: true, alpha: 0.4 + hg, color: base.color, glass: true };
      return { half: base.half, translucent: true, alpha: 1 + 1.5 * hg, color: base.color, glass: true };
    }
    const r = st.ranks.get(String(n.id));
    if (r !== undefined && r < st.shown && fade(r, st.soft) < 0.999) {
      // The frontier, part-way in: a glass orb gaining its own colour as the
      // slider passes it, then lit (2026-10-11: "smoothly brighten on soft
      // integer result nodes").
      return { half: Math.max(base.half, st.minHalf), translucent: true, alpha: fade(r, st.soft), color: base.color, glass: true };
    }
    if (r !== undefined && r < st.shown) {
      // A shown result, as itself, lit from within (item 88).
      // At least the scene's median size: a result is what the reader is
      // looking for, and chunk nodes drew as specks among the glass (seen
      // 2026-10-11).
      // A result glows as the default view glows (2026-10-17, PLUGIN_GOAL
      // 136: "the same glowing effect as the default for retrieval
      // renderings"): an orb in its own colour, brighter by its rank -- the
      // halo reads the orb's alpha. Returned opaque, a result had no glow at
      // all. Pictures stay pictures. Planted: `plantOpaqueResults`.
      const half = Math.max(base.half, st.minHalf), b = brightness(r, st.soft);
      if (base.picture || this.plantOpaqueResults) return { ...base, half, translucent: false, alpha: 1, glow: b };
      return { half, translucent: true, alpha: 1 + 1.5 * b, color: base.color, glass: true };
    }
    // Everything else: colourless glass, no picture -- a lens the results'
    // lights reflect off ("These nodes are the only nodes visible while a
    // user searches. All other nodes become *translucent-ish* ... colorless
    // but still applying a glassy lens material effect").
    return { half: base.half, translucent: true, alpha: 0, color: "#ffffff", glass: true };
  }

  /** Planted (G-199): a fold forgets the page's streamed chunks, as before. */
  plantFoldForgets = false;
  /** Planted: the opaque lit spheres the glowing orbs replaced as the default. */
  plantOpaqueOrbs = false;
  /** Planted (G-209): a search's results drawn opaque, without the glow. */
  plantOpaqueResults = false;

  // ---- PLUGIN_GOAL 84-88, 94-97: the search field, its results, glass and light ----
  //
  // **Retrieval is a LOOK** (2026-10-11, item 96: "streaming and node layout
  // pipelines ... that work unaffected by the retrieval results (since that's
  // just a brightness and fly-to-node thing)"). A search places no node,
  // moves none and removes none: each result lights the node that stands for
  // it NOW -- its own chunk if drawn, else its page node, the fallback a hover
  // takes -- re-resolved on every draw, so a stream adding nodes is picked up
  // without the search touching it. (The first version placed undrawn
  // results and removed them on clear: the layout changed with the query.)

  searchField: SearchField | null = null;
  /** The ranked results, how many are shown, and the drawn node each resolves to. */
  searchState: { query: string; hits: FieldHit[]; shown: number; soft: number; at: number; minHalf: number;
                 ranks: Map<string, number>; targets: (any | null)[] } | null = null;
  /** Planted (item 88): results shown, but nothing turned to glass and no lights. */
  plantNoGlass = false;
  /** Planted (item 96): the first version -- undrawn results PLACED in the scene. */
  plantPlaceResults = false;
  searchStats = { strip_hovers: 0, asked: 0, shown: 0, lights: 0, last_ms: 0, resolved_chunk: 0, resolved_page: 0, unresolved: 0,
                  placed: 0, web_merged: 0, flown_top: 0, web_asked: 0, reranks: 0, rerank_changed: 0 };

  /** Told the plugin, which tells the browser cell: search the web too (item 85). */
  onWebSearch: (query: string) => void = () => {};
  private webTimer = 0;
  private followQuery = "";
  private followQuiet = 0;
  private followBusy = false;
  /** Planted (item 107): every typed query also goes to the web, as before. */
  plantWebOnType = false;
  /** Planted (item 106): the ranking is asked once and never again. */
  plantNoRerank = false;
  /** How often a standing query is re-ranked, and how many unchanged rounds end it. */
  rerankMs = 3000;
  rerankQuietRounds = 20;
  /**
   * While a query stands, what streams into the store -- the web half's
   * pages, any capture -- re-ranks it, applied as a DIFF (item 106): the
   * field's `update` swaps in the new order, keeps the reader's scroll, says
   * what moved; the lights follow through `onShow`. Asked every `rerankMs`
   * and at once when the store hands the view new nodes (`absorb`); it rests
   * after `rerankQuietRounds` unchanged rounds and wakes on the next write.
   */
  private followStore(query: string): void {
    if (this.plantNoRerank || !query) return;
    if (this.followQuery !== query) { window.clearInterval(this.webTimer); this.webTimer = 0; }
    this.followQuery = query;
    this.followQuiet = 0;
    if (this.webTimer) return;
    this.webTimer = window.setInterval(() => { void this.rerank(); }, this.rerankMs);
  }
  private async rerank(): Promise<void> {
    if (this.closed) { GraphView.closedTick(); window.clearInterval(this.webTimer); return; }
    const f = this.searchField;
    const q = this.followQuery;
    if (!f || !q || f.query !== q) { window.clearInterval(this.webTimer); this.webTimer = 0; return; }
    if (this.followBusy) return;
    this.followBusy = true;
    try {
      const d = await f.update().catch(() => null);
      this.searchStats.reranks++;
      if (d && (d.added || d.removed || d.moved)) {
        this.searchStats.rerank_changed++;
        this.searchStats.web_merged += d.added;
        this.followQuiet = 0;
      } else if (++this.followQuiet >= this.rerankQuietRounds) {
        window.clearInterval(this.webTimer); this.webTimer = 0;
      }
    } finally { this.followBusy = false; }
  }

  /** One query: the store's ranking, `total` deep. Nothing in the scene changes. */
  private async searchAsk(query: string, total: number): Promise<FieldAnswer | null> {
    const t0 = performance.now();
    this.searchStats.asked++;
    if (this.plantWebOnType) { this.searchStats.web_asked++; this.onWebSearch(query); }
    this.followStore(query);
    const got: any = await this.sidecar.search(query, { k: total });
    if (!got) return null;
    const hits: FieldHit[] = (got.hits || []).map((h: any) => ({ cid: String(h.cid), url: String(h.url || "") }));
    if (this.plantPlaceResults) await this.placeResultsPlanted(hits);
    this.searchStats.last_ms = Math.round(performance.now() - t0);
    return { hits, n: Number(got.n || hits.length) };
  }

  /** The planted first version: undrawn results placed into the scene. */
  private async placeResultsPlanted(hits: FieldHit[]): Promise<void> {
    if (!this.graph || !hits.length) return;
    const have = new Set((this.graph.graphData() as any).nodes.map((n: any) => String(n.id)));
    const missing = hits.map((h) => h.cid).filter((c) => !have.has(c));
    if (!missing.length) return;
    const got: any = await this.sidecar.place(missing).catch(() => null);
    if (got && got.nodes && got.nodes.length) {
      this.absorb(got.nodes, got.edges, undefined, { keep: new Set(missing) });
      this.searchStats.placed += got.nodes.length;
    }
  }

  /** Each result to the drawn node standing for it: its chunk, else its page. */
  private resolveSearch(): void {
    const st = this.searchState;
    if (!st || !this.graph) return;
    const byId = new Map<string, any>(), pageOf = new Map<string, any>();
    for (const n of (this.graph.graphData() as any).nodes as any[]) {
      byId.set(String(n.id), n);
      if (n.level === "page" && !n.force && n.url) pageOf.set(String(n.url).split("#")[0], n);
    }
    const ranks = new Map<string, number>();
    let chunk = 0, page = 0, none = 0;
    st.targets = st.hits.map((h, i) => {
      let n = byId.get(h.cid);
      if (n) chunk++;
      else { n = pageOf.get(String(h.url).split("#")[0]); if (n) page++; else none++; }
      if (n && !ranks.has(String(n.id))) ranks.set(String(n.id), i);    // the best rank wins
      return n || null;
    });
    st.ranks = ranks;
    this.searchStats.resolved_chunk = chunk; this.searchStats.resolved_page = page; this.searchStats.unresolved = none;
  }

  private showSearch(hits: FieldHit[], shown: number, soft = shown): void {
    let minHalf = this.searchState ? this.searchState.minHalf : 0;
    if (!this.searchState && this.graph) {
      const ns = (this.graph.graphData() as any).nodes as any[], rs = this.graph.nodeRelSize();
      const hs: number[] = [];
      for (let i = 0; i < ns.length; i += Math.max(1, Math.floor(ns.length / 1500))) hs.push(this.baseLook(ns[i], rs, this.drawnMedia).half);
      hs.sort((a, b) => a - b);
      minHalf = hs.length ? hs[hs.length >> 1] : 0;
    }
    this.searchState = { query: this.searchField?.query || "", hits, shown, soft, minHalf,
                         ranks: new Map(), targets: [], at: performance.now() };
    this.resolveSearch();
    this.searchStats.shown = shown;
    this.updateSearchLights();
    this.batchDirty = true;
    // A NEW query's top result is flown to and, when it is a chunk, its panel
    // opened -- the hover's own path (focusOn, hoverPanel), so the same
    // persistence and time-to-live (2026-10-11: "we should also fly to the top
    // result similar to hover overlays and showing their panels and so on.
    // same link and idea").
    const q = this.searchState.query;
    const top = this.searchState.targets[0];
    if (top && q && q !== this.flownFor && !this.plantNoTopFlight) {
      this.flownFor = q;
      this.focusOn(top);
      if (top.level !== "page" && top.level !== "path") this.hoverPanel(top);
      this.searchStats.flown_top++;
    }
  }
  private flownFor = "";
  /** Planted (item 94): a query flies nowhere and opens no panel. */
  plantNoTopFlight = false;

  private clearSearch(): void {
    window.clearInterval(this.webTimer);
    this.webTimer = 0;
    this.followQuery = "";
    this.flownFor = "";
    this.searchState = null;
    this.batch?.setLights([], 1);
    this.searchStats.shown = 0; this.searchStats.lights = 0;
    this.batchDirty = true;
  }

  /** During a search an edge is drawn only between two shown results; every
   *  other edge is a trace (the glass is what stays visible, item 88). */
  private searchLineAlpha(): ((l: any) => number) | null {
    const st = this.searchState;
    if (!st || this.plantNoGlass) return null;
    const end = (x: any) => String(typeof x === "object" && x ? x.id : x);
    const shown = (id: string) => { const r = st.ranks.get(id); return r !== undefined && r < st.shown; };
    return (l: any) => (shown(end(l.source)) && shown(end(l.target)) ? 0.35 : 0.025);
  }

  /** The shown results' lights, brightest first, where their nodes ARE now. */
  private updateSearchLights(): void {
    const st = this.searchState;
    if (!st || !this.batch || !this.graph) return;
    if (this.plantNoGlass) { this.batch.setLights([], 1); this.searchStats.lights = 0; return; }
    const lights: { at: [number, number, number]; color: string; intensity: number; b: number }[] = [];
    const lit = new Set<any>();
    st.targets.slice(0, st.shown).forEach((n, i) => {
      if (!n || lit.has(n) || !Number.isFinite(n.x)) return;
      const b = brightness(i, st.soft);
      if (b <= 0) return;
      lit.add(n);
      lights.push({ at: [n.x, n.y, n.z || 0], color: n.color || "#ffffff", intensity: 0.6 + 1.6 * b, b });
    });
    lights.sort((a, b) => b.b - a.b);
    // A light falls to half over a tenth of the scene: the scene's own scale,
    // so it reads the same at every zoom of the corpus.
    const ns = (this.graph.graphData() as any).nodes as any[];
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < ns.length; i += Math.max(1, Math.floor(ns.length / 2000))) {
      const n = ns[i]; if (!Number.isFinite(n.x)) continue;
      const q = [n.x, n.y, n.z || 0];
      for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], q[k]); hi[k] = Math.max(hi[k], q[k]); }
    }
    const span = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]);
    this.batch.setLights(lights, Number.isFinite(span) && span > 0 ? span * 0.1 : 60);
    this.searchStats.lights = Math.min(lights.length, 16);
  }

  private baseLook(n: any, relSize: number, media: boolean): NodeLook {
    if (n.force) {
      // In chunk view a chunk still streaming is the size of a placed one:
      // at STREAM.RADIUS it was 10x the median chunk, a pile of giant orbs
      // over a page as it streamed (2026-10-11, PLUGIN_GOAL 110).
      const streaming = this.level === "chunk" && !this.plantSizedInChunkView ? Math.cbrt(this.unitVal()) * relSize : STREAM.RADIUS;
      return { half: n.level === "page" && !(this.level === "chunk" && !this.plantSizedInChunkView) ? STREAM.RADIUS * 1.6 : streaming, translucent: true,
               alpha: n.hovered ? 0.9 : (n.projected ? 0.75 : STREAM.OPACITY), color: n.hovered ? "#ffffff" : (n.color || "#9aa0a6") };
    }
    const src = media && !(this.plantNoPicture && n.level !== "page") ? n.image?.src : undefined;
    // Chunk view draws every node at ONE size (2026-10-11: "I'd like
    // consistent node sizes if possible"; "why are some of the spheres like
    // GIANT?" -- the DuckDuckGo page node, 605 members, at 43x the median
    // chunk). A page there is one node among chunks, not a cluster: its
    // member count stops sizing it. Pictures keep their panel scale ("if its
    // an image size thing then okay"). Planted: sized by members, as before.
    const one = this.level === "chunk" && !this.plantSizedInChunkView;
    // ONE size is the typical chunk's: the median `val` of the chunks drawn.
    // `{ val: 1 }` drew every orb at 2.65 against a median chunk's 0.19 --
    // fourteen times too big, a pile of overlapping orbs (2026-10-12).
    const sized = one ? { val: this.unitVal() } : n;
    if (src) {
      // A REVEALED picture -- under the pointer, hovered, its panel open --
      // is presented at its own panel scale. At the one size it was half a
      // world unit, about a pixel: in chunk view a hover showed no image at
      // all (2026-10-17: "hovering over nodes shows no image overlays in the
      // chunk view"). Unrevealed, it stays the one-size orb below.
      const shown = this.detail.has(n) || n.hovered || this.billboards.has(n.id);
      // Pictures too: a page's favicon is most of the colour in url view.
      let half = billboardEdge(shown && !this.plantTinyReveal ? n : sized, relSize) / 2 * this.nodeScale;
      // Presented at a size a reader can see, on SCREEN: between
      // `presentMinPx` and `presentMaxPx` of radius. A chunk's own panel
      // scale follows its `val`, and small chunks presented at 2 px; right by
      // the camera one filled the pane (1,204 px) (2026-10-17).
      if (shown && !this.plantTinyReveal && this.graph && this.canvasEl) {
        const cam: any = this.graph.camera(), P = cam.position, e = cam.matrixWorld.elements;
        const depth = -((n.x - P.x) * e[8] + (n.y - P.y) * e[9] + ((n.z || 0) - P.z) * e[10]);
        const yy = cam.projectionMatrix.elements[5], H = this.canvasEl.clientHeight;
        if (depth > 0 && yy > 0 && H > 0) {
          const perPx = depth * 2 / (H * yy);
          half = Math.min(Math.max(half, this.presentMinPx * perPx), this.presentMaxPx * perPx);
        }
      }
      // Pictures near the pointer's ray only (`refreshDetail`); elsewhere the
      // same size, as its colour -- so the collider, the pick proxy and the
      // drawn extent never change with where the mouse is.
      // Url (and branch) nodes always: the limit is for chunk view (2026-10-11:
      // "hover images also only apply for chunk view. not url view.").
      if (this.plantAllPictures || n.level === "page" || n.level === "path"
          || this.detail.has(n) || n.hovered || this.billboards.has(n.id))
        return { half, translucent: false, alpha: 0.95, color: n.color || "#888888", picture: src };
      // Unrevealed, in chunk view: an orb the size of every other orb. At the
      // panel's size it was 14x a chunk -- the DuckDuckGo page's 1,587 result
      // favicons as a pile of giant orbs (2026-10-11). Revealed, it opens to
      // its picture as before.
      if (one) return { half: Math.cbrt(sized.val) * relSize * this.nodeScale, translucent: false, alpha: 1, color: n.color || "#888888" };
      return { half, translucent: false, alpha: 1, color: n.color || "#888888" };
    }
    return { half: Math.cbrt(Math.max(sized.val ?? 1, 1e-9)) * relSize * this.nodeScale, translucent: false, alpha: 1,
             color: n.hovered ? "#ffffff" : (n.color || "#9aa0a6") };
  }
  /** A presented picture's largest radius on screen, px. */
  presentMaxPx = 64;
  presentMinPx = 12;
  /** Planted: a revealed picture at the one size (the invisible hover image). */
  plantTinyReveal = false;
  /** Spheres drawn this much larger by default (2026-10-12, PLUGIN_GOAL 115:
   *  "the nodes could be a little larger/brighter by default"). */
  nodeScale = 1.25;
  private pointerOver = false;
  private panHeldSince = 0;
  /** One arrow step, as a share of the camera's distance to its target. */
  panStepShare = 0.006;
  panStats = { steps: 0 };
  arrowPan(e: KeyboardEvent): boolean {
    const dir = ({ ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] } as any)[e.key];
    if (!dir || !this.graph || !this.pointerOver) return false;
    const t = e.target as HTMLElement | null;
    const a = document.activeElement as HTMLElement | null;
    const typing = (el: HTMLElement | null) => !!el && (/^(INPUT|TEXTAREA|SELECT|IFRAME)$/.test(el.tagName) || el.isContentEditable);
    if (typing(t) || typing(a)) return false;
    e.preventDefault();
    e.stopPropagation();
    const now = performance.now();
    if (!e.repeat || !this.panHeldSince) this.panHeldSince = now;
    const g: any = this.graph, cam = g.camera(), ctl = g.controls();
    const tgt = ctl && ctl.target ? ctl.target : new THREE.Vector3();
    const dist = cam.position.distanceTo(tgt);
    // Capped well below the fields' 100: a pan that runs away is not precise.
    const k = Math.min(12, holdStep(now - this.panHeldSince)) * this.panStepShare * dist;
    cam.updateMatrixWorld();
    const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0).multiplyScalar(dir[0] * k);
    const up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1).multiplyScalar(dir[1] * k);
    const move = right.add(up);
    cam.position.add(move);
    tgt.add(move);
    ctl?.update?.();
    // The reader acted: the idle turn stops, as for any input.
    (window as any).__vertiscopeReaderAt = Date.now();
    const by: Record<string, number> = ((window as any).__vertiscopeReaderBy = (window as any).__vertiscopeReaderBy || {});
    by["arrow-pan"] = (by["arrow-pan"] || 0) + 1;
    this.detailDirty = true;
    this.panStats.steps++;
    return true;
  }
  /** Planted: chunk view sizes nodes by their member count, as before. */
  plantSizedInChunkView = false;
  private unitValAt = { n: -1, v: 1, at: 0 };
  /**
   * Chunk view's ONE size, as a `val`: from the UMAP FIT, never from what is
   * drawn. 45% of the median nearest-neighbour distance between chunks at
   * their fit points -- the room the spacing rule gives a typical node -- so
   * the size cannot feed on a layout spaced for an earlier size. Read from
   * the drawn `val`s it did exactly that: places relaxed for orbs 14x too
   * big left room for orbs 14x too big, and the median came back 1
   * (2026-10-12). Re-read when the node count changes by a tenth.
   */
  unitVal(): number {
    const g: any = this.graph;
    const ns = g ? (g.graphData().nodes as any[]) : [];
    if (this.unitValAt.n >= 0 && Math.abs(ns.length - this.unitValAt.n) < Math.max(50, this.unitValAt.n * 0.1)) return this.unitValAt.v;
    const pts: number[][] = [];
    for (const n of ns) if (n.level !== "page" && !n.force && Number.isFinite(n.fitX)) pts.push([n.fitX, n.fitY, n.fitZ ?? 0]);
    let v = 1;
    if (pts.length > 8 && g) {
      // A grid at a cell the size of the typical spacing: estimated from the
      // cloud's extent and count, then each sampled point's nearest within
      // its 27 cells.
      let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      for (const q of pts) for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], q[a]); hi[a] = Math.max(hi[a], q[a]); }
      const vol = Math.max(1e-9, (hi[0] - lo[0]) * (hi[1] - lo[1]) * Math.max(hi[2] - lo[2], 1e-3));
      const cell = Math.max(1e-6, 2 * Math.cbrt(vol / pts.length));
      const key = (x: number, y: number, z: number) => `${Math.floor(x / cell)},${Math.floor(y / cell)},${Math.floor(z / cell)}`;
      const grid = new Map<string, number[]>();
      pts.forEach((q, i) => { const k = key(q[0], q[1], q[2]); const l = grid.get(k); if (l) l.push(i); else grid.set(k, [i]); });
      const nn: number[] = [];
      const step = Math.max(1, Math.floor(pts.length / 3000));
      for (let i = 0; i < pts.length; i += step) {
        const [x, y, z] = pts[i]; let best = Infinity;
        const cx = Math.floor(x / cell), cy = Math.floor(y / cell), cz = Math.floor(z / cell);
        for (let ox = -1; ox <= 1; ox++) for (let oy = -1; oy <= 1; oy++) for (let oz = -1; oz <= 1; oz++) {
          for (const j of grid.get(`${cx + ox},${cy + oy},${cz + oz}`) || []) {
            if (j === i) continue;
            const d = Math.hypot(pts[j][0] - x, pts[j][1] - y, pts[j][2] - z);
            if (d > 1e-9 && d < best) best = d;
          }
        }
        if (Number.isFinite(best)) nn.push(best);
      }
      nn.sort((a, b) => a - b);
      const rs = g.nodeRelSize ? g.nodeRelSize() : 1;
      if (nn.length) { const half = 0.45 * nn[nn.length >> 1]; v = Math.max(1e-6, Math.pow(half / rs, 3)); }
    }
    if (v !== this.unitValAt.v) this.batchDirty = true;
    this.unitValAt = { n: ns.length, v, at: performance.now() };
    return v;
  }


  /**
   * A picture decoded for the atlas, through the same CORS-free fetch.
   *
   * The bytes go to `createImageBitmap` as a Blob: decoded off the main
   * thread and already scaled toward the atlas cell. It used to be a data
   * url -- the bytes walked into a string one character at a time, base64'd,
   * then parsed again by an `<img>` -- 2.8 s of every 11 s on the main
   * thread with 23k nodes on screen, and Obsidian froze (2026-10-11). SVG,
   * which the bitmap decoder refuses, still goes through an `<img>`, on a
   * blob url rather than a data url. Planted: the old data-url path.
   */
  private async decoded(src: string): Promise<Picture | null> {
    if (this.plantDataUrlDecode) return this.decodedViaDataUrl(src);
    const got = await this.pictureBytes(src);
    if (!got) return null;
    const blob = new Blob([got.bytes as any], { type: got.type });
    if (got.type !== "image/svg+xml") {
      try { return await createImageBitmap(blob, { resizeWidth: 128, resizeQuality: "medium" }); }
      catch { /* a format the bitmap decoder refuses: try an <img> */ }
    }
    const url = URL.createObjectURL(blob);
    try {
      return await new Promise<HTMLImageElement | null>((resolve) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => resolve(null);
        img.src = url;
      });
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  /** Planted: the data-url decode the bitmap path replaced. */
  plantDataUrlDecode = false;

  private decodedViaDataUrl(src: string): Promise<HTMLImageElement | null> {
    return this.texture(src).then((url) => new Promise<HTMLImageElement | null>((resolve) => {
      if (!url) { resolve(null); return; }
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = url;
    }), () => null);
  }

  /** A picture's bytes and type, or null; refusals remembered (`textures`). */
  /** Planted (G-100): pictures from the web every load, as before -- no workspace store. */
  plantNoMediaCache = !!(window as any).__vertiscopePlantNoMediaCache;   // set before a load, for its check
  mediaStats = { from_store: 0, from_web: 0, saved: 0, failed: 0 };
  private async pictureBytes(src: string): Promise<{ bytes: Uint8Array; type: string } | null> {
    if (GraphView.textures.get(src) === null) return null;
    // The workspace's media store first (G-100: "re-fetches aren't required
    // by locally saving the media in a workspace cache"): a picture fetched
    // once is read from the workspace on every later load, and saved there
    // the first time it is fetched. Keyed as `snapshots.media_key`: sha1(url).
    let key = "";
    if (!this.plantNoMediaCache && /^https?:/i.test(src)) {
      try {
        const d = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(src));
        key = [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
        const held = await this.sidecar.media(key);
        if (held && held.bytes.byteLength) {
          this.mediaStats.from_store++;
          return { bytes: held.bytes, type: held.type || guessType(src) || "image/png" };
        }
      } catch { /* the web, below */ }
    }
    try {
      const res = await requestUrl({ url: src, method: "GET", throw: false } as any);
      if (res.status && (res.status < 200 || res.status >= 300)) { GraphView.textures.set(src, null); return null; }
      const bytes = new Uint8Array(res.arrayBuffer);
      if (!bytes.byteLength || bytes.byteLength > MAX_TEXTURE_BYTES) { GraphView.textures.set(src, null); return null; }
      let type = (res.headers?.["content-type"] || "").split(";")[0] || guessType(src);
      if (/\.svg($|\?)/i.test(src)) type = "image/svg+xml";
      // A page where a picture should be (a missing favicon answered with
      // HTML) is no picture: remembered as such, never decoded.
      if (/^text\//i.test(type || "")) { GraphView.textures.set(src, null); this.mediaStats.failed++; return null; }
      this.mediaStats.from_web++;
      if (key && !this.plantNoMediaCache) {
        void this.sidecar.saveMedia(src, bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer,
                                    type || "image/png").then((got: any) => { if (got && got.saved) this.mediaStats.saved++; });
      }
      return { bytes, type: type || "image/png" };
    } catch {
      GraphView.textures.set(src, null);
      return null;
    }
  }

  /**
   * Pictures for the nodes nearest the pointer's RAY (2026-10-11: "render
   * images within closest distance to the ray normal projection of the mouse
   * proximity at a time for efficient details while staying fast"). The ray
   * is cast from the camera through the mouse; a node's distance is the
   * length of the normal from it to that ray. The `DETAIL_PICTURES` nearest,
   * in front of the camera, draw their pictures; the rest draw as spheres of
   * the same size. Recomputed when the pointer or the camera moves, at most
   * every 80 ms. Planted: every picture, everywhere, as before.
   */
  private detail = new Set<any>();
  /** Nodes near the pointer's ray and how much they glow, 0..1 (item 102). */
  glowNear = new Map<any, number>();
  /** Nodes between the camera and the presented picture, drawn dark. */
  dimFront = new Set<any>();
  plantNoFrontDim = false;
  /** Planted (item 102): no hover glow. */
  plantNoHoverGlow = false;
  /** Planted (2026-10-11): the slow glow -- an 80 ms throttle and a full re-sync per change. */
  plantSlowGlow = false;
  /** Planted (2026-10-11): every pick proxy raycast on every pointer move. */
  plantFullPick = false;
  /** Nodes whose drawn disc covers the pointer's ray: always pickable. */
  pickNear = new Set<any>();
  /** The ranking's generation; a proxy is tested when its node carries it. */
  pickStamp = 0;
  private lastRevealed = new Set<any>();
  /** Pointer move -> its glow written, ms, last 300 (item 104). */
  glowLatency: number[] = [];
  private pointerAt = 0;
  plantAllPictures = false;
  detailStats = { computes: 0, last_ms: 0, size: 0, candidates: 0 };
  private pointerNdc: [number, number] = [0, 0];
  private detailDirty = true;
  private detailAt = 0;
  private detailCam = "";

  /** Planted (item 112): the K nearest the ray, anywhere -- no bound. */
  plantUnboundedReveal = false;
  /** The cylinder's radius as a share of the cloud's size; 0 < f. */
  // ~40 px at the usual zoom. 0.12 spanned too far ("the ray projections
  // still span too far", 2026-10-12); the reader chose the tight circle with
  // the glow kept in it -- graded by distance, so a lone node under the
  // pointer glows fully (it vanished when graded by rank).
  revealShare = 0.04;
  private revealR = { at: 0, r: 0 };
  /** The reveal cylinder's radius, world units: `revealShare` of the cloud's
   *  extent (its p5-p95 span), re-measured at most every 2 s. */
  revealRadius(g: any): number {
    const now = performance.now();
    if (this.revealR.r > 0 && now - this.revealR.at < 2000) return this.revealR.r;
    const ns = g.graphData().nodes as any[];
    const step = Math.max(1, Math.floor(ns.length / 2000));
    const xs: number[] = [], ys: number[] = [], zs: number[] = [];
    for (let i = 0; i < ns.length; i += step) {
      const n = ns[i]; if (!Number.isFinite(n.x)) continue;
      xs.push(n.x); ys.push(n.y); zs.push(n.z || 0);
    }
    const span = (a: number[]) => { if (a.length < 2) return 0; a.sort((x, y) => x - y); return a[Math.floor(a.length * 0.95)] - a[Math.floor(a.length * 0.05)]; };
    const ext = Math.max(span(xs), span(ys), span(zs), 1e-6);
    this.revealR = { at: now, r: ext * this.revealShare };
    return this.revealR.r;
  }

  private refreshDetail(g: any): void {
    const now = performance.now();
    const cam = g.camera();
    const p = cam.position, q = cam.quaternion;
    const camKey = `${p.x.toFixed(1)},${p.y.toFixed(1)},${p.z.toFixed(1)},${q.x.toFixed(3)},${q.y.toFixed(3)},${q.z.toFixed(3)}`;
    if (camKey !== this.detailCam) { this.detailCam = camKey; this.detailDirty = true; }
    // Once a frame at most: the ranking costs ~3.5 ms over 22k nodes, and the
    // 80 ms this used to wait was most of a hover's latency (2026-10-11).
    if (!this.detailDirty || now - this.detailAt < (this.plantSlowGlow ? 80 : 16)) return;
    this.detailDirty = false;
    this.detailAt = now;
    const t0 = now;
    cam.updateMatrixWorld();
    const dir = new THREE.Vector3(this.pointerNdc[0], this.pointerNdc[1], 0.5).unproject(cam).sub(p).normalize();
    const ox = p.x, oy = p.y, oz = p.z, dx = dir.x, dy = dir.y, dz = dir.z;
    const K = DETAIL_PICTURES;
    const best: any[] = [], dist: number[] = [];
    // The glow's own ranking, over EVERY node, by the same nearness (2026-10-11:
    // "nodes glow the same way as image billboards are revealed for their
    // hovered nodes within a certain region of the mouse on the camera normal").
    const gBest: any[] = [], gDist: number[] = [], gN: number[] = [];
    let gWorst = -1;
    // And every node whose drawn disc covers the ray, however far its centre:
    // a big node under the pointer must stay pickable (the raycast gate).
    const covers = new Set<any>();
    const rs = g.nodeRelSize();
    let worst = -1, candidates = 0;
    // The region is a CYLINDER about the ray (item 112, 2026-10-11: "the mouse
    // was in the top right corner of the screen ... the images from a far-away
    // url would still reveal"): a node further than `revealRadius` from the
    // ray -- in world units, the normal's own length -- is outside it, however
    // few are inside. The K nearest took whatever was nearest, anywhere.
    const R = this.revealRadius(g), R2 = R * R;
    for (const n of g.graphData().nodes) {
      if (!Number.isFinite(n.x)) continue;
      const vx = n.x - ox, vy = n.y - oy, vz = (n.z || 0) - oz;
      const t = vx * dx + vy * dy + vz * dz;
      if (t <= 0) continue;                         // behind the camera
      // The normal to the ray, per unit of depth along it: nearness to the
      // mouse ON SCREEN. The raw normal let nodes far down the ray -- specks --
      // take every slot from the ones under the cursor.
      const n2 = vx * vx + vy * vy + vz * vz - t * t;
      const d2 = n2 / (t * t);
      // The node's DRAWN radius (its proxy's): sized by `val` this was up to
      // 19 world units for a page node drawn at chunk size, so the ray
      // "covered" nodes far from the pointer near the camera (2026-10-12).
      const hr = this.plantStaleProxies ? Math.cbrt(Math.max(n.val ?? 1, 1e-9)) * rs * 1.75 * 1.4142
        : (n.__threeObj && n.__threeObj.__proxy ? n.__threeObj.scale.x : Math.cbrt(Math.max(n.val ?? 1, 1e-9)) * rs);
      if (n2 < hr * hr) covers.add(n);
      if (!this.plantUnboundedReveal && n2 > R2) continue;
      if (gBest.length < K) {
        gBest.push(n); gDist.push(d2); gN.push(n2);
        if (gBest.length === K) { gWorst = 0; for (let i = 1; i < K; i++) if (gDist[i] > gDist[gWorst]) gWorst = i; }
      } else if (d2 < gDist[gWorst]) {
        gBest[gWorst] = n; gDist[gWorst] = d2; gN[gWorst] = n2;
        gWorst = 0; for (let i = 1; i < K; i++) if (gDist[i] > gDist[gWorst]) gWorst = i;
      }
      if (!n.image?.src || n.level === "page" || n.level === "path") continue;
      candidates++;
      if (best.length < K) {
        best.push(n); dist.push(d2);
        if (best.length === K) { worst = 0; for (let i = 1; i < K; i++) if (dist[i] > dist[worst]) worst = i; }
      } else if (d2 < dist[worst]) {
        best[worst] = n; dist[worst] = d2;
        worst = 0; for (let i = 1; i < K; i++) if (dist[i] > dist[worst]) worst = i;
      }
    }
    const pictures = new Set(best);
    // **What stands in front of the presented picture is darkened** (2026-10-17:
    // "we should also darken nodes in front of the hovered node images (if
    // they are present ...)"). The picture nearest the ray is the one being
    // presented; every other node in the cylinder nearer the camera than it
    // is dimmed, its glow with it. Planted: `plantNoFrontDim`.
    const wasDim = this.dimFront;
    this.dimFront = new Set<any>();
    if (best.length && !this.plantNoFrontDim) {
      let k = 0;
      for (let i = 1; i < best.length; i++) if (dist[i] < dist[k]) k = i;
      const P = best[k];
      const tP = (P.x - ox) * dx + (P.y - oy) * dy + ((P.z || 0) - oz) * dz;
      for (const n of [...gBest, ...covers]) {
        if (pictures.has(n)) continue;
        const t = (n.x - ox) * dx + (n.y - oy) * dy + ((n.z || 0) - oz) * dz;
        if (t > 0 && t < tP) this.dimFront.add(n);
      }
    }
    const picturesChanged = pictures.size !== this.detail.size || [...pictures].some((n) => !this.detail.has(n));
    this.lastRevealed = this.detail;
    this.detail = pictures;
    // Graded: 1 for the node nearest the pointer, falling to 0.25 at the edge
    // of the region.
    const near = gDist.length ? Math.sqrt(Math.min(...gDist)) : 0, far = gDist.length ? Math.sqrt(Math.max(...gDist)) : 0;
    const span = Math.max(1e-9, far - near);
    const was = this.glowNear;
    this.pickNear = covers;
    // One number per candidate, compared per proxy: a Set lookup per proxy per
    // raycast was itself 7% of the CPU at 22k nodes.
    const stamp = ++this.pickStamp;
    for (const n of gBest) n.__pk = stamp;
    for (const n of covers) n.__pk = stamp;
    // Graded by the distance to the ray against the cylinder's radius: 1 on
    // the ray, 0.25 at the cylinder's wall -- so a lone node near the pointer
    // glows as brightly as one in a crowd (item 112). Planted (unbounded): by
    // rank among the K, as before.
    this.glowNear = new Map(gBest.map((n, i) => [n, this.plantUnboundedReveal
      ? 1 - 0.75 * (Math.sqrt(gDist[i]) - near) / span
      : 1 - 0.75 * Math.min(1, Math.sqrt(Math.max(0, gN[i])) / Math.max(R, 1e-9))]));
    // Only the nodes whose glow changed are rewritten, in place; a change of
    // which pictures are revealed changes what is drawn, and takes a full sync.
    if (this.plantSlowGlow || !this.batch) this.batchDirty = true;
    else {
      // The revealed pictures that changed move between meshes in place too.
      const changed = new Set<any>([...was.keys(), ...this.glowNear.keys(), ...wasDim, ...this.dimFront]);
      if (picturesChanged) for (const n of pictures) changed.add(n);
      for (const n of this.lastRevealed) if (!pictures.has(n)) changed.add(n);
      const rs = g.nodeRelSize(), media = this.drawnMedia;
      if (this.batch.patch(changed, (n) => this.lookOf(n, rs, media)) > 0) this.batchDirty = true;
    }
    // The pointer move this frame answers, to the moment its glow is written:
    // the hover latency the reader sees, minus the frame that draws it.
    if (this.pointerAt) {
      this.glowLatency.push(Math.round((performance.now() - this.pointerAt) * 10) / 10);
      if (this.glowLatency.length > 300) this.glowLatency.shift();
      this.pointerAt = 0;
    }
    this.detailStats = { computes: this.detailStats.computes + 1, last_ms: Math.round((performance.now() - t0) * 100) / 100,
                         size: best.length, candidates };
  }

  private startBatch(graph: any, media: boolean): void {
    this.stopBatch();
    // On the pane, not the canvas: the panel and caption layers sit above the
    // canvas and took the canvas's pointer moves.
    const el: HTMLElement = graph.renderer().domElement;
    const host: HTMLElement = this.canvasEl || this.contentEl;
    host.addEventListener("pointermove", (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      this.pointerNdc = [((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1];
      this.detailDirty = true;
      if (!this.pointerAt) this.pointerAt = e.timeStamp || performance.now();
      // Not a full re-sync per pointer move: the glow pass patches what changed
      // and asks for a sync only when the revealed pictures change.
      if (this.plantSlowGlow) this.batchDirty = true;
    }, { passive: true });
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
    if (!renderer.__vertiscopeTimed) {
      const draw = renderer.render.bind(renderer);
      renderer.__vertiscopeDraw = draw;
      renderer.render = (scene: any, camera: any) => {
        const t = performance.now();
        draw(scene, camera);
        this.renderMs.push(performance.now() - t);
        if (this.renderMs.length > 600) this.renderMs.splice(0, 100);
      };
      renderer.__vertiscopeTimed = true;
    }
    // Every graphData swap and reheat on the recorder's clock.
    const gd = graph.graphData.bind(graph), reheat = graph.d3ReheatSimulation?.bind(graph);
    graph.graphData = (...a: any[]) => {
      if (a.length) { this.motion.event("graphData", { nodes: a[0]?.nodes?.length, links: a[0]?.links?.length }); this.batchDirty = true; }
      return gd(...a);
    };
    for (const k of ["nodeVal", "nodeColor"]) {
      const f = graph[k].bind(graph);
      graph[k] = (...a: any[]) => { if (a.length) this.batchDirty = true; return f(...a); };
    }
    this.batch.onPlaced = () => { this.batchDirty = true; };
    // The scene and the graph's root group never move, but each recomposed
    // its matrix every frame -- and three.js then re-multiplies every child's
    // world matrix: 23k proxies, 2.8 s of every 6 s in chunk view (2026-10-11).
    // Composed once and left; the proxies compose theirs when they move.
    // Planted with the proxies' (`plantProxyAutoMatrix`).
    // Checked every frame, not once: the library adds its root group to the
    // scene on a later tick than this, and a one-time pass missed it.
    const freezeStatic = () => {
      if (this.plantProxyAutoMatrix) return;
      const freeze = (o: any) => { if (o && o.matrixAutoUpdate) { o.updateMatrix(); o.matrixAutoUpdate = false; o.updateMatrixWorld(true); this.frozenAncestors++; } };
      const sc: any = graph.scene();
      freeze(sc);
      for (const c of sc.children || []) if (!c.isCamera && !c.isLight && (c.isGroup || c.type === "Object3D")) freeze(c);
    };
    if (reheat) graph.d3ReheatSimulation = (...a: any[]) => { this.motion.event("reheat"); return reheat(...a); };
    const V3 = new THREE.Vector3();
    const tick = (t: number) => {
      this.batchRaf = requestAnimationFrame(tick);
      const g: any = this.graph;
      if (!g || !this.batch) return;
      this.stepGlides();
      freezeStatic();
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
        this.adaptPixelRatio(g, t);
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
      this.idleDrift(g, t);
      this.zoomTick(g);
      if (media && !this.plantAllPictures) this.refreshDetail(g);
      // Only when something drawn has changed (2026-10-11, measured in chunk
      // view: 4.7 s of every 5 s of script at 22.8k nodes, with nothing on
      // screen moving -- the batch rewrote and re-uploaded every node every
      // frame). Changes mark it dirty: the engine ticking, a glide, a new node
      // set, sizes or colours re-read, a hover, a picture landing, a panel.
      // And every 250 ms regardless, so a change nothing marked is drawn a
      // quarter-second late rather than never. Planted: every frame.
      const now = performance.now();
      // The safety net for a change nothing marked: every 250 ms on a small
      // graph, every 2 s on a large one -- a full sync of 22k nodes is ~25 ms,
      // and four a second were a tenth of every second (2026-10-11).
      const net = g.graphData().nodes.length > 5000 && !this.plantSyncEveryFrame ? 2000 : 250;
      if (!this.plantSyncEveryFrame && !this.batchDirty && !this.glides.size && now - this.batchSyncedAt < net) {
        this.batchStats.skipped++;
        return;
      }
      this.batchDirty = false;
      this.batchSyncedAt = now;
      this.batchStats.synced++;
      const d = g.graphData();
      const rs = g.nodeRelSize();
      if (this.searchState) { this.resolveSearch(); this.updateSearchLights(); }
      this.batch.sync(d.nodes, d.links.concat(this.drawableCodeEdges(d.nodes), this.drawableKgEdges(d.nodes)), (n) => this.lookOf(n, rs, media), this.searchLineAlpha());
      if (!this.plantStaleProxies) this.fitProxies(d.nodes, rs, media);
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
    renderer.setClearColor(this.plantGreyBackground ? 0x1e1e1e : 0x000000, 1);   // as the pane draws it
    renderer.clear();
    (renderer.__vertiscopeDraw || renderer.render.bind(renderer))(g.scene(), cam);
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
    this.batch.sync(d.nodes, d.links.concat(this.drawableCodeEdges(d.nodes), this.drawableKgEdges(d.nodes)), (n) => this.lookOf(n, rs, this.drawnMedia));
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
    if (!obj.matrixAutoUpdate) obj.updateMatrix();
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
      this.batchDirty = true;
      n.imgLoaded = false;
      any = true;
      // A picture changes what the node occupies (a panel's half-diagonal):
      // the proxy follows. The batch reads `n.image` on its next frame.
      if (!this.plantPerNode) { const o = (n as any).__threeObj; if (o) { o.scale.setScalar(this.proxyRadius(n)); if (!o.matrixAutoUpdate) o.updateMatrix(); } }
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
      // AS DRAWN: the batch's own size (nodeScale, one size in chunk view)
      // times the zoom factor (G-206) -- `drawnRadius` left both out.
      const r = this.lookOf(n, relSize, media).half * this.zoomScale;
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
  snapshotFor: ((cid: string, url: string, again?: boolean) => Promise<boolean>) | null = null;

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
      onFieldDone: () => this.releaseHeld(entry),
    });
    const toggle = entry.el.querySelector(".vertiscope-bb-head") as HTMLElement | null;
    if (toggle && !toggle.querySelector(".vertiscope-bb-form")) {
      const t = toggle.createSpan({ cls: "vertiscope-bb-form", text: "md" });
      t.setAttr("aria-label", "distilled form");
      t.onpointerdown = (e: PointerEvent) => e.stopPropagation();
      t.onclick = (e: MouseEvent) => {
        e.stopPropagation();
        const b = entry.el.querySelector(".vertiscope-bb-body") as HTMLElement;
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
  /** Planted (item 111): a panel redraws even while the reader types in it. */
  plantRedrawWhileTyping = false;
  panelStats = { held: 0, released: 0 };
  private typingIn(body: HTMLElement): boolean {
    const f = body.querySelector("iframe") as any;
    try { return !!(f && typeof f.vertiscopeTyping === "function" && f.vertiscopeTyping()); } catch { return false; }
  }
  private releaseHeld(entry: any): void {
    if (!entry || !entry.heldRefresh) return;
    entry.heldRefresh = false;
    this.panelStats.released++;
    this.refreshBillboards([entry.node.id]);
  }

  refreshBillboards(cids: string[]): void {
    const changed = new Set(cids);
    for (const c of cids) this.payloadCache.delete(c);   // its payload is stale now
    for (const [id, entry] of this.billboards.entries() as any) {
      if (!changed.has(id)) continue;
      const body = entry.el.querySelector(".vertiscope-bb-body") as HTMLElement | null;
      if (!body) continue;
      // The reader is typing in this panel: its redraw waits until they
      // leave the field (PLUGIN_GOAL 111) -- re-mounting replaced the field
      // under their fingers on every capture of a streaming page.
      if (!this.plantRedrawWhileTyping && this.typingIn(body)) {
        entry.heldRefresh = true;
        this.panelStats.held++;
        continue;
      }
      // The diff rewrote this chunk: its form is drawn again from the PAGE
      // (re-read) or the store, never from what was held.
      if (entry.form) { void this.renderForm(entry, entry.form, true); continue; }
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
    this.batchDirty = true;
    const entry: any = this.billboards.get(id);
    if (!entry) return;
    if (entry.surface) this.removeChild(entry.surface);
    entry.el.remove();
    this.billboards.delete(id);
    this.stopBillboardLoop();
    // A unit node exists for its panel: it goes with it (G-251). Kept, they
    // stood as grey nodes no projection would ever place -- read as scans
    // left unprojected (2026-10-18: "a lot of diff scans not yet at least
    // projected after vectorization"). Planted `plantKeepUnits`.
    if (this.unitNodes.has(id) && !this.plantKeepUnits && !id.startsWith("file:") && !id.startsWith("kg:")) this.dropUnitNode(id);
  }
  /** Planted: a unit node outlives its panel (grey until the cap), as before. */
  plantKeepUnits = false;
  private dropUnitNode(id: string): void {
    this.unitNodes.delete(id);
    if (!this.graph) return;
    const data: any = this.graph.graphData();
    if (!data.nodes.some((n: any) => String(n.id) === id && n.unit)) return;
    const end = (x: any) => String(typeof x === "object" && x ? x.id : x);
    this.graph.graphData({ nodes: data.nodes.filter((n: any) => !(n.unit && String(n.id) === id)),
                           links: data.links.filter((l: any) => end(l.source) !== id && end(l.target) !== id) });
    this.unitStats.dropped++;
    this.batchDirty = true;
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
  /** Chunks the browser holds pinned, so a deferred placement knows it is still wanted. */
  private pinWanted = new Set<string>();
  /** Planted: an unknown cid is retried like an unembedded one (the 25 s wait). */
  plantWaitUnknown = false;

  async pinChunk(cid: string): Promise<boolean> {
    if (!this.graph || !cid) return false;
    this.pinWanted.add(cid);
    let node = this.graph.graphData().nodes.find((n: any) => n.id === cid);
    // A chunk pinned moments after its page landed is in the store but not
    // yet VECTORISED -- embedding runs off the capture path by design -- so
    // placement has nothing to put it at. Asking once left the pin with no
    // billboard (D-36, 2026-10-07: 1 pin, 0 billboards on a fresh page). It
    // is asked again until the vector arrives, for as long as it is pinned.
    let drawnAs = cid;
    for (let i = 0; !node && i < 40 && this.pinWanted.has(cid); i++) {
      const got: any = await this.sidecar.place([cid]).catch(() => null);
      if (got?.nodes?.length) this.absorb(got.nodes, got.edges);
      // A duplicate or a merge group's member is drawn by ANOTHER chunk: the
      // pin's billboard opens on that one (G-82, 2026-10-12).
      if (got?.aliases?.[cid] && !this.plantNoPinAlias) drawnAs = String(got.aliases[cid]);
      // The store has no such chunk: no vector is coming, so stop asking and
      // let the browser re-anchor the pin by its address (G-82).
      else if (got?.unknown?.includes(cid) && !this.plantWaitUnknown) break;
      node = this.graph.graphData().nodes.find((n: any) => n.id === drawnAs);
      if (!node) await new Promise((r) => window.setTimeout(r, 500));
    }
    if (!node || !this.pinWanted.has(cid)) return false;
    await this.openBillboard(node, true);
    if (drawnAs !== cid) {
      this.pinAlias.set(cid, drawnAs);
      const entry: any = this.billboards.get(drawnAs);
      if (entry) (entry.pins = entry.pins || new Set()).add(cid);
    }
    return true;
  }
  /** A pinned chunk -> the chunk whose billboard shows it (duplicates, group members). */
  private pinAlias = new Map<string, string>();

  /** The browser let a chunk go: close its billboard. */
  unpinChunk(cid: string): void {
    this.pinWanted.delete(cid);
    const id = this.pinAlias.get(cid) || cid;
    this.pinAlias.delete(cid);
    const entry: any = this.billboards.get(id);
    if (entry && entry.pins) entry.pins.delete(cid);
    // Another pin still shows through this billboard: it stays.
    if (entry && entry.fromBrowser && !(entry.pins && entry.pins.size)) this.closeBillboard(id);
  }

  /** Which billboards are open, and which the browser holds -- for the
   *  harness, so a check reads the pane rather than re-deriving it. */
  billboardState(): { id: string; fromBrowser: boolean; shadow: boolean; form: string; elements: number; pins?: string[] }[] {
    return [...this.billboards.entries()].map(([id, e]: [string, any]) => {
      const host = e.el.querySelector(".vertiscope-html-host");
      const frame = e.el.querySelector("iframe.vertiscope-snapshot") as HTMLIFrameElement | null;
      let elements = 0;
      try {
        elements = frame ? (frame.contentDocument?.querySelectorAll("#vertiscope-root *").length || 0)
          : (host?.shadowRoot?.querySelectorAll("*").length || 0);
      } catch { /* not readable yet */ }
      // Two forms (D-36): the chunk as the PAGE draws it, when the page gave
      // one, else the distilled shadow-DOM form. Both are rendered HTML.
      return {
        id, fromBrowser: !!e.fromBrowser, minimized: !!e.minimized, pins: e.pins ? [...e.pins] : [],
        shadow: !!host?.shadowRoot || !!frame,
        form: frame ? "page" : (host?.shadowRoot ? "distilled" : "none"),
        elements,
      };
    });
  }

  /** Put a billboard where its node is, in screen coordinates. */
  /** Is the browser cell showing a page's offline form (`G-59`, `G-62`)? */
  private offlineNow(): boolean {
    const b: any = this.app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
    return !!(b && b.offlineFor) && !this.plantOfflineBillboard;
  }
  /** Planted (`G-59`): offline, the panel stays a projector billboard. */
  plantOfflineBillboard = false;
  docked = 0;

  /** Move a panel into the main offline pane: the same element, re-parented. */
  private async dockPanel(entry: any): Promise<void> {
    const ws = this.app.workspace;
    let leaf = ws.getLeavesOfType(PANEL_VIEW)[0];
    if (!leaf) {
      leaf = ws.getLeaf("tab");
      await leaf.setViewState({ type: PANEL_VIEW, active: true });
    }
    ws.revealLeaf(leaf);
    // One docked panel: the previous one goes back to being closed.
    for (const [id, e] of this.billboards) if (e !== entry && (e as any).docked) this.closeBillboard(id as string);
    (leaf.view as PanelView).dock(entry.el, String(entry.node.id));
    entry.docked = true;
    entry.pinned = true;
    this.docked++;
  }

  private positionBillboard(entry: { el: HTMLElement; node: any; pinned: boolean }): void {
    if (entry.pinned || !this.graph) return;
    const n = entry.node;
    if (!Number.isFinite(n.x)) return;
    const at: any = (this.graph as any).graph2ScreenCoords(n.x, n.y, n.z);
    if (!at) return;
    const e: any = entry;
    entry.el.style.left = `${Math.round(at.x) + (e.dx ?? 12)}px`;
    entry.el.style.top = `${Math.round(at.y) + (e.dy ?? 12)}px`;
  }

  /**
   * Follow the nodes while anything is open.
   *
   * Its own frame loop rather than `onEngineTick`: the simulation stops
   * ticking as soon as it settles, and the camera keeps moving after that --
   * so a panel anchored on ticks alone detaches from its node the moment the
   * reader orbits, which is exactly when they are looking at it.
   */
  /** Positioning errors swallowed by the billboard loop (for the harness). */
  billboardErrors = 0;
  private billboardBeat = 0;
  private startBillboardLoop(): void {
    // A loop that died (frame id set, no frame since) is restarted: the id
    // alone is not proof of life.
    if (this.billboardFrame && performance.now() - this.billboardBeat < 500) return;
    if (this.billboardFrame) window.cancelAnimationFrame(this.billboardFrame);
    this.billboardFrame = 0;
    const step = () => {
      if (!this.billboards.size) { this.billboardFrame = 0; return; }
      // One panel's error must not end the loop for all of them: a throw here
      // left `billboardFrame` set with no frame scheduled, so every panel
      // opened after it stayed where it first landed -- not following its
      // node, and not re-centred by the form switch (2026-10-07, found when
      // the centre shifted 85 px on a switch: dx/dy set, never applied).
      this.billboardBeat = performance.now();
      for (const entry of this.billboards.values()) {
        try { this.positionBillboard(entry); } catch (e) { this.billboardErrors++; }
      }
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
    if (node && node.url) { this.openedByReader.add(node.url); this.collapsedByReader.delete(node.url); }
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
  // ---- chunk view: a bounded collision relax (2026-10-11) -------------------

  /**
   * Chunk view is UMAP-only (item 78), and UMAP puts near-duplicates almost on
   * one point: 80% of 22,496 nodes sat at the shrink floor and the orbs still
   * clumped (2026-10-11: "a little too clumped together ... perhaps *some*
   * amount of force-directed is still worth, but not to the extent that we
   * have to break our memory bank or see nodes exploding everywhere because of
   * force superpositions"). So ONE relax after the layout lands -- not a live
   * simulation: collision only (no charge, no springs, so no superposition),
   * every node pulled back toward its own UMAP point each iteration, and none
   * moved more than `relaxMaxShift` of its own radii. A spatial hash on
   * integer keys, one iteration per frame, so the main thread is never held
   * and the memory is three floats a node. The fit (`fitX/Y/Z`) is never
   * written: the drawn place is the relaxed one, the fit stays the fit.
   * Planted: no relax, the UMAP points as they are.
   */
  plantNoChunkRelax = false;
  /** Planted (PLUGIN_GOAL 108): stored drawn places ignored; relax from the fit every switch. */
  plantNoDrawn = false;
  private relaxAfterSpacing = false;
  /** Planted: the relax moves stored places too, as before. */
  plantRelaxAll = false;
  drawnStats = { skipped: 0, posted: 0, saved: 0, free: 0, fixed: 0 };
  relaxIterations = 40;
  relaxMaxShift = 4;
  chunkRelaxStats = { runs: 0, iterations: 0, ms: 0, nodes: 0, overlaps_before: -1, overlaps_after: -1, max_shift_radii: 0, moved: 0 };
  private relaxSeq = 0;
  /** The relax's spacing, in drawn radii: a visible gap, not the collider's 2
   *  (at 2, chunk view held 2.1 million overlapping pairs and one iteration took
   *  300 ms). */
  relaxSafety = 1.25;
  /** Work per frame, ms: the relax yields to the renderer past this. */
  relaxBudgetMs = 8;
  private relaxChunkView(): void {
    const g: any = this.graph;
    if (!g || this.level !== "chunk" || this.plantNoChunkRelax) return;
    const seq = ++this.relaxSeq;
    const nodes = (g.graphData().nodes as any[]).filter((n) => Number.isFinite(n.fitX) && Number.isFinite(n.fitY));
    const N = nodes.length;
    if (N < 2) return;
    // Every node already has its stored drawn place (PLUGIN_GOAL 108): the
    // layout is the one the reader saw last -- nothing to relax, nothing moves.
    // A page node is placed by the fit itself and has no stored place: it
    // counts as placed (one page node kept 22,648 stored chunks relaxing).
    // ...and a stored place counts only at the SIZE it was relaxed at: places
    // spaced for orbs 14x too big are not this size's places (2026-10-12).
    const rs0 = g.nodeRelSize(), media0 = this.drawnMedia;
    const sameSize = (n: any) => Number.isFinite(n.drawnHalf)
      && Math.abs(n.drawnHalf - this.lookOf(n, rs0, media0).half) <= 0.1 * Math.max(n.drawnHalf, 1e-6);
    const placed = (n: any) => !this.plantNoDrawn && ((!!n.drawnAt && sameSize(n)) || n.level === "page");
    const stored = nodes.filter(placed).length;
    if (stored === N) {
      this.chunkRelaxStats = { ...this.chunkRelaxStats, runs: this.chunkRelaxStats.runs, from_store: N, relaxed: 0 } as any;
      this.drawnStats.skipped++;
      return;
    }
    const rs = g.nodeRelSize(), media = this.drawnMedia, S = this.relaxSafety;
    const H = new Float64Array(N), P = new Float64Array(3 * N), F = new Float64Array(3 * N);
    // Nodes with a stored place stay where they are; only the NEW ones are
    // relaxed, against everything (2026-10-12: the relax moved all 22,648
    // stored places again on every switch, 39-47 s, and re-saved them). With
    // none stored, every node is free, as before.
    const fixed = new Uint8Array(N);
    if (stored > 0 && !this.plantRelaxAll) nodes.forEach((n, i) => { if (placed(n)) fixed[i] = 1; });
    const free: number[] = [];
    for (let i = 0; i < N; i++) if (!fixed[i]) free.push(i);
    nodes.forEach((n, i) => {
      H[i] = Math.max(1e-6, this.lookOf(n, rs, media).half);
      F[3 * i] = n.fitX; F[3 * i + 1] = n.fitY; F[3 * i + 2] = n.fitZ ?? 0;
      // A stored place starts where it was left; only the new nodes start at their fit.
      const d = !this.plantNoDrawn && n.drawnAt;
      P[3 * i] = d ? d[0] : F[3 * i]; P[3 * i + 1] = d ? d[1] : F[3 * i + 1]; P[3 * i + 2] = d ? d[2] : F[3 * i + 2];
    });
    // The cell is a typical node's reach, not the largest one's: a few big
    // pictures would make every cell hold the whole cloud.
    const sorted = Array.from(H).sort((x, y) => x - y);
    const cell = Math.max(1e-3, 2 * S * sorted[Math.floor(N * 0.9)]);
    const hash = (cx: number, cy: number, cz: number) => ((cx * 73856093) ^ (cy * 19349663) ^ (cz * 83492791)) | 0;
    const build = () => {
      const grid = new Map<number, number[]>();
      for (let i = 0; i < N; i++) {
        const k = hash(Math.floor(P[3 * i] / cell), Math.floor(P[3 * i + 1] / cell), Math.floor(P[3 * i + 2] / cell));
        const l = grid.get(k); if (l) l.push(i); else grid.set(k, [i]);
      }
      return grid;
    };
    // Overlap, SAMPLED: every pair of a sample of nodes against all their
    // neighbours, as drawn (no safety). Exhaustive, it was one 1 s frame.
    const sampleStep = Math.max(1, Math.floor(N / 3000));
    const overlaps = (): number => {
      const grid = build();
      let o = 0;
      for (let i = 0; i < N; i += sampleStep) {
        const cx = Math.floor(P[3 * i] / cell), cy = Math.floor(P[3 * i + 1] / cell), cz = Math.floor(P[3 * i + 2] / cell);
        for (let ox = -1; ox <= 1; ox++) for (let oy = -1; oy <= 1; oy++) for (let oz = -1; oz <= 1; oz++) {
          for (const j of grid.get(hash(cx + ox, cy + oy, cz + oz)) || []) {
            if (j === i) continue;
            if (Math.hypot(P[3 * i] - P[3 * j], P[3 * i + 1] - P[3 * j + 1], P[3 * i + 2] - P[3 * j + 2]) < H[i] + H[j]) o++;
          }
        }
      }
      return o;
    };
    this.drawnStats.free = free.length; this.drawnStats.fixed = N - free.length;
    const t0 = performance.now();
    const before = overlaps();
    let it = 0, grid: Map<number, number[]> | null = null, cursor = 0, moved = 0, worst = 0;
    const step = () => {
      if (seq !== this.relaxSeq || this.level !== "chunk" || !this.graph) return;
      const tf = performance.now();
      if (!grid) { grid = build(); cursor = 0; moved = 0; }
      // Pairs, until this frame's budget is spent; the iteration resumes next frame.
      while (cursor < free.length && performance.now() - tf < this.relaxBudgetMs) {
        const i = free[cursor++];
        const cx = Math.floor(P[3 * i] / cell), cy = Math.floor(P[3 * i + 1] / cell), cz = Math.floor(P[3 * i + 2] / cell);
        for (let ox = -1; ox <= 1; ox++) for (let oy = -1; oy <= 1; oy++) for (let oz = -1; oz <= 1; oz++) {
          for (const j of grid.get(hash(cx + ox, cy + oy, cz + oz)) || []) {
            // A free pair is handled once (from its lower index); a fixed
            // neighbour is handled from the free side, which takes it all.
            if (j === i || (!fixed[j] && j < i)) continue;
            let dx = P[3 * j] - P[3 * i], dy = P[3 * j + 1] - P[3 * i + 1], dz = P[3 * j + 2] - P[3 * i + 2];
            let d = Math.hypot(dx, dy, dz);
            const want = S * (H[i] + H[j]);
            if (d >= want) continue;
            if (d < 1e-9) { dx = Math.cos(i * 2.399); dy = Math.sin(i * 2.399); dz = ((i % 7) - 3) / 7; d = Math.hypot(dx, dy, dz); }
            const share = fixed[j] ? 1 : 0.5;
            const push = (want - d) / d * share;
            P[3 * i] -= dx * push; P[3 * i + 1] -= dy * push; P[3 * i + 2] -= dz * push;
            if (!fixed[j]) { P[3 * j] += dx * push; P[3 * j + 1] += dy * push; P[3 * j + 2] += dz * push; }
            moved++;
          }
        }
      }
      worst = Math.max(worst, performance.now() - tf);
      if (cursor < free.length) { requestAnimationFrame(step); return; }
      // The iteration's end: back toward each UMAP point, never past the leash.
      for (const i of free) {
        for (let a = 0; a < 3; a++) P[3 * i + a] += (F[3 * i + a] - P[3 * i + a]) * 0.04;
        const dx = P[3 * i] - F[3 * i], dy = P[3 * i + 1] - F[3 * i + 1], dz = P[3 * i + 2] - F[3 * i + 2];
        const d = Math.hypot(dx, dy, dz), lim = this.relaxMaxShift * H[i];
        if (d > lim) { const f = lim / d; P[3 * i] = F[3 * i] + dx * f; P[3 * i + 1] = F[3 * i + 1] + dy * f; P[3 * i + 2] = F[3 * i + 2] + dz * f; }
      }
      it++;
      grid = null;
      if (moved && it < this.relaxIterations) { requestAnimationFrame(step); return; }
      let maxShift = 0, shifted = 0;
      const save: (string | number)[][] = [];
      nodes.forEach((n, i) => {
        const x = P[3 * i], y = P[3 * i + 1], z = P[3 * i + 2];
        // Kept on the chunk when new or moved (PLUGIN_GOAL 108), in the
        // layout's frame (z without the pane's depth squash).
        const was = n.drawnAt;
        if (n.level !== "page" && !String(n.id).startsWith("page:")
            && (!was || Math.hypot(x - was[0], y - was[1], z - was[2]) > 1e-6
                || !Number.isFinite(n.drawnHalf) || Math.abs(n.drawnHalf - H[i]) > 1e-6)) {
          save.push([String(n.id), x, y, z / DEPTH, n.fitX, n.fitY, (n.fitZ ?? 0) / DEPTH, H[i]]);
        }
        n.drawnAt = [x, y, z];
        n.drawnHalf = H[i];
        const sh = Math.hypot(x - F[3 * i], y - F[3 * i + 1], z - F[3 * i + 2]);
        if (sh > 1e-6) shifted++;
        maxShift = Math.max(maxShift, sh / H[i]);
        n.x = n.fx = x; n.y = n.fy = y; n.z = n.fz = z;
        n.relaxHalf = H[i];                 // the radius the leash was measured in
      });
      const after = overlaps();
      this.chunkRelaxStats = { runs: this.chunkRelaxStats.runs + 1, iterations: it, ms: Math.round(performance.now() - t0), nodes: N,
                               overlaps_before: before, overlaps_after: after, sampled_every: sampleStep,
                               max_shift_radii: Math.round(maxShift * 100) / 100, moved: shifted,
                               worst_frame_ms: Math.round(worst * 10) / 10 } as any;
      g.d3ReheatSimulation?.();          // two cool ticks move each pick proxy to its node
      this.batchDirty = true;
      if (save.length && !this.plantNoDrawn) {
        this.drawnStats.posted += save.length;
        void this.sidecar.saveDrawn(save).then((n) => { this.drawnStats.saved += n; });
      }
    };
    requestAnimationFrame(step);
  }

  // ---- PLUGIN_GOAL 83: idle drift ------------------------------------------

  /**
   * With no reader activity, the scene turns: the camera orbits its target
   * about the vertical, and the colours turn about the grey axis (2026-10-11:
   * "a latent feature that rotates both cartesian and color coordinates slowly
   * but noticeably whenever there is no user activity"). Both are DRAWN, never
   * written: the layout keeps its coordinates and the store its colours, so
   * the moment the reader acts the turn stops where it is and the colours ease
   * back to the fit's own. Activity is the plugin's own reader clock
   * (`__vertiscopeReaderAt`, stamped on every input in the app).
   */
  /** 4 s of quiet, not 20 (2026-10-17: "it could debounce a lot faster"). */
  idleDriftAfterMs = 4000;
  /** Camera orbit, radians a second: a full turn in about 5 minutes. It was
   *  0.063 (100 s) -- "physical rotation could be slower... im feeling dizzy"
   *  (2026-10-12). */
  driftOrbitRate = 0.035;   // "somewhat faster" (2026-10-12): ~3 min a turn
  /** Hue turn, radians a second: the full colour wheel in about 30 s. It was
   *  0.052 (2 minutes) -- "hsv rotation seems pretty slow" (2026-10-12). */
  driftHueRate = 0.8;       // "a lot faster" (2026-10-12): the wheel in ~8 s
  /** Planted: no drift at all. */
  plantNoDrift = false;
  /** Planted: a standing query stops the drift, as it did. */
  plantDriftStopsOnSearch = false;
  driftStats = { active: false, turned: 0, hue: 0, started: 0, stopped: 0 };
  /** Set by the drift's own check: drift although a check is running. */
  driftInCheck = false;
  /**
   * **Smaller at full view** (G-206, 2026-10-17, the reader's answer for
   * G-94: "Shrink nodes when the whole corpus is in frame, back to full size
   * when zoomed in"). Pages buried behind pages at full view are spaced fine
   * in 3D -- 0 of 179 buried pairs within 2 radii -- they line up in depth
   * inside site clusters; drawing smaller there uncovers them. DISPLAY only:
   * a uniform in the batch's shaders, so the layout, the colliders and the
   * stored places never change with zoom. Full size at a quarter of the
   * full-view distance or closer, `zoomMin` at it or beyond, eased in log
   * distance between. Planted: `plantNoZoomScale`.
   */
  zoomMin = 0.5;
  zoomScale = 1;
  /** The camera's distance to its target when the whole cloud was framed. */
  fullViewDist = 0;
  plantNoZoomScale = false;
  /** Planted: the transparent canvas over the pane's grey, as before. */
  plantGreyBackground = false;
  /** Planted (G-207): the chunk glow off -- orbs only reflect, as before. */
  plantNoHalo = false;
  private zoomTick(g: any): void {
    if (!this.batch) return;
    // The glow's pixel floor needs pixels -> view units (G-207).
    const cam0 = g.camera();
    if (this.canvasEl && cam0?.projectionMatrix) this.batch.setViewport(this.canvasEl.clientHeight, cam0.projectionMatrix.elements[5]);
    this.batch.setHalo(!this.plantNoHalo);
    let f = 1;
    if (!this.plantNoZoomScale && this.fullViewDist > 0) {
      const cam = g.camera(), t = g.controls()?.target;
      const d = t ? cam.position.distanceTo(t) : cam.position.length();
      const near = this.fullViewDist / 4;
      const k = Math.min(1, Math.max(0, Math.log(d / near) / Math.log(this.fullViewDist / near)));
      f = 1 + (this.zoomMin - 1) * k;
    }
    if (Math.abs(f - this.zoomScale) < 1e-3) return;
    // Picking follows what is drawn: the proxies refit early on a real change.
    if (Math.abs(f - this.zoomScale) > 0.1 * this.zoomScale) this.fitProxyAt = 0;
    this.zoomScale = f;
    this.batch.setZoom(f);
  }

  private driftAt = 0;
  private idleDrift(g: any, now: number): void {
    if (!this.batch) return;
    const dt = this.driftAt ? Math.min(0.1, (now - this.driftAt) / 1000) : 0;
    this.driftAt = now;
    const readerAt = (window as any).__vertiscopeReaderAt || 0;
    const idle = Date.now() - readerAt >= this.idleDriftAfterMs;
    const visible = !!this.canvasEl && this.canvasEl.offsetWidth > 0;
    // Not under a check or a stress run (their idle is not the reader's, and a
    // turning camera moves every screen position they measure) -- unless the
    // drift's own check asks for it.
    const w: any = window;
    const checking = (!!w.__vertiscope?.verify?.state?.()?.running || !!w.__vertiscopeStressing) && !this.driftInCheck;
    // A standing query does NOT stop it (2026-10-11: "lets standardize the
    // latent glowing glass orbs as the default, with the light sources
    // adjusting per the query scroll window. pls dont forget about the
    // rotating xyzhsv"): the lights ride on the turning scene. Gated on the
    // search, it never ran once a query had been typed. Planted: gated again.
    const on = idle && visible && !checking && !this.plantNoDrift && !(this.plantDriftStopsOnSearch && this.searchState);
    if (on !== this.driftStats.active) {
      this.driftStats.active = on;
      if (on) this.driftStats.started++; else this.driftStats.stopped++;
    }
    if (on && dt > 0) {
      const cam = g.camera(), ctl = g.controls();
      const tgt = ctl && ctl.target ? ctl.target : { x: 0, y: 0, z: 0 };
      const a = this.driftOrbitRate * dt;
      const dx = cam.position.x - tgt.x, dz = cam.position.z - tgt.z;
      cam.position.x = tgt.x + dx * Math.cos(a) - dz * Math.sin(a);
      cam.position.z = tgt.z + dx * Math.sin(a) + dz * Math.cos(a);
      cam.lookAt(tgt.x, tgt.y, tgt.z);
      this.driftStats.turned += a;
      this.batch.setHue((this.batch.hue + this.driftHueRate * dt) % (2 * Math.PI));
    } else if (this.batch.hue !== 0 && dt > 0) {
      // Back to the fit's colours the short way round, in about a second.
      let h = this.batch.hue;
      if (h > Math.PI) h -= 2 * Math.PI;
      const step = Math.sign(h) * Math.min(Math.abs(h), 3.2 * dt);
      h -= step;
      this.batch.setHue(Math.abs(h) < 1e-3 ? 0 : (h + 2 * Math.PI) % (2 * Math.PI));
    }
    this.driftStats.hue = Math.round(this.batch.hue * 1000) / 1000;
  }

  /**
   * The pixel ratio follows the frame time (2026-10-11: "node hover and
   * image/glow features ... noticeably slow latency" -- chunk view drew 70 ms
   * frames at ratio 1.5 while the pointer moved, 47% of the time native and
   * GPU: every glass orb is blended per pixel). Over the last 40 frames, a
   * median above 28 ms drops the ratio to 1; under 12 ms for 5 s puts the
   * screen's own ratio back. Planted: the ratio never moves.
   */
  plantFixedPixelRatio = false;
  dprStats = { drops: 0, restores: 0, ratio: 0 };
  private dprCheckAt = 0;
  private dprFastSince = 0;
  private adaptPixelRatio(g: any, now: number): void {
    if (this.plantFixedPixelRatio || now - this.dprCheckAt < 500 || this.frameGaps.length < 40) return;
    this.dprCheckAt = now;
    const r = g.renderer();
    const recent = this.frameGaps.slice(-40).sort((a, b) => a - b);
    const p50 = recent[20];
    const screen = window.devicePixelRatio || 1, cur = r.getPixelRatio();
    if (p50 > 28 && cur > 1) {
      r.setPixelRatio(1); this.dprStats.drops++; this.dprFastSince = 0;
    } else if (p50 < 12 && cur < screen) {
      if (!this.dprFastSince) this.dprFastSince = now;
      else if (now - this.dprFastSince > 5000) { r.setPixelRatio(screen); this.dprStats.restores++; this.dprFastSince = 0; }
    } else this.dprFastSince = 0;
    this.dprStats.ratio = r.getPixelRatio();
  }

  /** Static scene ancestors whose matrices were composed once and frozen. */
  frozenAncestors = 0;
  /** Something drawn changed since the last batch sync (see the frame loop). */
  private batchDirty = true;
  private batchSyncedAt = 0;
  /** Planted (2026-10-11): the batch rewritten every frame, changed or not. */
  plantSyncEveryFrame = false;
  batchStats = { synced: 0, skipped: 0 };
  /** Planted (2026-10-11): pick proxies recompose their matrix every frame. */
  plantProxyAutoMatrix = false;
  /** Planted (2026-10-11): proxies take part in three.js's per-frame world-matrix pass. */
  plantProxyWorldPass = false;

  /** Planted (2026-10-11): chunk view keeps the pages view's forces. */
  plantChunkForces = false;
  /** True while the drawn view is chunk view, positioned by UMAP alone. */
  umapOnly = false;

  /** Planted (2026-10-11): the all-pairs nearest-neighbour scan that froze the app. */
  plantAllPairsSpacing = false;
  /** Planted (2026-10-11): shrinking with no floor -- nodes down to specks. */
  plantSpecks = false;
  spacingStats = { runs: 0, ms: 0, nodes: 0 };

  private fitRadiiToSpacing(): boolean {
    if (!this.graph) return false;
    const data: any = this.graph.graphData();
    const nodes = data.nodes as any[];
    if (nodes.length < 2) return false;
    const relSize = (this.graph as any).nodeRelSize?.() ?? 1;
    const media = this.media();
    let changed = false;
    const t0 = performance.now();
    // Each node's nearest neighbour, through a grid (2026-10-11, the freeze:
    // the all-pairs scan was 23k x 23k = 530 million distances, 34 s on the
    // main thread every time the engine stopped). A node only needs its
    // neighbours within `drawn / 0.45` -- farther, and it is not shrunk -- so
    // the search covers that radius and no more, and the verdict is exactly
    // the all-pairs one. Planted: the all-pairs scan.
    // As DRAWN: `nodeScale` (G-188) enlarges every node, and spacing that
    // ignored it left crowded nodes a quarter wider than their room -- they
    // overlapped (G-94). Measured scaled, a node is larger where there is
    // room and shrinks to fit where there is not.
    const scale = this.plantUnscaledSpacing ? 1 : this.nodeScale;
    const drawnOf = nodes.map((a) => drawnRadius(a, relSize, media) * scale);
    const at = (a: any) => [a.x ?? 0, a.y ?? 0, a.z ?? 0];
    const sorted = drawnOf.filter((r) => r > 0).sort((x, y) => x - y);
    const typical = sorted.length ? sorted[Math.floor(sorted.length * 0.9)] : 1;
    const cell = Math.max(1e-3, typical / 0.45);
    const grid = new Map<string, number[]>();
    const keyOf = (x: number, y: number, z: number) => `${Math.floor(x / cell)},${Math.floor(y / cell)},${Math.floor(z / cell)}`;
    if (!this.plantAllPairsSpacing) {
      nodes.forEach((a, i) => { const [x, y, z] = at(a); const k = keyOf(x, y, z); const l = grid.get(k); if (l) l.push(i); else grid.set(k, [i]); });
    }
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      const drawn = drawnOf[i];
      if (drawn <= 0) continue;
      const reach = drawn / 0.45;                // nearer than this and it shrinks
      const [ax, ay, az] = at(a);
      let nearest = Infinity;
      const rings = Math.ceil(reach / cell);
      // A node so large its reach spans more cells than there are nodes (a
      // big page node): one pass over the nodes is cheaper than the cells.
      if (this.plantAllPairsSpacing || Math.pow(2 * rings + 1, 3) > nodes.length) {
        for (let j = 0; j < nodes.length; j++) {
          if (i === j) continue;
          const [bx, by, bz] = at(nodes[j]);
          const d = Math.hypot(ax - bx, ay - by, az - bz);
          if (d > 1e-6 && d < nearest) nearest = d;
        }
      } else {
        const cx = Math.floor(ax / cell), cy = Math.floor(ay / cell), cz = Math.floor(az / cell);
        for (let ox = -rings; ox <= rings; ox++) for (let oy = -rings; oy <= rings; oy++) for (let oz = -rings; oz <= rings; oz++) {
          for (const j of grid.get(`${cx + ox},${cy + oy},${cz + oz}`) || []) {
            if (j === i) continue;
            const [bx, by, bz] = at(nodes[j]);
            const d = Math.hypot(ax - bx, ay - by, az - bz);
            if (d > 1e-6 && d < nearest) nearest = d;
          }
        }
      }
      if (!Number.isFinite(nearest)) continue;
      // Never to a speck (2026-10-11: "empty nodes", hubs at val 0.0002
      // with 450 links converging on nothing visible): a node keeps at least
      // `MIN_SPACING_SHARE` of its drawn radius; the collider separates the rest.
      const allowed = Math.max(nearest * 0.45, this.plantSpecks ? 0 : drawn * MIN_SPACING_SHARE);
      if (drawn <= allowed) continue;
      // `val` is radius cubed, so a radius scale of k is k^3 on val.
      if (a.valFull === undefined) a.valFull = a.val;
      a.val = Math.max((a.val ?? 1) * Math.pow(allowed / drawn, 3), 1e-4);
      changed = true;
    }
    this.spacingStats = { runs: this.spacingStats.runs + 1, ms: Math.round(performance.now() - t0), nodes: nodes.length };
    // Chunk view's one size is the median of these: read it again.
    if (changed) this.unitValAt.at = 0;
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
         traceId?: string, opts: { pagesOnly?: boolean; keep?: Set<string> } = {}):
      { added: number; moved: number; edges: number } {
    // New nodes from the store: a standing query is re-ranked at once (item 106).
    if (this.followQuery && incoming && incoming.length && !this.plantNoRerank) {
      this.followStore(this.followQuery);
      if (!this.followBusy) window.setTimeout(() => { void this.rerank(); }, 0);
    }
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
      // A page the reader folded by right-click is never drawn from a
      // placement, even the page being browsed (`collapsedByReader`): its
      // chunks stay in the page node until an explicit expand.
      const open = (u: string) => !!u && !this.readerCollapsed(u) && (openNow.has(u) || this.openedByReader.has(u)
        || (!!browsing && u.split("#")[0] === browsing.split("#")[0]));
      const t = Date.now();
      incoming = incoming.filter((n) => {
        if ((n.level ?? "chunk") === "page") return true;
        // A search's results are drawn whatever page they are on (item 87).
        if (opts.keep && n.cid && opts.keep.has(n.cid)) return true;
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
        // A RENAMED chunk (the central diff: same content, shifted address)
        // starts where the node it replaces stood and glides to its fit.
        const carried = this.renamedFrom.get(node.cid);
        if (carried) {
          this.renamedFrom.delete(node.cid);
          if (node.level !== "page" && Date.now() - carried.t < 60000) {
            built.__glideTo = [built.x, built.y, built.z];
            [built.x, built.y, built.z] = carried.at;
          }
        }
        arrived.push(built);
        byId.set(node.cid, built);
        out.added++;
      }
    }
    // A new array, never pushed in place (D-38; see `addEdges`).
    if (arrived.length) data.nodes = data.nodes.concat(arrived);
    for (const n of arrived) {
      if (n.__glideTo) {
        const to = n.__glideTo;
        delete n.__glideTo;
        this.glide(n, to);
        this.diffStats.carried++;
      }
    }
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
    // The STORED stage reached the 3D view for each page whose stored chunks
    // just joined the drawn graph (item 91). Marked here, where they arrive --
    // a capture's reply carries no placed nodes any more (the projector places
    // them later), so a trace watching the reply ended "nothing placed" 287
    // times of 300. Provenance: the page's latest drain trace, its sidecar phases.
    const storedUrls = new Set<string>();
    for (const n of arrived) if (n && !n.force && n.level !== "page" && n.url) storedUrls.add(n.url);
    // The browsed page's panels prefetched, so a hover paints from memory
    // (2026-10-11, item 91: of 169 ms hover-to-panel at the stored stage, ~110
    // were this fetch).
    const browsing = this.browsingUrl ? this.browsingUrl().split("#")[0] : "";
    for (const u of storedUrls) if (u.split("#")[0] === browsing) this.prefetchPayloads(u);
    for (const u of storedUrls) {
      const tr = prof.lastFor(u);
      prof.mark(u, "stored", { nodes: arrived.filter((n: any) => n.url === u).length, trace: tr ? tr.id : null,
                               capture: tr ? tr.stages.capture : null, sidecar_total: tr ? tr.stages["sidecar.total"] : null,
                               transport: tr ? tr.stages.transport : null });
    }
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
      //: Where chunk view drew it last, kept on the chunk in the store
      //: (PLUGIN_GOAL 108) -- present only while the fit is unchanged.
      drawnAt: Array.isArray((n as any).drawn)
        ? [(n as any).drawn[0], (n as any).drawn[1], ((n as any).drawn[2] ?? 0) * DEPTH] : undefined,
      drawnHalf: (n as any).drawn_half,
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
    // The search field lives on the canvas too (item 84): put back.
    if (this.searchField) canvas.appendChild(this.searchField.el);
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
      // Black, opaque (2026-10-17: "ensure the background is also black and
      // not grey"): the glowing chunks read as points of light on it.
      .backgroundColor(this.plantGreyBackground ? "rgba(0,0,0,0)" : "#000000")
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
          // A ROOT toggles its whole tree (G-95, Addendum IX: "When the roots
          // are clicked, all nodes expand ... When the roots that are
          // uncollapsed are clicked again, all the chunks for that page
          // collapse back"): every stored chunk of the page at its UMAP
          // place, or all folded back. The step-wise unfold (160 nodes,
          // three levels) stays for branch nodes. Planted: as before.
          if (n.level === "page" && !this.plantUnfoldOnClick) void this.togglePage(n);
          else void this.unfoldNode(n);
          return;
        }
        if (n.url) void this.revealChunk(n);
        // `G-57`: the panel opens HERE, beside the node, rather than taking
        // over an Obsidian pane. The pane remains what the structures look
        // like offline (`G-59`); it is no longer what a click in the
        // projector reaches for.
        void this.openBillboard(n);
      })
      // Right-click on a PAGE node toggles its chunks: folded into the node
      // when drawn, the whole stored set at its UMAP positions when not
      // (`togglePage`). Anywhere else it releases the scope (`G-70`): back
      // to the corpus, from wherever the reader had narrowed to.
      .onNodeRightClick((n: any) => {
        // Right-click mode (G-196): a chunk's right-click opens its panel; a
        // page's still folds or unfolds it.
        if (this.panelsOn === "rightclick" && n && n.level !== "page" && n.level !== "path" && n.url) {
          this.panelModeStats.right_opened++;
          void this.openBillboard(n);
          return;
        }
        void this.togglePage(n);
      });

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
    // A proxy is placed, and its matrix composed, when the layout moves it --
    // its `matrixAutoUpdate` is off (`pickProxy`). Raycasting reads the matrix.
    graph.nodePositionUpdate((obj: any, c: any) => {
      if (this.plantPerNode || !obj?.__proxy || obj.matrixAutoUpdate) return false;
      obj.position.set(c.x, c.y || 0, c.z || 0);
      obj.updateMatrix();
      if (!this.plantProxyWorldPass) {
        if (obj.parent) obj.matrixWorld.multiplyMatrices(obj.parent.matrixWorld, obj.matrix);
        else obj.matrixWorld.copy(obj.matrix);
      }
      return true;
    });

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
      // Only what can MOVE, and what it can touch (2026-10-11: "really slow
      // ... the same feature set with significant speedups"). Collision moves
      // free nodes only -- a pinned node's velocity is discarded -- so a pass
      // over 23k nodes to move the forty a placement freed was 2.3 s of every
      // 11. The scope is the free nodes plus every node within reach of them:
      // a box around the free set grown by the largest two radii that can
      // meet. Pairs outside it are pinned pairs, which cannot move each other,
      // so the result is the same pass. Planted: the whole graph, as before.
      const scope = this.plantFullCollide ? gatedNodes : this.collideScope(gatedNodes, collideForce, maxRadius);
      if (!scope.length) { this.collideStats.idle++; return; }
      if (scope !== scopeNodes) { collideForce.initialize(scope, ...initArgs); scopeNodes = scope; }
      this.collideStats.passes++; this.collideStats.scoped += scope.length; this.collideStats.whole += gatedNodes.length;
      for (let k = 0; k < collideIterations; k++) {
        if (!this.octreeOk(scope, "collide", true)) { this.sanitize(scope); break; }
        collideForce(alpha);
      }
    };
    let initArgs: any[] = [];
    let scopeNodes: any[] | null = null;
    let maxRadius = 0;
    gated.initialize = (...a: any[]) => {
      gatedNodes = a[0] || []; initArgs = a.slice(1); scopeNodes = gatedNodes;
      const r = collideForce.initialize(...a);
      const radius = collideForce.radius();
      maxRadius = 0;
      for (const n of gatedNodes) { const v = +radius(n) || 0; if (v > maxRadius) maxRadius = v; }
      return r;
    };
    gated.radius = (...a: any[]) => { const r = collideForce.radius(...a); return a.length ? gated : r; };
    gated.strength = (...a: any[]) => { const r = collideForce.strength(...a); return a.length ? gated : r; };
    gated.iterations = (...a: any[]) => {
      if (!a.length) return collideIterations;
      collideIterations = Math.max(1, Math.floor(+a[0] || 1));
      return gated;
    };
    this.collideUntil = performance.now() + 3000;
    graph.d3Force("collide", gated);
    // **Chunk view is UMAP alone** (2026-10-11: "i dont think the chunk view
    // needs force-directed, might also slow things down and we can rely on
    // UMAP only for this view"). Every force goes but the link force, held at
    // strength 0 -- it is what resolves an edge's ids to the nodes the batch
    // draws it between -- and every node is pinned at its fit, so the engine
    // has nothing to integrate and stops on its first cool tick. The pages
    // view gets its forces back on the next load (`draw` builds anew).
    // Planted: the pages view's forces in chunk view, as before.
    if (this.level === "chunk" && !this.plantChunkForces) {
      for (const name of ["charge", "center", "home", "contain", "collide", "hold", "treeSpring"]) graph.d3Force(name, null);
      graph.d3Force("link")?.strength(0);
      // Nothing to integrate: two ticks put each proxy where its node is.
      graph.cooldownTicks(2);
      for (const n of graph.graphData().nodes as any[]) {
        if (!Number.isFinite(n.fitX)) continue;
        // The stored drawn place first (PLUGIN_GOAL 108): the switch shows
        // where the reader last saw the chunk, not the fit before relaxing.
        const d = !this.plantNoDrawn && n.drawnAt;
        if (d) { n.x = n.fx = d[0]; n.y = n.fy = d[1]; n.z = n.fz = d[2]; }
        else { n.x = n.fx = n.fitX; n.y = n.fy = n.fitY; n.z = n.fz = n.fitZ ?? 0; }
      }
      this.umapOnly = true;
      // After the spacing pass, never before it: the relax spaces nodes at
      // chunk view's one size, which is the median of the SPACED sizes -- a
      // relax at 400 ms ran on the load's unspaced `val` (every chunk 1) and
      // stored places spaced for orbs 14x too big (2026-10-12). The engine's
      // stop runs the spacing; a fallback covers an engine that never stops.
      this.relaxAfterSpacing = true;
      window.setTimeout(() => { if (this.relaxAfterSpacing) { this.relaxAfterSpacing = false; this.relaxChunkView(); } }, 3000);
    } else {
      this.umapOnly = false;
      graph.cooldownTicks(Infinity);
    }
    window.setTimeout(() => this.watchForces(), 0);

    // It has to be allowed to run, having been frozen. These are d3's own
    // defaults: the simulation cools over a few hundred ticks and stops.
    //
    // And it has to STOP. 3d-force-graph's `d3AlphaMin` defaults to 0, so the
    // engine ran out its whole 15 s `cooldownTime` after every reheat -- and
    // every click's `dragend` restarts that countdown without heating
    // anything, so one click on a node bought 15 s of ticks over all 23k
    // nodes (2026-10-11: "immediate lag after clicking a node. perhaps
    // force-directed has something to do with it"). d3's own `alphaMin`: a
    // cool simulation stops on the next tick, a click on a still graph costs
    // one. Planted: the old floor of 0.
    graph.d3AlphaDecay(0.0228).d3VelocityDecay(0.4).d3AlphaMin(this.plantNoAlphaMin ? 0 : 0.001);

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
    // The search field over the canvas (item 84): `ForceGraph3D(canvas)` empties
    // its element, so the field is put back AFTER the graph is built.
    if (this.searchField && !canvas.contains(this.searchField.el)) canvas.appendChild(this.searchField.el);
    this.calmFrom = performance.now() + 6000;
    graph.onEngineTick(() => { this.batchDirty = true; this.govern(); });
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
      if (this.relaxAfterSpacing && this.level === "chunk") {
        this.relaxAfterSpacing = false;
        this.unitValAt.at = 0;
        window.setTimeout(() => this.relaxChunkView(), 50);
      }
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
        const c = centre();
        const z = c.z + frameDistance(c);
        graph.cameraPosition({ x: c.x, y: c.y, z }, c, 0);
        placed = { x: c.x, y: c.y, z };
        this.fullViewDist = z - c.z;
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
    // **Where the cloud IS, not where the origin is (item 116).** Every
    // framing below aimed at (0,0,0) and measured the cloud's reach from it,
    // which frames a cloud off the origin -- a fresh store with a page or
    // two is the extreme -- as a corner of an empty frame. The camera moves
    // to the cloud; the cloud is never moved to the camera, because its
    // places are the map (stored `drawn` places, pins, anchors).
    const centre = (): { x: number; y: number; z: number } => {
      const pts = graph.graphData().nodes as any[];
      if (this.plantOriginFrame || !pts.length) return { x: 0, y: 0, z: 0 };
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      for (const p of pts) {
        const v = [p.x, p.y, p.z];
        for (let i = 0; i < 3; i++) {
          if (!Number.isFinite(v[i])) continue;
          if (v[i] < lo[i]) lo[i] = v[i];
          if (v[i] > hi[i]) hi[i] = v[i];
        }
      }
      const mid = (i: number) => (lo[i] <= hi[i] ? (lo[i] + hi[i]) / 2 : 0);
      return { x: mid(0), y: mid(1), z: mid(2) };
    };
    const frameDistance = (c = centre()) => {
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
        mx = Math.max(mx, Math.abs((p.x ?? 0) - c.x));
        my = Math.max(my, Math.abs((p.y ?? 0) - c.y));
        mz = Math.max(mz, Math.abs((p.z ?? 0) - c.z));
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
    const screenCoverage = (): { w: number; h: number; dx: number; dy: number } | null => {
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
      // `dx`/`dy`: how far the picture's middle sits from the pane's, as a
      // fraction of the pane -- 0 is centred, 0.5 is the middle on an edge.
      return { w: (maxX - minX) / W, h: (maxY - minY) / H,
               dx: (minX + maxX) / 2 / W - 0.5, dy: (minY + maxY) / 2 / H - 0.5 };
    };
    this.screenCoverage = screenCoverage;

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
        const c = centre();
        const d = Math.hypot((cam.x ?? 0) - c.x, (cam.y ?? 0) - c.y, (cam.z ?? 0) - c.z);
        if (!(d > 0)) return;
        // Screen span goes as 1/d, so scaling the distance by the shortfall
        // is the step that lands on target.
        let next = d * Math.min(1.6, Math.max(0.55, ratio));
        // **Never inside the cloud.** This is the guard the previous attempt
        // at this did not have, and it is why the pane went empty.
        const pts = g.graphData().nodes as any[];
        let frontmost = 0;
        for (const n of pts) frontmost = Math.max(frontmost, (n.z ?? 0) - c.z);
        const floor = frontmost + Math.max(20, frontmost * 0.15);
        if (next < floor) next = floor;
        g.cameraPosition({ x: c.x, y: c.y, z: c.z + next }, c, 0);
        this.fullViewDist = next;
      }
    };

    // A refit comes back where the reader was looking (G-194), registered by
    // the url nodes; a first draw, or no usable registration, frames anew.
    window.setTimeout(() => {
      const at = this.registeredPose();
      if (at) { placed = at; return; }
      place(); window.setTimeout(tighten, 120);
    }, 250);

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
      const c = centre();
      this.fullViewDist = frameDistance(c);
      graph.cameraPosition({ x: c.x, y: c.y, z: c.z + this.fullViewDist }, c, 400);
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
