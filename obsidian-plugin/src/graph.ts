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

import { ItemView, WorkspaceLeaf } from "obsidian";
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

    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin("anonymous");
    loader.load(
      src,
      (texture: any) => {
        material.map = texture;
        // White once a picture is on it: the colour was standing in for the
        // image, and leaving it would tint every photograph.
        material.color = new THREE.Color(0xffffff);
        material.needsUpdate = true;
      },
      undefined,
      () => {
        // Left as the coloured tile it already is, and said in the console
        // rather than silently: a graph of blank tiles and a graph whose
        // asset host is refusing look identical from the pane.
        console.warn("domvec: image did not load", src);
      },
    );
    return sprite;
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
      fx: n.pos[0] * 40,
      fy: n.pos[1] * 40,
      fz: (n.pos[2] ?? 0) * 40,
      val: Math.max(1, Math.sqrt(n.chars)),
      rank: n.rank,
      tokens: n.tokens ?? 0,
      image: n.image,
      color: colourOf(n),
    }));

    const graph = new ForceGraph3D(canvas)
      .graphData({ nodes, links: layout.edges.map((e) => ({ ...e })) })
      .nodeLabel((n: any) => `${n.name}<br><small>${n.url}</small>`)
      .nodeColor((n: any) => n.color)
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
  }
}
