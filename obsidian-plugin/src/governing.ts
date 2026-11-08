/**
 * GOVERNING CODE ARTIFACTS (PLUGIN_GOAL 142, ruling T-10): "Governing code
 * artifacts follow a standard high-level architecture, meaning that 25 lines
 * gives the full space of code capabilities of the 'thing' ... which are then
 * linked to by a markdown control panel counterpart on an instance."
 *
 * A governing artifact is a Python class in the vault (`domvec/governing/`)
 * whose public methods ARE the thing's capabilities. This module reads one
 * and turns each method into a control-panel field, typed by its signature:
 * no argument -> an action (a click, written `false`), `bool` -> a toggle,
 * `Literal[...]` -> a choice, anything else -> typed text. The panel is
 * generated FROM the code, so the code is the one source of what a thing
 * can do.
 */
export interface Capability { name: string; kind: "action" | "bool" | "choice" | "text"; value: string; choices?: string[]; note: string }

const DEF = /^\s+def\s+([a-z][A-Za-z0-9_]*)\s*\(\s*self\s*(?:,\s*([A-Za-z_]\w*)\s*:\s*([^=)]+?)\s*(?:=\s*([^)]*?))?)?\s*\)\s*(?:->[^:]*)?:\s*(?:\.\.\.)?\s*(?:#\s*(.*))?$/;

/** Every public method of the first class in `src`, in source order. */
export function capabilitiesOf(src: string): Capability[] {
  const out: Capability[] = [];
  for (const line of src.split(/\r?\n/)) {
    const m = line.match(DEF);
    if (!m) continue;
    const [, name, arg, type, dflt, note] = m;
    const unq = (s: string) => s.trim().replace(/^["']|["']$/g, "");
    if (!arg) { out.push({ name, kind: "action", value: "false", note: note || "" }); continue; }
    const t = type.trim();
    if (t === "bool") { out.push({ name, kind: "bool", value: dflt && dflt.trim() === "True" ? "true" : "false", note: note || "" }); continue; }
    const lit = t.match(/^Literal\[(.*)\]$/);
    if (lit) {
      const choices = lit[1].split(",").map(unq);
      out.push({ name, kind: "choice", value: dflt ? unq(dflt) : choices[0], choices, note: note || "" });
      continue;
    }
    out.push({ name, kind: "text", value: dflt ? unq(dflt) : "", note: note || "" });
  }
  return out;
}

/** The control panel's slate text for an instance titled `title`. */
export function panelText(title: string, caps: Capability[]): string {
  const T = "\t";
  return ["---", "domvec: slate", "---", title, ...caps.map((c) => T + c.name + T + c.value), ""].join("\n");
}

/** The fields `caps` declares that `text` lacks, appended in order (a method
 *  added to the class grows the panel without touching what is there). */
export function withMissing(text: string, caps: Capability[]): { text: string; added: string[] } {
  const have = new Set([...text.matchAll(/^\t([a-z]\w*)\t/gm)].map((m) => m[1]));
  const added = caps.filter((c) => !have.has(c.name));
  if (!added.length) return { text, added: [] };
  const body = text.replace(/\s*$/, "");
  return { text: body + "\n" + added.map((c) => "\t" + c.name + "\t" + c.value).join("\n") + "\n", added: added.map((c) => c.name) };
}
