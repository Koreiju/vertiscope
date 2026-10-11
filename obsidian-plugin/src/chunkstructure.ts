/**
 * The chunk structure around a hovered chunk (`P-B7`: *"Hover overlays the
 * chunk structure on the page's own cartesian layout, showing the chunks
 * embedded in it"*), read from the trie and nothing else.
 *
 * A chunk's addresses share a prefix: that prefix is its node in the patricia
 * trie. The node's PARENT is the container the chunk is embedded in, and the
 * other chunks whose nodes lie under that parent are the structure the reader
 * is looking at -- the other cards of a grid, the other rows of a table, the
 * other paragraphs of a section. When the immediate parent holds no other
 * chunk, the walk goes up a level (a chunk alone in its `<div>` is still one
 * of several in the `<section>` above), at most `MAX_UP` levels: the whole
 * page is not "the structure around" anything.
 *
 * Pure: the overlay measures what this names (`PipelineBox`), and the test
 * checks the naming without a page.
 */

/** How far up the trie the walk looks for a container with siblings. */
export const MAX_UP = 3;

/** An address's element steps: text nodes and attributes are not containers. */
function elementSteps(xpath: string): string[] {
  const steps = xpath.split("/").filter(Boolean);
  while (steps.length && /^(text\(\)|@|comment\(\))/.test(steps[steps.length - 1])) steps.pop();
  return steps;
}

/** The longest run of element steps every address shares: the chunk's trie node. */
export function chunkNode(xpaths: string[]): string[] {
  if (!xpaths.length) return [];
  let common = elementSteps(xpaths[0]);
  for (let i = 1; i < xpaths.length && common.length; i++) {
    const s = elementSteps(xpaths[i]);
    let k = 0;
    while (k < common.length && k < s.length && common[k] === s[k]) k++;
    common = common.slice(0, k);
  }
  return common;
}

function under(node: string[], container: string[]): boolean {
  if (node.length <= container.length) return false;
  for (let i = 0; i < container.length; i++) if (node[i] !== container[i]) return false;
  return true;
}

/**
 * The container the hovered chunk is embedded in, and the other chunks in it.
 * `container` is an xpath ("" when none was found); `siblings` are cids, in
 * the order given, at most `limit`.
 */
export function embedded(hovered: string, cids: string[], xpathsOf: (cid: string) => string[],
                         limit = 24): { container: string; siblings: string[] } {
  const own = chunkNode(xpathsOf(hovered));
  if (own.length < 3) return { container: "", siblings: [] };       // /html/body is not a container
  const nodes = new Map<string, string[]>();
  for (const c of cids) if (c !== hovered) nodes.set(c, chunkNode(xpathsOf(c)));
  for (let up = 1; up <= MAX_UP && own.length - up >= 2; up++) {
    const container = own.slice(0, own.length - up);
    const siblings: string[] = [];
    for (const [c, node] of nodes) {
      // Under the container, and not an ANCESTOR of the hovered chunk (a
      // chunk whose node holds the hovered one is its frame, not a sibling).
      if (under(node, container) && !under(own, node)) siblings.push(c);
      if (siblings.length >= limit) break;
    }
    if (siblings.length) return { container: "/" + container.join("/"), siblings };
  }
  return { container: "", siblings: [] };
}
