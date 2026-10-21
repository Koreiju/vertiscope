/*
 * deep_serialize.js — deep DOM serialization with Merkle pruning.
 *
 * Why this exists
 * ---------------
 * The in-page chunk engine (wfh_chunk_engine.js) streams *chunk events* via
 * MutationObserver: it is a signal-flow component, built for a live GUI that
 * wants deltas as they happen. A batch scrape wants the opposite — one
 * complete, settled snapshot — so this script does the data-flow half:
 * walk the composed tree once and emit HTML.
 *
 * Open shadow roots are emitted as declarative shadow DOM
 * (`<template shadowrootmode="open">`), which is exactly what
 * shadow_html_parser.ShadowDOM already knows how to read, so the Python
 * side needs no new parsing rules. Closed shadow roots are unreachable
 * from script by definition and are skipped.
 *
 * Incremental transport
 * ---------------------
 * Every node gets a Merkle hash over its tag, content-bearing attributes,
 * text and its children's hashes. Pass a map of hashes the caller already
 * holds and any subtree whose hash is in it is replaced by a placeholder:
 *
 *     <template data-vertiscope-same="HASH"></template>
 *
 * The caller splices its own copy back in. On a page being scrolled, the part
 * that did not change is the overwhelming majority, so the second and later
 * snapshots cost a fraction of the first.
 *
 * The hashing is done here rather than in Python on purpose. Hashing after
 * transfer identifies what changed but has already paid to move everything;
 * the saving only exists if the unchanged bytes never cross the bridge. The
 * upstream implementation hashed in Python and therefore saved nothing on
 * transport, which is the bug this fixes.
 *
 * Argument: `arguments[0]` — optional object mapping hash -> 1.
 * Returns: JSON string {html, hashes, stats}.
 *   hashes  path -> hash, for every node emitted or pruned
 *   stats   {nodes, emitted, pruned, prunedNodes, bytes}
 */
/* `arguments` here is the injected script's own, which is where Selenium puts
 * the call's parameters. It must be read *outside* the closure below and
 * passed in: an IIFE has its own `arguments`, and reading it inside would see
 * the IIFE's empty argument list instead. That mistake is silent — `known`
 * comes out null, nothing is ever pruned, and the transport quietly stays
 * full-size while every other number still looks right. */
var __known = (typeof arguments !== 'undefined' && arguments.length)
    ? arguments[0] : null;

return (function (known) {
    var VOID = {
        area: 1, base: 1, br: 1, col: 1, embed: 1, hr: 1, img: 1, input: 1,
        link: 1, meta: 1, param: 1, source: 1, track: 1, wbr: 1
    };
    // Nodes that carry no extractable content and bloat the payload.
    var SKIP = { SCRIPT: 1, NOSCRIPT: 1 };
    /* Attributes that participate in identity.
     *
     * This must cover everything the extractor can *read*, or the hash is
     * unsound as a reuse key: a subtree whose only change is in an unhashed
     * attribute would hash equal, and the incremental tagger would splice in
     * the previous pass's detections — serving stale content that nothing
     * reports. The first version listed fifteen attributes chosen for
     * stability, which left `style` (CSS urls), `cite`, `longdesc`,
     * `formaction`, `data-original` and every JSON-bearing `data-*` unhashed
     * while the extractor read all of them.
     *
     * So the rule is inverted: hash every attribute *except* those the
     * extractor provably ignores. The skip list below mirrors the tagger's
     * own (`_SKIP_ATTRS` / `_SKIP_ATTR_PREFIXES`), which is what keeps a
     * framework rewriting a state flag from looking like a content change —
     * the original concern, met without trading away correctness for it.
     */
    var SKIP_ATTRS = {
        'class': 1, 'style': 0, 'tabindex': 1, 'aria-posinset': 1,
        'aria-setsize': 1, 'aria-hidden': 1, 'aria-expanded': 1,
        'aria-selected': 1, 'aria-checked': 1, 'aria-controls': 1,
        'aria-owns': 1, 'aria-activedescendant': 1, 'role': 0,
        'width': 1, 'height': 1, 'viewbox': 1, 'd': 1, 'points': 1,
        'fill': 1, 'stroke': 1, 'transform': 1, 'loading': 1, 'decoding': 1
    };
    var SKIP_PREFIXES = [
        'data-vertiscope-', 'data-testid', 'data-cy-', 'data-qa-',
        'data-automation', 'data-react', 'data-radix', 'data-state',
        'data-orientation', 'data-side', 'data-align', 'data-disabled'
    ];

    function skipAttr(name) {
        if (SKIP_ATTRS[name] === 1) return true;
        for (var i = 0; i < SKIP_PREFIXES.length; i++) {
            if (name.lastIndexOf(SKIP_PREFIXES[i], 0) === 0) return true;
        }
        return false;
    }

    var MAX_NODES = 400000;   // hard stop; pathological pages exist
    var seen = 0;

    var hashes = {};
    var stats = { nodes: 0, emitted: 0, pruned: 0, prunedNodes: 0, bytes: 0 };

    function escText(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function escAttr(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    /* 32-bit FNV-1a over a string, hex. Not cryptographic and does not need
     * to be: a collision costs a missed update on one subtree, and the cost
     * of a real hash per node on a 100k-node page is not worth paying. */
    function fnv(str) {
        var h = 0x811c9dc5;
        for (var i = 0; i < str.length; i++) {
            h ^= str.charCodeAt(i);
            h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
        }
        return h.toString(16);
    }

    /* Bottom-up: a node's hash covers its whole subtree, so one comparison
     * at the top answers "did anything below here change".
     *
     * This walks in exactly the order `serialize` does, with the same two
     * separate counters for shadow and light children. That is load-bearing,
     * not tidiness: the two passes address nodes by path, so any divergence
     * would store a hash under a path the serializer never asks about and
     * pruning would silently never fire — a performance feature that appears
     * to work and does nothing. */
    function hashOf(node, path) {
        stats.nodes++;
        if (node.nodeType === 3) {
            var txt = (node.nodeValue || '').trim();
            var th = txt ? fnv('t|' + txt) : '';
            if (th) hashes[path] = th;
            return th;
        }
        if (node.nodeType !== 1) return '';
        var tag = node.tagName.toLowerCase();
        if (SKIP[node.tagName]) return '';

        var parts = [tag];
        var attrs = node.attributes;
        var names = [];
        for (var a = 0; a < attrs.length; a++) {
            var name = attrs[a].name.toLowerCase();
            if (!skipAttr(name)) names.push(name + '=' + attrs[a].value);
        }
        // Sorted: attribute order is not part of a document's meaning, and a
        // browser is free to report it differently between reads. Hashing
        // them in encounter order would make identical subtrees hash
        // differently and defeat the pruning at random.
        names.sort();
        for (var s = 0; s < names.length; s++) parts.push(names[s]);

        if (node.shadowRoot) {
            var sk = node.shadowRoot.childNodes;
            var scounts = {};
            for (var s = 0; s < sk.length; s++) {
                var sh = hashOf(sk[s], childPath(path, sk[s], s, scounts));
                if (sh) parts.push(sh);
            }
        }

        var kids = node.childNodes;
        var counts = {};
        for (var c = 0; c < kids.length; c++) {
            var kh = hashOf(kids[c], childPath(path, kids[c], c, counts));
            if (kh) parts.push(kh);
        }

        var h = fnv(parts.join('|'));
        hashes[path] = h;
        return h;
    }

    function serialize(node, path) {
        if (seen++ > MAX_NODES) return;

        if (node.nodeType === 3) {
            var txt = node.nodeValue;
            if (txt && txt.trim()) out.push(escText(txt));
            return;
        }
        if (node.nodeType !== 1) return;
        if (SKIP[node.tagName]) return;

        var tag = node.tagName.toLowerCase();
        var hash = hashes[path];

        /* The pruning. An unchanged subtree becomes a placeholder the caller
         * re-inflates from its own previous copy. Never prune the root: a
         * document that is entirely a placeholder has no structure for the
         * splice to attach to. */
        if (known && hash && known[hash] && path !== '/html') {
            out.push('<template data-vertiscope-same="' + escAttr(hash) + '"></template>');
            stats.pruned++;
            stats.prunedNodes += countNodes(node);
            return;
        }

        stats.emitted++;
        out.push('<' + tag);
        var attrs = node.attributes;
        for (var i = 0; i < attrs.length; i++) {
            out.push(' ' + attrs[i].name + '="' + escAttr(attrs[i].value) + '"');
        }
        if (hash) out.push(' data-vertiscope-hash="' + escAttr(hash) + '"');
        out.push('>');

        if (VOID[tag]) return;

        if (node.shadowRoot) {
            out.push('<template shadowrootmode="open">');
            var sk = node.shadowRoot.childNodes;
            var scounts = {};
            for (var s = 0; s < sk.length; s++) {
                serialize(sk[s], childPath(path, sk[s], s, scounts));
            }
            out.push('</template>');
        }

        var kids = node.childNodes;
        var counts = {};
        for (var c = 0; c < kids.length; c++) {
            serialize(kids[c], childPath(path, kids[c], c, counts));
        }
        out.push('</' + tag + '>');
    }

    function childPath(path, kid, index, counts) {
        if (kid.nodeType === 1) {
            var kt = kid.tagName.toLowerCase();
            counts[kt] = (counts[kt] || 0) + 1;
            return path + '/' + kt + '[' + counts[kt] + ']';
        }
        return path + '/#text' + index;
    }

    function countNodes(node) {
        var n = 1;
        if (node.shadowRoot) {
            var sk = node.shadowRoot.childNodes;
            for (var s = 0; s < sk.length; s++) n += countNodes(sk[s]);
        }
        var kids = node.childNodes;
        for (var i = 0; i < kids.length; i++) n += countNodes(kids[i]);
        return n;
    }

    var out = [];
    var root = document.documentElement;

    /* The hash pass must mirror the serialize pass's paths exactly, or a
     * subtree would be looked up under a path it was never stored at and
     * pruning would silently never fire. Both build the path the same way. */
    hashOf(root, '/html');
    serialize(root, '/html');

    var html = out.join('');
    stats.bytes = html.length;
    return JSON.stringify({ html: html, hashes: hashes, stats: stats });
})(__known);
