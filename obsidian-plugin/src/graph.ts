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
      data.nodes.push(built);
      opened.push(built);
    }
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
         edges?: { source: string; target: string }[]):
      { added: number; moved: number; edges: number } {
    const out = { added: 0, moved: 0, edges: 0 };
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
    // **The trie's own edges, which were computed and then dropped.**
    //
    // `place_into` returns the containment edges among what it placed --
    // `G-6` -- and the pane's callback chain passed only the nodes, so a
    // live capture drew its chunks as loose dots. Measured before this:
    // 921 nodes, 84 links, and of 793 chunk nodes exactly 16 had an edge of
    // any kind. A patricia trie that is not drawn has no structure for a
    // force to act on, which is most of why the picture reads as a clump.
    out.edges = this.addEdges(data, edges);
    this.graph.graphData(data);
    void this.drawContainment();
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
      //: The territory this node must stay inside, and the point it is
      //: measured from (`D-27`). Present only on what an unfolding
      //: produced; a page node owns the whole cloud and is bounded by
      //: nothing. `containWithin` is what enforces it.
      room: (n as any).room,
      anchorPos: (n as any).anchor,
      rank: n.rank,
      tokens: n.tokens ?? 0,
      image: n.image,
      color: colourOf(n),
    };
  }

  private draw(canvas: HTMLElement, layout: Layout) {
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
      const k = alpha * 0.55;
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
      window.setTimeout(() => tighten(), 450);
    };
  }
}
