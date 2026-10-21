/**
 * The built-in switch between an EMPTY test workspace and the reader's own
 * (2026-10-04: "We will begin with a completely empty workspace. This refresh
 * component must be built-in for testing vs regular usage.").
 *
 * `empty()` starts a sidecar on a new, empty workspace folder on its own port
 * (8791: beside the reader's 8788 and the Verifier's 8790, never instead of
 * either), points the plugin at it IN MEMORY, clears both panes and the
 * browser cell, and shows a status-bar badge for as long as it lasts.
 * `reader()` stops that sidecar and puts the plugin back on the saved
 * setting. The reader's store is never opened by a test session.
 *
 * The session lives on the WINDOW, not the plugin: a plugin reload (how a new
 * build is loaded) would otherwise fall back to the saved setting and quietly
 * move a test session onto the reader's store. On load, `resume()` re-applies
 * a session whose sidecar still answers.
 *
 * In trie terms: a session is which trie store every pane reads and writes --
 * one switch, applied to the one setting all of them consult.
 */
import { App } from "obsidian";
import type { Verifier } from "./verify";

const PORT = 8791;
const KEY = "__vertiscopeSession";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export interface SessionState {
  kind: "reader" | "empty";
  url: string;
  workspace: string;
  startedAt: number;
  pid: number | null;
  /** The reader's own sidecar, restored by `reader()`. */
  saved: string;
  phase: string;
}

export class SessionSwitch {
  badge: HTMLElement | null = null;

  constructor(private app: App, private verifier: Verifier) {}

  private get plugin(): any { return (this.app as any).plugins.getPlugin("vertiscope-bridge"); }

  state(): SessionState {
    return (window as any)[KEY] || { kind: "reader", url: String(this.plugin?.settings?.sidecar || ""),
                                     workspace: "", startedAt: 0, pid: null, saved: "", phase: "" };
  }

  private set(s: SessionState): void {
    (window as any)[KEY] = s;
    this.paint();
  }

  /** A status-bar badge while a test workspace is in use: never ambiguous. */
  paint(): void {
    const s = this.state();
    if (!this.badge) return;
    this.badge.setText(s.kind === "empty" ? `vertiscope: TEST workspace :${PORT}${s.phase ? " · " + s.phase : ""}` : "");
    this.badge.toggleClass("vertiscope-session-test", s.kind === "empty");
  }

  /** After a plugin reload: a live test session is put back. */
  async resume(): Promise<boolean> {
    const s = this.state();
    if (s.kind !== "empty") return false;
    const alive = await this.verifier.ask(s.url, "/health", 3000);
    if (!alive) {
      this.set({ ...s, kind: "reader", phase: "test sidecar gone" });
      return false;
    }
    this.plugin.settings.sidecar = s.url;
    this.paint();
    return true;
  }

  async empty(): Promise<SessionState> {
    const plugin = this.plugin;
    const prev = this.state();
    if (prev.kind === "empty") await this.reader();
    const req = (window as any).require;
    const path = req("path");
    const fsp = req("fs/promises");
    const base = (this.app.vault.adapter as any).basePath || "";
    const root = path.join(base, "build", "sessions");
    await fsp.mkdir(root, { recursive: true });
    for (const old of await fsp.readdir(root)) {
      if (old.startsWith("session_")) await fsp.rm(path.join(root, old), { recursive: true, force: true });
    }
    const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
    const ws = path.join(root, `session_${stamp}`);
    await fsp.mkdir(ws);
    const url = `http://127.0.0.1:${PORT}`;
    const saved = String(plugin.settings.sidecar || "");
    this.set({ kind: "empty", url, workspace: ws, startedAt: Date.now(), pid: null, saved, phase: "starting its sidecar" });
    await this.freePort();
    const child = this.verifier.spawnSidecar(ws, base, plugin.settings.python || "python", PORT);
    this.set({ ...this.state(), pid: child.pid ?? null });
    if (!(await this.verifier.waitHealthy(url, 240000, child))) {
      this.set({ ...this.state(), kind: "reader", phase: "its sidecar did not start (see sidecar.log)" });
      return this.state();
    }
    await this.verifier.ensurePanes();
    plugin.settings.sidecar = url;
    for (const l of this.app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      try { (l.view as any).go?.("about:blank"); } catch { /* not ready */ }
    }
    this.verifier.resetGraphs("an empty test workspace");
    await this.verifier.redrawGraphs();
    this.verifier.restoreLive();
    this.set({ ...this.state(), phase: "" });
    return this.state();
  }

  /** The test workspace's sidecar restarted on the SAME folder: new sidecar
   *  code, the same store (what the reader browsed is kept). */
  async restart(): Promise<SessionState> {
    const s = this.state();
    if (s.kind !== "empty") return s;
    await this.kill(s.pid);
    this.set({ ...s, pid: null, phase: "restarting its sidecar" });
    await this.freePort();
    const base = (this.app.vault.adapter as any).basePath || "";
    const child = this.verifier.spawnSidecar(s.workspace, base, this.plugin.settings.python || "python", PORT);
    this.set({ ...this.state(), pid: child.pid ?? null });
    const ok = await this.verifier.waitHealthy(s.url, 240000, child);
    this.set({ ...this.state(), phase: ok ? "" : "its sidecar did not restart (see sidecar.log)" });
    if (ok) { this.verifier.resetGraphs("test sidecar restarted"); await this.verifier.redrawGraphs(); }
    return this.state();
  }

  private async kill(pid: number | null): Promise<void> {
    if (!pid) return;
    const proc = (window as any).process;
    const cp = (window as any).require("child_process");
    if (proc.platform === "win32") {
      await new Promise((r) => cp.execFile("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true }, () => r(null)));
    } else {
      try { proc.kill(pid); } catch { /* gone */ }
    }
  }

  async reader(): Promise<SessionState> {
    const s = this.state();
    if (s.kind !== "empty") return s;
    const plugin = this.plugin;
    plugin.settings.sidecar = s.saved || plugin.settings.sidecar;
    if (s.pid) {
      const proc = (window as any).process;
      const cp = (window as any).require("child_process");
      if (proc.platform === "win32") {
        await new Promise((r) => cp.execFile("taskkill", ["/PID", String(s.pid), "/T", "/F"],
          { windowsHide: true }, () => r(null)));
      } else {
        try { proc.kill(s.pid); } catch { /* gone */ }
      }
    }
    this.set({ kind: "reader", url: plugin.settings.sidecar, workspace: "", startedAt: 0, pid: null, saved: "", phase: "" });
    this.verifier.resetGraphs("back on the reader's workspace");
    await this.verifier.redrawGraphs();
    return this.state();
  }

  /** Whatever still listens on the session port goes (a crashed session). */
  private async freePort(): Promise<void> {
    if (!(await this.verifier.ask(`http://127.0.0.1:${PORT}`, "/health", 1500))) return;
    const proc = (window as any).process;
    if (proc.platform !== "win32") return;
    const cp = (window as any).require("child_process");
    const out: string = await new Promise((r) => cp.execFile("netstat", ["-ano", "-p", "TCP"],
      { windowsHide: true }, (_e: any, so: string) => r(String(so || ""))));
    for (const line of out.split(/\r?\n/)) {
      const f = line.trim().split(/\s+/);
      if (f.length >= 5 && f[1].endsWith(`:${PORT}`) && f[3] === "LISTENING") {
        await new Promise((r) => cp.execFile("taskkill", ["/PID", f[4], "/T", "/F"], { windowsHide: true }, () => r(null)));
      }
    }
    for (let i = 0; i < 20 && (await this.verifier.ask(`http://127.0.0.1:${PORT}`, "/health", 1000)); i++) await sleep(500);
  }
}
