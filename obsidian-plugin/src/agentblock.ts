/**
 * An agent's run, started from a note and APPEARING in the app (G-384: "Not
 * built: the run appearing live in the app"). A ```agent block's text is the
 * task; its button starts a smolagents CodeAgent over the kernel's own tool
 * panels (`POST /agent_run`), which writes the run into a new note under
 * `domvec/agents/` step by step -- each step a python cell with its output --
 * and that note opens on the plane, growing as the agent works.
 *
 * In trie terms: the run writes vault://domvec/agents/<run>.md, one cell per
 * step; this block only names the task and opens the page.
 */
import type { App, TFile } from "obsidian";

export const agentStats = { started: 0, opened: 0, carried: 0, last: "" };

export function agentBlock(app: App, sidecar: () => string, openNote: (f: TFile) => Promise<any>,
                           /** An editor ask the agent made (create/link/invoke/commit/review), carried out
                            *  by the reader's own gesture methods (`EditorCalls.carry`). */
                           carry: (ask: any) => Promise<string | null> = async () => null) {
  return (src: string, el: HTMLElement, ctx?: { sourcePath: string }) => {
    const task = src.trim();
    const box = el.createDiv({ cls: "domvec-agent-block" });
    box.createDiv({ cls: "domvec-agent-task", text: task || "(write the agent's task in this block)" });
    const btn = box.createEl("button", { cls: "domvec-agent-run", text: "▶ run agent" });
    const say = box.createDiv({ cls: "domvec-agent-status" });
    btn.onclick = async () => {
      if (!task) return;
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      const note = `domvec/agents/${task.replace(/[^\w\s-]/g, "").trim().slice(0, 40)} ${stamp}.md`;
      const dry = (window as any).__domvecAgentDry;
      // G-412: the functions this note's cells define are the agent's tools too.
      const body: any = { task, note, tools_from: ctx?.sourcePath || "",
        ...(dry ? { dry_replies: dry.replies, pace_s: dry.pace_s || 0, plant_write_at_end: !!dry.plant, plant_no_editor_tools: !!dry.plantNoTools, plant_no_cell_tools: !!dry.plantNoCellTools } : {}) };
      btn.disabled = true; say.setText("starting...");
      try {
        const r = await (await fetch(sidecar().replace(/[/]+$/, "") + "/agent_run", { method: "POST",
          headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" }, body: JSON.stringify(body) })).json();
        if (!r.started) { say.setText("not started: " + (r.error || "?")); return; }
        agentStats.started++; agentStats.last = note;
        say.setText("running into " + note);
        for (let i = 0; i < 100; i++) {
          const f = app.vault.getAbstractFileByPath(note);
          if (f) { await openNote(f as TFile); agentStats.opened++; break; }
          await new Promise((res) => setTimeout(res, 200));
        }
        // The agent's editor calls, carried out as they are asked, until the run ends.
        let carried = 0;
        for (let i = 0; i < 1200; i++) {
          const st = await (await fetch(sidecar().replace(/[/]+$/, "") + "/agent_status", { method: "POST",
            headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" }, body: JSON.stringify({ note }) })).json();
          for (const ask of (st.asks || []).slice(carried)) { await carry(ask); carried++; agentStats.carried++; }
          if (st.done) { say.setText((st.error ? "stopped: " + st.error : `done: ${st.steps} steps`) + (carried ? `, ${carried} editor calls` : "")); break; }
          await new Promise((res) => setTimeout(res, 500));
        }
      } catch (e) { say.setText("the sidecar did not answer"); }
      finally { btn.disabled = false; }
    };
  };
}
