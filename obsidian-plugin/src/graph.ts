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
import * as THREE from "three";

import { Sidecar } from "./sidecar";

export const GRAPH_VIEW = "domvec-graph-view";

interface LayoutNode {
  cid: string;
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
  halves: { lexical?: number; semantic?: number; equalised: boolean };
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
  private onPick: (cid: string) => void;

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

    const canvas = root.createDiv({ cls: "domvec-graph-canvas" });

    const load = async () => {
      status.setText("fitting…");
      const layout = (await this.sidecar.layout()) as Layout | null;
      if (!layout) {
        status.setText("no sidecar — start it to see the graph");
        return;
      }
      if (!layout.nodes.length) {
        status.setText(layout.note || "nothing to place yet");
        return;
      }
      this.draw(canvas, layout);
      // The spaces are named on the bar rather than left implicit. A layout
      // fitted on frequency alone and one fitted on both are different
      // pictures, and a reader who cannot tell them apart will read a lexical
      // clustering as a semantic one.
      const halves = layout.halves.equalised
        ? `equal halves of ${layout.halves.lexical}`
        : "not equalised";
      // `fitted_dims`, not an assumption: a viewer colouring by hue is
      // showing three more dimensions of the projection, and one falling back
      // to a per-host palette is showing a legend. The two look identical
      // from the pane, so the pane says which it is.
      const colour = layout.hsv
        ? `${layout.fitted_dims ?? 6}D · colour from the fit`
        : "3D · colour by host";
      const pictures = layout.images
        ? ` · ${layout.images} with a picture` : "";
      status.setText(
        `${layout.n} chunks · ${layout.spaces.join(" + ")} · ${halves} · ` +
        `${colour}${pictures}`);
    };

    again.onclick = () => load();
    await load();
  }

  async onClose() {
    // `_destructor` releases the WebGL context. Without it, reopening the
    // pane a few times exhausts the browser's context limit and every graph
    // after that renders black.
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
  private billboard(node: any): any {
    const src = node?.image?.src;
    if (!src) return null;
    const material = new THREE.SpriteMaterial({
      color: new THREE.Color(node.color || "#888"),
      transparent: true,
      opacity: 0.95,
    });
    const sprite = new THREE.Sprite(material);
    const size = Math.max(6, Math.min(18, Math.sqrt(node.val) * 4));
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

  private draw(canvas: HTMLElement, layout: Layout) {
    canvas.empty();
    const nodes = layout.nodes.map((n) => ({
      id: n.cid,
      name: n.title || n.url,
      url: n.url,
      // The fitted position, held fixed. `fx/fy/fz` pin a node where the
      // projection put it: running the force simulation on top would drift
      // the points off the embedding and quietly turn a UMAP of two vector
      // spaces into a spring layout that happened to start there.
      //
      // Used as delivered. This multiplied by 40, which was a constant chosen
      // when the coordinates were whatever UMAP happened to emit -- so the
      // world size of the cloud moved with the corpus. `layout.py` centres
      // and scales to a known cube now, and a second scale here would only
      // put the guesswork back.
      fx: n.pos[0],
      fy: n.pos[1],
      fz: n.pos[2] ?? 0,
      val: Math.max(1, Math.sqrt(n.chars)),
      rank: n.rank,
      tokens: n.tokens ?? 0,
      image: n.image,
      color: colourOf(n),
    }));

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
      .nodeLabel((n: any) => `${n.name}<br><small>${n.url}</small>`)
      .nodeColor((n: any) => n.color)
      .nodeRelSize(relSize)
      .nodeVal((n: any) => n.val)
      .linkOpacity(0.25)
      .linkWidth(0.5)
      .backgroundColor("rgba(0,0,0,0)")
      .onNodeClick((n: any) => this.onPick(n.id));

    // A chunk that showed a picture looks like the thing it showed.
    //
    // Only when the reader has remote media on, and for the reason the
    // surface asks: fetching a page's assets from a vault tells those
    // hosts the page was read again, at a new time, from a new address.
    // A graph that quietly fetched a few hundred images the moment it
    // opened would be the loudest version of that.
    if (this.media()) graph.nodeThreeObject((n: any) => this.billboard(n));

    // Cooling the simulation immediately: the coordinates are already the
    // answer, and the only job left is layout of the camera.
    graph.d3AlphaDecay(1).d3VelocityDecay(1);
    this.graph = graph;

    const fit = () => graph.width(canvas.clientWidth)
                           .height(canvas.clientHeight);
    fit();
    this.registerEvent(this.app.workspace.on("resize", fit));

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
      let r = 0;
      for (const p of pts) {
        const d = Math.hypot(p.x ?? 0, p.y ?? 0, p.z ?? 0);
        if (d > r) r = d;
      }
      if (!(r > 0)) r = extent;
      const cam: any = graph.camera();
      const vfov = ((cam?.fov ?? 50) * Math.PI) / 180;
      const aspect = Math.max(0.01, canvas.clientWidth / Math.max(1, canvas.clientHeight));
      const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
      const half = Math.max(0.01, Math.min(vfov, hfov) / 2);
      // 1.12 leaves a margin so the outermost nodes are not clipped by their
      // own radius, which this calculation deliberately does not know about.
      return (r / Math.sin(half)) * 1.12;
    };

    window.setTimeout(() => {
      try {
        graph.cameraPosition({ x: 0, y: 0, z: frameDistance() },
                             { x: 0, y: 0, z: 0 }, 0);
      } catch {
        /* an empty scene has nothing to fit; the status bar already says so */
      }
    }, 250);

    // The same thing, on demand. A reader who has orbited into the middle of
    // the cloud has no way back otherwise, and "the graph went blank" is not
    // a state anyone should have to recognise.
    this.reframe = () => {
      graph.cameraPosition({ x: 0, y: 0, z: frameDistance() },
                           { x: 0, y: 0, z: 0 }, 400);
    };
  }
}
