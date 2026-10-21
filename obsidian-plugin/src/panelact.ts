/**
 * A chunk panel's gesture, as a record the browser cell can carry out.
 *
 * The chunk card (snapshot.ts) clones the live page's elements and tags each
 * with the patricia-trie address the store holds for it
 * (`data-vertiscope-address` = `url|xpath|taxonomy|accessor`). A click or a change
 * on one of them is NOT handled in the panel: it becomes an `ActRecord` --
 * which address, which action, which value -- and goes to the browser cell
 * (`BrowserView.actOn`), which navigates to the page, scrolls to the element
 * and performs the action in the page through the sensor. The panel then
 * re-renders from what the page now is; it holds no state of its own.
 *
 * In trie terms this file reads one address key and writes nothing: it is the
 * inverse of `ContentAddress.key()` for the two fields a gesture needs, and a
 * table from the chunk's own lines (`key`, `control_key`) to the xpaths the
 * snapshot reader should tag. Pure -- no DOM, no Obsidian -- so a Node test
 * can plant defects in it.
 */

/** What a panel may ask of a page. The vocabulary is `enact.PLAN_KINDS`. */
export type PanelAction = "press" | "type" | "toggle" | "choose";

export interface ActRecord {
  /** The trie address the gesture names (`url|xpath|taxonomy|accessor`). */
  key: string;
  /** The page it lives on, and the element's xpath -- both read from `key`. */
  url: string;
  xpath: string;
  action: PanelAction;
  /** The text typed or the option chosen. */
  value?: string;
  /** The reader pressed Enter in the field: the page's Enter follows the
   *  typing, as their own keyboard's would (PLUGIN_GOAL 111). */
  enter?: boolean;
}

/** What `actOn` reports, stage by stage, so a refusal and a failure differ. */
export interface ActResult {
  ok: boolean;
  /** Where it stopped: the sidecar's adjudication, the cell, or the page. */
  stage: "planted" | "plan" | "navigate" | "sensor" | "perform" | "done";
  did?: string;
  error?: string;
  refused?: boolean;
  /** The cell had to leave the page it was on, and the page it ended on. */
  navigated?: boolean;
  url?: string;
  /** The xpath resolved in the page when the cell scrolled to it. */
  scrolled?: boolean;
  /** `perform`'s own report: ticks done, and `[kind, why]` for the others. */
  done?: string[];
  failed?: [string, string][];
}

const SEP = "|";

/** `ContentAddress._unesc`: `%7C` and `%25` are the only escapes the key makes. */
function unesc(s: string): string {
  return s.replace(/%([0-9A-Fa-f]{2})/g, (_m, h) => String.fromCharCode(parseInt(h, 16)));
}

/** The four fields of an address key, or null for anything else. */
export function parseAddressKey(key: string):
    { url: string; xpath: string; tag: string; accessor: string } | null {
  const parts = String(key || "").split(SEP);
  if (parts.length !== 4) return null;
  const [url, xpath, tag, accessor] = parts.map(unesc);
  if (!xpath.startsWith("/")) return null;
  return { url, xpath, tag, accessor };
}

/** An element of the panel, reduced to what deciding on a gesture reads. */
export interface PanelEl {
  /** `data-vertiscope-address`; absent on anything the trie did not address. */
  address?: string;
  /** `data-vertiscope-act`: what the snapshot reader decided this element is for. */
  act?: string;
  /** Current value (inputs, selects) or checked state is not needed: a toggle is a click. */
  value?: string;
}

const ACTIONS = new Set<string>(["press", "type", "toggle", "choose"]);

/**
 * Which gesture, on which element, is an action -- and on what.
 *
 * - a `click` acts on `press` and `toggle` elements (a link, a button, a
 *   checkbox); a click into a text field or a select only focuses it;
 * - a `change` acts on `type` and `choose` elements, carrying the value the
 *   reader entered; a change on a checkbox is the same click the page already
 *   received, so it is not a second action.
 *
 * No address, or an address that is not an address key, is no action: an
 * element the trie does not hold is not live (`G-102`).
 */
export function actFromEvent(kind: "click" | "change", el: PanelEl): ActRecord | null {
  if (!el || !el.address || !el.act || !ACTIONS.has(el.act)) return null;
  const action = el.act as PanelAction;
  if (kind === "click" && action !== "press" && action !== "toggle") return null;
  if (kind === "change" && action !== "type" && action !== "choose") return null;
  const at = parseAddressKey(el.address);
  if (!at) return null;
  const rec: ActRecord = { key: el.address, url: at.url, xpath: at.xpath, action };
  if (kind === "change") rec.value = String(el.value ?? "");
  return rec;
}

/**
 * The in-page chain for a record: scroll to the element, then act. The sensor's
 * `perform` takes `{xpath}` targets (the trie's own spelling) and refuses what
 * the never-press set names, element by element, at the moment of the act.
 */
export function chainFor(kind: string, xpath: string, value?: string, enter = false):
    { ticks: { kind: string; xpath: string; text?: string }[] } {
  const ticks: { kind: string; xpath: string; text?: string }[] =
    [{ kind: "scrollIntoView", xpath }];
  const act: { kind: string; xpath: string; text?: string } = { kind, xpath };
  if (kind === "type" || kind === "choose") act.text = String(value ?? "");
  ticks.push(act);
  // Enter in a typed field: the key the page's own handler listens for (a
  // search box submits on it), on the same element -- not a form submit
  // invented here.
  if (enter && kind === "type") ticks.push({ kind: "key", xpath, text: "Enter" });
  return { ticks };
}

/**
 * The chunk's lines as the table the snapshot reader tags with: xpath ->
 * `[address key, is a control]`.
 *
 * A control's own address (`control_key`) wins over the line's, because an
 * anchor's line is stored under a `urls.*` or `text.visible` address and
 * acting on THAT names the wrong thing (`htmlform._address_attrs`). Where two
 * lines share an element, the first keeps it unless a later one is a control.
 * Only the xpath (not the accessor suffix) is the table's key.
 */
export function addressTable(lines: { key?: string; control_key?: string; control?: boolean }[],
                             max = 1200): Record<string, [string, number]> {
  const out: Record<string, [string, number]> = {};
  let n = 0;
  for (const l of lines || []) {
    for (const [k, ctl] of [[l.control_key, 1], [l.key, l.control ? 1 : 0]] as [string | undefined, number][]) {
      if (!k) continue;
      const at = parseAddressKey(k);
      if (!at) continue;
      const have = out[at.xpath];
      if (have && !(ctl && !have[1])) continue;
      if (!have && ++n > max) return out;
      out[at.xpath] = [k, ctl];
    }
  }
  return out;
}

/** One line for the readout under a panel. */
export function describeResult(r: ActResult | null): string {
  if (!r) return "no answer from the sidecar";
  if (!r.ok) {
    if (r.refused) return `refused: ${r.error || "never-press set"}`;
    return `${r.stage}: ${r.error || "failed"}`;
  }
  const bits = [r.did || "done"];
  if (r.navigated) bits.push("went to the page");
  if (r.scrolled === false) bits.push("scrolled by the sensor");
  return bits.join(" · ");
}
