/**
 * The CRAFT: the ego computation graph as ONE unit in 3D (PLUGIN_GOAL 67-69,
 * 2026-11-01: "the full ego computation graph as one unit, its own graph
 * separate from the red of the UMAPped components, all interconnected in 3D
 * ... this being where our "cockpit" view really comes in"; 2026-10-29:
 * "something like kerbal space program, where we can see from both first
 * person view within a "cockpit" as well as a 3rd person view, but for a
 * "craft" that is where our 3D computation graphs ... comes in").
 *
 * What it holds (RESERVOIR_DESIGN 5a): every computation-graph artifact in
 * the vault -- the cockpit (`ego`, the craft's root: the controls "collapsed
 * within the "ego" 2D node which corresponds to the cockpit"), each slate,
 * each notebook (a note holding a python cell) with its code cells and its
 * markdown trees (G-297: the extended markdown cell). One record per
 * artifact, fused: a slate IS its tree, the cockpit IS the ego node.
 *
 * How it is linked, "all interconnected": a note contains its trees and
 * cells; they run in document order in the note's one kernel (`order`); a
 * `{ref}` naming another artifact is an edge to it; every note hangs from
 * `ego`. Its I/O are its links into the world (item 69): a run's recorded
 * inputs, chunks of the UMAP world, wired to the cell's note -- never the
 * craft's nodes dissolved into the world.
 *
 * Where it is: its own frame, not the fit's. Third person (the map view),
 * the craft stands where the agent last flew, outside the fit's placement; a
 * note's bearing from the ego node is its UMAP bearing in the world (item 43:
 * "UMAP happens on the ego reservoir"), so the craft is a miniature of the
 * directions its artifacts point in. First person (the ego view), the camera
 * IS the craft -- the reader is in the cockpit, the panels on the 2D plane
 * are its inside, and the 3D craft is not drawn around the camera.
 *
 * Gestures: a click on a craft node opens its panel on the plane (a cell's
 * or tree's at its line), a click on a node whose panel is open closes it
 * back into the node; a node with an open panel is ringed (item 65: "2D
 * "sticked" panels and 3D nodes depending on selection and view").
 */
import * as THREE from "three";
import { App, TFile } from "obsidian";
import { findFences } from "./fences";
import { COCKPIT_PATH } from "./cockpit";
import { PLANE_FOLDER } from "./planepanels";

const PY = /^(python|py|python3)$/;

export type CraftKind = "ego" | "note" | "cell" | "tree" | "web" | "readout" | "code";
export interface CraftNode {
  id: string; kind: CraftKind; path: string; line: number; label: string;
  /** Where in the craft's own frame. */
  local: { x: number; y: number; z: number };
  mesh?: any;
}
export interface CraftEdge { a: string; b: string; kind: "root" | "contains" | "order" | "ref" | "forward" | "instance" | "module" }
export interface V3 { x: number; y: number; z: number }

export interface CraftHost {
  app: App;
  scene(): any;
  camera(): any;
  canvas(): HTMLElement | null;
  mode(): string;
  /** Where the agent's craft is: its last place flying, or null. */
  anchor(): V3 | null;
  /** The vehicle's heading, a unit vector (PLUGIN_GOAL 146): the craft's own
   *  UMAP turns with it -- non-holonomic, it points where it goes. */
  heading?(): V3 | null;
  /** The world's centre and outer radius (the fit's shell). */
  world(): { cx: number; cy: number; cz: number; r: number };
  /** A node of the WORLD graph by id (a chunk's cid, `page:<url>`). */
  worldNode(id: string): any;
  /** Each recorded run's input -> its cell note (G-292). */
  signalEdges(): { note: string; cid: string; url: string }[];
  isOpen(path: string): boolean;
  /** The note's text as its open panel holds it NOW -- a run's output is in
   *  the editor before autosave writes it (G-331) -- or null when not open. */
  liveText?(path: string): string | null;
  /** The ego set to the store: the craft's notes (items 74, 78). */
  postEgo?(urls: string[]): void;
  /** The web chunks the reader tagged into the ego (item 74b). */
  egoTags?(): Promise<string[]>;
  /** The ego's own projection (item 76): knowledge key -> place in the unit ball. */
  egoProjection?(): Promise<{ method: string; places: Record<string, number[]> } | null>;
  /** The code graph's most central modules and the edges among them (G-318). */
  codeNet?(): Promise<{ nodes: { name: string; url: string; rank: number }[]; edges: { a: string; b: string; n: number }[] } | null>;
  openPanel(path: string, line: number): void;
  closePanel(path: string): void;
}

const CRAFT_COLOUR = 0xa882ff;       // Obsidian's link purple: the variables' colour on the panels (item 55)
const CELL_COLOUR = 0xe8e8e8;
const IO_COLOUR = 0xffd27a;          // the signal's colour (G-292)
const LIT_MAT = new THREE.MeshBasicMaterial({ color: IO_COLOUR });
/** A signal in flight (G-331): bright, drawn over what it passes. */
const PULSE_MAT = new THREE.MeshBasicMaterial({ color: 0xfff1a8, transparent: true, opacity: 0.95, depthTest: false });

/** A unit direction for the k-th of n, spread evenly on the sphere. */
function fib(k: number, n: number): V3 {
  const y = 1 - (2 * (k + 0.5)) / Math.max(1, n);
  const r = Math.sqrt(Math.max(0, 1 - y * y));
  const t = k * Math.PI * (3 - Math.sqrt(5));
  return { x: Math.cos(t) * r, y, z: Math.sin(t) * r };
}
function norm(v: V3): V3 { const d = Math.hypot(v.x, v.y, v.z) || 1; return { x: v.x / d, y: v.y / d, z: v.z / d }; }

/** A note's markdown trees outside its fences: an unindented line followed by
 *  a tab-indented one (the slate grammar; `slate_module.trees_of`). */
function treesOf(text: string, fenced: Set<number>): { name: string; line: number; refs: string[] }[] {
  const lines = text.split("\n");
  const out: { name: string; line: number; refs: string[] }[] = [];
  let start = 0;
  if (lines[0] === "---") { const e = lines.indexOf("---", 1); if (e > 0) start = e + 1; }
  for (let i = start; i < lines.length - 1; i++) {
    const l = lines[i];
    if (fenced.has(i) || !l.trim() || /^\s/.test(l) || /^(#|>|-|\*|\d+\.|```|~~~|<!--)/.test(l)) continue;
    if (!/^\t\S/.test(lines[i + 1]) || fenced.has(i + 1)) continue;
    const name = l.trim().split(/\s+/)[0];
    const refs: string[] = [];
    let j = i + 1;
    for (; j < lines.length && (/^\t/.test(lines[j]) && !fenced.has(j)); j++) {
      for (const m of lines[j].matchAll(/\{([^{}\n]+)\}/g)) refs.push(m[1].trim());
    }
    out.push({ name, line: i, refs });
    i = j - 1;
  }
  return out;
}

export class Craft {
  nodes: CraftNode[] = [];
  edges: CraftEdge[] = [];
  stats = { builds: 0, notes: 0, cells: 0, trees: 0, web: 0, edges: 0, io: 0, refs: 0, visible: false, opened: 0, closed: 0,
            projection: "", placed_by_ego: 0, io_to_ego: 0, lit: 0, readouts: 0, reattached: 0,
            anchor: null as V3 | null, radius: 0, map_scale: 0, map_left_overlapping: 0, modules: 0, modules_by_ego: 0 };
  /** Planted (G-318): the code graph's modules are not the ego's. */
  plantNoCodeNet = false;
  /** Planted (G-324): every craft node on a sphere by bearing, the map's distances dropped. */
  plantSphereEgo = false;
  /** Planted (G-302): a plane panel that is not a slate or a ran notebook is not the craft's. */
  plantPlaneNotCells = false;
  /** The ego's scaled map is an OPTION, off -- the sphere is the layout again (PLUGIN_GOAL 127). */
  useScaledMap = false;
  /** Planted (item 67): the craft's nodes unlinked -- no edges inside it. */
  plantNoLinks = false;
  /** Per note: the distinct inputs its readout has been fed (item 96). */
  readoutInputs: Record<string, number> = {};
  /** Planted (item 89): instances drawn with no link to their code. */
  plantNoInstances = false;
  /** Planted (item 96): runs leave no readout in the craft. */
  plantNoReadouts = false;
  /** Planted (item 68): the craft drawn in the ego view too (around the camera). */
  plantAlwaysDrawn = false;
  plantLargeCraft = false;
  plantCraftDepthTested = false;
  plantLightCellOnly = false;
  private hotLines: any = null;
  /** Planted: hidden in the first-person view -- shipped TRUE from 2026-11-08
   *  (drawn around the camera it filled the lens) until 2026-11-14, when the
   *  reader could not find the ego at all: "I cannot find our ego anywhere. I
   *  can't even find the node" (PLUGIN_GOAL 157). */
  plantHiddenInEgo = false;
  /** Planted: first person draws the craft AT the camera (the 11-08 lens). */
  plantNoInset = false;
  /** First person: the craft's angular radius on screen, degrees. */
  insetDeg = 10;
  /** In the inset, nodes and labels drawn this much larger (2026-11-14: "I
   *  should also see the nodes much larger than currently, which are
   *  illegible"). */
  insetNodeScale = 1.6;
  insetLabelScale = 1.4;   // 2.6 overlapped into a wall of text (2026-11-14 screenshot)
  /** Planted: a shape per kind, as before 2026-11-14. */
  plantKindShapes = false;
  /** Planted: world matrices left to the scene's own pass -- which runs
   *  BEFORE the render hook places the inset, so the inset was drawn and
   *  picked where it was a frame (or more) ago. */
  plantStaleMatrices = false;
  /** Where the inset sits, as a fraction of the half-screen (x right, y up);
   *  moved by dragging any craft node. */
  insetShift = { x: 0, y: -0.4 };
  /** Third person: the craft's offset from its anchor, moved by a drag. */
  mapShift = { x: 0, y: 0, z: 0 };
  /** Planted: the inset placed on the TICK with a rounded redraw key, as it
   *  was -- it trailed the camera and snapped ("significant shaking of the
   *  ego when moving around", 2026-11-14). Now it is placed in the scene's
   *  onBeforeRender, after the camera has moved for that frame. */
  plantInsetOnTick = false;
  insetStats = { render_places: 0, tick_places: 0 };
  private hookedScene: any = null;
  /** Planted (146): the craft's map never turns with the heading. */
  plantFixedFrame = false;
  private q = new THREE.Quaternion();
  private group: any = null;
  private lines: any = null;
  ioLines: any = null;
  private rings: any = null;
  private labels: any[] = [];
  private stale = true;
  /** Knowledge key -> place, from the ego's own projection (item 76). */
  private places: Record<string, number[]> = {};
  private builtAt = -1e9;
  building = false;
  private key = "";

  constructor(private host: CraftHost) {}

  /** The vault changed (or a panel opened): rebuild on the next frame. */
  dirty(): void {
    this.stale = true; this.key = "";
    // Rebuilt whether or not the craft is on screen: the ego set (what
    // "similar" and the ego search rank over) came only from the draw loop, so
    // a note made on the plane joined it only once the craft was looked at
    // (2026-11-07, the polar surface finding nothing). Planted
    // `__domvecPlantCraftOnFrame`: rebuilt by the frame only, as before.
    if ((window as any).__domvecPlantCraftOnFrame) return;
    window.clearTimeout(this.dirtyTimer);
    this.dirtyTimer = window.setTimeout(() => {
      if (this.stale && !this.building) { this.builtAt = performance.now(); void this.build(); }
    }, 1200);
  }
  private dirtyTimer = 0;
  /** The craft as the vault stands NOW (G-331): a build in flight is waited
   *  out, then one more is made -- a run's end is pulsed through the craft
   *  that holds its readout, not the one built before the output existed. */
  async fresh(): Promise<void> {
    window.clearTimeout(this.dirtyTimer);
    for (let i = 0; this.building && i < 150; i++) await new Promise((r) => window.setTimeout(r, 20));
    this.stale = true; this.key = "";
    this.builtAt = performance.now();
    await this.build();
  }

  /** The craft's artifacts read from the vault. */
  async build(): Promise<void> {
    if (this.building) return;
    this.building = true;
    try {
      const app = this.host.app;
      const nodes: CraftNode[] = [];
      const edges: CraftEdge[] = [];
      const ego: CraftNode = { id: "craft:" + COCKPIT_PATH, kind: "ego", path: COCKPIT_PATH, line: -1, label: "ego", local: { x: 0, y: 0, z: 0 } };
      nodes.push(ego);
      const names = new Map<string, string>();          // a name -> the node it is
      names.set("ego", ego.id);
      const pending: { from: string; ref: string }[] = [];
      for (const f of app.vault.getMarkdownFiles()) {
        if (f.path === COCKPIT_PATH) continue;
        const cache = app.metadataCache.getFileCache(f);
        const kind = String(cache?.frontmatter?.domvec || "");
        if (kind === "chunk") continue;
        const slate = kind === "slate";
        const hasCode = (cache?.sections || []).some((s) => s.type === "code");
        // Cheap first cut -- but never past a note on the plane or made by its
        // tools: a markdown panel with no cell is the reader's own artifact
        // (item 74c), and this cut once dropped it before the rule below.
        const planeNote = !this.plantPlaneNotCells && (f.path.startsWith(PLANE_FOLDER + "/") || this.host.isOpen(f.path));
        if (!slate && !hasCode && !planeNote) continue;
        // Membership: G-291's rule for a computation-graph artifact -- a slate,
        // or a note whose python cell has RUN (a stored readout) -- and any note
        // the plane's tools made or the plane shows (item 65: its panel IS its
        // node). The vault is a repository: a README's fenced example is not
        // a kernel cell.
        if (f.path.includes("node_modules/") || f.path.startsWith(".")) continue;
        const onPlane = f.path.startsWith(PLANE_FOLDER + "/") || this.host.isOpen(f.path);
        // The panel IS the node (item 65): an open panel's text is read as it
        // stands, not as the disk had it at the last autosave -- a run's
        // readout exists the moment its output is in the editor. Planted
        // `plantDiskText`: the disk's, as before (the readout lags ~2 s).
        const live = this.plantDiskText ? null : (this.host.liveText?.(f.path) ?? null);
        const text = live ?? await app.vault.cachedRead(f);
        const fences = findFences(text).filter((x) => PY.test(x.lang));
        const ran = fences.length > 0 && /^\s*<!--\s*nb-output\s/m.test(text);
        // The reader's own markdown panels too (item 74c): on the plane, or
        // made by its tools, a note is an ego artifact with or without a cell.
        if (!slate && !ran && !onPlane) continue;
        const id = "craft:" + f.path;
        const note: CraftNode = { id, kind: "note", path: f.path, line: -1, label: f.basename, local: { x: 0, y: 0, z: 0 } };
        nodes.push(note);
        names.set(f.basename.toLowerCase(), id);
        edges.push({ a: ego.id, b: id, kind: "root" });
        const fenced = new Set<number>();
        for (const x of findFences(text)) for (let i = x.openLine; i <= x.closeLine; i++) fenced.add(i);
        // A slate IS its one tree (fused): its name names the note.
        const trees = treesOf(text, fenced);
        const steps: { id: string; line: number }[] = [];
        for (const t of trees) {
          if (slate) { names.set(t.name.toLowerCase(), id); for (const r of t.refs) pending.push({ from: id, ref: r }); continue; }
          const tid = `${id}#tree:${t.line}`;
          nodes.push({ id: tid, kind: "tree", path: f.path, line: t.line, label: t.name, local: { x: 0, y: 0, z: 0 } });
          edges.push({ a: id, b: tid, kind: "contains" });
          names.set(t.name.toLowerCase(), tid);
          for (const r of t.refs) pending.push({ from: tid, ref: r });
          steps.push({ id: tid, line: t.line });
        }
        fences.forEach((x, i) => {
          const cid = `${id}#cell:${x.openLine}`;
          nodes.push({ id: cid, kind: "cell", path: f.path, line: x.openLine, label: `[${i + 1}]`, local: { x: 0, y: 0, z: 0 } });
          edges.push({ a: id, b: cid, kind: "contains" });
          for (const r of x.refs || []) pending.push({ from: cid, ref: r });
          steps.push({ id: cid, line: x.openLine });
        });
        // The ego's MEMORY (item 96): a note whose cell has run holds a READOUT
        // -- its own node, linked forward from the cell that produced it; the
        // run's recorded inputs are its inverse lookups (lines into the world).
        if (ran && !this.plantNoReadouts) {
          const lines = text.split("\n");
          let producer = "";
          for (const x of fences) {
            const after = lines.slice(x.closeLine + 1, x.closeLine + 4).join("\n");
            if (/<!--\s*nb-output\s/.test(after)) producer = `${id}#cell:${x.openLine}`;
          }
          const rid = "craft:readout:" + f.path;
          nodes.push({ id: rid, kind: "readout", path: f.path, line: -1, label: "readout", local: { x: 0, y: 0, z: 0 } });
          edges.push({ a: producer || id, b: rid, kind: "forward" });
        }
        // One kernel per note, run in the note's order (trees and cells).
        steps.sort((a, b) => a.line - b.line);
        for (let i = 1; i < steps.length; i++) edges.push({ a: steps[i - 1].id, b: steps[i].id, kind: "order" });
      }
      // CODE and its INSTANCES (item 89): the browser's definition one node,
      // each browser instance (its cockpit note) linked to it -- undirected,
      // forward (code -> instance) and inverse (instance -> its code) alike.
      const browsers = nodes.filter((n) => n.kind === "note" && /^domvec\/browser( \d+)?\.md$/.test(n.path));
      if (browsers.length && !this.plantNoInstances) {
        // The class is the GOVERNING artifact (T-10): its methods are the
        // instances' control fields; a click opens it as code.
        const code: CraftNode = { id: "craft:code:BrowserView", kind: "code", path: "domvec/governing/browser.py", line: -1,
                                  label: "Browser (governing)", local: { x: 0, y: 0, z: 0 } };
        nodes.push(code);
        edges.push({ a: ego.id, b: code.id, kind: "root" });
        for (const b of browsers) edges.push({ a: code.id, b: b.id, kind: "instance" });
      }
      // Web chunks tagged into the ego (item 74b): each a `web` node of the
      // craft, its I/O line to its world node.
      const tags = this.host.egoTags ? await this.host.egoTags() : [];
      for (const cid of tags) {
        const w = this.host.worldNode(cid);
        const label = String((w && (w.name || w.title)) || cid).slice(0, 18);
        nodes.push({ id: "craft:web:" + cid, kind: "web", path: "", line: -1, label, local: { x: 0, y: 0, z: 0 } });
        edges.push({ a: ego.id, b: "craft:web:" + cid, kind: "root" });
      }
      this.stats.web = tags.length;
      // THE CODE GRAPH WEB in the ego (G-318, items 93-95): the code graph's
      // most central modules, each a code node of the craft, joined by the
      // calls / imports / inherits between them -- and posted into the ego set,
      // so the ego's OWN projection places them (item 76). Planted `plantNoCodeNet`.
      const modUrls: string[] = [];
      const net = this.plantNoCodeNet || !this.host.codeNet ? null : await this.host.codeNet().catch(() => null);
      if (net && net.nodes.length) {
        for (const m of net.nodes) {
          if (!m.url) continue;
          const id = "craft:mod:" + m.name;
          nodes.push({ id, kind: "code", path: m.url, line: -1, label: m.name.split(".").slice(-1)[0] + " (module)", local: { x: 0, y: 0, z: 0 } });
          edges.push({ a: ego.id, b: id, kind: "root" });
          modUrls.push(m.url);
        }
        const have = new Set(nodes.map((n) => n.id));
        for (const e of net.edges) {
          const a = "craft:mod:" + e.a, b = "craft:mod:" + e.b;
          if (have.has(a) && have.has(b)) edges.push({ a, b, kind: "module" });
        }
      }
      this.stats.modules = modUrls.length;
      const vaultName = app.vault.getName();
      this.host.postEgo?.(nodes.filter((n) => n.kind === "note" || n.kind === "ego").map((n) => "vault://" + vaultName + "/" + n.path).concat(modUrls));
      let refs = 0;
      for (const p of pending) {
        const head = p.ref.split(".")[0].trim().toLowerCase();
        const to = names.get(head);
        if (to && to !== p.from) { edges.push({ a: p.from, b: to, kind: "ref" }); refs++; }
      }
      // The ego's own projection (item 76, binding): asked after the store has
      // the membership the post above sent it -- and the new graph published
      // only once it is placed and drawn (published before this await, a
      // reader saw nodes with no mesh, G-299).
      const proj = this.host.egoProjection ? await this.host.egoProjection() : null;
      this.nodes = nodes;
      this.edges = this.plantNoLinks ? [] : edges;
      this.places = proj?.places || {};
      this.stats.projection = proj?.method || "none";
      this.layout();
      this.rebuildScene();
      this.stats.builds++;
      this.stats.notes = nodes.filter((n) => n.kind === "note").length;
      this.stats.cells = nodes.filter((n) => n.kind === "cell").length;
      this.stats.trees = nodes.filter((n) => n.kind === "tree").length;
      this.stats.edges = this.edges.length;
      this.stats.refs = refs;
    } finally {
      this.building = false;
      this.stale = false;
    }
  }

  /** The craft's own frame: notes on its sphere along their UMAP bearing in
   *  the world, their trees and cells around them, outward. */
  private layout(): void {
    const w = this.host.world();
    // Much smaller and more compact (PLUGIN_GOAL 149, 2026-11-08: "The ego in
    // 3d could be much smaller and more compact"): 6% of the world's radius,
    // was 22%. Planted `plantLargeCraft`: the old size.
    const R = this.plantLargeCraft ? Math.max(10, w.r * 0.22) : Math.max(2, w.r * 0.03);
    this.stats.radius = Math.round(R);
    const vault = this.host.app.vault.getName();
    // Places from the EGO's own projection by knowledge key (item 76): a
    // note's `vault://` url, a tagged chunk's cid. Planted world-projection:
    // the world fit's bearings, as before the rule. Unplaced: spread evenly.
    let byEgo = 0;
    const world = this.stats.projection === "world";
    const placeOf = (key: string, i: number, n: number, worldId: string): V3 => {
      const p = this.places[key];
      if (p && p.length === 3 && Math.hypot(p[0], p[1], p[2]) > 1e-6) { byEgo++; return norm({ x: p[0], y: p[1], z: p[2] }); }
      const page = world ? this.host.worldNode(worldId) : null;
      if (page && Number.isFinite(page.fitX ?? page.x)) {
        const fx = page.fitX ?? page.x, fy = page.fitY ?? page.y, fz = page.fitZ ?? page.z ?? 0;
        return norm({ x: fx - w.cx, y: fy - w.cy, z: fz - w.cz });
      }
      return fib(i, n);
    };
    for (const n of this.nodes) if (n.kind === "code" && !n.id.startsWith("craft:mod:")) n.local = { x: 0, y: -R * 0.5, z: 0 };
    // The code graph's modules (G-318): by the EGO's projection of their
    // `code://` address, on a shell just outside the notes.
    const mods = this.nodes.filter((n) => n.id.startsWith("craft:mod:"));
    let modsByEgo = 0;
    mods.forEach((n, i) => {
      const p = this.places[n.path];
      if (p && p.length === 3 && Math.hypot(p[0], p[1], p[2]) > 1e-6) modsByEgo++;
      const d = placeOf(n.path, i, Math.max(2, mods.length), "page:" + n.path);
      n.local = { x: d.x * R * 1.25, y: d.y * R * 1.25, z: d.z * R * 1.25 };
    });
    this.stats.modules_by_ego = modsByEgo;
    const webs = this.nodes.filter((n) => n.kind === "web");
    const notes = this.nodes.filter((n) => n.kind === "note");
    // THE MAP, SCALED (item 107, G-324): a node the ego's UMAP placed sits at
    // that place -- centred, times ONE factor chosen so that no two notes'
    // cell orbits overlap (bar the closest 2%) -- not projected onto a sphere,
    // which kept the bearing and threw the map's distances away. A node the
    // map has not placed waits on a sphere just outside it. Planted
    // `plantSphereEgo`: every node on the sphere, as before.
    const keyOf = (n: CraftNode) => n.kind === "web" ? n.id.slice("craft:web:".length) : "vault://" + vault + "/" + n.path;
    const mapped = [...notes, ...webs].filter((n) => { const p = this.places[keyOf(n)]; return p && p.length === 3 && p.every(Number.isFinite); });
    const mapAt = new Map<CraftNode, V3>();
    if (this.useScaledMap && !this.plantSphereEgo && mapped.length >= 2) {
      const P = mapped.map((n) => this.places[keyOf(n)]);
      const c = [0, 1, 2].map((a) => P.reduce((s, p) => s + p[a], 0) / P.length);
      const nn = P.map((p, i) => Math.min(...P.map((q, j) => j === i ? Infinity : Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]))));
      // STRICT (item 119): the closest pair of notes just touching; no node
      // nudged (item 121) -- two on one point are counted, never moved.
      const need = 2 * R * 0.32 * 1.15;
      const apart = nn.filter((d) => d > 0);
      const s = apart.length ? need / Math.min(...apart) : 1;
      this.stats.map_scale = Math.round(s * 1e6) / 1e6;
      this.stats.map_left_overlapping = nn.filter((d) => d * s < need - 1e-9).length;
      mapped.forEach((n, i) => mapAt.set(n, { x: (P[i][0] - c[0]) * s, y: (P[i][1] - c[1]) * s, z: (P[i][2] - c[2]) * s }));
    }
    const outer = Math.max(R, ...[...mapAt.values()].map((v) => Math.hypot(v.x, v.y, v.z) + R * 0.4));
    webs.forEach((n, i) => {
      const at = mapAt.get(n);
      if (at) { n.local = at; return; }
      const cid = n.id.slice("craft:web:".length);
      const d = placeOf(cid, i, Math.max(2, webs.length), cid);
      const r = mapAt.size ? outer : R * 0.8;
      n.local = { x: d.x * r, y: d.y * r, z: d.z * r };
    });
    notes.forEach((n, i) => {
      const at = mapAt.get(n);
      const d = at ? norm(at) : placeOf("vault://" + vault + "/" + n.path, i, notes.length, "page:vault://" + vault + "/" + n.path);
      const r = mapAt.size ? outer : R;
      n.local = at || { x: d.x * r, y: d.y * r, z: d.z * r };
      // A readout outward of its note, past its cells.
      const ro = this.nodes.find((k) => k.kind === "readout" && k.path === n.path);
      if (ro) ro.local = { x: n.local.x + d.x * R * 0.45, y: n.local.y + d.y * R * 0.45, z: n.local.z + d.z * R * 0.45 };
      const kids = this.nodes.filter((k) => k.path === n.path && (k.kind === "cell" || k.kind === "tree"));
      kids.forEach((k, j) => {
        const o = fib(j, Math.max(2, kids.length));
        const kd = norm({ x: d.x + 0.8 * o.x, y: d.y + 0.8 * o.y, z: d.z + 0.8 * o.z });
        k.local = { x: n.local.x + kd.x * R * 0.32, y: n.local.y + kd.y * R * 0.32, z: n.local.z + kd.z * R * 0.32 };
      });
    });
    this.stats.placed_by_ego = byEgo;
  }

  /**
   * **Signal-flow glow, iterative-recursive** (PLUGIN_GOAL 114, G-331): a
   * finished run sends a glowing pulse down every edge leaving its note --
   * the note to its cells, a cell to its readout (`forward`), a definition to
   * every cell that READS it (`ref`, followed backwards) -- and each node a
   * pulse reaches flashes and sends its own on, hop by hop, never back to a
   * node already reached. Where a hop lands on a note, `onPulse` tells the
   * plane, which lights that panel in the same order. Planted `plantNoPulse`.
   */
  plantNoPulse = false;
  /** Planted (G-331): the craft reads every note from disk, open or not. */
  plantDiskText = false;
  onPulse: ((path: string) => void) | null = null;
  pulseStats = { started: 0, hops: 0, reached: [] as string[], last_ms: 0 };
  private pulses: { a: string; b: string; t0: number; ms: number; dot: any; depth: number }[] = [];
  private pulseSeen = new Set<string>();
  static PULSE_MS = 420;
  static PULSE_DEPTH = 6;
  /** Where a signal goes next from a node: forward along contains, order and
   *  forward edges; backward along ref (the reader of a definition). */
  downstream(id: string): string[] {
    const out: string[] = [];
    for (const e of this.edges) {
      if (e.a === id && (e.kind === "contains" || e.kind === "order" || e.kind === "forward")) out.push(e.b);
      else if (e.b === id && e.kind === "ref") out.push(e.a);
    }
    return out;
  }
  pulse(path: string): number {
    if (this.plantNoPulse || !this.group) return 0;
    const start = "craft:" + path;
    if (!this.nodes.some((n) => n.id === start)) return 0;
    this.pulseSeen = new Set([start]);
    this.pulseStats.started++;
    this.pulseStats.reached = [path];
    this.pulseStats.last_ms = performance.now();
    return this.sendFrom(start, 0);
  }
  private sendFrom(id: string, depth: number): number {
    if (depth >= Craft.PULSE_DEPTH) return 0;
    let sent = 0;
    for (const b of this.downstream(id)) {
      if (this.pulseSeen.has(b)) continue;
      this.pulseSeen.add(b);
      const R = this.stats.radius || 10;
      const dot = new THREE.Mesh(new THREE.SphereGeometry(R * 0.022, 10, 8), PULSE_MAT);
      this.group.add(dot);
      this.pulses.push({ a: id, b, t0: performance.now(), ms: Craft.PULSE_MS, dot, depth });
      sent++;
    }
    return sent;
  }
  /** Each frame: every pulse in flight moved along its edge; one that arrives
   *  flashes its target and sends the signal on. */
  private stepPulses(at: V3): void {
    if (!this.pulses.length) return;
    const byId = new Map(this.nodes.map((n) => [n.id, n]));
    const now = performance.now();
    const still: typeof this.pulses = [];
    // The ones in flight this frame; arrivals send theirs into a fresh list.
    const cur = this.pulses;
    this.pulses = [];
    for (const p of cur) {
      const a = byId.get(p.a), b = byId.get(p.b);
      const e = Math.min(1, (now - p.t0) / p.ms);
      if (a && b) {
        // Along the drawn edge: the meshes are already turned with the heading.
        const A = a.mesh?.position, B = b.mesh?.position;
        if (A && B) p.dot.position.set(A.x + (B.x - A.x) * e, A.y + (B.y - A.y) * e, A.z + (B.z - A.z) * e);
        else p.dot.position.set(at.x + a.local.x + (b.local.x - a.local.x) * e, at.y + a.local.y + (b.local.y - a.local.y) * e,
                                at.z + a.local.z + (b.local.z - a.local.z) * e);
      }
      if (e < 1) { still.push(p); continue; }
      p.dot.removeFromParent(); p.dot.geometry.dispose();
      this.pulseStats.hops++;
      if (b?.mesh) {
        const m = b.mesh;
        if (!m.userData.flashBase) m.userData.flashBase = m.material;
        m.material = PULSE_MAT;
        window.setTimeout(() => { if (m.userData.flashBase) { m.material = m.userData.flashBase; delete m.userData.flashBase; } }, 260);
      }
      if (b && b.kind === "note" && b.path) { this.pulseStats.reached.push(b.path); try { this.onPulse?.(b.path); } catch { /* the plane is optional */ } }
      this.sendFrom(p.b, p.depth + 1);
    }
    this.pulses = still.concat(this.pulses);
  }

  /** Computation in flight (item 99): a note's node and its I/O lines lit. */
  lit = new Set<string>();
  setLit(path: string, on: boolean): void {
    if (on) this.lit.add(path); else this.lit.delete(path);
    const n = this.nodes.find((x) => x.id === "craft:" + path);
    if (n?.mesh) {
      if (on && !n.mesh.userData.base) n.mesh.userData.base = n.mesh.material;
      n.mesh.material = on ? LIT_MAT : (n.mesh.userData.base || n.mesh.material);
      n.mesh.scale.setScalar(on ? 1.8 : 1);
    }
    // The whole TRIPLE lit while it computes (PG 4909: "these computations
    // must be clearly visible lights from the active triples being computed"):
    // the cell's readout node, and -- in `frame` -- its input lines drawn
    // bright. Planted `plantLightCellOnly`: the note alone, as before.
    const ro = this.nodes.find((x) => x.id === "craft:readout:" + path);
    if (ro?.mesh && !this.plantLightCellOnly) {
      if (on && !ro.mesh.userData.base) ro.mesh.userData.base = ro.mesh.material;
      ro.mesh.material = on ? LIT_MAT : (ro.mesh.userData.base || ro.mesh.material);
      ro.mesh.scale.setScalar(on ? 1.8 : 1);
    }
    if (this.ioLines) this.ioLines.material.opacity = this.lit.size ? 0.95 : 0.4;
    this.stats.lit = this.lit.size;
    this.key = "";
  }

  /** A note's I/O toggle (item 79): its `maps` frontmatter, "web" by default. */
  mapsOf(path: string): string {
    const f = this.host.app.vault.getAbstractFileByPath(path);
    const fm = f instanceof TFile ? this.host.app.metadataCache.getFileCache(f)?.frontmatter : null;
    return String((fm && fm.maps) || "web");
  }

  /** The craft's centre in the world. */
  /** Where the craft sits in first person, and how it faces: on the view
   *  axis at the distance that makes its radius `insetDeg` on screen, lowered
   *  to the bottom third, turned to face the lens. */
  inset(): { at: V3; q: any } | null {
    const cam = this.host.camera();
    if (!cam || !cam.position) return null;
    const R = this.stats.radius || 10;
    const D = R / Math.tan((this.insetDeg * Math.PI) / 180);
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(cam.quaternion);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(cam.quaternion);
    const halfH = D * Math.tan(((cam.fov || 50) * Math.PI) / 360);
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(cam.quaternion);
    const halfW = halfH * (cam.aspect || 1);
    const p = cam.position.clone().addScaledVector(fwd, D)
      .addScaledVector(up, halfH * this.insetShift.y).addScaledVector(right, halfW * this.insetShift.x);
    (this.stats as any).inset = { D: Math.round(D), deg: this.insetDeg };
    return { at: { x: p.x, y: p.y, z: p.z }, q: cam.quaternion.clone() };
  }

  where(): V3 {
    const a = this.host.anchor();
    if (a) return { x: a.x + this.mapShift.x, y: a.y + this.mapShift.y, z: a.z + this.mapShift.z };
    const w = this.host.world();
    return { x: w.cx + w.r * 1.3, y: w.cy, z: w.cz };
  }

  private rebuildScene(): void {
    const scene = this.host.scene();
    if (!scene) return;
    if (!this.group) { this.group = new THREE.Group(); this.group.name = "domvec-craft"; scene.add(this.group); }
    this.hotLines = null;
    this.memRings = null;
    for (const c of [...this.group.children]) { c.removeFromParent(); c.geometry?.dispose?.(); if (c.material?.map) c.material.map.dispose(); }
    this.labels = [];
    const R = this.stats.radius || 10;
    // ONE shape for every node (2026-11-14: "we should only have one uniform
    // display of node and links. No fancy shapes."): a sphere, one size; the
    // kind is its colour alone. Planted `plantKindShapes`: the old cubes,
    // octahedra, tetrahedra and icosahedra.
    const ball = new THREE.SphereGeometry(R * 0.05, 16, 12);
    const geo: Record<CraftKind, any> = this.plantKindShapes ? {
      ego: new THREE.SphereGeometry(R * 0.07, 20, 14),
      note: new THREE.SphereGeometry(R * 0.045, 16, 12),
      tree: new THREE.OctahedronGeometry(R * 0.032),
      cell: new THREE.BoxGeometry(R * 0.045, R * 0.045, R * 0.045),
      web: new THREE.TetrahedronGeometry(R * 0.04),
      readout: new THREE.IcosahedronGeometry(R * 0.04),
      code: new THREE.BoxGeometry(R * 0.07, R * 0.07, R * 0.07),
    } : { ego: ball, note: ball, tree: ball, cell: ball, web: ball, readout: ball, code: ball };
    const mat: Record<CraftKind, any> = {
      ego: new THREE.MeshBasicMaterial({ color: 0xffffff }),
      note: new THREE.MeshBasicMaterial({ color: CRAFT_COLOUR }),
      tree: new THREE.MeshBasicMaterial({ color: CRAFT_COLOUR }),
      cell: new THREE.MeshBasicMaterial({ color: CELL_COLOUR }),
      web: new THREE.MeshBasicMaterial({ color: IO_COLOUR }),
      readout: new THREE.MeshBasicMaterial({ color: 0x8fd3ff }),
      code: new THREE.MeshBasicMaterial({ color: 0x9ae6b4 }),
    };
    for (const n of this.nodes) {
      const m = new THREE.Mesh(geo[n.kind], mat[n.kind]);
      (m as any).__craft = n.id;
      n.mesh = m;
      // A computation still in flight stays lit through a rebuild.
      if (n.kind === "note" && this.lit.has(n.path)) { m.userData.base = m.material; m.material = LIT_MAT; m.scale.setScalar(1.8); }
      this.group.add(m);
      if (n.kind !== "cell" && n.kind !== "tree") this.labels.push(this.label(n, R));
    }
    this.lines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: CRAFT_COLOUR, transparent: true, opacity: 0.75 }));
    this.ioLines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: IO_COLOUR, transparent: true, opacity: 0.4 }));
    this.rings = new THREE.Group();
    this.group.add(this.lines, this.ioLines, this.rings);
    // Drawn OVER the world (PLUGIN_GOAL 149 follow-up): centred on the focus,
    // the craft sat inside the world cloud, buried under its billboards
    // (screenshot 2026-11-08). Its meshes, labels and lines skip the depth
    // test and draw last. Planted `plantCraftDepthTested`: buried, as before.
    if (!this.plantCraftDepthTested) {
      this.group.traverse((o: any) => {
        o.renderOrder = 1000;
        const ms = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
        for (const m of ms) { m.depthTest = false; m.depthWrite = false; m.transparent = true; }
      });
    }
    this.key = "";
  }

  private label(n: CraftNode, R: number): any {
    const c = document.createElement("canvas");
    c.width = 256; c.height = 64;
    const x = c.getContext("2d")!;
    x.font = "28px sans-serif"; x.fillStyle = n.kind === "ego" ? "#ffffff" : "#c8b4ff"; x.textBaseline = "middle";
    x.fillText(n.label.slice(0, 18), 4, 32);
    const tex = new THREE.CanvasTexture(c);
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    s.scale.set(R * 0.4, R * 0.1, 1);
    (s as any).__for = n.id;
    this.group.add(s);
    return s;
  }

  /** Each frame: drawn in the map view only, placed at its anchor; its I/O
   *  lines follow the world's nodes. Cheap when nothing moved. */
  frame(fromRender = false): void {
    // Rebuilt at most every two seconds: an autosave per keystroke burst is a
    // vault change, and the craft reads every artifact's text.
    if (this.stale && !this.building && performance.now() - this.builtAt > 2000) { this.builtAt = performance.now(); void this.build(); }
    if (!this.group) return;
    // The graph view rebuilds its whole scene on a redraw (a refit, a level
    // toggle): the craft rejoins the CURRENT scene -- left in the old one it
    // was drawn nowhere and no ray could reach it (found 2026-11-02, G-320).
    const scene = this.host.scene();
    if (scene && this.group.parent !== scene) { scene.add(this.group); this.stats.reattached = (this.stats.reattached || 0) + 1; }
    if (scene && this.hookedScene !== scene) {
      // Placed AFTER the camera moved this frame: the renderer calls the
      // scene's onBeforeRender once per draw, with the camera it draws with.
      const prev = scene.onBeforeRender;
      scene.onBeforeRender = (...args: any[]) => {
        try { if (typeof prev === "function") prev.apply(scene, args); } catch { /* theirs */ }
        if (this.group?.visible && this.host.mode() === "ego" && !this.plantNoInset && !this.plantInsetOnTick) {
          try {
            this.frame(true);
            // The renderer updated world matrices BEFORE calling this hook:
            // without this the draw (and every pick) used last frame's place.
            if (!this.plantStaleMatrices) this.group.updateMatrixWorld(true);
          } catch { /* next frame */ }
        }
      };
      this.hookedScene = scene;
    }
    // Drawn in BOTH views (PLUGIN_GOAL 146: "moves in first and third person
    // camera view, always at the 'center' of view"): third person, the chase
    // camera keeps it at the centre of the screen; first person, the camera is
    // at the ego node, inside its own map ("zoom ... into the microscope of
    // the ego", PG 4909). Planted `plantHiddenInEgo`: hidden in the ego view.
    const egoView = this.host.mode() === "ego";
    const show = this.plantAlwaysDrawn || !this.plantHiddenInEgo || !egoView;
    this.group.visible = show;
    this.stats.visible = show;
    // Placed and counted drawn or not: hidden in the ego view, its I/O still
    // counts (a count taken only when drawn read 0 in the ego view, G-306).
    // First person (2026-11-14): an INSET -- ahead of the camera and below the
    // centre, sized to a fixed angle, facing the lens -- so the ego is always
    // in view without filling it. Third person keeps the chase anchor.
    const insetMode = egoView && !this.plantNoInset;
    // The inset is placed by the render hook only (see above), at full
    // precision every frame; the tick's call does the rest of the frame work.
    if (insetMode && !fromRender && !this.plantInsetOnTick) return;
    if (insetMode) { if (fromRender) this.insetStats.render_places++; else this.insetStats.tick_places++; }
    const inset = insetMode ? this.inset() : null;
    const at = inset ? inset.at : this.where();
    this.stats.anchor = { x: Math.round(at.x), y: Math.round(at.y), z: Math.round(at.z) };
    // Pulses move every frame, before the redraw key can skip it (G-331).
    this.stepPulses(at);
    const open = this.nodes.filter((n) => (n.kind === "note" || n.kind === "ego") && this.host.isOpen(n.path)).map((n) => n.id);
    const sig = this.host.signalEdges();
    // Redrawn when the anchor, the open panels or the runs change -- and once a
    // second, for the world's nodes its I/O lines end on.
    // The heading turns the craft's frame: its map's +z points along it.
    const h = this.plantFixedFrame ? null : this.host.heading?.();
    if (inset) this.q.copy(inset.q);
    else if (h && Number.isFinite(h.x) && Math.hypot(h.x, h.y, h.z) > 1e-6) {
      const L = Math.hypot(h.x, h.y, h.z);
      this.q.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(h.x / L, h.y / L, h.z / L));
    } else this.q.identity();
    (this.stats as any).heading = h ? [h.x, h.y, h.z].map((v) => Math.round(v * 100) / 100) : null;
    const key = `${Math.round(at.x)},${Math.round(at.y)},${Math.round(at.z)}|${this.q.x.toFixed(3)},${this.q.y.toFixed(3)},${this.q.z.toFixed(3)},${this.q.w.toFixed(3)}|${open.join(",")}|${sig.length}|${this.nodes.length}|${Math.floor(performance.now() / 1000)}`;
    // The inset redraws every frame: a key rounded to whole units held it
    // still under small camera moves and then snapped it (the shake).
    if (key === this.key && !(inset && !this.plantInsetOnTick)) return;
    this.key = key;
    const byId = new Map(this.nodes.map((n) => [n.id, n]));
    const tmp = new THREE.Vector3();
    const pos = (n: CraftNode) => { tmp.set(n.local.x, n.local.y, n.local.z).applyQuaternion(this.q); return { x: at.x + tmp.x, y: at.y + tmp.y, z: at.z + tmp.z }; };
    const kN = inset ? this.insetNodeScale : 1, kL = inset ? this.insetLabelScale : 1;
    for (const n of this.nodes) { const p = pos(n); n.mesh?.position.set(p.x, p.y, p.z); n.mesh?.scale.setScalar(kN); }
    const R = this.stats.radius || 10;
    for (const s of this.labels) { const n = byId.get(s.__for); if (n) { const p = pos(n); s.position.set(p.x + R * 0.2 * kL, p.y + R * 0.07 * kL, p.z); s.scale.set(R * 0.4 * kL, R * 0.1 * kL, 1); } }
    const pts: number[] = [];
    for (const e of this.edges) {
      const a = byId.get(e.a), b = byId.get(e.b);
      if (!a || !b) continue;
      const p = pos(a), q = pos(b);
      pts.push(p.x, p.y, p.z, q.x, q.y, q.z);
    }
    this.lines.geometry.dispose();
    this.lines.geometry = new THREE.BufferGeometry();
    this.lines.geometry.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    // I/O: what a run read, a chunk of the world, wired to its cell's note.
    const io: number[] = [];
    const seen = new Set<string>();
    let toEgo = 0;
    for (const s of sig) {
      const k = s.note + "|" + s.cid;
      if (seen.has(k)) continue;
      seen.add(k);
      const n = byId.get("craft:readout:" + s.note) || byId.get("craft:" + s.note);
      if (!n) continue;
      const p = pos(n);
      // The note's toggle (item 79): `maps: ego` ends its I/O on the ego's own
      // node for that input (a tagged chunk, an ego note); `web` on the world's.
      if (this.mapsOf(s.note) === "ego") {
        const e = byId.get("craft:web:" + s.cid) || (s.url.startsWith("vault://") ? byId.get("craft:" + s.url.replace(/^vault:\/\/[^/]+\//, "")) : undefined);
        if (e) { const q = pos(e); io.push(q.x, q.y, q.z, p.x, p.y, p.z); toEgo++; }
        continue;
      }
      const w = this.host.worldNode(s.cid) || (s.url ? this.host.worldNode("page:" + s.url) : null);
      if (!w || !Number.isFinite(w.x)) continue;
      io.push(w.x, w.y, w.z || 0, p.x, p.y, p.z);
    }
    this.stats.io_to_ego = toEgo;
    // Each readout's memory: how many distinct inputs its runs have read.
    const fed = new Map<string, Set<string>>();
    for (const q of sig) { if (!fed.has(q.note)) fed.set(q.note, new Set()); fed.get(q.note)!.add(q.cid); }
    this.readoutInputs = Object.fromEntries([...fed].map(([k, v]) => [k, v.size]));
    // THE EGO'S MEMORY, live (PG 4909: "actively evolving egoic memory
    // structures being mapped from recursive calls ... with undirected
    // lookup/indexing links"): each readout that has read inputs wears a
    // memory ring whose radius grows with the log of the distinct inputs its
    // runs have read -- a call on a new input grows it, a repeat does not.
    // Planted `plantNoMemory`: no rings.
    this.drawMemory(byId, pos);
    this.stats.readouts = this.nodes.filter((x) => x.kind === "readout").length;
    // A tagged chunk's line to its place in the world.
    for (const n of this.nodes) {
      if (n.kind !== "web") continue;
      const w = this.host.worldNode(n.id.slice("craft:web:".length));
      if (!w || !Number.isFinite(w.x)) continue;
      const p = pos(n);
      io.push(w.x, w.y, w.z || 0, p.x, p.y, p.z);
    }
    this.ioLines.geometry.dispose();
    this.ioLines.geometry = new THREE.BufferGeometry();
    this.ioLines.geometry.setAttribute("position", new THREE.Float32BufferAttribute(io, 3));
    // A computing note's inputs: their lines again, bright, over the rest.
    const hot: number[] = [];
    if (!this.plantLightCellOnly && this.lit.size) {
      for (const q of sig) {
        if (!this.lit.has(q.note)) continue;
        const n = byId.get("craft:readout:" + q.note) || byId.get("craft:" + q.note);
        const w = this.host.worldNode(q.cid) || (q.url ? this.host.worldNode("page:" + q.url) : null);
        if (!n || !w || !Number.isFinite(w.x)) continue;
        const p = pos(n);
        hot.push(w.x, w.y, w.z || 0, p.x, p.y, p.z);
      }
    }
    if (!this.hotLines) {
      this.hotLines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xfff1a8, transparent: true, opacity: 1, depthTest: false }));
      this.hotLines.renderOrder = 1001;
      this.group.add(this.hotLines);
    }
    this.hotLines.geometry.dispose();
    this.hotLines.geometry = new THREE.BufferGeometry();
    this.hotLines.geometry.setAttribute("position", new THREE.Float32BufferAttribute(hot, 3));
    (this.stats as any).lit_inputs = hot.length / 6;
    this.stats.io = io.length / 6;
    // A node whose panel is stuck on the plane is ringed.
    for (const r of [...this.rings.children]) { r.removeFromParent(); r.geometry?.dispose?.(); }
    for (const id of open) {
      const n = byId.get(id);
      if (!n) continue;
      const ring = new THREE.Mesh(new THREE.TorusGeometry(R * 0.09, R * 0.008, 8, 32), new THREE.MeshBasicMaterial({ color: 0xffffff }));
      const p = pos(n);
      ring.position.set(p.x, p.y, p.z);
      ring.lookAt(this.host.camera().position);
      (ring as any).__ringOf = id;
      this.rings.add(ring);
    }
  }

  plantNoMemory = false;
  memoryStats = { rings: 0, max_inputs: 0 };
  private memRings: any = null;
  private drawMemory(byId: Map<string, CraftNode>, pos: (n: CraftNode) => V3): void {
    if (!this.group) return;
    if (!this.memRings || this.memRings.parent !== this.group) { this.memRings = new THREE.Group(); this.group.add(this.memRings); }
    for (const r of [...this.memRings.children]) { r.removeFromParent(); r.geometry?.dispose?.(); }
    this.memoryStats.rings = 0; this.memoryStats.max_inputs = 0;
    if (this.plantNoMemory) return;
    const R = this.stats.radius || 10;
    for (const [note, k] of Object.entries(this.readoutInputs)) {
      const n = byId.get("craft:readout:" + note) || byId.get("craft:" + note);
      if (!n || !k) continue;
      const p = pos(n);
      const rr = R * 0.06 * (1 + Math.log2(1 + k));
      const ring = new THREE.Mesh(new THREE.TorusGeometry(rr, R * 0.006, 6, 40),
        new THREE.MeshBasicMaterial({ color: 0xfff1a8, transparent: true, opacity: 0.85, depthTest: false }));
      ring.position.set(p.x, p.y, p.z);
      ring.lookAt(this.host.camera().position);
      ring.renderOrder = 1002;
      (ring as any).__memory = note; (ring as any).__inputs = k;
      this.memRings.add(ring);
      this.memoryStats.rings++;
      this.memoryStats.max_inputs = Math.max(this.memoryStats.max_inputs, k);
    }
  }

  /** The craft node under a screen point, by the scene's own raycaster. */
  nodeAt(clientX: number, clientY: number): CraftNode | null {
    const el = this.host.canvas();
    if (!this.group || !this.group.visible || !el) return null;
    const r = el.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    if (!this.plantStaleMatrices) this.group.updateMatrixWorld(true);
    const rc = new THREE.Raycaster();
    rc.setFromCamera(ndc, this.host.camera());
    const meshes = this.nodes.map((n) => n.mesh).filter(Boolean);
    const hits = rc.intersectObjects(meshes, false);
    const id = hits.length ? (hits[0].object as any).__craft : null;
    return id ? this.nodes.find((n) => n.id === id) || null : null;
  }

  /** Drag the whole craft by a node: in the inset, its place on screen; in
   *  third person, its anchor, in the camera's plane. `dx, dy` in pixels. */
  dragBy(dx: number, dy: number): void {
    const el = this.host.canvas(), cam = this.host.camera();
    if (!el || !cam) return;
    const r = el.getBoundingClientRect();
    if (this.host.mode() === "ego" && !this.plantNoInset) {
      this.insetShift.x = Math.max(-0.95, Math.min(0.95, this.insetShift.x + (2 * dx) / r.width));
      this.insetShift.y = Math.max(-0.95, Math.min(0.95, this.insetShift.y - (2 * dy) / r.height));
    } else {
      const at = this.where();
      const dist = cam.position.distanceTo(new THREE.Vector3(at.x, at.y, at.z));
      const perPx = (2 * dist * Math.tan(((cam.fov || 50) * Math.PI) / 360)) / r.height;
      const right = new THREE.Vector3(1, 0, 0).applyQuaternion(cam.quaternion);
      const up = new THREE.Vector3(0, 1, 0).applyQuaternion(cam.quaternion);
      this.mapShift.x += (right.x * dx - up.x * dy) * perPx;
      this.mapShift.y += (right.y * dx - up.y * dy) * perPx;
      this.mapShift.z += (right.z * dx - up.z * dy) * perPx;
    }
    this.key = "";
    this.dragStats.moved++;
  }
  dragStats = { started: 0, moved: 0 };

  /** A click on a craft node: its panel on the plane, or closed back into it. */
  click(n: CraftNode): "opened" | "closed" {
    if (n.kind === "web" || n.kind === "code") return "opened";   // their panels are elsewhere
    if (n.kind !== "ego" && this.host.isOpen(n.path) && (n.kind === "note")) {
      this.host.closePanel(n.path);
      this.stats.closed++;
      return "closed";
    }
    this.host.openPanel(n.path, n.line);
    this.stats.opened++;
    return "opened";
  }

  /** The craft as data, for the checks: one connected unit? */
  summary(): any {
    const adj = new Map<string, string[]>();
    for (const e of this.edges) { (adj.get(e.a) || adj.set(e.a, []).get(e.a)!).push(e.b); (adj.get(e.b) || adj.set(e.b, []).get(e.b)!).push(e.a); }
    const seen = new Set<string>(["craft:" + COCKPIT_PATH]);
    const q = ["craft:" + COCKPIT_PATH];
    while (q.length) { const x = q.shift()!; for (const y of adj.get(x) || []) if (!seen.has(y)) { seen.add(y); q.push(y); } }
    return { ...this.stats, nodes: this.nodes.length, reached_from_ego: seen.size,
             kinds: this.nodes.reduce((m: any, n) => { m[n.kind] = (m[n.kind] || 0) + 1; return m; }, {}),
             edge_kinds: this.edges.reduce((m: any, e) => { m[e.kind] = (m[e.kind] || 0) + 1; return m; }, {}) };
  }

  unload(): void {
    this.group?.removeFromParent();
    this.group = null;
  }
}
