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

import { ItemView, Notice, WorkspaceLeaf } from "obsidian";
import ForceGraph3D, { ForceGraph3DInstance } from "3d-force-graph";

import { Sidecar } from "./sidecar";

export const GRAPH_VIEW = "domvec-graph-view";

interface LayoutNode {
  cid: string;
  url: string;
  title: string;
  rank: number;
  chars: number;
  pos: number[];
}

interface Layout {
  nodes: LayoutNode[];
  edges: { source: string; target: string }[];
  spaces: string[];
  n: number;
  halves: { lexical?: number; semantic?: number; equalised: boolean };
  note?: string;
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
              onPick: (cid: string) => void) {
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
      status.setText(
        `${layout.n} chunks · ${layout.spaces.join(" + ")} · ${halves}`);
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
      color: hue(n.url),
    }));

    const graph = new ForceGraph3D(canvas)
      .graphData({ nodes, links: layout.edges.map((e) => ({ ...e })) })
      .nodeLabel((n: any) => `${n.name}<br><small>${n.url}</small>`)
      .nodeColor((n: any) => n.color)
      .nodeVal((n: any) => n.val)
      .linkOpacity(0.25)
      .linkWidth(0.5)
      .backgroundColor("rgba(0,0,0,0)")
      .onNodeClick((n: any) => {
        this.onPick(n.id);
        new Notice(`${n.name}\n${n.url}`);
      });

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
