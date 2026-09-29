/**
 * SceneBatch -- every node and edge of the 3D view in THREE draw calls.
 *
 * Design: `.design/L3-design/pg-062.render.{uml,api}.md`, `.design/L4-arch/
 * pg-062.render.md`. The claim it serves ([[L1.pg-062.render]]): the 3D view
 * draws every stored chunk of an open page within a frame budget -- the user
 * ruled "Everything stored" ([[Q.001]]), so the cost comes out of HOW the scene
 * is drawn, not out of what is drawn. Measured before this: ~1,800 draw calls a
 * frame at 2,467 nodes, one per node and per link, and Obsidian's timers ran
 * 3-5x late while the forum streamed.
 *
 *   opaque quads      spheres (a lit impostor) and pictures (an atlas cell)
 *   translucent quads streaming nodes, drawn after, no depth write
 *   line batch        every edge
 *
 * It READS the layout and never writes it (the D-38 lesson: the pane owns the
 * live arrays). Picking stays with 3d-force-graph: each node keeps an
 * invisible proxy object that is raycast but never drawn.
 */
import * as THREE from "three";

const ATLAS = 4096;
const CELL = 64;
const PER_ROW = ATLAS / CELL;               // 64 cells a row, 4,096 in the page

const VERT = `
attribute vec3 iOffset;
attribute float iSize;
attribute vec4 iColor;
attribute vec4 iUv;
varying vec2 vCorner;
varying vec4 vColor;
varying vec4 vUv;
void main() {
  vCorner = position.xy;
  vColor = iColor;
  vUv = iUv;
  vec4 mv = modelViewMatrix * vec4(iOffset, 1.0);
  // Camera-facing: the quad's corners are laid out in VIEW space.
  mv.xy += position.xy * iSize;
  gl_Position = projectionMatrix * mv;
}`;

const FRAG = `
uniform sampler2D atlas;
varying vec2 vCorner;
varying vec4 vColor;
varying vec4 vUv;
void main() {
  if (vUv.z < 0.0) {
    // No picture: a sphere impostor, lit from the upper left.
    float r2 = dot(vCorner, vCorner);
    if (r2 > 1.0) discard;
    vec3 n = vec3(vCorner, sqrt(1.0 - r2));
    float l = 0.38 + 0.62 * max(dot(n, normalize(vec3(-0.35, 0.55, 0.75))), 0.0);
    gl_FragColor = vec4(vColor.rgb * l, vColor.a);
  } else {
    vec2 t = vCorner * 0.5 + 0.5;
    vec4 c = texture2D(atlas, vec2(mix(vUv.x, vUv.z, t.x), mix(vUv.y, vUv.w, t.y)));
    if (c.a < 0.04) discard;
    gl_FragColor = vec4(c.rgb, c.a * vColor.a);
  }
  #include <colorspace_fragment>
}`;

interface Mesh {
  geo: THREE.InstancedBufferGeometry;
  mesh: THREE.Mesh;
  offset: THREE.InstancedBufferAttribute;
  size: THREE.InstancedBufferAttribute;
  color: THREE.InstancedBufferAttribute;
  uv: THREE.InstancedBufferAttribute;
  cap: number;
}

/** What the pane tells the batch about one node, per frame. */
export interface NodeLook {
  /** Half the drawn extent: the sphere's radius, or half a picture's edge. */
  half: number;
  /** Streaming (translucent) or not. */
  translucent: boolean;
  alpha: number;
  color: string;
  /** A picture's src, when the node shows one. */
  picture?: string;
}

export class SceneBatch {
  private opaque: Mesh;
  private clear: Mesh;
  private lines: THREE.LineSegments;
  private linePos: THREE.BufferAttribute;
  private lineCol: THREE.BufferAttribute;
  private lineCap = 0;
  private atlas: THREE.DataTexture;
  private atlasReady = false;
  private cells = new Map<string, number>();       // src -> cell index
  private pending = new Set<string>();              // src being decoded
  private nextCell = 0;
  private colours = new Map<string, THREE.Color>();
  lastStats = { drawCalls: 3, opaque: 0, translucent: 0, lines: 0, atlasCells: 0, atlasFull: 0, syncMs: 0 };

  constructor(private scene: THREE.Scene, private renderer: THREE.WebGLRenderer,
              private load: (src: string) => Promise<HTMLImageElement | null>) {
    this.atlas = new THREE.DataTexture(new Uint8Array(4), 1, 1);   // replaced on first use
    this.opaque = this.makeMesh(512, false);
    this.clear = this.makeMesh(128, true);
    this.lines = this.makeLines(1024);
    this.linePos = this.lines.geometry.getAttribute("position") as THREE.BufferAttribute;
    this.lineCol = this.lines.geometry.getAttribute("color") as THREE.BufferAttribute;
    scene.add(this.opaque.mesh, this.clear.mesh, this.lines);
  }

  private material(translucent: boolean): THREE.ShaderMaterial {
    return new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { atlas: { value: this.atlas } },
      transparent: translucent, depthWrite: !translucent,
    });
  }

  private makeMesh(cap: number, translucent: boolean): Mesh {
    const geo = new THREE.InstancedBufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
    geo.setIndex([0, 1, 2, 0, 2, 3]);
    const attr = (n: number) => {
      const a = new THREE.InstancedBufferAttribute(new Float32Array(cap * n), n);
      a.setUsage(THREE.DynamicDrawUsage);
      return a;
    };
    const m: Mesh = { geo, mesh: null as any, offset: attr(3), size: attr(1), color: attr(4), uv: attr(4), cap };
    geo.setAttribute("iOffset", m.offset); geo.setAttribute("iSize", m.size);
    geo.setAttribute("iColor", m.color); geo.setAttribute("iUv", m.uv);
    geo.instanceCount = 0;
    m.mesh = new THREE.Mesh(geo, this.material(translucent));
    m.mesh.frustumCulled = false;           // instances span the whole cloud
    m.mesh.renderOrder = translucent ? 2 : 1;
    (m.mesh as any).__batch = true;          // not a node: never picked
    m.mesh.raycast = () => {};
    return m;
  }

  private grow(m: Mesh, need: number): void {
    if (need <= m.cap) return;
    let cap = m.cap;
    while (cap < need) cap *= 2;
    const re = (a: THREE.InstancedBufferAttribute) => {
      const b = new THREE.InstancedBufferAttribute(new Float32Array(cap * a.itemSize), a.itemSize);
      b.setUsage(THREE.DynamicDrawUsage);
      return b;
    };
    m.offset = re(m.offset); m.size = re(m.size); m.color = re(m.color); m.uv = re(m.uv);
    m.geo.setAttribute("iOffset", m.offset); m.geo.setAttribute("iSize", m.size);
    m.geo.setAttribute("iColor", m.color); m.geo.setAttribute("iUv", m.uv);
    m.cap = cap;
  }

  private makeLines(cap: number): THREE.LineSegments {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(cap * 6), 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(cap * 8), 4).setUsage(THREE.DynamicDrawUsage));
    geo.setDrawRange(0, 0);
    const mat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false });
    const l = new THREE.LineSegments(geo, mat);
    l.frustumCulled = false;
    l.renderOrder = 0;
    l.raycast = () => {};
    this.lineCap = cap;
    return l;
  }

  private colour(css: string): THREE.Color {
    let c = this.colours.get(css);
    if (!c) {
      try { c = new THREE.Color(css || "#9aa0a6"); } catch { c = new THREE.Color("#9aa0a6"); }
      this.colours.set(css, c);
      if (this.colours.size > 4096) this.colours.clear();
    }
    return c;
  }

  /** The atlas page, allocated on the GPU once; pictures are copied into cells. */
  private ensureAtlas(): void {
    if (this.atlasReady) return;
    const tex = new THREE.DataTexture(null as any, ATLAS, ATLAS, THREE.RGBAFormat);
    // Storage only: `dataReady = false` makes three allocate the page on the
    // GPU (texStorage2D) and upload nothing -- no 64 MB array in the heap.
    tex.source.dataReady = false;
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.magFilter = THREE.LinearFilter;
    tex.minFilter = THREE.LinearFilter;
    tex.generateMipmaps = false;
    tex.needsUpdate = true;
    this.renderer.initTexture(tex);
    this.atlas.dispose();
    this.atlas = tex;
    (this.opaque.mesh.material as THREE.ShaderMaterial).uniforms.atlas.value = tex;
    (this.clear.mesh.material as THREE.ShaderMaterial).uniforms.atlas.value = tex;
    this.atlasReady = true;
  }

  /** The cell a picture occupies, starting its decode if it has none yet. */
  private cellOf(src: string): number | undefined {
    const c = this.cells.get(src);
    if (c !== undefined) return c;
    if (this.pending.has(src)) return undefined;
    if (this.nextCell >= PER_ROW * PER_ROW) { this.lastStats.atlasFull++; return undefined; }
    this.pending.add(src);
    void this.load(src).then((img) => {
      this.pending.delete(src);
      if (!img || this.nextCell >= PER_ROW * PER_ROW) return;
      this.ensureAtlas();
      const cell = this.nextCell++;
      // Fit the picture into its cell, aspect kept, on a small canvas the
      // GPU copies into the atlas page (never a re-upload of the page).
      const cv = document.createElement("canvas");
      cv.width = CELL; cv.height = CELL;
      const g = cv.getContext("2d");
      if (!g) return;
      const k = Math.min(CELL / (img.naturalWidth || CELL), CELL / (img.naturalHeight || CELL));
      const w = Math.max(1, Math.round((img.naturalWidth || CELL) * k)), h = Math.max(1, Math.round((img.naturalHeight || CELL) * k));
      g.drawImage(img, (CELL - w) / 2, (CELL - h) / 2, w, h);
      const small = new THREE.CanvasTexture(cv);
      small.flipY = false;
      small.colorSpace = THREE.SRGBColorSpace;
      const x = (cell % PER_ROW) * CELL, y = Math.floor(cell / PER_ROW) * CELL;
      try { this.renderer.copyTextureToTexture(small, this.atlas, null, new THREE.Vector2(x, y)); }
      catch { /* context lost: the cell stays a sphere */ }
      small.dispose();
      this.cells.set(src, cell);
    });
    return undefined;
  }

  /** One frame: every node and edge written into the three batches. */
  sync(nodes: any[], links: any[], look: (n: any) => NodeLook | null): void {
    const t0 = performance.now();
    this.grow(this.opaque, nodes.length);
    this.grow(this.clear, nodes.length);
    let no = 0, nt = 0;
    for (const n of nodes) {
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) continue;
      const lk = look(n);
      if (!lk) continue;
      const m = lk.translucent ? this.clear : this.opaque;
      const i = lk.translucent ? nt++ : no++;
      m.offset.setXYZ(i, n.x, n.y, n.z || 0);
      m.size.setX(i, lk.half);
      const col = this.colour(lk.color);
      let cell: number | undefined;
      if (lk.picture) cell = this.cellOf(lk.picture);
      if (cell !== undefined) {
        const u0 = (cell % PER_ROW) / PER_ROW, v0 = Math.floor(cell / PER_ROW) / PER_ROW;
        // Row 0 of the atlas is the picture's top: the quad's top corner reads v0.
        m.uv.setXYZW(i, u0, v0 + 1 / PER_ROW, u0 + 1 / PER_ROW, v0);
        m.color.setXYZW(i, 1, 1, 1, lk.alpha);
        n.imgLoaded = true;
      } else {
        m.uv.setXYZW(i, 0, 0, -1, 0);
        m.color.setXYZW(i, col.r, col.g, col.b, lk.alpha);
      }
    }
    for (const [m, count] of [[this.opaque, no], [this.clear, nt]] as [Mesh, number][]) {
      m.geo.instanceCount = count;
      m.offset.needsUpdate = true; m.size.needsUpdate = true; m.color.needsUpdate = true; m.uv.needsUpdate = true;
    }
    // Edges.
    if (links.length > this.lineCap) {
      let cap = this.lineCap;
      while (cap < links.length) cap *= 2;
      this.lines.geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(cap * 6), 3).setUsage(THREE.DynamicDrawUsage));
      this.lines.geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(cap * 8), 4).setUsage(THREE.DynamicDrawUsage));
      this.linePos = this.lines.geometry.getAttribute("position") as THREE.BufferAttribute;
      this.lineCol = this.lines.geometry.getAttribute("color") as THREE.BufferAttribute;
      this.lineCap = cap;
    }
    let nl = 0;
    for (const l of links) {
      const s = l.source, t = l.target;
      if (typeof s !== "object" || typeof t !== "object" || !s || !t) continue;
      if (!Number.isFinite(s.x) || !Number.isFinite(t.x)) continue;
      this.linePos.setXYZ(nl * 2, s.x, s.y, s.z || 0);
      this.linePos.setXYZ(nl * 2 + 1, t.x, t.y, t.z || 0);
      // 3d-force-graph's own link colour (#f0f0f0) at the pane's linkOpacity.
      this.lineCol.setXYZW(nl * 2, 0.87, 0.87, 0.87, 0.25);
      this.lineCol.setXYZW(nl * 2 + 1, 0.87, 0.87, 0.87, 0.25);
      nl++;
    }
    this.lines.geometry.setDrawRange(0, nl * 2);
    this.linePos.needsUpdate = true;
    this.lineCol.needsUpdate = true;
    this.lastStats = { drawCalls: 3, opaque: no, translucent: nt, lines: nl, atlasCells: this.nextCell,
                       atlasFull: this.lastStats.atlasFull, syncMs: Math.round((performance.now() - t0) * 100) / 100 };
  }

  setVisible(on: boolean): void {
    this.opaque.mesh.visible = on;
    this.clear.mesh.visible = on;
    this.lines.visible = on;
  }

  dispose(): void {
    this.scene.remove(this.opaque.mesh, this.clear.mesh, this.lines);
    for (const m of [this.opaque, this.clear]) { m.geo.dispose(); (m.mesh.material as THREE.Material).dispose(); }
    this.lines.geometry.dispose(); (this.lines.material as THREE.Material).dispose();
    this.atlas.dispose();
  }
}
