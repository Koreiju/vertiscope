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
/** Pictures decoded at once. Unbounded, 23k nodes asked for every picture in
 *  the corpus in one frame and Obsidian froze (2026-10-11). */
const MAX_LOADS = 4;
/** A decoded picture: an `<img>` or an `ImageBitmap`. */
export type Picture = CanvasImageSource & { width: number; height: number };

const VERT = `
attribute vec3 iOffset;
attribute float iSize;
attribute vec4 iColor;
attribute vec4 iUv;
// Display-only scale with the camera's distance (G-206: smaller at full view).
uniform float uZoom;
varying vec2 vCorner;
varying vec4 vColor;
varying vec4 vUv;
void main() {
  vCorner = position.xy;
  vColor = iColor;
  vUv = iUv;
  vec4 mv = modelViewMatrix * vec4(iOffset, 1.0);
  // Camera-facing: the quad's corners are laid out in VIEW space.
  // A PICTURE keeps its size at every zoom: it is being presented (2026-10-17:
  // "hovering over nodes shows no image overlays in the chunk view"); only
  // orbs (iUv.z < 0) draw smaller at full view (G-206).
  mv.xy += position.xy * iSize * (iUv.z < 0.0 ? uZoom : 1.0);
  gl_Position = projectionMatrix * mv;
}`;

const FRAG = `
uniform sampler2D atlas;
uniform float uHue;
// The colour coordinates turned about the grey axis by uHue (PLUGIN_GOAL 83:
// "rotates both cartesian and color coordinates ... whenever there is no user
// activity"). 0 is the fit's own colour.
vec3 turnHue(vec3 c, float a) {
  const vec3 k = vec3(0.57735027);
  float ca = cos(a);
  return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}
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
    // A search result's own light (PLUGIN_GOAL 88): vUv.x is its glow, 0 for
    // every other node -- brightened from within, with a white core.
    float g = vUv.x;
    vec3 base = uHue == 0.0 ? vColor.rgb : clamp(turnHue(vColor.rgb, uHue), 0.0, 1.0);
    gl_FragColor = vec4(base * l * (1.0 + 1.4 * g) + g * 0.45 * pow(n.z, 3.0), vColor.a);
  } else {
    vec2 t = vCorner * 0.5 + 0.5;
    vec4 c = texture2D(atlas, vec2(mix(vUv.x, vUv.z, t.x), mix(vUv.y, vUv.w, t.y)));
    if (c.a < 0.04) discard;
    // A hovered picture keeps its image and glows (item 102): vColor.r - 1 is
    // the glow -- brighter, with a soft light at its edge.
    float hg = max(vColor.r - 1.0, 0.0);
    float edge = smoothstep(0.62, 1.0, max(abs(vCorner.x), abs(vCorner.y)));
    gl_FragColor = vec4(c.rgb * (1.0 + 0.35 * hg) + vec3(0.9, 0.95, 1.0) * edge * hg * 0.85, c.a * vColor.a);
  }
  #include <colorspace_fragment>
}`;

/** Point lights the glass is lit by: the shown search results (item 88). */
export const MAX_LIGHTS = 16;

const GLASS_VERT = `
attribute vec3 iOffset;
attribute float iSize;
attribute vec4 iColor;
uniform float uZoom;
varying vec2 vCorner;
varying vec3 vCenterW;
varying float vR;
varying vec4 vTint;
void main() {
  vCorner = position.xy;
  vR = iSize * uZoom;
  vTint = iColor;
  vec4 w = modelMatrix * vec4(iOffset, 1.0);
  vCenterW = w.xyz;
  vec4 mv = viewMatrix * w;
  mv.xy += position.xy * iSize * uZoom;
  gl_Position = projectionMatrix * mv;
}`;

// A lens, not a ball (PLUGIN_GOAL 88: "colorless but still applying a glassy
// lens material effect"): almost clear at its centre, a fresnel rim at its
// edge, and each result's point light reflected off it as a highlight -- the
// "point source light ... that reflects off the glassy lensing". Computed per
// fragment on the impostor's own sphere normal, in WORLD space, so the lights
// are uniforms set when the results change, not every frame.
const GLASS_FRAG = `
uniform vec3 uLightPos[${MAX_LIGHTS}];
uniform vec3 uLightCol[${MAX_LIGHTS}];
uniform float uLightI[${MAX_LIGHTS}];
uniform int uLights;
uniform float uFall;
uniform float uHue;
uniform float uBright;
varying vec2 vCorner;
varying vec3 vCenterW;
varying float vR;
varying vec4 vTint;
vec3 turnHue(vec3 c, float a) {
  const vec3 k = vec3(0.57735027);
  float ca = cos(a);
  return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}
void main() {
  float r2 = dot(vCorner, vCorner);
  if (r2 > 1.0) discard;
  vec3 nV = vec3(vCorner, sqrt(1.0 - r2));
  vec3 n = normalize((vec4(nV, 0.0) * viewMatrix).xyz);
  vec3 P = vCenterW + n * vR;
  vec3 V = normalize(cameraPosition - P);
  float fres = pow(1.0 - max(dot(n, V), 0.0), 3.0);
  // The orb's own colour and how much it glows (iColor.a): 1 for the default
  // glowing orb (2026-10-11: "standardize the latent glowing glass orbs as the
  // default"), 0 for the colourless lens a search turns the rest into.
  float glow = vTint.a;
  vec3 tint = uHue == 0.0 ? vTint.rgb : clamp(turnHue(vTint.rgb, uHue), 0.0, 1.0);
  vec3 glassC = mix(vec3(0.82, 0.88, 1.0), tint, min(glow, 1.0));
  // uBright (2026-10-12: "the nodes could be a little larger/brighter by
  // default ... so that I see more color"): the orb's own colour and its
  // glow's opacity, scaled.
  vec3 col = glassC * (0.05 + 0.55 * fres) + tint * glow * uBright * (0.10 + 0.30 * (1.0 - fres));
  float a = 0.05 + 0.42 * fres + 0.20 * uBright * min(glow, 2.5);
  for (int i = 0; i < ${MAX_LIGHTS}; i++) {
    if (i >= uLights) break;
    vec3 L = uLightPos[i] - P;
    float d = length(L);
    L /= max(d, 1e-4);
    float att = uLightI[i] / (1.0 + (d / uFall) * (d / uFall));
    float spec = pow(max(dot(reflect(-L, n), V), 0.0), 40.0);
    float lens = pow(max(dot(-L, V), 0.0), 6.0) * (1.0 - fres);
    col += uLightCol[i] * (1.7 * spec + 0.35 * fres * max(dot(n, L), 0.0) + 0.3 * lens) * att;
    a += (0.7 * spec + 0.12 * lens) * att;
  }
  gl_FragColor = vec4(col, clamp(a, 0.0, 0.92));
  #include <colorspace_fragment>
}`;

// **The liminal glow** (G-207, 2026-10-17: "a liminal diffuse-glow effect to
// our chunk nodes since they're currently pretty small and only reflect light
// rays through each other rather than something truly 'latent and luminal'
// where we can see the chunk nodes as brightness points"). A soft additive
// halo in the orb's own colour, drawn from the GLASS mesh's own instance
// buffers -- no slots of its own, so it cannot fall out of step -- at the
// orb's size times uHaloK but never under uMinPx on screen: a chunk too small
// to draw as a sphere still shows as a point of light.
const HALO_VERT = `
attribute vec3 iOffset;
attribute float iSize;
attribute vec4 iColor;
uniform float uZoom;
uniform float uHaloK;
uniform float uMinPx;
uniform float uPxView;
varying vec2 vCorner;
varying vec4 vTint;
void main() {
  vCorner = position.xy;
  vTint = iColor;
  vec4 mv = modelViewMatrix * vec4(iOffset, 1.0);
  float s = max(iSize * uZoom * uHaloK, uMinPx * max(-mv.z, 0.0) * uPxView);
  mv.xy += position.xy * s;
  gl_Position = projectionMatrix * mv;
}`;
const HALO_FRAG = `
uniform float uHue;
uniform float uHaloI;
uniform float uCore;
varying vec2 vCorner;
varying vec4 vTint;
vec3 turnHue(vec3 c, float a) {
  const vec3 k = vec3(0.57735027);
  float ca = cos(a);
  return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}
void main() {
  float r2 = dot(vCorner, vCorner);
  if (r2 > 1.0) discard;
  // Power vs diffuse (2026-10-17: "broader and less concentrated at their
  // centers, or a more smooth rolloff"): a broad (1 - r^2)^2 that reaches
  // zero smoothly at the edge, mixed with a little concentrated core by
  // uCore. The first gaussian clipped every orb's centre at 255.
  float diffuse = (1.0 - r2) * (1.0 - r2);
  float core = exp(-14.0 * r2);
  float f = mix(diffuse, core, uCore);
  vec3 tint = uHue == 0.0 ? vTint.rgb : clamp(turnHue(vTint.rgb, uHue), 0.0, 1.0);
  vec3 c = mix(tint, vec3(1.0), 0.12 * core);
  gl_FragColor = vec4(c * f * uHaloI * min(vTint.a, 1.5), 1.0);
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
  /** Drawn as glass: colourless, a lens lit by the search's lights (item 88). */
  glass?: boolean;
  /** A search result's own brightness, 0..1 (item 88). */
  glow?: number;
}

export class SceneBatch {
  private opaque: Mesh;
  private clear: Mesh;
  private glass: Mesh;
  /** The glass orbs' glow (G-207): the glass geometry, an additive material. */
  private halo: THREE.Mesh;
  private lines: THREE.LineSegments;
  private linePos: THREE.BufferAttribute;
  private lineCol: THREE.BufferAttribute;
  private lineCap = 0;
  private atlas: THREE.DataTexture;
  private atlasReady = false;
  private cells = new Map<string, number>();       // src -> cell index
  private pending = new Set<string>();              // src queued or being decoded
  /** Pictures that would not load: never asked for again (2026-10-11, the
   *  freeze -- every frame re-requested every failed picture). */
  private failed = new Set<string>();
  /** Decodes waiting their turn, and how many are running (`MAX_LOADS`). */
  private queue: string[] = [];
  private queueAt = 0;
  private inFlight = 0;
  plantFifoLoads = false;
  /** The glass orbs' colour and glow, scaled (2026-10-12, PLUGIN_GOAL 115). */
  nodeBright = 1.4;
  /** A link's opacity (was 0.25): links visible, the nodes' colour first. */
  linkAlpha = 0.14;
  setBright(b: number): void {
    this.nodeBright = b;
    const m: any = this.glass && (this.glass.mesh.material as any);
    if (m && m.uniforms && m.uniforms.uBright) m.uniforms.uBright.value = b;
  }
  /** Planted: every picture fetched at once and failures retried each frame. */
  plantUnthrottled = false;
  /** Planted: a picture not loaded yet draws as the old opaque sphere. */
  plantSphereFallback = false;
  /** Planted: a mesh change defers to a full sync, as before. */
  plantNoMove = false;
  loadStats = { started: 0, placed: 0, failed: 0, maxInFlight: 0 };
  /** Told when a picture lands in the atlas: what is drawn has changed. */
  onPlaced: (() => void) | null = null;
  private nextCell = 0;
  private colours = new Map<string, THREE.Color>();
  lastStats = { drawCalls: 3, opaque: 0, translucent: 0, glass: 0, spheres: 0, pending_pictures: 0, lines: 0, atlasCells: 0, atlasFull: 0, syncMs: 0 };

  constructor(private scene: THREE.Scene, private renderer: THREE.WebGLRenderer,
              private load: (src: string) => Promise<Picture | null>) {
    this.atlas = new THREE.DataTexture(new Uint8Array(4), 1, 1);   // replaced on first use
    this.opaque = this.makeMesh(512, false);
    this.clear = this.makeMesh(128, true);
    this.glass = this.makeMesh(128, true, true);
    this.lines = this.makeLines(1024);
    this.linePos = this.lines.geometry.getAttribute("position") as THREE.BufferAttribute;
    this.lineCol = this.lines.geometry.getAttribute("color") as THREE.BufferAttribute;
    this.halo = this.makeHalo();
    scene.add(this.opaque.mesh, this.clear.mesh, this.glass.mesh, this.halo, this.lines);
  }

  /** Glow on screen: the halo's factor on the orb, its floor in pixels, its intensity. */
  // 2026-10-17: "way too low glow" at 3.2 / 5 px / 0.55; then "broader and
  // less concentrated at their centers": wider, a lower peak, mostly diffuse.
  haloK = 6;
  haloMinPx = 12;
  haloI = 0.75;
  /** 0 all diffuse, 1 all concentrated core. */
  haloCore = 0.15;
  private makeHalo(): THREE.Mesh {
    const mat = new THREE.ShaderMaterial({
      vertexShader: HALO_VERT, fragmentShader: HALO_FRAG,
      uniforms: { uZoom: { value: this.zoom }, uHaloK: { value: this.haloK }, uMinPx: { value: this.haloMinPx },
                  uPxView: { value: 0.002 }, uHue: { value: 0 }, uHaloI: { value: this.haloI }, uCore: { value: this.haloCore } },
      transparent: true, depthWrite: false, depthTest: true,
      // Colour ADDED, alpha left alone. The canvas is transparent over the
      // pane, and AdditiveBlending also added the halo's alpha: its faint
      // fringe turned opaque and nearly black over the pane's grey -- a dark
      // disc round every node (2026-10-17: "dark halo rings around the
      // nodes"). With alpha untouched the glow adds to whatever is behind.
      blending: THREE.CustomBlending, blendEquation: THREE.AddEquation,
      blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor,
      blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor,
    });
    const m = new THREE.Mesh(this.glass.geo, mat);
    m.frustumCulled = false;
    // FIRST, before every node: a picture drawn after it covers the light it
    // added -- a presented image is not washed out by glows around or in
    // front of it (2026-10-17: "the hovered node images should occlude other
    // light sources"). The glass orbs, drawn later, sit over their own glow.
    m.renderOrder = 0;
    (m as any).__batch = true;
    m.raycast = () => {};
    return m;
  }
  /** Pixels -> view-space units at unit depth, for the halo's floor: 2 / (H * P[1][1]). */
  setViewport(heightPx: number, projYY: number): void {
    const u = (this.halo.material as THREE.ShaderMaterial).uniforms;
    if (heightPx > 0 && projYY > 0) u.uPxView.value = 2 / (heightPx * projYY);
  }
  setHalo(on: boolean): void { this.halo.visible = on && this.glass.mesh.visible; this.haloOn = on; }
  /** Tune the glow live: size factor, pixel floor, intensity, core share. */
  tuneHalo(t: { k?: number; minPx?: number; i?: number; core?: number }): void {
    const u = (this.halo.material as THREE.ShaderMaterial).uniforms;
    if (t.k !== undefined) u.uHaloK.value = this.haloK = t.k;
    if (t.minPx !== undefined) u.uMinPx.value = this.haloMinPx = t.minPx;
    if (t.i !== undefined) u.uHaloI.value = this.haloI = t.i;
    if (t.core !== undefined) u.uCore.value = this.haloCore = t.core;
  }
  private haloOn = true;

  private material(translucent: boolean, glass = false): THREE.ShaderMaterial {
    if (glass) {
      return new THREE.ShaderMaterial({
        vertexShader: GLASS_VERT, fragmentShader: GLASS_FRAG,
        uniforms: {
          uLightPos: { value: Array.from({ length: MAX_LIGHTS }, () => new THREE.Vector3()) },
          uLightCol: { value: Array.from({ length: MAX_LIGHTS }, () => new THREE.Vector3()) },
          uLightI: { value: new Array(MAX_LIGHTS).fill(0) },
          uLights: { value: 0 },
          uFall: { value: 60 },
          uHue: { value: 0 },
          uBright: { value: this.nodeBright },
          uZoom: { value: this.zoom },
        },
        transparent: true, depthWrite: false,
      });
    }
    return new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { atlas: { value: this.atlas }, uHue: { value: 0 }, uZoom: { value: this.zoom } },
      transparent: translucent, depthWrite: !translucent,
    });
  }

  private makeMesh(cap: number, translucent: boolean, glass = false): Mesh {
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
    m.mesh = new THREE.Mesh(geo, this.material(translucent, glass));
    m.mesh.frustumCulled = false;           // instances span the whole cloud
    m.mesh.renderOrder = glass ? 3 : translucent ? 2 : 1;
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
      // Cleared only past what a corpus can hold: at 4,096 a 23k-node graph
      // of distinct hues re-parsed every colour every frame (1.9 s in 7).
      if (this.colours.size > 1 << 17) this.colours.clear();
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
    if (this.pending.has(src)) {
      // Asked for again while still queued: to the TOP of the stack, so the
      // picture under the pointer now is not buried under the sweep that
      // first queued it (two of three hovered pictures took 5 s, 2026-10-17).
      if (!this.plantFifoLoads) {
        const at = this.queue.lastIndexOf(src);
        if (at >= 0 && at < this.queue.length - 4) { this.queue.splice(at, 1); this.queue.push(src); }
      }
      return undefined;
    }
    if (this.failed.has(src) && !this.plantUnthrottled) return undefined;
    if (this.nextCell >= PER_ROW * PER_ROW) { this.lastStats.atlasFull++; return undefined; }
    this.pending.add(src);
    this.queue.push(src);
    this.pump();
    return undefined;
  }

  /** Start queued decodes up to `MAX_LOADS` at once. */
  private pump(): void {
    const cap = this.plantUnthrottled ? Infinity : MAX_LOADS;
    while (this.inFlight < cap && this.queueAt < this.queue.length) {
      // NEWEST first (2026-10-17): the picture under the pointer now is the
      // one being presented; first-in-first-out left it behind every picture
      // the pointer had swept past (3 of 6 hovered pictures still pending
      // after 8 s). Planted `plantFifoLoads`: the old order.
      const src = this.plantFifoLoads ? this.queue[this.queueAt++] : (this.queue.pop() as string);
      this.inFlight++;
      this.loadStats.started++;
      this.loadStats.maxInFlight = Math.max(this.loadStats.maxInFlight, this.inFlight);
      void this.load(src).then((img) => this.place(src, img), () => this.place(src, null));
    }
    if (this.queueAt > 256 && this.queueAt * 2 > this.queue.length) {
      this.queue = this.queue.slice(this.queueAt); this.queueAt = 0;
    }
  }

  /** A decode finished: copy it into the next cell, or remember it failed. */
  private place(src: string, img: Picture | null): void {
    this.inFlight--;
    this.pending.delete(src);
    try {
      if (!img) { this.failed.add(src); this.loadStats.failed++; return; }
      if (this.nextCell >= PER_ROW * PER_ROW) return;
      this.ensureAtlas();
      const cell = this.nextCell++;
      // Fit the picture into its cell, aspect kept, on a small canvas the
      // GPU copies into the atlas page (never a re-upload of the page).
      const cv = document.createElement("canvas");
      cv.width = CELL; cv.height = CELL;
      const g = cv.getContext("2d");
      if (!g) return;
      const iw = (img as any).naturalWidth || img.width || CELL, ih = (img as any).naturalHeight || img.height || CELL;
      const k = Math.min(CELL / iw, CELL / ih);
      const w = Math.max(1, Math.round(iw * k)), h = Math.max(1, Math.round(ih * k));
      g.drawImage(img, (CELL - w) / 2, (CELL - h) / 2, w, h);
      const small = new THREE.CanvasTexture(cv);
      small.flipY = false;
      small.colorSpace = THREE.SRGBColorSpace;
      const x = (cell % PER_ROW) * CELL, y = Math.floor(cell / PER_ROW) * CELL;
      try { this.renderer.copyTextureToTexture(small, this.atlas, null, new THREE.Vector2(x, y)); }
      catch { /* context lost: the cell stays a sphere */ }
      small.dispose();
      this.cells.set(src, cell);
      this.loadStats.placed++;
      this.onPlaced?.();
    } finally {
      if (img && typeof (img as any).close === "function") (img as any).close();
      this.pump();
    }
  }

  /** One frame: every node and edge written into the three batches. */
  sync(nodes: any[], links: any[], look: (n: any) => NodeLook | null,
       lineAlpha: ((l: any) => number) | null = null): void {
    const t0 = performance.now();
    this.grow(this.opaque, nodes.length);
    this.grow(this.clear, nodes.length);
    this.grow(this.glass, nodes.length);
    let no = 0, nt = 0, ng = 0, spheres = 0, pendingPics = 0;
    this.slots = [[], [], []];
    for (const n of nodes) {
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) continue;
      const lk = look(n);
      if (!lk) continue;
      let cell: number | undefined;
      if (lk.picture) cell = this.cellOf(lk.picture);
      // A picture not in the atlas yet (or never: it failed) is the node's
      // glowing orb meanwhile, not the old opaque sphere (2026-10-11: "still
      // seeing older nodes" -- 282 url icons drew as flat spheres until their
      // pictures landed). Planted: the old fallback.
      const pending = !!lk.picture && cell === undefined && !lk.translucent && !this.plantSphereFallback;
      const toGlass = lk.glass || pending;
      const m = toGlass ? this.glass : lk.translucent ? this.clear : this.opaque;
      const i = toGlass ? ng++ : lk.translucent ? nt++ : no++;
      n.__bm = toGlass ? 2 : lk.translucent ? 1 : 0; n.__bi = i; n.__bpic = cell !== undefined;
      this.slots[n.__bm][i] = n;
      m.offset.setXYZ(i, n.x, n.y, n.z || 0);
      m.size.setX(i, lk.half);
      const col = this.colour(lk.color);
      if (pending) { pendingPics++; m.uv.setXYZW(i, 0, 0, -1, 0); m.color.setXYZW(i, col.r, col.g, col.b, 1); continue; }
      if (!toGlass && !lk.translucent && cell === undefined) spheres++;     // the old opaque material
      if (cell !== undefined) {
        const u0 = (cell % PER_ROW) / PER_ROW, v0 = Math.floor(cell / PER_ROW) / PER_ROW;
        // Row 0 of the atlas is the picture's top: the quad's top corner reads v0.
        m.uv.setXYZW(i, u0, v0 + 1 / PER_ROW, u0 + 1 / PER_ROW, v0);
        const pg = lk.glow || 0;
        m.color.setXYZW(i, 1 + pg, 1, 1, lk.alpha);
        n.imgLoaded = true;
      } else {
        m.uv.setXYZW(i, lk.glow || 0, 0, -1, 0);
        m.color.setXYZW(i, col.r, col.g, col.b, lk.alpha);
      }
    }
    for (const [m, count] of [[this.opaque, no], [this.clear, nt], [this.glass, ng]] as [Mesh, number][]) {
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
      // 3d-force-graph's own link colour (#f0f0f0) at the pane's linkOpacity;
      // during a search, the pane says how much of an edge to draw (item 88).
      const a = lineAlpha ? lineAlpha(l) : this.linkAlpha;
      // A typed edge (G-241: a code CALLS / INHERITS) carries its own colour.
      if (l.color) {
        const c = this.colour(l.color), la = l.alpha ?? 0.85;
        this.lineCol.setXYZW(nl * 2, c.r, c.g, c.b, la);
        this.lineCol.setXYZW(nl * 2 + 1, c.r, c.g, c.b, la);
      } else {
        this.lineCol.setXYZW(nl * 2, 0.87, 0.87, 0.87, a);
        this.lineCol.setXYZW(nl * 2 + 1, 0.87, 0.87, 0.87, a);
      }
      nl++;
    }
    this.lines.geometry.setDrawRange(0, nl * 2);
    this.linePos.needsUpdate = true;
    this.lineCol.needsUpdate = true;
    this.lastStats = { drawCalls: ng ? 4 : 3, opaque: no, translucent: nt, glass: ng, spheres, pending_pictures: pendingPics, lines: nl, atlasCells: this.nextCell,
                       atlasFull: this.lastStats.atlasFull, syncMs: Math.round((performance.now() - t0) * 100) / 100 };
  }

  /**
   * The lights the glass is lit by, in WORLD space: one per shown search
   * result, brightest first, at most `MAX_LIGHTS` (item 88). `fall` is the
   * distance at which a light has fallen to half.
   */
  lightStats = { lights: 0, fall: 0 };
  setLights(lights: { at: [number, number, number]; color: string; intensity: number }[], fall: number): void {
    const u = (this.glass.mesh.material as THREE.ShaderMaterial).uniforms;
    const use = lights.slice(0, MAX_LIGHTS);
    use.forEach((l, i) => {
      (u.uLightPos.value[i] as THREE.Vector3).set(l.at[0], l.at[1], l.at[2]);
      const c = this.colour(l.color);
      (u.uLightCol.value[i] as THREE.Vector3).set(c.r, c.g, c.b);
      u.uLightI.value[i] = l.intensity;
    });
    u.uLights.value = use.length;
    u.uFall.value = Math.max(1e-3, fall);
    this.lightStats = { lights: use.length, fall: Math.round(fall * 10) / 10 };
  }

  /** Display-only size factor with the camera's distance (G-206). */
  zoom = 1;
  setZoom(f: number): void {
    if (Math.abs(f - this.zoom) < 1e-4) return;
    this.zoom = f;
    for (const m of [this.opaque.mesh, this.clear.mesh, this.glass.mesh, this.halo]) {
      const u = (m.material as THREE.ShaderMaterial).uniforms;
      if (u.uZoom) u.uZoom.value = f;
    }
  }

  /** The colours' turn about the grey axis, radians (item 83). */
  hue = 0;
  setHue(a: number): void {
    this.hue = a;
    for (const m of [this.opaque, this.clear, this.glass]) (m.mesh.material as THREE.ShaderMaterial).uniforms.uHue.value = a;
    (this.halo.material as THREE.ShaderMaterial).uniforms.uHue.value = a;
  }

  /**
   * A LOOK change for a few nodes, written into their slots in place -- not a
   * full sync of every node (2026-10-11: "node hover and image/glow features
   * ... have a noticeably slow latency": a glow change re-synced all 22,663
   * nodes, 13.8 ms, to change about 64). Only colour and glow move; a node
   * whose look would change pass (glass/opaque/clear) or picture-ness is left
   * for the next full sync, and says so in the return value.
   */
  patchStats = { patches: 0, nodes: 0, deferred: 0, moved: 0, last_ms: 0 };
  /** The node in each instance slot, per mesh (opaque, clear, glass), as of the last sync. */
  private slots: any[][] = [[], [], []];
  private meshOf(k: number): Mesh { return k === 2 ? this.glass : k === 1 ? this.clear : this.opaque; }
  /** Write one node's look into slot `i` of `m`. */
  private writeSlot(m: Mesh, i: number, n: any, lk: NodeLook, cell: number | undefined, pending: boolean): void {
    m.offset.setXYZ(i, n.x, n.y, n.z || 0);
    m.size.setX(i, lk.half);
    if (cell !== undefined) {
      const u0 = (cell % PER_ROW) / PER_ROW, v0 = Math.floor(cell / PER_ROW) / PER_ROW;
      m.uv.setXYZW(i, u0, v0 + 1 / PER_ROW, u0 + 1 / PER_ROW, v0);
      m.color.setXYZW(i, 1 + (lk.glow || 0), 1, 1, lk.alpha);
    } else {
      const col = this.colour(lk.color);
      m.uv.setXYZW(i, pending ? 0 : (lk.glow || 0), 0, -1, 0);
      m.color.setXYZW(i, col.r, col.g, col.b, pending ? 1 : lk.alpha);
    }
  }
  /** Move a node's instance to another mesh: swap-remove, then append. */
  private moveSlot(n: any, to: number): boolean {
    const from = this.meshOf(n.__bm), dst = this.meshOf(to);
    const i = n.__bi, last = from.geo.instanceCount - 1;
    if (i > last || this.slots[n.__bm][i] !== n || dst.geo.instanceCount + 1 > dst.cap) return false;
    if (i !== last) {
      const other = this.slots[n.__bm][last];
      for (const a of [from.offset, from.size, from.color, from.uv]) {
        for (let c = 0; c < a.itemSize; c++) (a.array as Float32Array)[i * a.itemSize + c] = (a.array as Float32Array)[last * a.itemSize + c];
      }
      this.slots[n.__bm][i] = other; if (other) other.__bi = i;
    }
    // (A full destination was refused above: `grow` reallocates WITHOUT
    // copying -- it precedes a full sync -- so that is the full sync's job.)
    this.slots[n.__bm].length = last;
    from.geo.instanceCount = last;
    const j = dst.geo.instanceCount;
    dst.geo.instanceCount = j + 1;
    this.slots[to][j] = n;
    n.__bm = to; n.__bi = j;
    return true;
  }
  patch(nodes: Iterable<any>, look: (n: any) => NodeLook | null): number {
    const t0 = performance.now();
    let done = 0, deferred = 0, moved = 0;
    const touched = new Set<Mesh>([this.opaque, this.clear, this.glass].filter(() => false));
    for (const n of nodes) {
      if (n.__bi === undefined) { deferred++; continue; }
      const lk = look(n);
      if (!lk) { deferred++; continue; }
      const cell = lk.picture ? this.cells.get(lk.picture) : undefined;
      const pending = !!lk.picture && cell === undefined && !lk.translucent && !this.plantSphereFallback;
      const want = (lk.glass || pending) ? 2 : lk.translucent ? 1 : 0;
      if (want !== n.__bm) {
        // Revealed or hidden picture, hover in or out: the node changes mesh.
        if (this.plantNoMove || !this.moveSlot(n, want)) { deferred++; continue; }
        touched.add(this.meshOf(want)); touched.add(this.meshOf(n.__bm === want ? want : n.__bm));
        moved++;
      }
      const m = this.meshOf(want);
      const i = n.__bi;
      if (i >= m.geo.instanceCount) { deferred++; continue; }
      this.writeSlot(m, i, n, lk, cell, pending);
      n.__bpic = cell !== undefined;
      touched.add(m);
      done++;
    }
    if (moved) { touched.add(this.opaque); touched.add(this.clear); touched.add(this.glass); }
    for (const m of touched) { m.offset.needsUpdate = true; m.color.needsUpdate = true; m.uv.needsUpdate = true; m.size.needsUpdate = true; }
    this.patchStats = { patches: this.patchStats.patches + 1, nodes: this.patchStats.nodes + done,
                        deferred: this.patchStats.deferred + deferred, moved: this.patchStats.moved + moved,
                        last_ms: Math.round((performance.now() - t0) * 100) / 100 };
    return deferred;
  }

  setVisible(on: boolean): void {
    this.opaque.mesh.visible = on;
    this.clear.mesh.visible = on;
    this.glass.mesh.visible = on;
    this.halo.visible = on && this.haloOn;
    this.lines.visible = on;
  }

  dispose(): void {
    this.scene.remove(this.opaque.mesh, this.clear.mesh, this.glass.mesh, this.halo, this.lines);
    for (const m of [this.opaque, this.clear, this.glass]) { m.geo.dispose(); (m.mesh.material as THREE.Material).dispose(); }
    (this.halo.material as THREE.Material).dispose();      // its geometry is the glass mesh's
    this.lines.geometry.dispose(); (this.lines.material as THREE.Material).dispose();
    this.atlas.dispose();
  }
}
