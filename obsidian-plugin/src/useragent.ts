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
 * about the focus (yaw, pitch); Q/R roll it about the view normal.
 *
 * A key acts only while the pointer is over the graph and nothing is typed
 * into -- the rule `arrowPan` already followed.
 */

export type AgentMode = "ego" | "map";

export interface AgentHost {
  camera(): any;
  controls(): any;
  /** Fly back out to the whole picture (the "recentre" action). */
  recentre(): void;
  /** The reader acted: idle turns stop. */
  touched(what: string): void;
}

const KEY = "domvec.useragent";

/** The keys the agent answers, and what each does, as the strip shows them. */
const CAPS: [string, string, string][] = [
  ["w", "W", "forward"], ["a", "A", "strafe left"], ["s", "S", "back"], ["d", "D", "strafe right"],
  ["q", "Q", "roll left"], ["r", "R", "roll right"],
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
  /** Radians per key step for arrows and Q/R. */
  rotStep = 0.035;
  target: any = null;
  /** The craft's velocity, world units a second: the state a new hover bends. */
  vel = v3();
  stats = { flights: 0, frames: 0, at_floor: 0, keys: 0, mode_switches: 0, last_d: 0, speed: 0, bends: 0, rolls: 0, orbits: 0 };
  /** Planted: the old 0.4 s tween to wherever `zoomFor` said, no floor. */
  plantFastFlight = false;
  /** Planted: a new hover restarts the flight from rest (no carried velocity). */
  plantRestart = false;
  private hud: HTMLElement | null = null;
  private lit = new Map<string, number>();
  private lastAction = "";

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
    if (this.target && this.target !== n) this.stats.bends++;
    if (this.plantRestart) this.vel = v3();
    this.target = n;
    this.stats.flights++;
    return true;
  }

  /** One frame. `dt` in seconds. */
  tick(dt: number): void {
    const cam = this.host.camera(), ctl = this.host.controls();
    if (!cam || !ctl || !ctl.target) return;
    const p = cam.position, t = ctl.target;
    const n = this.mode === "ego" ? this.target : null;
    let want = v3();
    if (n && Number.isFinite(n.x) && !this.paused && this.throttle > 0) {
      const nx = n.x, ny = n.y, nz = n.z || 0;
      // Aim: the look point turns onto the node at the craft's turn rate.
      const ka = 1 - Math.exp(-this.turn * 2 * dt);
      t.x += (nx - t.x) * ka; t.y += (ny - t.y) * ka; t.z += (nz - t.z) * ka;
      const to = v3(nx - p.x, ny - p.y, nz - p.z), d = len(to);
      this.stats.last_d = Math.round(d * 10) / 10;
      const left = d - this.floor;
      if (left > 1e-3) {
        // The speed the throttle asks for, capped so the craft can still stop
        // at the floor: v^2 = 2 a s.
        const speed = Math.min(this.throttle * this.vmax, Math.sqrt(2 * this.accel * left));
        want = v3(to.x / d * speed, to.y / d * speed, to.z / d * speed);
      } else {
        this.stats.at_floor++;
      }
    }
    // The heading turns toward `want` at most `turn` rad/s (the trajectory
    // BENDS); the speed changes at most `accel`.
    const sv = len(this.vel), sw = len(want);
    let dir = sv > 1e-6 ? v3(this.vel.x / sv, this.vel.y / sv, this.vel.z / sv) : null;
    if (sw > 1e-6) {
      const wd = v3(want.x / sw, want.y / sw, want.z / sw);
      if (!dir) dir = wd;
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
      // The floor is HARD: no step ends nearer the target than it.
      if (n && Number.isFinite(n.x)) {
        const q = v3(p.x + step.x - n.x, p.y + step.y - n.y, p.z + step.z - (n.z || 0));
        const dq = len(q);
        if (dq < this.floor) {
          const k = this.floor / Math.max(dq, 1e-9);
          step = v3(n.x + q.x * k - p.x, n.y + q.y * k - p.y, (n.z || 0) + q.z * k - p.z);
          this.vel = v3();
        }
      }
      p.x += step.x; p.y += step.y; p.z += step.z;
      this.stats.frames++;
      ctl.update?.();
    }
    this.fade();
  }

  setMode(mode: AgentMode): void {
    if (mode === this.mode) return;
    this.mode = mode;
    this.stats.mode_switches++;
    this.target = null;
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

  /** KSP's keys, arrows and Q/R. Returns true when the key was the agent's. */
  key(e: KeyboardEvent): boolean {
    if (e.altKey || e.metaKey) return false;
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    const bare = (name: string) => e.key === name;           // shift/ctrl pressed ALONE
    let took = true;
    if (bare("Shift")) this.setThrottle(this.throttle + 0.05);
    else if (bare("Control")) this.setThrottle(this.throttle - 0.05);
    else if (e.ctrlKey || e.shiftKey) took = false;          // a shortcut, not ours
    else if (k === "w" || k === "a" || k === "s" || k === "d") this.move(k);
    else if (k === "q" || k === "r") this.roll(k === "q" ? -1 : 1);
    else if (k === "ArrowLeft" || k === "ArrowRight") this.orbit(k === "ArrowLeft" ? 1 : -1, 0);
    else if (k === "ArrowUp" || k === "ArrowDown") this.orbit(0, k === "ArrowUp" ? 1 : -1);
    else took = false;
    if (took) {
      this.stats.keys++;
      this.light(k);
      this.host.touched("user-agent");
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

  /** WASD: forward/back along the view, strafe, at the throttle's speed. */
  private move(k: string): void {
    const { ctl, right, back, cam } = this.axes();
    if (!ctl || !ctl.target) return;
    const s = Math.max(0.05, this.throttle) * this.vmax * 0.12;      // one key step
    const v = k === "w" ? v3(-back.x * s, -back.y * s, -back.z * s) : k === "s" ? v3(back.x * s, back.y * s, back.z * s)
      : k === "a" ? v3(-right.x * s, -right.y * s, -right.z * s) : v3(right.x * s, right.y * s, right.z * s);
    const p = cam.position, t = ctl.target;
    p.x += v.x; p.y += v.y; p.z += v.z;
    t.x += v.x; t.y += v.y; t.z += v.z;
    // A hand on the stick: the hover's target is dropped, the velocity kept.
    this.target = null;
    ctl.update?.();
  }

  /** Q/R: roll about the view normal. */
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
    let newUp = v3(cam.up.x, cam.up.y, cam.up.z);
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
    if (cap) this.lastAction = `${cap[1]}  ${cap[2]}`;
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
