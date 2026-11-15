/**
 * The "user agent": a throttle, a switch between the global MAP view and the
 * EGO traversal view, a slow STATEFUL flight to what is hovered, and full
 * rotational control from the keyboard (PLUGIN_GOAL 2026-10-29, items 1-3,
 * 9, 11, 14, 17-22).
 *
 * The reader's words, in the order they corrected the first build:
 * "a very slow tracking fly-to-node as we hover ... the forward movement is
 * of course stopped for some standard camera zoom (non adaptive, hard
 * floor)"; "The adaptive motion and zoom is a bad idea. The two should be
 * independent"; "switching node hovers should diff the same ego motion
 * trajectory"; "so, ego motion is stateful"; "q and r are camera normal
 * rotation"; "arrow keys for camera pan over the focus, coupled with q r for
 * normal, gives full 3 DOF rotational motion control"; "I'd also like to see
 * the keypresses alongside the ego throttle panel ... for when keyboard
 * controls are pressed and for what action".
 *
 * So the flight is a CRAFT with a velocity: its speed is the throttle's
 * (world units a second, nothing to do with zoom), its heading turns toward
 * the target at a bounded rate -- a new hover bends the trajectory in flight
 * rather than starting another -- and it brakes so as to stop at the FLOOR,
 * a fixed distance from the target, never nearer. The wheel zooms on its
 * own. With no target the craft coasts to a stop. Arrows turn the camera
 * about the focus (yaw, pitch); Q/E roll it about the view normal.
 *
 * A key acts only while the pointer is over the graph and nothing is typed
 * into -- the rule `arrowPan` already followed.
 *
 * And SELECTIVELY (2026-10-30, items 39, 46): "ego motion is always happening
 * rather than selectively"; "ego motion should respect zoom outs when flying
 * to new nodes as well". A flight stops at the reader's own zoom distance
 * (`standoff`, never nearer than the floor) and ENDS there: the target is
 * released once the craft is at rest and aimed, and nothing moves the camera
 * again until the next hover or key. A reader's own drag is a hand on the
 * stick: target and velocity both dropped (`release`).
 */

export type AgentMode = "ego" | "map";

export interface AgentHost {
  camera(): any;
  controls(): any;
  /** Fly back out to the whole picture (the "recentre" action). */
  recentre(): void;
  /** The reader acted: idle turns stop. `trusted` false: a check's synthetic key, not the reader. */
  touched(what: string, trusted?: boolean): void;
  /** World units: the nearest a camera may be to `n` and still see all of
   *  it (graph.ts: its drawn radius over the half field of view). */
  fit?(n: any): number;
  /** End a running camera tween where the camera is now (G-311). */
  haltTween?(): void;
}

const KEY = "domvec.useragent";

/** The keys the agent answers, and what each does, as the strip shows them. */
export const CAPS: [string, string, string][] = [
  ["w", "W", "forward"], ["a", "A", "slide left"], ["s", "S", "back"], ["d", "D", "slide right"],
  ["v", "V", "first / third person"],
  ["q", "Q", "roll left"], ["e", "E", "roll right"],
  ["ArrowLeft", "←", "yaw left about the focus"], ["ArrowRight", "→", "yaw right about the focus"],
  ["ArrowUp", "↑", "pitch up about the focus"], ["ArrowDown", "↓", "pitch down about the focus"],
  ["Shift", "⇧", "throttle up"], ["Control", "ctrl", "throttle down"],
];
// Z, X and M (full throttle, pause, map/ego) are deprecated (2026-10-29:
// "zxm etc are deprecated as well. not needed"). Pause and the view switch
// remain as state, to be driven from the dialect's controls (G-274).

function v3(x = 0, y = 0, z = 0) { return { x, y, z }; }
function len(a: any) { return Math.hypot(a.x, a.y, a.z); }

/** Rotate vector `p` about unit axis `k` by angle `t` (Rodrigues). */
function rotate(p: any, k: any, t: number) {
  const c = Math.cos(t), s = Math.sin(t), d = p.x * k.x + p.y * k.y + p.z * k.z;
  return v3(p.x * c + (k.y * p.z - k.z * p.y) * s + k.x * d * (1 - c),
            p.y * c + (k.z * p.x - k.x * p.z) * s + k.y * d * (1 - c),
            p.z * c + (k.x * p.y - k.y * p.x) * s + k.z * d * (1 - c));
}

export class UserAgent {
  mode: AgentMode = "ego";
  /** 0..1 of `vmax`. */
  throttle = 0.25;
  paused = false;
  /** World units: flight stops this far from its target (the hard floor). */
  floor = 24;
  /** World units a second at full throttle. */
  vmax = 160;
  /** World units a second squared: how hard the craft speeds up and brakes. */
  accel = 120;
  /** Radians a second the heading may turn toward a new target. */
  turn = 1.6;
  /** Radians per key step for arrows and Q/E. */
  rotStep = 0.035;
  target: any = null;
  /** World units: where THIS flight stops -- the reader's zoom distance when
   *  it began, floored. A bend keeps it; a wheel re-reads it. */
  standoff = 24;
  /** The last node flown to, kept after the flight ends: the zoom floor's
   *  subject (graph.ts `applyZoomFloor`). */
  focus: any = null;
  private rezoom = false;
  /** The craft's velocity, world units a second: the state a new hover bends. */
  vel = v3();
  stats = { flights: 0, frames: 0, at_floor: 0, keys: 0, mode_switches: 0, last_d: 0, speed: 0, bends: 0, rolls: 0, orbits: 0,
           arrivals: 0, releases: 0, idle_ticks: 0, standoff: 0 };
  /** Planted: the old 0.4 s tween to wherever `zoomFor` said, no floor. */
  plantFastFlight = false;
  /** Planted: a new hover restarts the flight from rest (no carried velocity). */
  plantRestart = false;
  /**
   * A FLIGHT PLAN (items 8-9, 2026-10-29: "we can also draw flight plans for
   * various searches and anchored nodes ... We will have a throttle to set the
   * speed, the pause, and be able to plan efficiently that way"; G-283). An
   * ordered list of nodes; played, the craft flies to each in turn at the
   * throttle, each leg ending on arrival as any flight does (G-285). The
   * pause holds it; a hand on the stick (`release`) stops the play.
   */
  plan: any[] = [];
  planAt = -1;
  playing = false;
  planStats = { legs: 0, plays: 0, finished: 0, stopped: 0 };
  /** Planted (G-283): the play flies the first leg and stops there. */
  plantNoAdvance = false;
  setPlan(nodes: any[]): void { this.plan = nodes.filter((n) => n && Number.isFinite(n.x)); this.planAt = -1; }
  play(on: boolean): void {
    if (on === this.playing) return;
    this.playing = on && this.plan.length > 0;
    if (this.playing) { this.planStats.plays++; this.planAt = -1; this.target = null; }
  }
  private advance(): void {
    if (this.planAt >= 0 && this.plantNoAdvance) { this.playing = false; return; }
    const next = this.planAt + 1;
    if (next >= this.plan.length) { this.playing = false; this.planStats.finished++; return; }
    this.planAt = next;
    this.planStats.legs++;
    this.fly(this.plan[next]);
  }
  /** Planted (item 46): every flight closes to the floor, the reader's zoom-out lost. */
  plantIgnoreZoom = false;
  /** Planted (item 39): the target is held for good -- the aim pulls every frame. */
  plantHoldTarget = false;
  private hud: HTMLElement | null = null;
  private lit = new Map<string, number>();
  /** The last key and the action it took (item 19), as the cockpit shows it. */
  lastAction = "";
  /** The last keys and their actions, newest first: `{keys}`'s samples (G-280). */
  keyLog: string[] = [];

  constructor(private host: AgentHost) {
    try {
      const saved = JSON.parse(window.localStorage.getItem(KEY) || "{}");
      if (saved.mode === "map" || saved.mode === "ego") this.mode = saved.mode;
      if (typeof saved.throttle === "number") this.throttle = Math.max(0, Math.min(1, saved.throttle));
    } catch { /* a convenience only */ }
  }

  private save(): void {
    try { window.localStorage.setItem(KEY, JSON.stringify({ mode: this.mode, throttle: this.throttle })); }
    catch { /* a convenience only */ }
  }

  /** A hover asked to go to `n`. True when the agent took the flight. */
  fly(n: any): boolean {
    if (this.plantFastFlight) return false;
    if (this.mode === "map") { this.target = null; return true; }   // a hover moves nothing
    const bend = !!this.target && this.target !== n;
    if (bend) this.stats.bends++;
    if (this.plantRestart) this.vel = v3();
    // A NEW flight stops where the reader is zoomed to; a bend keeps the
    // flight's own standoff (mid-bend the look point is between two nodes).
    // Never nearer than `stopFloor(n)`.
    if (!bend) {
      const cam = this.host.camera(), ctl = this.host.controls();
      const dTarget = cam && ctl && ctl.target ? Math.hypot(cam.position.x - ctl.target.x, cam.position.y - ctl.target.y, cam.position.z - ctl.target.z) : this.floor;
      const dNode = cam && n && Number.isFinite(n.x) ? Math.hypot(cam.position.x - n.x, cam.position.y - n.y, cam.position.z - (n.z || 0)) : dTarget;
      const anchorD = Number.isFinite(dTarget) && dTarget > 1e-3 ? dTarget : (Number.isFinite(dNode) && dNode > 1e-3 ? dNode : this.floor);
      if (cam && ctl && ctl.target && Number.isFinite(anchorD) && anchorD > 1e-3) {
        const { back } = this.axes();
        ctl.target.set(cam.position.x - back.x * anchorD, cam.position.y - back.y * anchorD, cam.position.z - back.z * anchorD);
        if (ctl._zoomStart && ctl._zoomEnd) ctl._zoomStart.copy(ctl._zoomEnd);
        if (ctl._panStart && ctl._panEnd) ctl._panStart.copy(ctl._panEnd);
        if (typeof ctl._lastAngle === "number") ctl._lastAngle = 0;
      }
      const sf = this.stopFloor(n);
      const floorHere = Number.isFinite(dNode) && dNode < sf ? Math.max(1.5, dNode) : sf;
      this.standoff = this.plantIgnoreZoom ? this.floor : Math.max(floorHere, Number.isFinite(anchorD) ? anchorD : 0);
      this.stats.standoff = Math.round(this.standoff * 10) / 10;
    }
    this.target = n;
    this.focus = n;
    this.stats.flights++;
    return true;
  }

  /** One frame. `dt` in seconds. */
  tick(dt: number): void {
    const cam = this.host.camera(), ctl = this.host.controls();
    if (!cam || !ctl || !ctl.target) return;
    // Third person is the keyboard's chase view (G-333): the craft is at the
    // vehicle, the camera behind it -- a hover's flight does not move it.
    if (this.view === "third") { if (this.vehicle) this.craftAt = { ...this.vehicle.p }; this.target = null; this.fade(); return; }
    const p = cam.position, t = ctl.target;
    // ALWAYS at the centre of view (PLUGIN_GOAL 146), every tick, at rest
    // too: first person the craft is where the camera is (the cockpit); the
    // map view, at the focus the view turns about (the screen's centre).
    // Measured before: at rest it stayed where it last flew, 1,700 units off
    // screen. Planted `plantCraftLeftBehind`: only while flying, as before.
    if (!this.plantCraftLeftBehind) {
      this.craftAt = this.mode === "ego" ? { x: p.x, y: p.y, z: p.z } : { x: t.x, y: t.y, z: t.z };
    }
    const n = this.mode === "ego" ? this.target : null;
    // Nothing selected and at rest: the camera is the reader's alone.
    if (!n && len(this.vel) < 1e-4 && !(this.playing && !this.paused)) { this.stats.idle_ticks++; this.fade(); return; }
    // The craft is where the agent FLIES (item 68): its place follows the
    // camera only while the ego view is under way -- a mode switch alone
    // never moves it (each toggle once carried it outward with the camera).
    if (this.mode === "ego") this.craftAt = { x: p.x, y: p.y, z: p.z };
    if (this.rezoom) {
      this.rezoom = false;
      const dT = Math.hypot(p.x - t.x, p.y - t.y, p.z - t.z);
      const dN = n && Number.isFinite(n.x) ? Math.hypot(p.x - n.x, p.y - n.y, p.z - (n.z || 0)) : dT;
      const dz = Math.min(dT, dN);
      if (Number.isFinite(dz)) { this.standoff = Math.max(1.5, dz); this.vel = v3(); this.stats.standoff = Math.round(this.standoff * 10) / 10; }
    }
    let want = v3();
    let arrived = false;
    let turned = false;
    if (n && Number.isFinite(n.x) && !this.paused && this.throttle > 0) {
      const nx = n.x, ny = n.y, nz = n.z || 0;
      // Aim: the look point turns onto the node at the craft's turn rate.
      const ka = 1 - Math.exp(-this.turn * 2 * dt);
      t.x += (nx - t.x) * ka; t.y += (ny - t.y) * ka; t.z += (nz - t.z) * ka;
      turned = true;
      const to = v3(nx - p.x, ny - p.y, nz - p.z), d = len(to);
      this.stats.last_d = Math.round(d * 10) / 10;
      // Never back out when already zoomed in closer than `standoff`.
      const left = Math.max(0, d - this.standoff);
      if (left > 0.25) {
        // The speed the throttle asks for, capped so the craft can still stop
        // at the standoff: v^2 = 2 a s.
        const speed = Math.min(this.throttle * this.vmax, Math.sqrt(2 * this.accel * left));
        want = v3(to.x / d * speed, to.y / d * speed, to.z / d * speed);
      } else {
        this.stats.at_floor++;
        const off = Math.hypot(nx - t.x, ny - t.y, nz - t.z);
        arrived = off < Math.max(0.05, d * 0.01) && len(this.vel) < 0.5;
      }
    }
    // The heading turns toward `want` at most `turn` rad/s (the trajectory
    // BENDS); the speed changes at most `accel`.
    const sv = len(this.vel);
    let sw = len(want);
    let dir = sv > 1e-6 ? v3(this.vel.x / sv, this.vel.y / sv, this.vel.z / sv) : null;
    if (sw > 1e-6) {
      const wd = v3(want.x / sw, want.y / sw, want.z / sw);
      // Wanted BEHIND the heading (past the standoff, or zoomed in nearer
      // than it): brake to rest first, then set off the other way. Turning
      // round at the bounded rate kept the speed up through the half-circle,
      // and the craft orbited the node instead of stopping (live G-285,
      // 2026-10-30: 0 arrivals in six flights).
      if (dir && dir.x * wd.x + dir.y * wd.y + dir.z * wd.z < 0) {
        if (sv <= this.accel * dt) dir = wd; else sw = 0;
      } else if (!dir) dir = wd;
      else {
        const cos = Math.max(-1, Math.min(1, dir.x * wd.x + dir.y * wd.y + dir.z * wd.z));
        const ang = Math.acos(cos), maxA = this.turn * dt;
        if (ang <= maxA || ang < 1e-6) dir = wd;
        else {
          const axis = v3(dir.y * wd.z - dir.z * wd.y, dir.z * wd.x - dir.x * wd.z, dir.x * wd.y - dir.y * wd.x);
          const al = len(axis);
          dir = al > 1e-9 ? rotate(dir, v3(axis.x / al, axis.y / al, axis.z / al), maxA) : wd;
        }
      }
    }
    const ds = Math.max(-this.accel * dt, Math.min(this.accel * dt, sw - sv));
    const speed = Math.max(0, sv + ds);
    this.vel = dir ? v3(dir.x * speed, dir.y * speed, dir.z * speed) : v3();
    this.stats.speed = Math.round(speed * 10) / 10;
    if (speed > 1e-4) {
      let step = v3(this.vel.x * dt, this.vel.y * dt, this.vel.z * dt);
      // The floor is HARD when closing in: a step that would cross the
      // standoff lands ON it, at rest, without ever snapping backwards.
      if (n && Number.isFinite(n.x)) {
        const nz = n.z || 0;
        const d0 = Math.hypot(p.x - n.x, p.y - n.y, p.z - nz);
        const q = v3(p.x + step.x - n.x, p.y + step.y - n.y, p.z + step.z - nz);
        const dq = len(q);
        const stop = this.plantIgnoreZoom ? this.floor : this.standoff;
        if (d0 >= stop && dq < stop) {
          const k = stop / Math.max(dq, 1e-9);
          step = v3(n.x + q.x * k - p.x, n.y + q.y * k - p.y, nz + q.z * k - p.z);
          this.vel = v3();
        }
      }
      p.x += step.x; p.y += step.y; p.z += step.z;
      this.stats.frames++;
      ctl.update?.();
    } else if (turned) {
      this.stats.frames++;
      ctl.update?.();
    }
    // At the standoff, at rest, aimed: the flight is over.
    if (arrived && !this.plantHoldTarget) { this.target = null; this.vel = v3(); this.stats.arrivals++; }
    // A plan in play takes its next leg once the last has ended.
    if (this.playing && !this.target && !this.paused && this.mode === "ego") this.advance();
    this.fade();
  }

  /** The nearest a flight to `n` stops: the hard floor, or nearer than that
   *  never -- but no nearer than `n` fits the view either (item 38: "zoomed
   *  nodes all-the way are out of view"; a page node of radius 14 needs 33). */
  stopFloor(n: any): number {
    const f = this.host.fit ? this.host.fit(n) : 0;
    return Math.max(this.floor, Number.isFinite(f) ? f : 0);
  }

  /** The reader's own camera gesture: a hand on the stick. */
  release(): void {
    if (this.playing) { this.playing = false; this.planStats.stopped++; }
    if (!this.target && len(this.vel) < 1e-4) return;
    this.target = null;
    this.vel = v3();
    this.stats.releases++;
  }

  /** The wheel turned: the flight in progress stops at the new distance. */
  zoomed(): void { if (this.target) this.rezoom = true; }

  /** Where the craft is (PLUGIN_GOAL 68): the agent's place on its last
   *  flight in the ego view; null until it has flown. */
  craftAt: { x: number; y: number; z: number } | null = null;

  setMode(mode: AgentMode): void {
    if (mode === this.mode) return;
    this.mode = mode;
    this.stats.mode_switches++;
    this.target = null;
    // Third person (item 68): the craft is left where the agent was flying,
    // and the map view sees it there.
    if (mode === "map") { this.vel = v3(); this.host.recentre(); }
    this.save();
    this.draw();
  }

  setThrottle(v: number): void {
    this.throttle = Math.max(0, Math.min(1, Math.round(v * 100) / 100));
    if (this.throttle > 0) this.paused = false;
    this.save();
    this.draw();
  }

  /** KSP's keys, arrows and Q/E. Returns true when the key was the agent's. */
  key(e: KeyboardEvent): boolean {
    if (e.altKey || e.metaKey) return false;
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    const bare = (name: string) => e.key === name;           // shift/ctrl pressed ALONE
    let took = true;
    if (bare("Shift")) this.setThrottle(this.throttle + 0.05);
    else if (bare("Control")) this.setThrottle(this.throttle - 0.05);
    else if (e.ctrlKey || e.shiftKey) took = false;          // a shortcut, not ours
    else if (k === "w" || k === "s") this.move(k);
    // LATERAL in the camera plane (PLUGIN_GOAL 159, over 116's non-holonomic
    // A/D: "s and d keys should be lateral on the camera plane in the 3D
    // space, since the left-right arrows are better off with the rotational
    // aspect"). The arrows turn. Planted `plantTurnAD`: A/D turn the heading,
    // as 116 had them.
    else if (k === "a" || k === "d") { if (this.plantTurnAD) this.turnHeading(k === "a" ? 1 : -1); else this.move(k); }
    else if (k === "v") this.setView(this.view === "first" ? "third" : "first");
    // Q and E roll, as a pair (159: "a complementary roll function for *both*
    // q and e"). Planted `plantRollR`: the old Q/R pair.
    else if (k === "q" || k === (this.plantRollR ? "r" : "e")) this.roll(k === "q" ? -1 : 1);
    else if (k === "ArrowLeft" || k === "ArrowRight") this.orbit(k === "ArrowLeft" ? 1 : -1, 0);
    else if (k === "ArrowUp" || k === "ArrowDown") this.orbit(0, k === "ArrowUp" ? 1 : -1);
    else took = false;
    if (took) {
      this.stats.keys++;
      this.light(k);
      this.host.touched("user-agent", e.isTrusted);
    }
    return took;
  }

  keyUp(e: KeyboardEvent): void {
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (!this.lit.has(k)) return;
    // A short afterglow, cleared by a timer: the frame loop that also fades
    // stalls in a covered or unfocused window, and the key stayed lit.
    const until = performance.now() + 180;
    this.lit.set(k, until);
    window.setTimeout(() => { if (this.lit.get(k) === until) { this.lit.delete(k); this.draw(); } }, 200);
  }

  private axes() {
    const cam = this.host.camera(), ctl = this.host.controls();
    cam.updateMatrixWorld();
    const e = cam.matrixWorld.elements;
    return { cam, ctl, right: v3(e[0], e[1], e[2]), up: v3(e[4], e[5], e[6]), back: v3(e[8], e[9], e[10]) };
  }

  /**
   * **The vehicle** (PLUGIN_GOAL 116, G-333): the ego graph and its 3D map
   * move as ONE cockpit-like entity with a heading. In FIRST person the
   * camera is the vehicle; in THIRD person the camera rides behind and above
   * it, looking at it, and the ego craft is drawn where the vehicle is
   * (`craftAt`). W/S move along the heading, A/D turn it -- never sideways.
   */
  view: "first" | "third" = "first";
  plantCraftLeftBehind = false;
  plantStoredUp = false;
  /** Planted (G-333, 159): A/D turn the heading, as 116's vehicle had them. */
  plantTurnAD = false;
  /** Planted (159): roll right on R, as before; E does nothing. */
  plantRollR = false;
  vehicleStats = { turns: 0, views: 0, sideways_max: 0 };
  /** The vehicle's place and heading (third person keeps them apart from the camera). */
  vehicle: { p: any; dir: any } | null = null;
  /** Where the vehicle points (PLUGIN_GOAL 146): its own heading in third
   *  person, the camera's look in first (the camera IS the vehicle). */
  headingNow(): { x: number; y: number; z: number } | null {
    if (this.view === "third" && this.vehicle) return { x: this.vehicle.dir.x, y: this.vehicle.dir.y, z: this.vehicle.dir.z };
    const { back } = this.axes();
    return back ? { x: -back.x, y: -back.y, z: -back.z } : null;
  }
  /** The chase camera's distance behind the vehicle (third person); the wheel shortens it. */
  chaseD = 0;
  private cameThrough = false;
  zoomStats = { in: 0, out: 0, into_cockpit: 0, out_of_cockpit: 0 };
  /** The wheel in the ego view: in third person it closes on the vehicle and,
   *  past `cockpitD`, passes INTO the cockpit; in first person a wheel-out
   *  backs out to third. Returns true when the wheel was the vehicle's. */
  zoomThrough(deltaY: number): boolean {
    const base = Math.max(20, this.vmax * 0.6), cockpitD = base * 0.12;
    if (this.view === "third") {
      if (!this.chaseD) this.chaseD = base;
      this.chaseD = Math.min(base * 3, this.chaseD * (deltaY < 0 ? 0.8 : 1.25));
      if (deltaY < 0) this.zoomStats.in++; else this.zoomStats.out++;
      if (this.chaseD < cockpitD) {
        this.chaseD = 0;
        this.zoomStats.into_cockpit++;
        this.setView("first");
        this.cameThrough = true;
        return true;
      }
      this.chase();
      return true;
    }
    // Only a cockpit ENTERED by the wheel is left by it: otherwise a wheel-out
    // in first person is the ordinary zoom.
    if (deltaY > 0 && this.vehicle && this.cameThrough) {
      this.cameThrough = false;
      // Out of the cockpit: the chase begins just behind it.
      this.zoomStats.out_of_cockpit++;
      this.setView("third");
      this.chaseD = cockpitD * 1.5;
      this.chase();
      return true;
    }
    return false;
  }
  /** The controls' own momentum, cleared when the AGENT places the camera
   *  (as `fly` does): Trackball's damped zoom, pan and turn keep applying a
   *  past gesture on every frame's update, and moved the chase camera off its
   *  vehicle -- a sample at 1,937 in a chase closing 81 -> 52, a cockpit
   *  1,427 units from its vehicle (G-311, 2026-11-15). Planted
   *  `plantKeepMomentum`: kept, as before. */
  plantKeepMomentum = false;
  /** Planted: a running camera tween is left to finish (it overwrites the placement). */
  plantKeepTween = false;
  /** Every time the agent places the camera: a deferred camera move begun
   *  before (the recentre's tighten, 450 ms on) yields to it. */
  placements = 0;
  private settle(ctl: any): void {
    this.placements++;
    if (!this.plantKeepTween) this.host.haltTween?.();
    if (this.plantKeepMomentum || !ctl) return;
    if (ctl._zoomStart && ctl._zoomEnd) ctl._zoomStart.copy(ctl._zoomEnd);
    if (ctl._panStart && ctl._panEnd) ctl._panStart.copy(ctl._panEnd);
    if (ctl._movePrev && ctl._moveCurr) ctl._movePrev.copy(ctl._moveCurr);
    if (typeof ctl._lastAngle === "number") ctl._lastAngle = 0;
  }
  private chase(): void {
    const { cam, ctl } = this.axes();
    if (!ctl || !this.vehicle) return;
    this.settle(ctl);
    const D = this.chaseD || Math.max(20, this.vmax * 0.6), v = this.vehicle;
    const up = v3(cam.up.x, cam.up.y, cam.up.z);
    cam.position.set(v.p.x - v.dir.x * D + up.x * D * 0.35, v.p.y - v.dir.y * D + up.y * D * 0.35, v.p.z - v.dir.z * D + up.z * D * 0.35);
    ctl.target.set(v.p.x, v.p.y, v.p.z);
    cam.lookAt(ctl.target);
    this.craftAt = { x: v.p.x, y: v.p.y, z: v.p.z };
    ctl.update?.();
  }
  setView(view: "first" | "third"): void {
    if (view === this.view) return;
    this.cameThrough = false;     // the wheel's own entry sets it again, after
    this.chaseD = 0;              // the chase starts at its own distance; the wheel's exit sets it, after
    const { cam, ctl, back } = this.axes();
    if (!ctl || !ctl.target) return;
    this.vehicleStats.views++;
    if (view === "third") {
      // The vehicle is where the camera WAS, heading where it looked.
      this.vehicle = { p: v3(cam.position.x, cam.position.y, cam.position.z), dir: v3(-back.x, -back.y, -back.z) };
      this.view = "third";
      this.chase();
    } else {
      // Back into the cockpit: the camera at the vehicle, looking along its heading.
      const v = this.vehicle;
      this.view = "first";
      if (v) {
        const L = Math.max(1, Math.hypot(ctl.target.x - cam.position.x, ctl.target.y - cam.position.y, ctl.target.z - cam.position.z));
        this.settle(ctl);
        cam.position.set(v.p.x, v.p.y, v.p.z);
        ctl.target.set(v.p.x + v.dir.x * L, v.p.y + v.dir.y * L, v.p.z + v.dir.z * L);
        cam.lookAt(ctl.target);
        ctl.update?.();
      }
    }
    this.save();
    this.draw();
  }
  /** A/D: the heading turns about the vehicle's up -- in place, no translation. */
  private turnHeading(sign: number): void {
    const { cam, ctl, up } = this.axes();
    if (!ctl || !ctl.target) return;
    this.vehicleStats.turns++;
    this.target = null;
    if (this.view === "third" && this.vehicle) {
      this.vehicle.dir = rotate(this.vehicle.dir, up, sign * this.rotStep * 1.5);
      this.chase();
      return;
    }
    const p = cam.position, t = ctl.target;
    const rel = rotate(v3(t.x - p.x, t.y - p.y, t.z - p.z), up, sign * this.rotStep * 1.5);
    t.x = p.x + rel.x; t.y = p.y + rel.y; t.z = p.z + rel.z;
    cam.lookAt(t);
    ctl.update?.();
  }

  /** W/S: forward/back along the heading; A/D: sideways in the camera's plane -- at the throttle's speed. */
  private move(k: string): void {
    const { ctl, right, back, cam } = this.axes();
    if (!ctl || !ctl.target) return;
    const s = Math.max(0.05, this.throttle) * this.vmax * 0.12;      // one key step
    if (this.view === "third" && this.vehicle) {
      // Third person: the VEHICLE moves -- along its heading (W/S) or across
      // the camera's plane (A/D) -- and the chase camera follows.
      const sg = k === "w" || k === "d" ? 1 : -1;
      const d = k === "w" || k === "s" ? this.vehicle.dir : right;
      this.vehicle.p = v3(this.vehicle.p.x + d.x * s * sg, this.vehicle.p.y + d.y * s * sg, this.vehicle.p.z + d.z * s * sg);
      this.target = null;
      this.chase();
      return;
    }
    const v = k === "w" ? v3(-back.x * s, -back.y * s, -back.z * s) : k === "s" ? v3(back.x * s, back.y * s, back.z * s)
      : k === "a" ? v3(-right.x * s, -right.y * s, -right.z * s) : v3(right.x * s, right.y * s, right.z * s);
    // The sideways part of the step, along the camera's right: 0 for a vehicle.
    const side = Math.abs(v.x * right.x + v.y * right.y + v.z * right.z);
    if (side > this.vehicleStats.sideways_max) this.vehicleStats.sideways_max = side;
    const p = cam.position, t = ctl.target;
    p.x += v.x; p.y += v.y; p.z += v.z;
    t.x += v.x; t.y += v.y; t.z += v.z;
    // A hand on the stick: the hover's target is dropped, the velocity kept.
    this.target = null;
    ctl.update?.();
  }

  /** Q/E: roll about the view normal. */
  private roll(sign: number): void {
    const { cam, ctl, back } = this.axes();
    if (!ctl) return;
    const up = rotate(cam.up, back, sign * this.rotStep * 1.5);
    cam.up.set(up.x, up.y, up.z);
    cam.lookAt(ctl.target);
    this.stats.rolls++;
    ctl.update?.();
  }

  /** Arrows: turn the camera about the focus -- yaw about its up, pitch
   *  about its right -- the distance to the focus kept. */
  private orbit(yaw: number, pitch: number): void {
    const { cam, ctl, right, up } = this.axes();
    if (!ctl || !ctl.target) return;
    const t = ctl.target, p = cam.position;
    let rel = v3(p.x - t.x, p.y - t.y, p.z - t.z);
    // The camera's OWN up (its matrix column), not `cam.up`: after a roll the
    // stored up is not exactly perpendicular to the view, and re-aiming with
    // it drifted the frame 0.2% a stroke (G-273, 2026-11-08).
    let newUp = this.plantStoredUp ? v3(cam.up.x, cam.up.y, cam.up.z) : v3(up.x, up.y, up.z);
    if (yaw) { rel = rotate(rel, up, yaw * this.rotStep); }
    if (pitch) { rel = rotate(rel, right, -pitch * this.rotStep); newUp = rotate(newUp, right, -pitch * this.rotStep); }
    p.set(t.x + rel.x, t.y + rel.y, t.z + rel.z);
    cam.up.set(newUp.x, newUp.y, newUp.z);
    cam.lookAt(t);
    this.stats.orbits++;
    ctl.update?.();
  }

  // -- the strip ----------------------------------------------------------------

  private light(k: string): void {
    this.lit.set(k, Infinity);
    const cap = CAPS.find((c) => c[0] === k);
    if (cap) { this.lastAction = `${cap[1]}  ${cap[2]}`; this.keyLog.unshift(this.lastAction); this.keyLog.length = Math.min(this.keyLog.length, 12); }
    this.draw();
  }

  private fade(): void {
    if (!this.lit.size) return;
    const now = performance.now();
    let changed = false;
    for (const [k, until] of this.lit) if (until !== Infinity && now > until) { this.lit.delete(k); changed = true; }
    if (changed) this.draw();
  }

  /** What is lit now, for checks. */
  litKeys(): string[] { return [...this.lit.keys()]; }

  /** The control strip: a stickable corner of the graph pane. */
  mount(parent: HTMLElement): void {
    this.hud?.remove();
    this.hud = parent.createDiv({ cls: "domvec-agent" });
    this.draw();
  }

  draw(): void {
    const hud = this.hud;
    if (!hud) return;
    hud.empty();
    const row = hud.createDiv({ cls: "domvec-agent-row" });
    const seg = row.createDiv({ cls: "domvec-agent-mode" });
    for (const m of ["ego", "map"] as AgentMode[]) {
      const b = seg.createEl("button", { text: m, cls: this.mode === m ? "is-on" : "" });
      b.title = m === "ego" ? "ego traversal: a hover flies slowly to the node (M)" : "global map: a hover moves nothing (M)";
      b.onclick = () => this.setMode(m);
    }
    const thr = row.createDiv({ cls: "domvec-agent-throttle" });
    thr.title = "throttle: shift up, ctrl down, Z full, X pause";
    const bar = thr.createDiv({ cls: "domvec-agent-bar" });
    bar.createDiv({ cls: "domvec-agent-fill" }).style.width = `${Math.round(this.throttle * 100)}%`;
    bar.onclick = (ev) => {
      const r = bar.getBoundingClientRect();
      this.setThrottle((ev.clientX - r.left) / Math.max(1, r.width));
    };
    thr.createSpan({ text: this.paused ? "paused" : `${Math.round(this.throttle * 100)}%`, cls: "domvec-agent-val" });
    const pause = row.createEl("button", { text: this.paused ? "▶" : "❚❚", cls: "domvec-agent-pause" });
    pause.title = "pause the flight (X)";
    pause.onclick = () => { this.paused = !this.paused; this.draw(); };
    // The keys, lit while pressed -- as a hovered node glows -- and the action
    // the last one took.
    const keys = hud.createDiv({ cls: "domvec-agent-keys" });
    for (const [k, label, what] of CAPS) {
      const cap = keys.createSpan({ text: label, cls: "domvec-agent-cap" + (this.lit.has(k) ? " is-lit" : "") });
      cap.title = what;
    }
    hud.createDiv({ cls: "domvec-agent-action", text: this.lastAction || "keys: hover the graph" });
  }

  unmount(): void { this.hud?.remove(); this.hud = null; }
}
