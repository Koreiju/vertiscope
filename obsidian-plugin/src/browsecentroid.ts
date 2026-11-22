/**
 * The browser centroid node in 3D (G-205; BROWSER_CENTROID_DESIGN.md §4.3):
 * the retrieval artifact's HANDLE in the world. It stands at the centroid of
 * the artifact's results as the world draws them, with a ray from it to each
 * result's node; a click on it opens the artifact's card on the plane.
 *
 * A result's node is its chunk's node when the world draws that chunk, else
 * its page's node (a folded page draws only its page). A result the world
 * draws neither way gets no ray, and is counted, never placed by guess.
 *
 * Reads the card's artifact (a view of the sidecar's session) and the world's
 * node positions; writes only its own THREE group. Patricia-trie terms: the
 * rays join trie reads (the results) to the trie's addresses as drawn.
 */
import * as THREE from "three";

export class BrowseCentroid {
  group: any = null;
  private key = "";
  /** What the last frame drew: for the live check and the reader's status. */
  drawn = { results: 0, rays: 0, unplaced: 0, version: -1, at: [0, 0, 0] as number[], rebuilt: 0, clicks: 0 };
  /** Planted: the node drawn at the world's origin, not at its results. */
  plantAtOrigin = false;

  constructor(private artifact: () => { art: any; version: number } | null, private openCard: () => void) {}

  /** One frame: place the node and its rays; rebuild only when the artifact
   *  or a result's position moved by more than a unit. */
  frame(g: any): void {
    const got = this.artifact();
    const art = got?.art;
    const results: any[] = (art && art.results) || [];
    if (!results.length) { if (this.group) this.group.visible = false; this.drawn.results = 0; this.drawn.rays = 0; return; }
    const nodes: any[] = g.graphData().nodes;
    const byId = new Map<string, any>(), pageOf = new Map<string, any>();
    for (const n of nodes) {
      if (n.id) byId.set(String(n.id), n);
      if (n.level === "page" && n.url) pageOf.set(String(n.url).split("#")[0], n);
    }
    const ends: number[][] = [];
    let unplaced = 0;
    for (const h of results) {
      const n = byId.get(String(h.cid)) || pageOf.get(String(h.url || "").split("#")[0]);
      if (n && Number.isFinite(n.x)) ends.push([n.x, n.y, n.z || 0]); else unplaced++;
    }
    if (!ends.length) { if (this.group) this.group.visible = false; this.drawn.unplaced = unplaced; return; }
    const c = this.plantAtOrigin ? [0, 0, 0] : [0, 1, 2].map((i) => ends.reduce((s, p) => s + p[i], 0) / ends.length);
    if (!this.group) {
      this.group = new THREE.Group();
      const node = new THREE.Mesh(new THREE.OctahedronGeometry(4.5), new THREE.MeshBasicMaterial({ color: 0xffd166 }));
      (node as any).__browseCentroid = true;
      const rays = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xffd166, transparent: true, opacity: 0.45 }));
      this.group.add(node, rays);
    }
    if (this.group.parent !== g.scene()) g.scene().add(this.group);
    this.group.visible = true;
    const key = (got?.version ?? 0) + "|" + c.map(Math.round).join(",") + "|" + ends.map((p) => p.map(Math.round).join(",")).join(";");
    if (key !== this.key) {
      this.key = key;
      const [node, rays] = this.group.children;
      node.position.set(c[0], c[1], c[2]);
      const pts: any[] = [];
      for (const p of ends) pts.push(new THREE.Vector3(c[0], c[1], c[2]), new THREE.Vector3(p[0], p[1], p[2]));
      rays.geometry.dispose(); rays.geometry = new THREE.BufferGeometry().setFromPoints(pts);
      this.drawn.rebuilt++;
    }
    this.drawn.results = results.length; this.drawn.rays = ends.length; this.drawn.unplaced = unplaced;
    this.drawn.version = got?.version ?? 0; this.drawn.at = c.map((v) => Math.round(v * 10) / 10);
  }

  /** Is the centroid node under this screen point? (the scene's own raycaster) */
  hit(g: any, clientX: number, clientY: number): boolean {
    if (!this.group || !this.group.visible) return false;
    const el: HTMLElement = g.renderer().domElement, r = el.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    const rc = new THREE.Raycaster();
    rc.setFromCamera(ndc, g.camera());
    return rc.intersectObject(this.group.children[0], false).length > 0;
  }

  click(): void { this.drawn.clicks++; this.openCard(); }

  /** Where the node is on screen (for a real click by a probe). */
  screenAt(g: any): { x: number; y: number } | null {
    if (!this.group || !this.group.visible) return null;
    const v = this.group.children[0].position.clone().project(g.camera());
    const r = g.renderer().domElement.getBoundingClientRect();
    return { x: r.left + (v.x + 1) / 2 * r.width, y: r.top + (1 - v.y) / 2 * r.height };
  }
}
