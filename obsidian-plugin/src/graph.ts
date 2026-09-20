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

import { ItemView, WorkspaceLeaf, requestUrl } from "obsidian";
import ForceGraph3D, { ForceGraph3DInstance } from "3d-force-graph";
// `d3-force-3d` is what `3d-force-graph` runs its simulation on, so this is
// the same module instance the graph already uses -- not a second copy whose
// forces the graph would ignore.
import { forceCollide } from "d3-force-3d";
import * as THREE from "three";

import { Sidecar } from "./sidecar";

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
 * Clearance beyond the drawn sphere, as a fraction of its radius (`G-21`).
 *
 * "a quarter distance safety factor". A collider exactly the size of the
 * sphere lets two nodes rest in contact, which draws as a single shape; the
 * margin keeps a visible gap between things the projection calls distinct.
 */
const COLLIDER_SAFETY = 1.25;

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
  /**
   * Fetched pictures, shared across every instance of the view.
   *
   * Many nodes of one site point at the same avatar or logo, and reopening
   * the pane refits and rebuilds every sprite. Without this, closing and
   * reopening the graph re-downloads the corpus's images.
   */
  private static textures = new Map<string, string | null>();
  private graph: ForceGraph3DInstance | null = null;
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
  private onPick: (cid: string) => void;
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
              onPick: (cid: string) => void,
              private media: () => boolean) {
    super(leaf);
    this.onPick = onPick;
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
      status.setText("fitting…");
      const asked = this.space;
      const asking = this.level;
      const layout = (await this.sidecar.layout(3, asked, asking)) as
        Layout | null;
      if (!layout) {
        status.setText("no sidecar — start it to see the graph");
        return;
      }
      if (!layout.nodes.length) {
        status.setText(layout.note || "nothing to place yet");
        return;
      }
      this.draw(canvas, layout);
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
      this.captionTail =
        `${(layout.spaces ?? []).join(" + ")} · ${fit} · ${colour}${pictures}`;
      status.setText(`${unit} · ${this.captionTail}`);
      } catch (err) {
        // Say the count, which is the one thing a reader needs to know the
        // pane is alive, and name the failure rather than swallowing it.
        status.setText(`${layout.nodes.length} nodes · caption failed: ` +
                       `${err instanceof Error ? err.message : String(err)}`);
      }
    };

    again.onclick = () => load();
    await load();
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
    this.statusEl.setText(`${parts.join(" · ")} · ${this.captionTail}`);
  }

  private addEdges(data: any, edges?: { source: string; target: string }[]) {
    if (!edges || !edges.length) return 0;
    const byId = new Map<string, any>(data.nodes.map((n: any) => [n.id, n]));
    const have = new Set(data.links.map(
      (l: any) => `${l.source?.id ?? l.source} ${l.target?.id ?? l.target}`));
    let added = 0;
    for (const edge of edges) {
      const source = byId.get(edge.source);
      const target = byId.get(edge.target);
      if (!source || !target || source === target) continue;
      const key = `${edge.source} ${edge.target}`;
      if (have.has(key)) continue;
      have.add(key);
      data.links.push({ source, target });
      added++;
    }
    return added;
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
    for (const node of nodes) {
      if (!node || !node.cid || have.has(node.cid)) continue;
      fresh.nodes.push(this.nodeFrom(node));
      drawn.push(node.cid);
    }
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
  async openBillboard(node: any): Promise<void> {
    if (!node || !node.id || !this.graph) return;
    const existing = this.billboards.get(node.id);
    if (existing) {                       // a second click closes it
      existing.el.remove();
      this.billboards.delete(node.id);
      this.stopBillboardLoop();
      return;
    }
    if (!this.billboardLayer) {
      const host = this.canvasEl || this.contentEl;
      this.billboardLayer = host.createDiv({ cls: "domvec-bb-layer" });
    }
    const el = this.billboardLayer.createDiv({ cls: "domvec-bb" });
    const head = el.createDiv({ cls: "domvec-bb-head" });
    head.setText(String(node.name || node.id).slice(0, 44));
    const close = head.createSpan({ cls: "domvec-bb-close" });
    close.setText("\u00d7");
    close.onclick = (e: MouseEvent) => {
      e.stopPropagation();
      el.remove();
      this.billboards.delete(node.id);
      this.stopBillboardLoop();
    };
    const body = el.createDiv({ cls: "domvec-bb-body" });
    body.setText("\u2026");

    const entry = { el, node, pinned: false };
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

    // The content, from the store -- the same panel, in a different place.
    const got = await this.sidecar.chunk(node.id);
    const lines = (got && (got.lines as { text: string }[])) || [];
    body.empty();
    if (!lines.length) {
      body.setText(node.level === "page" || node.level === "path"
        ? "a page stands for its chunks -- click to unravel it"
        : "no panel for this node");
      return;
    }
    for (const line of lines.slice(0, 40)) {
      body.createDiv({ cls: "domvec-bb-line" }).setText(line.text);
    }
    if (lines.length > 40) {
      body.createDiv({ cls: "domvec-bb-more" })
        .setText(`\u2026 ${lines.length - 40} more lines`);
    }
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

  private async unfoldNode(node: any): Promise<void> {
    if (!this.graph || !node || !node.url) return;
    const got = await this.sidecar.unfold(node.url, node.path || "", this.space);
    const nodes = (got && (got.nodes as LayoutNode[])) || [];
    if (!nodes.length) return;

    const data: any = this.graph.graphData();
    const hub = data.nodes.find((n: any) => n.id === node.id);
    const known = new Set(data.nodes.map((n: any) => n.id));
    const opened: any[] = [];
    for (const incoming of nodes) {
      if (!incoming || !incoming.cid || known.has(incoming.cid)) continue;
      const built = this.nodeFrom(incoming);
      data.nodes.push(built);
      opened.push(built);
    }
    // An opened container is subordinate to what it opened into. A page node
    // is sized by the chunks it stands for, so RFC 9110 arrived at `members`
    // 1,173 and drew as a sphere that swallowed all 26 of its own branches.
    // Once it is open it no longer stands for them -- they are on screen --
    // so it shrinks to the smallest thing it revealed and becomes a hub
    // rather than a lid.
    if (hub) {
      hub.unfolded = true;
      if (hub.valFull === undefined) hub.valFull = hub.val;
      const smallest = opened.reduce(
        (m: number, n: any) => Math.min(m, n.val ?? 1), Infinity);
      hub.val = Number.isFinite(smallest) ? Math.max(smallest, 1) : 1;
      // Its picture goes with its size: a billboard is drawn at the panel
      // edge, not at `val`, so leaving the image would leave the lid.
      delete hub.image;
    }
    this.addEdges(data, got?.edges);
    this.graph.graphData(data);
    this.graph.d3ReheatSimulation();
    this.sayCounts();
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
  absorb(incoming: LayoutNode[]): { added: number; moved: number } {
    const out = { added: 0, moved: 0 };
    if (!this.graph || !incoming || !incoming.length) return out;
    const data: any = this.graph.graphData();
    const byId = new Map<string, any>(data.nodes.map((n: any) => [n.id, n]));

    for (const node of incoming) {
      if (!node || !node.cid || !node.pos) continue;
      const built = this.nodeFrom(node);
      const existing = byId.get(node.cid);
      if (existing) {
        // Fields the render reads, and the fit's own coordinates. `x/y/z` is
        // set too: the simulation owns those, but a chunk whose meaning moved
        // should not be left drawing at its old meaning's address.
        Object.assign(existing, {
          name: built.name, url: built.url, val: built.val,
          tokens: built.tokens, image: built.image, color: built.color,
          fitX: built.fitX, fitY: built.fitY, fitZ: built.fitZ,
          x: built.x, y: built.y, z: built.z,
        });
        out.moved++;
      } else {
        data.nodes.push(built);
        byId.set(node.cid, built);
        out.added++;
      }
    }
    if (!out.added && !out.moved) return out;
    // The links array is handed back unchanged. `forceLink` resolved its
    // endpoints in place at boot, so rebuilding it here would hand d3 a list
    // of node OBJECTS where it expects to re-resolve, and the edges would
    // stop drawing -- which is exactly the failure that removing the link
    // force caused.
    this.graph.graphData(data);
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
      z: n.pos[2] ?? 0,
      //: Where the FIT put this node, kept so drift off the embedding can be
      //: measured rather than assumed. Nothing reads it to draw.
      fitX: n.pos[0],
      fitY: n.pos[1],
      fitZ: n.pos[2] ?? 0,
      // The payload's own `val` when it has one, because a page node's size
      // is its CHUNK COUNT and it has no characters of its own. Deriving it
      // from `chars` gave every one of 96 pages the same radius -- a
      // 1,173-chunk reference index drawn as the same dot as a one-chunk
      // stub -- and the `val` the layout computed was simply discarded here.
      val: n.val ?? Math.max(1, Math.sqrt(n.chars)),
      rank: n.rank,
      tokens: n.tokens ?? 0,
      image: n.image,
      color: colourOf(n),
    };
  }

  private draw(canvas: HTMLElement, layout: Layout) {
    canvas.empty();
    const nodes = layout.nodes.map((n) => this.nodeFrom(n));

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
    const relSize = measured > 0
      ? Math.max(0.05, measured / 6)
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
    if (media) graph.nodeThreeObject((n: any) => this.billboard(n, relSize));

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
    graph.d3Force("link")?.strength(0);
    graph.d3Force("collide", forceCollide()
      // `G-21`: the drawn radius, plus a quarter of it as clearance. A
      // collider exactly the size of the sphere lets two nodes rest touching,
      // which reads as one shape; the margin makes a gap a reader can see
      // between things the projection says are distinct.
      .radius((n: any) => drawnRadius(n, relSize, media) * COLLIDER_SAFETY)
      // Soft and iterated rather than hard and once. `d3-force-3d` documents
      // collision as "by default a soft constraint with a configurable
      // strength and iteration count" to reduce jitter; a hard shove would
      // trade overlap for nodes visibly vibrating against each other.
      .strength(0.7)
      .iterations(2));

    // It has to be allowed to run, having been frozen. These are d3's own
    // defaults: the simulation cools over a few hundred ticks and stops.
    graph.d3AlphaDecay(0.0228).d3VelocityDecay(0.4);
    this.graph = graph;

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
      // **Per NODE, not per axis.**
      //
      // This took `max|x|`, `max|y|` and `max|z|` independently and framed
      // their combination -- the worst case of three nodes that need not be
      // the same node, and usually are not. Then it added the whole depth
      // `mz` on top, pushing the camera back by the cloud's full thickness
      // as though the widest node were also the nearest one.
      //
      // For a roughly round cloud of radius R that lands at about 3.5R when
      // 2.1R would do, and the picture shrinks by the square of the error:
      // measured through the harness, the cloud occupied **23.8% of the
      // canvas** at page level with more than half its nodes overlapping,
      // which is the "clump" the requirement forbids and the checks could
      // not see.
      //
      // The exact condition is per node: a point at (x, y, z) seen from
      // (0, 0, d) is inside when `|x| <= (d - z)·tan(h/2)`, so it needs
      // `d >= z + |x|/tan(h/2)`, and the camera must satisfy the largest
      // such demand. Using each node's OWN z is what stops a deep cloud
      // paying twice for its depth.
      const th = Math.tan(usable ? hfov / 2 : vfov / 2);
      const tv = Math.tan(vfov / 2);
      let need = 0;
      for (const p of pts) {
        const x = Math.abs(p.x ?? 0), y = Math.abs(p.y ?? 0), z = p.z ?? 0;
        need = Math.max(need, z + x / th, z + y / tv);
      }
      if (!(need > 0)) need = Math.max(mx / th, my / tv) + mz;
      // 1.06 leaves a margin so the outermost nodes are not clipped by their
      // own radius, which this calculation deliberately does not know about.
      // It was 1.12 on top of a distance already too large by half.
      return need * 1.06;
    };

    window.setTimeout(place, 250);

    // The same thing, on demand. A reader who has orbited into the middle of
    // the cloud has no way back otherwise, and "the graph went blank" is not
    // a state anyone should have to recognise.
    this.reframe = () => {
      placed = null;              // an explicit reframe is always wanted
      graph.cameraPosition({ x: 0, y: 0, z: frameDistance() },
                           { x: 0, y: 0, z: 0 }, 400);
    };
  }
}
