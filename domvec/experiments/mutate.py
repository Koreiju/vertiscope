"""A deterministic mutation sequence, for measuring cost across passes.

Half the design space only pays on the *second* read — `gate` suppresses an
unchanged chunk, `subtreegate` refuses to descend one, `chunkdelta` sends a
difference against what the receiver holds, `coalesce` waits for a payload
worth carrying, `deepgate` stops the fold re-summing a settled branch. A
contrast that performs one drain per axis cannot see any of them: measured
that way `subtreegate` reads -0.0%, and under a scrolling protocol the same
mechanism read -56.9%.

Scrolling would expose them but is not repeatable — a page loads different
content on each visit, so axes would be compared across different documents,
which is the confound that wasted several runs of this sweep.

So the page is held still and *we* supply the change. The sequence below is
fixed, ordered, and **self-inverting**: it appends, edits, then removes
exactly what it appended and restores exactly what it edited, so the document
ends each axis byte-identical to how it started. Every axis therefore sees
the same document and the same deltas, and the only variable left is the
mechanism.

Shadow roots survive this because nothing re-writes innerHTML; nodes are
appended to and removed from the live tree.
"""

from __future__ import annotations

# Each step returns a short description; the page keeps its own undo state
# under a single non-enumerable property so nothing leaks into the document.
SETUP = """
var K = arguments[0];
if (!window.__mut) {
  Object.defineProperty(window, '__mut', {
    value: {added: [], edited: []}, enumerable: false, configurable: true});
}
return true;
"""

# 1. grow: clone the most repeated sibling shape and append copies of it.
#    This is what an infinite feed does — new items of an existing shape.
GROW = """
var n = arguments[0];
var best = null, bestN = 0;
var all = document.body ? document.body.querySelectorAll('*') : [];
for (var i = 0; i < all.length; i++) {
  var p = all[i].parentNode;
  if (!p || !p.children || p.children.length < 3) continue;
  var same = 0;
  for (var j = 0; j < p.children.length; j++) {
    if (p.children[j].tagName === all[i].tagName) same++;
  }
  if (same > bestN) { bestN = same; best = all[i]; }
}
if (!best || !best.parentNode) return 0;
var made = 0;
for (var k = 0; k < n; k++) {
  var c = best.cloneNode(true);
  c.setAttribute('data-mut', '1');
  best.parentNode.appendChild(c);
  window.__mut.added.push(c);
  made++;
}
return made;
"""

# 2. edit: change the text of a few existing nodes, remembering the old text.
#    This is the live-update case: a chunk whose digest moves by one line.
EDIT = """
var n = arguments[0], done = 0;
var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
var node;
while (done < n && (node = w.nextNode())) {
  var t = node.nodeValue;
  if (!t || t.trim().length < 12) continue;
  window.__mut.edited.push([node, t]);
  node.nodeValue = t.slice(0, -3) + 'zzq';
  done++;
}
return done;
"""

# 3. restore: undo both, exactly. The document returns to what it was, so
#    the next axis begins from the same state this one did.
RESTORE = """
var m = window.__mut || {added: [], edited: []};
var i, removed = 0;
for (i = 0; i < m.added.length; i++) {
  if (m.added[i].parentNode) { m.added[i].parentNode.removeChild(m.added[i]); removed++; }
}
for (i = 0; i < m.edited.length; i++) {
  try { m.edited[i][0].nodeValue = m.edited[i][1]; } catch (e) {}
}
m.added = []; m.edited = [];
return removed;
"""

# The sequence, in order. Each entry is (label, script, argument).
SEQUENCE = [
    ("grow-10", GROW, 10),
    ("edit-5", EDIT, 5),
    ("grow-10", GROW, 10),
    ("edit-5", EDIT, 5),
    ("grow-20", GROW, 20),
]
