/*
 * sensor.js — a passive catamorphism cache over the composed tree.
 *
 * One fold computes, per node, in one visit:
 *   spine        balanced aggregation over children: digest + count (rank)
 *   content      commutative invertible fingerprint over tokens
 *   chars        content size, for chunk boundaries
 *   det          local content detections
 *   sketch       fixed-width token counts, for containment tests
 * and carries `path` downward as an inherited attribute.
 *
 * State lives in a WeakMap keyed on Node. Nothing is written to the DOM: no
 * attributes, no expandos. Nothing reads layout. The only reachable surface
 * is the handle returned by this IIFE, which the injector parks under a
 * random non-enumerable property.
 *
 * Boundary contract (one round trip):
 *   drain() -> {v, dict[], chunks[], removed[], stats{}}
 */
(function (CFG) {
  'use strict';

  // A factory expression, not a self-invocation: the injector applies it and
  // keeps the returned handle. That keeps the module a single value with no
  // statement of its own, so it can be embedded in any boot wrapper without
  // the wrapper having to know how it ends.
  CFG = CFG || {};
  var BUDGET = CFG.budget > 0 ? CFG.budget : 1200;
  var MERGE_AT = BUDGET >> 1;          // hysteresis: split at BUDGET, merge below half
  // Both are reassigned by the `budget` axis below.
  var DEBOUNCE = CFG.debounce > 0 ? CFG.debounce : 80;
  // PUSH, not poll (2026-09-27): with `signal` set, the sensor tells its host
  // the moment a repair leaves chunks to drain, and which chunk the pointer
  // is over. The host polled instead -- a drain every 1.2 s, a hover read
  // every 80 ms, each a crossing that cost 10-23 ms on a busy page -- and a
  // reader felt 65-138 ms of hover lag and up to 1.2 s of stream lag. The
  // channel is the page's console (the webview reports it to the host); no
  // DOM is touched. Captured at boot, so a page that wraps console later
  // cannot swallow it.
  var SIGNAL = typeof CFG.signal === 'string' && CFG.signal ? CFG.signal : '';
  //
  // Only the browser's OWN console. A page that has wrapped it -- error
  // reporters keep console calls as breadcrumbs and send them with their
  // reports -- would carry these signals off the machine, and nothing is
  // transmitted; such a page gets no signals and its host polls instead.
  var SAY = null;
  try {
    if (SIGNAL && typeof console !== 'undefined' && console.debug
        && /\[native code\]/.test(Function.prototype.toString.call(console.debug))) {
      SAY = console.debug.bind(console);
    }
  } catch (e) { SAY = null; }
  // `push`: the drain itself travels on that channel, sent from the task that
  // folded it (2026-09-27, discourse after long scrolling: a drain PULLED by
  // the host queued behind the page's own long tasks -- a bare round trip
  // measured 12 ms p50 and 942 ms max -- so the diff reached the overlay
  // 30-231 ms after the fold, growing drain by drain). One channel, in order.
  var PUSH = !!(SAY && CFG.push);
  var signalled = false;
  // When the oldest undrained mutation arrived (epoch ms: the host's clock
  // agrees with it, performance.now()'s origin does not), so the host can
  // time mutation -> overlay end to end. Not a layout read.
  var dirtySince = 0;
  // When the last pushed fold ran (see `schedule`).
  var lastFoldAt = -1e9;
  var SKETCH_W = 16;                   // counters per node, fixed width

  // Variants. Each names one mechanism from the design space and can be
  // switched independently, so the harness can run the same pages through
  // different combinations and compare them rather than argue about them.
  // Each axis names one mechanism from the design-space notes and defaults to
  // the choice the design settled on, so `variant <name> off` in the REPL
  // reads the same page without it and the two can be compared rather than
  // argued about.
  var V = CFG.variants || {};
  var USE_DEDUP = !!V.dedup;           // II §7  sketch-then-verify subsumption
  var USE_GATE = V.gate !== false;     // II §10 emit only moved digests
  var USE_CACHE = V.cache !== false;   // II §6  cache-consulting walk filter
  var USE_INTERN = V.intern !== false; // II §10 / DS §J interned transport

  // --- transport encodings ------------------------------------------------
  // Measured: the payload is ~45% path and ~22% text, and drain time tracks
  // payload at roughly 0.9 ms/KB, so what crosses the wire is the dominant
  // per-pass cost. These four attack it from different directions and are
  // off by default, because a transport that is not the one the decoder
  // expects is a corruption, not a saving.
  var USE_PATHDELTA = !!V.pathdelta;   // path as (shared prefix, suffix)
  var USE_SHAPE = !!V.shape;           // shape table + per-line ordinals
  var USE_VALDICT = !!V.valdict;       // intern line values, not just segments
  var USE_PACKED = !!V.packed;         // int runs as one string, not an array

  // --- work avoided -------------------------------------------------------
  var USE_SUBTREEGATE = !!V.subtreegate;  // never descend an unmoved subtree
  var USE_SPANS = !!V.spans;              // re-aggregate only the dirty range
  var USE_VIEWPORT = !!V.viewport;        // emit what is on screen first

  // --- chunking policy ----------------------------------------------------
  var USE_MERGE = !!V.merge;       // MERGE_AT hysteresis: fold tiny siblings
  var PLANT_UNSEEN_MERGED = !!V.unseenmerged;  // planted: merged slots swept (G-142)
  // Planted arms a check flips at RUN time (the V flags are fixed at boot).
  // Peripheral reads only -- nothing here touches the fold.
  // `codespans` may also be set at boot (`variants.codespans`): chunks are
  // emitted and cached at the first fold, before a run-time flip could act.
  var RT_PLANTS = { yclip: false, lightpath: false, codespans: !!V.codespans, xmlnsurl: !!V.xmlnsurl };
  var USE_SEMANTIC = !!V.semantic; // prefer heading/section boundaries
  var USE_RANK = !!V.rank;         // heaviest subtree first, not document order
  var WIDE = V.budget === 'wide', NARROW = V.budget === 'narrow';

  // --- observation --------------------------------------------------------
  var USE_WIDEATTRS = !!V.attrs;      // every attribute, not the content ten
  var NO_CHARWATCH = V.charwatch === false;  // stop watching text mutations
  var USE_PERCHUNK = !!V.perchunk;    // an observer per chunk root

  // --- scheduling ---------------------------------------------------------
  var USE_LAZY = !!V.lazy;    // no timer at all: repair only when drained
  var USE_EAGER = !!V.eager;  // repair inside the mutation callback

  // --- addressing ---------------------------------------------------------
  var USE_ANCHORED = !!V.anchored;  // generalise ordinals below the landmark
  var USE_IDANCHOR = !!V.idanchor;  // root the path at the nearest id

  // --- dedup / suppression ------------------------------------------------
  var USE_SIMHASH = !!V.simhash;    // near-duplicate, not exact containment
  // simhash is a mode of dedup, not a peer of it: the suppression it changes
  // only runs on the dedup path. Selecting it alone silently did nothing, so
  // it turns dedup on rather than pretending to be independent.
  if (USE_SIMHASH) USE_DEDUP = true;
  // Content digests the receiver already holds, passed in at boot. This is
  // the original serializer's `known_hashes` idea moved to where it pays:
  // it prunes before the bytes cross rather than after.
  var KNOWN = {};
  if (CFG.known && CFG.known.length) {
    for (var _k = 0; _k < CFG.known.length; _k++) KNOWN[CFG.known[_k]] = 1;
  }
  var USE_CROSSPAGE = !!V.crosspage;

  // --- variants proposed from what the sweep measured ---------------------
  // `chunkdelta`: the largest untested headroom. Every existing axis
  // compresses *within* one payload; none exploits that a re-emitted chunk
  // usually differs from its predecessor by a line or two. Send the lines
  // that changed against the version the receiver already holds.
  var USE_CHUNKDELTA = !!V.chunkdelta;
  // `textdict`: interning covers path segments and, with `valdict`, whole
  // line values. Neither helps prose, which is ~22% of the payload and
  // mostly unique — but its *words* are not. A per-drain word dictionary
  // costs one pass over text already in hand.
  var USE_TEXTDICT = !!V.textdict;
  // `coalesce`: measured drains showed many passes carrying a single
  // changed chunk. Holding a drain until either N chunks or T ms have
  // accumulated trades latency for round trips, and the boundary is the
  // fixed cost.
  var USE_COALESCE = !!V.coalesce;
  // `deepgate`: `subtreegate` stops the *walk*; the fold above it still
  // re-aggregates a clean subtree's ancestors. Carry the emitted digest
  // upward so an unchanged branch is skipped before its parent sums it.
  var USE_DEEPGATE = !!V.deepgate;

  // `shape` and `pathdelta` both rewrite the same field, so they are not
  // independent and must not both be believed in one sweep. Shape wins when
  // both are set, and the flag reported back says which actually ran.
  if (USE_SHAPE) USE_PATHDELTA = false;

  if (WIDE) { BUDGET = BUDGET * 2; MERGE_AT = BUDGET >> 1; }
  if (NARROW) { BUDGET = BUDGET >> 1; MERGE_AT = BUDGET >> 1; }

  // Blocks a reader would not want split down the middle. `semantic` lets one
  // of these overrun the budget rather than cut it, which trades a bigger
  // chunk for a whole one — a quality choice, so `verify` judges it, not
  // `compare`.
  var SEMANTIC_TAGS = { ARTICLE: 1, SECTION: 1, LI: 1, TR: 1, BLOCKQUOTE: 1,
                        FIGURE: 1, DD: 1, DT: 1, ASIDE: 1, MAIN: 1, NAV: 1,
                        HEADER: 1, FOOTER: 1, FORM: 1, TABLE: 1, UL: 1, OL: 1 };
  var LANDMARK_TAGS = { MAIN: 1, NAV: 1, ARTICLE: 1, SECTION: 1, ASIDE: 1,
                        HEADER: 1, FOOTER: 1, FORM: 1, TABLE: 1 };

  // Not traversed, matching docs/CONTENT_EXTRACTION_RULES section 8.5 so
  // both extraction paths agree on what is not content.
  //
  // HEAD is the addition, and it earns its place at the render: a results
  // page opened with `text/html; charset=UTF-8`, a viewport declaration,
  // `noindex, nofollow` and eleven favicon urls before the first result.
  // Those are real detections -- `content` and `href` attributes, exactly as
  // the rules describe them -- and they are also the first thing a reader
  // sees, which makes a structure-native render of the page a render of its
  // metadata. The tagger has never traversed head; the sensor was the only
  // one that did.
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1,
                    HEAD: 1 };
  // Drawn as a single control, never descended into. Their children exist,
  // and a reader reaches them by acting on the control -- which is exactly
  // what a browser does with them.
  //
  // `svg` moved here from SKIP_TAGS. Skipping it was right about the
  // children -- a few hundred <path> elements are geometry, not content --
  // and wrong about the element, which carries the picture's accessible
  // name. Skipped outright, the fold never saw it, so nothing entered the
  // trie: every logo on lit.dev ("Adobe", "Cisco", "Google", "IBM",
  // "Alaska Airlines") was absent from the map, and `attr` capture measured
  // 72% against a page-side ground truth that counts them.
  //
  // Folded instead, the element is emitted with its own detections and its
  // children are not descended -- the exact shape a <select> already had.
  // Ordinals are per tag name, so admitting `svg` renumbers only `svg`
  // siblings and moves no other address.
  var FOLDED = { SELECT: 1, DATALIST: 1, OPTGROUP: 1, svg: 1 };
  // The detectable-content space of docs/CONTENT_EXTRACTION_RULES, in the
  // page. This list was ten attributes, chosen by hand, and the cost of that
  // was measured against the host tagger on one Wikipedia article: `resource`
  // 0 vs 85, `data-title` 0 vs 137, `aria-labelledby` 0 vs 48, `data-mw` 0 vs
  // 465. Every one of those is content the live path could not see and the
  // snapshot path could, which made the O(delta) route the impoverished one.
  //
  // Three named groups, exactly as the host has them: attributes that bear a
  // URL, attributes that bear an accessible name, and attributes that bear
  // metadata. Union, deduplicated, because one attribute may be more than one
  // of those and the address records which rule found it, not which list it
  // came from.
  var URL_ATTRS = ['action', 'cite', 'data', 'data-image', 'data-lazy-src',
                   'data-original', 'data-original-src', 'data-src',
                   'formaction', 'href', 'longdesc', 'poster', 'src'];
  var TEXT_ATTRS = ['abbr', 'acronym', 'alt', 'aria-describedby',
                    'aria-description', 'aria-errormessage', 'aria-label',
                    'aria-labelledby', 'aria-placeholder',
                    'aria-roledescription', 'aria-valuetext', 'caption',
                    'label', 'placeholder', 'summary', 'title'];
  var META_ATTRS = ['content', 'data-alt', 'data-caption', 'data-description',
                    'data-label', 'data-name', 'data-placeholder',
                    'data-text', 'data-title', 'data-tooltip', 'data-value',
                    'datetime'];
  var CONTENT_ATTRS = (function () {
    var seen = {}, out = [], i, g, groups = [URL_ATTRS, TEXT_ATTRS, META_ATTRS,
                                             ['srcset', 'value']];
    for (g = 0; g < groups.length; g++)
      for (i = 0; i < groups[g].length; i++)
        if (!seen[groups[g][i]]) { seen[groups[g][i]] = 1; out.push(groups[g][i]); }
    return out;
  }());

  // Outside the named lists the scan is attribute-agnostic: the URL pattern is
  // applied to whatever is left. That is what recovers content from
  // site-specific attributes nobody enumerated -- `data-mw`, `resource` and
  // `typeof` all carry URLs on real pages and appear in no list anywhere.
  // Enumerating them was never going to work; the host reaches them this way
  // and the sensor could not reach them at all.
  var CONTENT_SET = {};
  (function () {
    for (var i = 0; i < CONTENT_ATTRS.length; i++) CONTENT_SET[CONTENT_ATTRS[i]] = 1;
  }());
  var ATTR_SKIP = {};
  (function () {
    var deny = ('aria-activedescendant aria-atomic aria-busy aria-checked '
      + 'aria-colcount aria-colindex aria-colspan aria-controls aria-current '
      + 'aria-disabled aria-expanded aria-flowto aria-haspopup aria-hidden '
      + 'aria-invalid aria-level aria-live aria-modal aria-multiline '
      + 'aria-multiselectable aria-orientation aria-owns aria-posinset '
      + 'aria-pressed aria-readonly aria-relevant aria-required aria-rowcount '
      + 'aria-rowindex aria-rowspan aria-selected aria-setsize aria-sort '
      + 'aria-valuemax aria-valuemin aria-valuenow autocapitalize autocomplete '
      + 'autocorrect class clip-path clip-rule d dir enctype fill fill-rule '
      + 'filter for height id is lang method name opacity points slot '
      + 'spellcheck stroke stroke-linecap stroke-linejoin stroke-width style '
      + 'tabindex target transform translate type version viewbox width xmlns '
      + 'checked cols colspan contenteditable disabled draggable enterkeyhint '
      + 'headers hidden inputmode max maxlength min minlength multiple pattern '
      + 'pubdate readonly required reversed role rows rowspan scope selected '
      + 'size start step wrap').split(' ');
    for (var i = 0; i < deny.length; i++) ATTR_SKIP[deny[i]] = 1;
  }());
  var ATTR_SKIP_PREFIX = ['data-testid', 'data-cy-', 'data-qa-',
                          'data-automation', 'data-react', 'data-radix',
                          'data-state', 'data-orientation', 'data-side',
                          'data-align', 'data-disabled'];
  var URL_IN_ATTR = /(https?:\/\/[^\s"'<>(){}\[\]]+|\/\/[^\s"'<>(){}\[\]]+|data:[a-zA-Z0-9+\/.-]+;[^\s"'<>]+|blob:[^\s"'<>]+)/;

  // Every URL in one attribute value, each keyed by where in the value it
  // sits. The sub-path is intrinsic -- a character offset in the attribute's
  // own text -- so it is re-derivable by anyone holding the address and does
  // not depend on the order detectors happened to run in.
  function pushUrls(out, name, val, skipFirst) {
    var re = new RegExp(URL_IN_ATTR.source, 'g');
    var m, n = 0;
    while ((m = re.exec(val)) !== null) {
      if (m[0].length < 2) { re.lastIndex++; continue; }
      if (!(skipFirst && n === 0)) {
        out.push([intern(n === 0 ? name : name + '@' + m.index), m[0]]);
      }
      n++;
      if (n > 64) break;
    }
  }

  var URL_SET = {};
  (function () {
    for (var i = 0; i < URL_ATTRS.length; i++) URL_SET[URL_ATTRS[i]] = 1;
    URL_SET.srcset = 1;
  }());
  var MULTI_URL = /[,\s]/;

  function agnosticSkip(name) {
    if (ATTR_SKIP[name]) return true;
    // A namespace declaration names a vocabulary, never a resource. Only
    // `xmlns` itself was denied, so every inline SVG declaring
    // `xmlns:xlink` became a picture of `http://www.w3.org/1999/xlink` --
    // eleven broken images in one copykat share bar (G-197, 2026-10-18).
    // `content_tagger` denied it all along. Planted (run time):
    // `plants.xmlnsurl`.
    if (!RT_PLANTS.xmlnsurl && name.lastIndexOf('xmlns', 0) === 0) return true;
    for (var i = 0; i < ATTR_SKIP_PREFIX.length; i++)
      if (name.indexOf(ATTR_SKIP_PREFIX[i]) === 0) return true;
    return false;
  }
  // With `attrs` on, every attribute is content. That is more of the page,
  // and also every framework's bookkeeping — the cost of the wider net is
  // exactly what the axis exists to price.
  var ATTR_FILTER = USE_WIDEATTRS ? null : CONTENT_ATTRS;

  // ---- state ------------------------------------------------------------
  var records = new WeakMap();   // Node -> Record
  var chunkOf = new WeakMap();   // Node -> {id, digest} for chunk roots only
  var roots = new Map();         // root Node -> MutationObserver
  var dirtySpans = new Map();    // parent Node -> {lo, hi}
  var pendingMasks = null;       // masked href -> 1, families to recheck
  var front = [], back = [];     // double-buffered emissions
  var removedIds = [];
  var chunkRoots = [];           // live chunk-root slots, for the removal sweep
  var dict = [], dictIndex = new Map(), dictSent = 0;
  // What "already sent" means. `resync` moves it on, and every gate that
  // skips an unchanged chunk asks for the current generation too -- so the
  // next fold sends the whole page, with the whole dictionary, to a receiver
  // that lost its copy (a sidecar restarted under a page left open, 2026-10-11:
  // ids decoded against an empty dictionary stored /header/tr[2]/b/small/i[88]
  // for Wikipedia's table rows).
  var EMIT_GEN = 0;
  var timer = null, chunkSeq = 1, version = 0;
  // Chunks whose content is unchanged and whose address moved.
  // Carried beside `chunks` and `removed`, and drained with them.
  var moves = [];
  var SVG_TITLE_ID = -1;
  var OFFSET_ID = -1;   // `text()@`, the accessor a split piece carries
  var stats = { nodes: 0, folds: 0, repairs: 0, chunks: 0, spans: 0,
                movedChunks: 0, unrooted: 0, reclassified: 0,
                observers: 0, closedRoots: 0, errors: 0, skipped: 0,
                sketchHits: 0, deduped: 0, pruned: 0, offscreen: 0,
                sr_seen: 0, sr_badtype: 0, sr_badname: 0,
                sr_novocab: 0, sr_hit: 0, sr_form: 0, sr_type: 0,
                sr_url: 0, sr_queryform: 0, chunkDeltas: 0,
                wordsInterned: 0, coalesced: 0, deepPruned: 0,
                spanHits: 0, spanWide: 0, merged: 0, knownSkips: 0,
                nearDups: 0 };

  // ---- interning (§10) --------------------------------------------------
  // With the axis off, a segment travels as its own string. The payload then
  // needs no dictionary and no receiver state, and costs the difference —
  // which is the point of being able to switch it.
  function intern(s) {
    if (!USE_INTERN) return s;
    var id = dictIndex.get(s);
    if (id === undefined) { id = dict.length; dict.push(s); dictIndex.set(s, id); }
    return id;
  }

  // ---- hashing ----------------------------------------------------------
  // 32-bit FNV-1a. Structure digests combine positionally; content
  // fingerprints combine by addition mod 2^32, which is commutative and
  // invertible so an ancestor repairs by subtract-old/add-new.
  function fnv(s) {
    var h = 0x811c9dc5;
    for (var i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h >>> 0;
  }
  function mix(a, b) { return (((a << 5) - a) + b) >>> 0; }

  // A digest says what a subtree contains. It does not say where the subtree
  // is, and the two gates below were treating "unchanged" as though it did.
  // A subtree that MOVES keeps its digest exactly — a slot reassignment, a
  // reordered list — so its chunk was suppressed and the receiver went on
  // holding the address the content used to have, with nothing anywhere
  // reporting a change. Measured on composed_slots_bulk.html at budget 200:
  // after one slot reassignment, both addresses for the moved block were
  // stale and neither was right. The path is already built by the time
  // either gate runs, so closing this costs one fold over it.
  function pathKey(path) {
    var h = 2166136261, i, v;
    if (!path) return 0;
    for (i = 0; i < path.length; i++) {
      v = path[i];
      h = mix(h, (typeof v === 'number') ? (v >>> 0) : fnv(String(v)));
    }
    return h >>> 0;
  }

  // ---- tokens -----------------------------------------------------------
  var TOKEN_RE = /[A-Za-z0-9À-￿]+/g;
  function tokenize(text) {
    if (!text) return null;
    return text.toLowerCase().match(TOKEN_RE);
  }

  // ---- records ----------------------------------------------------------
  // One shape, always the same fields in the same order, never deleted, so
  // the JIT keeps a single hidden class for every record in the document.
  function newRecord() {
    return {
      digest: 0,        // positional, over children
      content: 0,       // commutative invertible, over tokens
      chars: 0,
      count: 1,         // subtree node count, doubles as spine rank weight
      det: null,
      sketch: null,
      text: '',
      toks: null,       // own tokens, for the exact containment check
      tax: null,        // memoised [taxId, ruleId, rank]; local, not inherited
      sim: 0,           // memoised simhash, for the near-duplicate axis
      chunk: 0,
      emit: -1,         // digest at last emission, for `subtreegate`
      emitPath: -1,     // and where it was emitted, so a move is not "unchanged"
      lo: -1,           // dirty child range, for `spans`
      hi: -1,
      // The aggregate over children as last computed, kept apart from the
      // node's own totals (which also carry its detections). `spans` repairs
      // these by subtract-old/add-new instead of re-summing every child —
      // which is the whole reason the content fingerprint is commutative and
      // invertible rather than positional like the digest.
      kc: 0, kh: 0, kn: 0, ks: null,
      dirty: true
    };
  }

  // The element's own classification, computed once per fold. `taxonomyOf`
  // needs the label text for the pagination vocabulary, and only anchors and
  // buttons carry a label worth reading — bounded by the chunk budget, so
  // this never walks a large subtree.
  function taxOf(node, rec) {
    if (rec.tax) return rec.tax;
    var tag = node.tagName, text = '';
    if ((tag === 'A' || tag === 'BUTTON') && rec.chars <= BUDGET) {
      try { text = node.textContent || ''; } catch (e) { text = ''; }
    }
    // Two classifications, and only one of them decides anything.
    //
    // `kindOf` is the render class: what to draw, from the element's type via
    // HTML-AAM. It goes in the address's taxonomy slot and governs the glyph,
    // so every structure on the page is drawn because of what it IS.
    //
    // `taxonomyOf` still runs, and its verdict still travels -- as the rule
    // that fired, in the detection slot, next to the render class it could
    // not override. That demotion is the point. Search and pagination name
    // intentions; a wrong guess about one now costs a label in the
    // provenance and no longer costs a control the reader never sees.
    var t = taxonomyOf(node, text);
    var k = kindOf(node);
    // The verdict is registered here, from `t`, because here is the only
    // place it still exists. The line below keeps `t[1]` -- the rule that
    // fired -- and drops `t[0]`, the word it decided on, so a caller reading
    // the finished address cannot ask "is this a pager?" any more.
    notePager(node, t[0]);
    rec.tax = [intern(k[0]), intern(t[1] + '/' + k[1]), KIND_RANK[k[0]] || 0];
    return rec.tax;
  }

  function sketchOf(tokens, into) {
    var s = into || new Uint16Array(SKETCH_W);
    if (tokens) {
      for (var i = 0; i < tokens.length; i++) {
        s[fnv(tokens[i]) & (SKETCH_W - 1)] += 1;
      }
    }
    return s;
  }
  function sketchAdd(dst, src) {
    for (var i = 0; i < SKETCH_W; i++) dst[i] += src[i];
    return dst;
  }
  // §7 step one: does the ancestor account for every counter of the child?
  function covers(anc, child) {
    for (var i = 0; i < SKETCH_W; i++) if (child[i] > anc[i]) return false;
    return true;
  }


  // ---- the detection bank ------------------------------------------------
  // Every entry has an address, and that address is the `@regex-addr` tail of
  // the §1 path — so a rendered line can name the rule that found it. The
  // taxonomy it returns is the `@taxonomy` segment, which decides what
  // markdown field the content becomes.
  //
  // Negative vocabularies matter more than positive ones here: on a real page
  // "next" appears in a video player, a cart and a social toolbar long before
  // it appears in a pager. Ported from the collectors in
  // backend/dom/web_distiller_freq.py.
  var SEARCH_VOCAB = ['search', 'query', 'find', 'keyword', 'lookup', 'srch',
                      'buscar', 'recherche', 'suche'];
  var SEARCH_BAD_TYPE = { hidden: 1, email: 1, checkbox: 1, radio: 1, file: 1,
                          image: 1, color: 1, date: 1, range: 1, password: 1 };
  var SEARCH_BAD_NAME = /(first.?name|last.?name|subbox|subscribe|signup|newsletter|password|captcha|token|nonce|csrf|turnstile)/i;

  var PAGE_NEG = { player: 1, volume: 1, mute: 1, fullscreen: 1, pip: 1,
                   rewind: 1, scrub: 1, playback: 1, audio: 1, video: 1,
                   cart: 1, wishlist: 1, addtocart: 1, reply: 1, repost: 1,
                   retweet: 1, bookmark: 1, dropdown: 1, haspopup: 1,
                   favorite: 1, share: 1, social: 1 };
  var PAGE_WIDGET_DENY = { 'slick-fab': 1, 'slick-heartbeat': 1,
                           'soso-button': 1, 'soso-icon-button': 1,
                           'soso-icon': 1 };

  // Specificity. Taxonomy descends as an inherited attribute (§1: the
  // `@taxonomy` segment belongs to the extracted content, not to whichever
  // element happens to hold the characters), and a descendant overrides an
  // ancestor only when it is at least as specific. That is what makes inline
  // wrappers transparent without enumerating them: SPAN, EM, SMALL and their
  // kind classify as `paragraph`, rank 0, which never overrides — so text
  // inside `<h1><span>` is a heading, and text inside `<blockquote><p>` is a
  // quote. Equal ranks let the deeper element win, so LI beats UL.
  var TAX_RANK = { paragraph: 0, field: 3, control: 3, link: 3,
                   list: 4, table: 4, quote: 4, code: 4, media: 4, form: 4,
                   heading: 5, search: 6, pagination: 6 };

  // Specificity ladder over render classes, so classification is an
  // inherited attribute and a wrapper cannot claim its content. `group` sits
  // at the floor deliberately: a container that outranked its children would
  // draw a whole article as one undifferentiated block.
  var KIND_RANK = { none: 0, text: 0, group: 0, slider: 3,
                    item: 2, row: 2, cell: 2,
                    link: 3, button: 3, field: 3, choice: 3, check: 3,
                    quote: 4, code: 4, image: 4, media: 4, rule: 4,
                    heading: 5 };

  var HEADING = { H1: 1, H2: 2, H3: 3, H4: 4, H5: 5, H6: 6 };
  var LIST_TAGS = { UL: 1, OL: 1, LI: 1, DL: 1, DT: 1, DD: 1 };
  var MEDIA_TAGS = { IMG: 1, PICTURE: 1, VIDEO: 1, AUDIO: 1, SOURCE: 1,
                     FIGURE: 1, CANVAS: 1, OBJECT: 1, EMBED: 1 };

  function attrSoup(el) {
    var s = el.tagName.toLowerCase(), a = el.attributes, i;
    for (i = 0; i < a.length; i++) {
      s += ' ' + a[i].name.toLowerCase() + '=' + (a[i].value || '').toLowerCase();
    }
    return s;
  }

  function hasNeg(soup, table) {
    for (var k in table) if (soup.indexOf(k) !== -1) return true;
    return false;
  }

  // A whole label that names a pager. Anchored at both ends on purpose: a
  // pager says what it is and nothing else, so "Next" is one and "Search
  // with your voice" is not, however much markup happens to contain "next".
  var PAGE_LABEL = new RegExp(
    '^[\\s«»‹›←→]*(?:' +
      '\\d{1,4}' +                                   // 1 2 3 …
      '|(?:load|show|see|view|read)\\s+more(?:\\s+\\w+)?' +
      '|more\\s+(?:results|pages|items|posts|stories|articles|entries|comments)' +
      '|next(?:\\s+(?:page|results|set))?' +
      '|prev(?:ious)?(?:\\s+(?:page|results|set))?' +
      '|(?:older|newer)(?:\\s+\\w+)?' +
      '|continue(?:\\s+reading)?' +
      '|first(?:\\s+page)?|last(?:\\s+page)?' +
    ')[\\s«»‹›←→]*$', 'i');

  // A bare number is a page number only inside something that says it is a
  // pager. Four levels is enough for `nav > ul > li > a` and stops there.
  function nearPagerContainer(el) {
    var n = el, hops = 0;
    while (n && n.nodeType === 1 && hops++ < 4) {
      var id = ((n.className && n.className.baseVal !== undefined
                 ? n.className.baseVal : n.className) || '') + ' ' + (n.id || '');
      if (/paginat|pager\b|page-nav|page-numbers/i.test(id)) return true;
      var role = n.getAttribute && n.getAttribute('aria-label');
      if (role && /paginat|pages?\b/i.test(role)) return true;
      n = n.parentNode;
    }
    return false;
  }

  // ---- structural signals ------------------------------------------------
  // Vocabulary is a guess about what a page calls a thing. These are
  // statements about what the thing *is*, and they hold in any language.

  // A field whose name appears as a query parameter of the page you are
  // standing on produced this page. Nothing needs to be recognised: the URL
  // is the evidence, and it is evidence the site itself wrote.
  function fieldEchoedInUrl(name) {
    if (!name) return false;
    try {
      var qs = location.search || '';
      if (!qs) return false;
      var esc = String(name).replace(/[^A-Za-z0-9_]/g, '\$&');
      return new RegExp('[?&]' + esc + '=').test(qs);
    } catch (e) { return false; }
  }

  // A GET form carrying exactly one visible text field and nothing else to
  // fill in is a query form. That is what "search" *means* structurally —
  // submitting it can only produce a URL with that field in the query — and
  // it is true of sites that call the field `q`, `s`, `term`, or nothing.
  function isQueryForm(el) {
    var f = null;
    try { f = el.form || (el.closest ? el.closest('form') : null); }
    catch (e) { return false; }
    if (!f) return false;
    var method = ((f.getAttribute && f.getAttribute('method')) || 'get')
      .toLowerCase();
    if (method !== 'get') return false;
    var els = f.elements || [], texts = 0, others = 0, i, c, t;
    for (i = 0; i < els.length; i++) {
      c = els[i];
      t = ((c.type || '') + '').toLowerCase();
      if (t === 'hidden' || t === 'submit' || t === 'image' || t === 'button'
          || c.tagName === 'BUTTON') continue;
      if (t === 'text' || t === 'search' || t === ''
          || c.tagName === 'TEXTAREA') texts++;
      else others++;
    }
    return texts === 1 && others === 0;
  }

  // Sibling links whose hrefs are identical except for their digits are a
  // pager, whatever they are labelled. `?page=2` beside `?page=3` beside
  // `?page=4` is a pagination control in every language there is, and the
  // vocabulary bank never has to have heard of the site.
  //
  // The families in a scope are read ONCE per fold pass. Asked per link, a
  // topic list of N digit-bearing links queried its whole scope N times --
  // quadratic in the batch, and on discourse's /latest the larger part of a
  // 30-topic fold (2026-09-27). What the memo is a function of (5c): the
  // scope's subtree at this instant. A fold pass is synchronous and writes
  // nothing into the page, so that subtree cannot change during one; the
  // memo is dropped when the pass ends and never outlives it.
  var familyMemo = null;
  function familiesIn(scope) {
    var got = familyMemo && familyMemo.get(scope);
    if (got) return got;
    var links = scope.querySelectorAll('a[href]');
    var fam = { links: links.length, by: {} };
    for (var i = 0; i < links.length; i++) {
      var h = links[i].getAttribute('href');
      if (!h || !/\d/.test(h)) continue;
      var mask = h.replace(/\d+/g, '#');
      var key = h.match(/\d+/g).join(',');
      var f = fam.by[mask] || (fam.by[mask] = { n: 0, seen: {} });
      if (!f.seen[key]) { f.seen[key] = 1; f.n++; }
    }
    if (familyMemo) familyMemo.set(scope, fam);
    return fam;
  }

  function numericFamily(el) {
    var href = el.getAttribute && el.getAttribute('href');
    if (!href || !/\d/.test(href)) return false;
    var scope = el.parentNode;
    for (var up = 0; up < 3 && scope && scope.parentNode; up++) {
      scope = scope.parentNode;
    }
    if (!scope || !scope.querySelectorAll) return false;
    var fam = familiesIn(scope);
    if (fam.links < 3) return false;
    var mine = fam.by[href.replace(/\d+/g, '#')];
    // Three distinct members of one numeric family, differing only in their
    // digits. Two is a coincidence; three is a series.
    return !!mine && mine.n >= 3;
  }

  // -> the rule that fired, i.e. the `@regex-addr` tail, or null
  function pagerSignal(el, lowText) {
    // The standard first: rel=next / rel=prev is what the spec provides for
    // exactly this, and a page that uses it is telling us outright.
    var rel = (el.getAttribute && el.getAttribute('rel') || '').toLowerCase();
    if (/(^|\s)(next|prev|previous)(\s|$)/.test(rel)) return 'pagination.rel';

    // A numeric family of sibling links is a pager in any language. This
    // sits above the label vocabulary because it needs no words at all: the
    // site's own url scheme is the evidence, and a page that numbers its
    // pages has told us where they are without naming them.
    if (numericFamily(el)) return 'pagination.family';

    // Then the accessible name — what a reader would call the control.
    var label = lowText;
    if (!label && el.getAttribute) {
      // `value` last, and it matters: a great many pagers are
      // `<input type=submit value="Next">`, which has no text content at all.
      label = (el.getAttribute('aria-label') || el.getAttribute('title')
               || el.getAttribute('value') || '').trim().toLowerCase();
    }
    if (label && label.length <= 40 && PAGE_LABEL.test(label)) {
      if (/^[\s«»‹›←→]*\d{1,4}[\s«»‹›←→]*$/.test(label)
          && !nearPagerContainer(el)) {
        return null;                      // a bare number, but not in a pager
      }
      return 'pagination.label';
    }

    // Finally a class or id that names pagination outright. Whole tokens
    // only, which is the difference between `pagination` and `shape-next`.
    var cls = ((el.className && el.className.baseVal !== undefined
                ? el.className.baseVal : el.className) || '')
              + ' ' + (el.id || '');
    if (/(^|[\s_-])(paginat\w*|pager|page-numbers|load-?more)([\s_-]|$)/i
        .test(cls)) return 'pagination.class';
    return null;
  }

  // -> [taxonomy, regexAddr]
  // ---- HTML-AAM: element type -> role -> render class -------------------
  // Mirrors vertiscope/aam.py. Data, not logic, and checked rather than
  // trusted: invariants.a1_aam_tables_agree parses this out of the source
  // and compares it, so a divergence is a reported violation, not a drift.
  //
  // Why this replaces taxonomyOf's judgement calls: 'search' and 'pagination'
  // name intentions, and two independent rebuilds of detecting them settled
  // at the same ceiling across 890 pages. What a page does declare, in HTML,
  // is what each element IS -- natively for 98.6 percent of the affordances
  // measured across five unrelated sites. A search box draws as a field
  // because it is a field. Nothing has to be recognised for a reader to use
  // it, which is the whole point: a control we could not name used to be a
  // control the reader never saw.
  var IMPLICIT_ROLE = {"article": "article", "aside": "complementary", "audio": "audio", "blockquote": "blockquote", "button": "button", "caption": "caption", "code": "code", "datalist": "listbox", "dd": "definition", "del": "deletion", "details": "group", "dfn": "term", "dialog": "dialog", "dt": "term", "em": "emphasis", "fieldset": "group", "figcaption": "caption", "figure": "figure", "footer": "contentinfo", "form": "form", "h1": "heading", "h2": "heading", "h3": "heading", "h4": "heading", "h5": "heading", "h6": "heading", "header": "banner", "hgroup": "group", "hr": "separator", "iframe": "document", "ins": "insertion", "li": "listitem", "main": "main", "mark": "mark", "math": "math", "menu": "list", "meter": "meter", "nav": "navigation", "ol": "list", "optgroup": "group", "option": "option", "output": "status", "p": "paragraph", "picture": "image", "pre": "code", "progress": "progressbar", "samp": "code", "search": "search", "strong": "strong", "sub": "subscript", "summary": "button", "sup": "superscript", "svg": "graphics-document", "table": "table", "tbody": "rowgroup", "textarea": "textbox", "tfoot": "rowgroup", "thead": "rowgroup", "time": "time", "tr": "row", "ul": "list", "video": "video"};
  var INPUT_ROLE = {"button": "button", "checkbox": "checkbox", "color": "textbox", "date": "textbox", "datetime-local": "textbox", "email": "textbox", "file": "button", "hidden": "none", "image": "button", "month": "textbox", "number": "spinbutton", "password": "textbox", "radio": "radio", "range": "slider", "reset": "button", "search": "searchbox", "submit": "button", "tel": "textbox", "text": "textbox", "time": "textbox", "url": "textbox", "week": "textbox"};
  var RENDER_CLASS = {"article": "group", "audio": "media", "banner": "group", "blockquote": "quote", "button": "button", "caption": "text", "cell": "cell", "checkbox": "check", "code": "code", "columnheader": "cell", "combobox": "choice", "complementary": "group", "contentinfo": "group", "definition": "text", "deletion": "text", "dialog": "group", "document": "media", "emphasis": "text", "figure": "group", "form": "group", "graphics-document": "image", "grid": "group", "gridcell": "cell", "group": "group", "heading": "heading", "image": "image", "img": "image", "insertion": "text", "link": "link", "list": "group", "listbox": "choice", "listitem": "item", "main": "group", "mark": "text", "math": "text", "menuitem": "button", "menuitemcheckbox": "check", "menuitemradio": "check", "meter": "text", "navigation": "group", "none": "none", "option": "item", "paragraph": "text", "presentation": "none", "progressbar": "text", "radio": "check", "region": "group", "row": "row", "rowgroup": "group", "rowheader": "cell", "search": "group", "searchbox": "field", "separator": "rule", "slider": "slider", "spinbutton": "field", "status": "text", "strong": "text", "subscript": "text", "superscript": "text", "switch": "check", "tab": "button", "table": "group", "tablist": "group", "term": "text", "textbox": "field", "time": "text", "video": "media"};
  var INTERACTIVE_KIND = {"button": 1, "check": 1, "choice": 1, "field": 1, "link": 1, "slider": 1};

  function roleOf(el) {
    var tag = (el.tagName || '').toLowerCase();
    var explicit = el.getAttribute ? (el.getAttribute('role') || '') : '';
    if (explicit) {
      var toks = explicit.toLowerCase().split(/\s+/);
      for (var i = 0; i < toks.length; i++)
        if (RENDER_CLASS[toks[i]]) return toks[i];
    }
    function at(n) { return el.getAttribute ? el.getAttribute(n) : null; }
    if (tag === 'a' || tag === 'area') return at('href') !== null ? 'link' : 'generic';
    if (tag === 'input') {
      var t = (at('type') || 'text').toLowerCase();
      var r = INPUT_ROLE[t] || 'textbox';
      if (r === 'textbox' && at('list') !== null) return 'combobox';
      return r;
    }
    if (tag === 'select') {
      var size = parseInt(at('size') || '0', 10) || 0;
      return (at('multiple') !== null || size > 1) ? 'listbox' : 'combobox';
    }
    if (tag === 'img') return at('alt') === '' ? 'none' : 'img';
    if (tag === 'th') return (at('scope') || '').toLowerCase() === 'row'
      ? 'rowheader' : 'columnheader';
    if (tag === 'td') return 'cell';
    if (tag === 'section')
      return (at('aria-label') || at('aria-labelledby')) ? 'region' : 'group';
    return IMPLICIT_ROLE[tag] || 'generic';
  }

  // Elements whose whole purpose is to carry a resource, and the attributes
  // that carry it. Mirrored by `aam.MEDIA_TAGS` / `aam.has_source`.
  var MEDIA_TAGS = { IMG: 1, PICTURE: 1, SVG: 1, VIDEO: 1, AUDIO: 1,
                     SOURCE: 1, IFRAME: 1, EMBED: 1, OBJECT: 1 };
  var MEDIA_SRC_ATTRS = ['src', 'srcset', 'poster', 'data', 'data-src',
                         'href'];

  function hasSource(el) {
    if (!el || !el.getAttribute) return false;
    for (var i = 0; i < MEDIA_SRC_ATTRS.length; i++) {
      var v = el.getAttribute(MEDIA_SRC_ATTRS[i]);
      if (v !== null && String(v).trim() !== '') return true;
    }
    return false;
  }

  function kindOf(el) {
    var role = roleOf(el);
    // An option inside a select is not a line of the page. A browser draws
    // the select collapsed, showing the one value it currently holds, and
    // the eighty others are behind it until asked for. Drawn flat instead,
    // DuckDuckGo's region filter opened the results view with eighty lines
    // of country names before the first result -- structurally faithful to
    // the markup and useless as a page.
    if (role === 'option' || el.tagName === 'OPTION') {
      try {
        var owner = el.closest && el.closest('select,datalist,[role=listbox]');
        if (owner) return ['none', role];
      } catch (e) { /* fall through and draw it */ }
    }
    var kind = RENDER_CLASS[role] || 'text';
    // A picture with no alt text is still a picture.
    //
    // `roleOf` is right, and stays right: `<img alt="">` is role
    // `presentation` in HTML-AAM, because an empty alt is the author saying
    // "do not announce this". That is a statement about announcement. It is
    // not a statement that the resource does not exist, and using the role
    // as the *render class* turned it into one -- the media reference was
    // dropped and the file was gone from the record. On lit.dev every
    // illustration carries `alt=""`, so the page rendered with zero of its
    // images: 0 of 3 media references reached the markdown.
    //
    // The role is left alone and the class is corrected here, beside the
    // OPTION case, for the same reason: the AAM tables are data checked by
    // invariant a1 and must keep saying what the standard says. What a
    // reader is shown is a separate decision, and this is where it is made.
    if (kind === 'none' && MEDIA_TAGS[el.tagName] && hasSource(el)) {
      return [el.tagName === 'IMG' || el.tagName === 'PICTURE'
              || el.tagName === 'SVG' ? 'image' : 'media', role];
    }
    return [kind, role];
  }

  function taxonomyOf(el, text) {
    var tag = el.tagName;
    var soup = attrSoup(el);
    var lowText = (text || '').trim().toLowerCase();
    var i;

    // search: an input-ish thing whose vocabulary says search and whose
    // type and name do not say something else entirely
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
        || /role="?(search|searchbox|combobox)/.test(soup)) {
      var type = (el.getAttribute && el.getAttribute('type') || '').toLowerCase();
      var name = (el.getAttribute && el.getAttribute('name') || '');
      // A submit whose label names a page is a pager, and this is not an
      // edge case: html.duckduckgo.com — generic search results, the most
      // ordinary page there is — turns its pages with
      // `<input type=submit value="Next">`, which the A/BUTTON-only branch
      // below could never see.
      if (type === 'submit' || type === 'button' || type === 'image') {
        var ph = pagerSignal(el, '');
        if (ph) return ['pagination', ph];
      }
      // Counted, not just decided. Search is found on ~65% of pages and
      // nothing said what the other third looked like: a page with no box
      // at all and a page whose box was rejected are the same outcome and
      // completely different problems.
      stats.sr_seen++;
      if (SEARCH_BAD_TYPE[type]) { stats.sr_badtype++; return ['field', 'field.input']; }
      if (SEARCH_BAD_NAME.test(name)) { stats.sr_badname++; return ['field', 'field.input']; }
      // Structure first. The URL echo is the strongest evidence there is —
      // the page in front of us was produced by submitting this field — and
      // the query-form shape is what "search" means independently of what
      // the site calls it. Vocabulary is the fallback now, not the rule.
      if (fieldEchoedInUrl(name)) { stats.sr_url++; return ['search', 'search.urlparam']; }
      if (isQueryForm(el)) { stats.sr_queryform++; return ['search', 'search.queryform']; }
      for (i = 0; i < SEARCH_VOCAB.length; i++) {
        if (soup.indexOf(SEARCH_VOCAB[i]) !== -1) {
          stats.sr_hit++;
          return ['search', 'search.vocab'];
        }
      }
      // The vocabulary missed. Before giving up, ask the *form* — a text
      // input alone in a form that submits to a search endpoint is a search
      // box whatever it calls itself, and plenty of sites name the field
      // `q`, `s`, `term` or nothing at all.
      if (type === '' || type === 'text' || type === 'search'
          || tag === 'TEXTAREA') {
        var f = el.form || (el.closest ? el.closest('form') : null);
        if (f) {
          var act = ((f.getAttribute && f.getAttribute('action')) || '')
            .toLowerCase();
          var frole = ((f.getAttribute && f.getAttribute('role')) || '')
            .toLowerCase();
          if (frole === 'search' || /search|find|query|suche|recherche/.test(act)) {
            stats.sr_form++;
            return ['search', 'search.form'];
          }
        }
        if (type === 'search') { stats.sr_type++; return ['search', 'search.type']; }
      }
      stats.sr_novocab++;
      return ['field', 'field.input'];
    }

    // pagination: anchors and buttons only, and judged on the control's
    // *name* rather than on its markup. Searching the whole attribute soup
    // for a bare substring is what made this useless on a real page:
    // YouTube's design system calls a component `yt-spec-button-shape-next`,
    // so 37 controls on one results page matched "next" — the mic button,
    // "My Ad Center", "Filters", and "Sign in", whose return URL carries a
    // `next=` query parameter. Class names and query strings are not
    // evidence about what a control does; its accessible name is.
    if (tag === 'A' || tag === 'BUTTON') {
      if (!PAGE_WIDGET_DENY[tag.toLowerCase()] && !hasNeg(soup, PAGE_NEG)) {
        var how = pagerSignal(el, lowText);
        if (how) return ['pagination', how];
      }
      if (tag === 'A') return ['link', 'link.anchor'];
      return ['control', 'control.button'];
    }

    if (HEADING[tag]) return ['heading', 'heading.tag'];
    if (LIST_TAGS[tag]) return ['list', 'list.tag'];
    if (tag === 'TABLE' || tag === 'TR' || tag === 'TD' || tag === 'TH')
      return ['table', 'table.tag'];
    if (tag === 'BLOCKQUOTE' || tag === 'Q') return ['quote', 'quote.tag'];
    if (tag === 'PRE' || tag === 'CODE') return ['code', 'code.tag'];
    if (MEDIA_TAGS[tag]) return ['media', 'media.tag'];
    if (tag === 'FORM') return ['form', 'form.tag'];
    return ['paragraph', 'text.visible'];
  }

  // ---- detection (§6: the rules live in one place) ----------------------
  function detect(el, rec) {
    var out = null, i, name, val;
    var tag = el.tagName;
    // <link> is metadata content, and a reader never sees one.
    //
    // Its href is a machine reference -- a stylesheet, a canonical url, a
    // category. Wikipedia's Parsoid output puts 377 of them in the *body* of
    // one article, `rel="mw:PageProp/Category"`, each with zero area, and
    // capturing their hrefs put 377 addresses per page into the trie that no
    // reader can reach and that dilute what retrieval ranks over. Ground
    // truth emits nothing for them, and this was roughly half the corpus's
    // invented capture addresses.
    //
    // The mirror of the svg case: there, folding lost a page's content; here,
    // capturing gained noise. Both are the same question -- is this something
    // the page shows a reader -- answered in opposite directions.
    if (tag === 'LINK') return null;
    if (USE_WIDEATTRS) {
      // Every attribute is content. Widening the observer alone changed
      // nothing measurable, because extraction still read the chosen ten —
      // the axis has to move both ends or it is only pretending to.
      var all = el.attributes || [];
      for (i = 0; i < all.length; i++) {
        val = all[i].value;
        if (!val) continue;
        (out || (out = [])).push([intern(all[i].name), val]);
      }
    } else {
    // A hidden or password input's `value` is not content.
    //
    // Reading the *attribute* rather than the property already means nothing
    // a reader types is captured -- a real and non-obvious safeguard. But a
    // server-rendered `<input type=hidden value=...>` carries CSRF tokens,
    // session ids and cart state, and those were being stored verbatim in
    // the address value. They are not what anyone came to read, and keeping
    // them makes the local record hold credentials it has no use for.
    var inputType = '';
    if (tag === 'INPUT' && el.getAttribute) {
      inputType = (el.getAttribute('type') || '').toLowerCase();
    }
    var secretive = (inputType === 'hidden' || inputType === 'password');

    for (i = 0; i < CONTENT_ATTRS.length; i++) {
      name = CONTENT_ATTRS[i];
      if (secretive && name === 'value') continue;
      if (!el.hasAttribute || !el.hasAttribute(name)) continue;
      val = el.getAttribute(name);
      if (!val) continue;
      (out || (out = [])).push([intern(name), val]);
      // One accessor can carry an ordered sequence of values, and `srcset`
      // is the ordinary case rather than the exotic one: every responsive
      // image on the page names three or four sources in a single
      // attribute. Taking the attribute whole counted that as one media
      // resource -- measured at 44 against the host's 88 on one article,
      // which is every second image on the page going unrecorded.
      if (URL_SET[name] && MULTI_URL.test(val)) pushUrls(out, name, val, true);
    }
    // A table cell's SPAN (`D-5`): which columns a cell under a rowspan fills
    // is layout the markdown table needs, and nothing else carries it. Above
    // 1 only; the denylist below keeps the attributes out of the URL scan.
    if ((tag === 'TD' || tag === 'TH') && el.getAttribute) {
      var rspan = +el.getAttribute('rowspan'), cspan = +el.getAttribute('colspan');
      if (rspan > 1) (out || (out = [])).push([intern('rowspan'), String(rspan)]);
      if (cspan > 1) (out || (out = [])).push([intern('colspan'), String(cspan)]);
    }
    // Then everything the lists do not name, for URLs only. Bounded by the
    // denylist so a framework's own bookkeeping does not become content.
    var rest = el.attributes || [];
    for (i = 0; i < rest.length; i++) {
      name = rest[i].name;
      if (CONTENT_SET[name] || agnosticSkip(name)) continue;
      val = rest[i].value;
      if (!val || val.length > 8192) continue;
      // A serialized payload is not this element's reference.
      //
      // Parsoid writes `data-mw='{"parts":[{"template":...}'` on every
      // transcluded citation, and mining it yielded 106 of es.wikipedia's
      // charged inventions: urls that are template *parameters*, addressed at
      // the <cite> that carries the blob. The citation's real link is an
      // <a href> a few nodes away and is captured there, as itself.
      //
      // The test is the shape of the value, not the name of the attribute, so
      // this does not encode one wiki's conventions: a value that begins as
      // JSON is structured data whose urls are fields inside it.
      var lead = val.charAt(0);
      if (lead === '{' || lead === '[') continue;
      pushUrls(out || (out = []), name, val);
    }
    }
    if (tag === 'A' || tag === 'AREA') { /* link-ness implied by href above */ }
    else if (tag === 'INPUT' || tag === 'BUTTON' || tag === 'SELECT' ||
             tag === 'TEXTAREA') {
      // A hidden input is a form's machine payload, not a control a reader
      // can reach: openlibrary's search results carry 422 of them, and the
      // placeholder emitted here was 422 of that page's invented capture
      // addresses -- a line saying "there is an input here" about something
      // nobody can see or use.
      //
      // The same judgement as <link>: metadata the page carries for the
      // machine does not enter the trie as content. Its `value` and `name`
      // are still captured above if they hold anything, because a hidden
      // field's *content* is content; what is dropped is the claim that
      // there is a control to interact with.
      if (tag !== 'INPUT'
          || (el.getAttribute('type') || 'text').toLowerCase() !== 'hidden') {
        (out || (out = [])).push([intern('@control'), tag.toLowerCase()]);
      }
    } else if (tag === 'SELECT') {
      // What the control currently says. Without it the select drew as an
      // empty `[ ]` -- present, unreadable, and indistinguishable from an
      // empty text field.
      try {
        var sel = el.options && el.options[el.selectedIndex];
        var shown = sel ? (sel.textContent || sel.value || '') : '';
        if (shown) (out || (out = [])).push([intern('value'), shown.trim()]);
      } catch (e) { stats.errors++; }
    } else if (el.hasAttribute && el.hasAttribute('role')) {
      // `presentation` and `none` are the author saying this element has no
      // semantics. Emitting a content line whose value is the word
      // "presentation" contradicts the sensor's own reading of it --
      // RENDER_CLASS maps both to `none` -- and puts a machine annotation
      // into the trie as though it were something on the page.
      //
      // 155 of one eurostat page's charged inventions were exactly this, on
      // svg, span and ul alike, every value the same word. Third of the
      // metadata family after <link> and the hidden-input placeholder.
      // A role is never text a reader sees. It is the author naming what
      // an element IS, which this fold already reads -- RENDER_CLASS is
      // computed from it -- so emitting it a second time as a content line
      // puts the annotation into the document as though the page displayed
      // the word.
      //
      // The exclusion above was written for `presentation` and `none` and
      // the reasoning never depended on which value it was: 155 of one
      // eurostat page's charged inventions were roles, and duckduckgo draws
      // `list`, `navigation` and `radiogroup` as lines of prose. Same
      // argument, whole class.
      //
      // The role still classifies. It just stops being content.
    }
    return out;
  }

  // ---- composed children -----------------------------------------------
  // Shadow children come first and are counted apart from light ones. Sharing
  // one ordinal namespace shifted every light-DOM index on a shadow host — a
  // host whose shadow root holds a <div> made the host's own first <div> read
  // as div[2], which no engine would resolve. `shadowCount` marks where the
  // boundary falls so callers can address across it explicitly.
  //
  // `childNodes` is not the composed tree, and the two differ at exactly the
  // points a component library lives at. A light child of a shadow host is
  // drawn where the <slot> that claims it sits *inside* the shadow root, not
  // where it is written; a slot with something assigned to it does not draw
  // its own children; a slot with nothing assigned draws them and only them.
  // Walking `childNodes` got all three wrong at once, and measurably: on
  // tests/fixtures/composed_slots.html the fold emitted every filled slot's
  // fallback — text no reader can ever see — and put the slotted content
  // after the whole shadow subtree instead of inside it, so a card's title
  // read out below its own footer.
  function composedKids(node) {
    if (node.nodeType !== 1) return node.childNodes;
    if (node.tagName === 'SLOT' && node.assignedNodes) {
      var an = null;
      try { an = node.assignedNodes({ flatten: true }); }
      catch (e) { stats.errors++; an = null; }
      // Assigned or fallback, never both — that is what the slot algorithm
      // says and what the fallback is for.
      if (an && an.length) return an;
    }
    return node.childNodes;
  }

  function childrenOf(node) {
    var kids = [], i;
    if (node.shadowRoot) {
      var sk = node.shadowRoot.childNodes;
      for (i = 0; i < sk.length; i++) kids.push(sk[i]);
      observe(node.shadowRoot);
      // The host's own light children are deliberately *not* appended. Each
      // one is drawn at the slot that claims it and is reached through that
      // slot, one descent further down; appending them here as well is how
      // the same text arrived twice, once in the wrong place. A light child
      // no slot claims is drawn nowhere, and is dropped here for the same
      // reason the renderer drops it.
      kids.shadowCount = sk.length;
      return kids;
    }
    noteOpaque(node);
    var ck = composedKids(node);
    for (i = 0; i < ck.length; i++) kids.push(ck[i]);
    kids.shadowCount = 0;
    return kids;
  }

  // A closed root is unreachable from script and stays that way: reaching in
  // means patching `attachShadow`, which is detectable and is the one thing
  // the privacy posture rules out. What is *not* acceptable is for it to read
  // as an empty element, because then the coverage number quietly counts a
  // component we cannot see as a component with nothing in it.
  //
  // There is no API that answers "does this element have a closed root", so
  // this reports the observable fact instead: a defined custom element that
  // exposes neither an open root nor any light children. That is the set of
  // elements we can see nothing inside of, whatever the reason.
  // Held rather than counted, and re-checked each repair. A count incremented
  // during the walk reads 0 on any pass where the fold legitimately skips the
  // clean subtree the host sits in — which is most passes, and is the whole
  // point of the cache. What the number has to mean is "opaque right now".
  var opaqueHosts = (typeof Set === 'function') ? new Set() : null;
  // Custom-element hosts folded WITHOUT a shadow root (2026-10-06). A
  // component attaches its root when it upgrades, which is often after the
  // light DOM it sits in was folded -- archive.org: 426 open roots nested 8
  // deep and 32,231 characters inside them, the sensor folding 17 chunks
  // through 33 observers. Attaching a root fires no mutation, so a root that
  // arrives late was never observed. Each such host is held here and looked
  // at again (`sweepHosts`) on every repair and on a short backoff while any
  // are held; one that gains an OPEN root is observed and re-folded. Nothing
  // is patched: `attachShadow` stays the page's own.
  var pendingHosts = (typeof Set === 'function') ? new Set() : null;
  var hostTimer = null, hostDelay = 0;
  var HOST_DELAYS = [30, 100, 300, 1000, 3000, 5000];
  function noteOpaque(node) {
    if (!opaqueHosts || node.nodeType !== 1) return;
    var name = node.localName || '';
    if (name.indexOf('-') < 0) return;
    if (pendingHosts && pendingHosts.size < 5000 && !pendingHosts.has(node)) {
      pendingHosts.add(node);
      hostDelay = 0;
      armHosts();
    }
    if (node.childNodes.length) return;
    // `:defined` is the element's own CSS state, the same in every world; the
    // registry (`customElements.get`) is per world, and an isolated world's
    // is empty, so every host read as undefined there.
    var defined = false;
    try { defined = node.matches(':defined'); } catch (e) { return; }
    if (!defined) return;
    opaqueHosts.add(node);
  }
  function armHosts() {
    if (hostTimer !== null || !pendingHosts || !pendingHosts.size) return;
    var wait = HOST_DELAYS[Math.min(hostDelay, HOST_DELAYS.length - 1)];
    hostDelay++;
    hostTimer = setTimeout(function () {
      hostTimer = null;
      if (sweepHosts()) hostDelay = 0;
      armHosts();
    }, wait);
  }
  function sweepHosts() {
    // `nolateroots`: the planted arm -- the old fold, which never looked again.
    if (!pendingHosts || V.nolateroots) return 0;
    var found = 0;
    pendingHosts.forEach(function (el) {
      try {
        if (!el.isConnected) { pendingHosts.delete(el); return; }
        if (el.shadowRoot) {
          pendingHosts.delete(el);
          observe(el.shadowRoot);
          markDirty(el);
          found++;
        }
      } catch (e) { pendingHosts.delete(el); }
    });
    if (found) {
      stats.lateRoots = (stats.lateRoots || 0) + found;
      schedule();
    }
    stats.pendingHosts = pendingHosts.size;
    return found;
  }

  // Anything that has since gained children, gained an open root, or left the
  // document is no longer opaque and stops being counted. Bounded by the
  // number of such elements on the page, so the strong references are cheap
  // and are dropped the moment the element is.
  function sweepOpaque() {
    if (!opaqueHosts) return;
    opaqueHosts.forEach(function (el) {
      try {
        if (!el.isConnected || el.shadowRoot || el.childNodes.length) {
          opaqueHosts.delete(el);
        }
      } catch (e) { opaqueHosts.delete(el); }
    });
    stats.closedRoots = opaqueHosts.size;
  }

  // One path step for a child, in the composed tree. `counts` and `scounts`
  // are separate ordinal namespaces; crossing into the shadow root inserts an
  // explicit `#shadow-root` step, so the address says where the boundary is
  // rather than hiding it in an index.
  var SHADOW_SEG = null;
  function stepFor(kid, path, inShadow, counts, scounts) {
    var c = inShadow ? scounts : counts, key, tag;
    if (kid.nodeType === 1) {
      if (SKIP_TAGS[kid.tagName]) return null;
      tag = kid.tagName.toLowerCase();
      key = tag;
    } else if (kid.nodeType === 3) {
      tag = '#text';
      key = tag;
    } else return null;
    c[key] = (c[key] || 0) + 1;
    if (!inShadow) return path.concat([intern(tag), c[key]]);
    if (SHADOW_SEG === null) SHADOW_SEG = intern('#shadow-root');
    return path.concat([SHADOW_SEG, 1, intern(tag), c[key]]);
  }

  // ---- the fold ---------------------------------------------------------
  // Post-order. Children first, then this node's summaries from theirs.
  // A node whose record is present and clean is returned untouched, which
  // is where incrementality actually lives: a clean subtree costs one map
  // lookup, not a traversal.
  function fold(node) {
    var rec = records.get(node);
    // The whole of incrementality is this line: a clean subtree costs one map
    // lookup instead of a traversal. With the axis off every node is re-folded
    // on every repair, which is the O(page) baseline the design is measured
    // against — not a mode anyone should run, but the one that says what the
    // cache is worth.
    if (rec && !rec.dirty && USE_CACHE) return rec;
    // `deepgate`: a node marked dirty only because a *sibling* changed has
    // nothing of its own to recompute. `cache` returns a clean record
    // untouched; this catches the case one level up, where the parent is
    // dirty and most of its children are not, and stops the aggregation
    // from descending into branches whose digest has not moved since they
    // were last emitted.
    if (USE_DEEPGATE && rec && rec.digest !== 0 && rec.emit === rec.digest) {
      rec.dirty = false;
      stats.deepPruned++;
      return rec;
    }

    var type = node.nodeType;
    if (type === 3) {                       // text
      rec = rec || newRecord();
      var t = node.nodeValue || '';
      var trimmed = t.trim();
      rec.text = trimmed;
      rec.chars = trimmed.length;
      rec.count = 1;
      var toks = tokenize(trimmed);
      rec.digest = trimmed ? fnv('t|' + trimmed) : 0;
      rec.content = rec.digest;
      rec.sketch = sketchOf(toks, rec.sketch && rec.sketch.fill(0));
      rec.toks = toks;
      rec.det = null;
      rec.tax = null;
      rec.dirty = false;
      records.set(node, rec);
      stats.folds++;
      return rec;
    }
    if (type !== 1) return null;            // comments, doctype: no record
    if (SKIP_TAGS[node.tagName]) return null;

    rec = rec || newRecord();
    if (rec.sketch) rec.sketch.fill(0); else rec.sketch = new Uint16Array(SKETCH_W);
    rec.chars = 0; rec.count = 1; rec.content = 0; rec.text = ''; rec.tax = null;

    var d = fnv(node.tagName);
    var kids = childrenOf(node), i, k, kr;
    // The span path: re-fold only the children a mutation actually touched
    // and repair the aggregate by subtracting what they contributed before
    // and adding what they contribute now. Every quantity here is
    // commutative and invertible, which is why this is possible at all; the
    // digest is positional and is recomputed by walking the children's
    // cached digests, which costs a map lookup each and no recursion.
    //
    // It falls back to the full sum whenever the bookkeeping cannot be
    // trusted — no cached aggregate, a child count that moved, a span that
    // covers everything — because a wrong aggregate is a wrong digest is a
    // wrong chunk, and the saving is not worth that.
    var spanned = USE_SPANS && rec.ks !== null && rec.lo >= 0
      && rec.kn >= 0 && rec.hi <= kids.length && rec.lo < rec.hi
      && (rec.hi - rec.lo) < kids.length;
    if (spanned) {
      stats.spanHits++;
      var kc = rec.kc, kh = rec.kh, kn = rec.kn, ks = rec.ks;
      var old16 = new Uint16Array(SKETCH_W);
      for (i = rec.lo; i < rec.hi; i++) {
        var before = records.get(kids[i]);
        if (before) {
          kc = (kc - before.content) >>> 0;
          kh -= before.chars;
          kn -= before.count;
          if (before.sketch) old16.set(before.sketch);
          else old16.fill(0);
        } else {
          old16.fill(0);
        }
        kr = fold(kids[i]);
        if (kr) {
          kc = (kc + kr.content) >>> 0;
          kh += kr.chars;
          kn += kr.count;
          for (k = 0; k < SKETCH_W; k++) {
            ks[k] = (ks[k] - old16[k] + (kr.sketch ? kr.sketch[k] : 0));
          }
        } else {
          for (k = 0; k < SKETCH_W; k++) ks[k] = ks[k] - old16[k];
        }
      }
      rec.kc = kc; rec.kh = kh; rec.kn = kn;
      rec.content = kc; rec.chars = kh; rec.count = 1 + kn;
      rec.sketch.set(ks);
      for (i = 0; i < kids.length; i++) {
        kr = records.get(kids[i]);
        if (kr) d = mix(d, kr.digest);
      }
    } else {
      var akc = 0, akh = 0, akn = 0;
      for (i = 0; i < kids.length; i++) {
        kr = fold(kids[i]);
        if (!kr) continue;
        d = mix(d, kr.digest);                       // positional
        rec.content = (rec.content + kr.content) >>> 0;   // commutative
        rec.chars += kr.chars;
        rec.count += kr.count;
        sketchAdd(rec.sketch, kr.sketch);
        akc = (akc + kr.content) >>> 0; akh += kr.chars; akn += kr.count;
      }
      if (USE_SPANS) {
        rec.kc = akc; rec.kh = akh; rec.kn = akn;
        if (rec.ks === null) rec.ks = new Uint16Array(SKETCH_W);
        rec.ks.set(rec.sketch);
      }
    }
    rec.lo = -1; rec.hi = -1;
    rec.det = detect(node, rec);
    if (rec.det) {
      for (i = 0; i < rec.det.length; i++) {
        var av = fnv(String(rec.det[i][1]));
        d = mix(d, av);
        rec.content = (rec.content + av) >>> 0;
        rec.chars += String(rec.det[i][1]).length;
      }
    }
    // The address carries the classification, so the classification is part
    // of the write decision -- rule 5b, the two Merkles. `rec.content` is
    // deliberately left out of this: matching content across a move must
    // stay blind to role, and only the digest, which answers "does this
    // draw the same?", may see it.
    //
    // Deleting one sibling re-classified a citation link from
    // `pagination.family` to `link.anchor` without touching its href. A
    // value-only digest made that invisible: the gate skipped the chunk, and
    // the trie kept four addresses the page no longer had while missing the
    // four it did. No xpath was wrong -- the accessor was.
    //
    // `taxOf` is memoised on the record and cleared at the top of every
    // re-fold, so this hoists the call rather than adding one, and it reads
    // `tagName` and `textContent` only -- the fold still reads no layout.
    var tax = taxOf(node, rec);
    d = mix(d, fnv(tax[0] + '/' + tax[1]));
    rec.digest = d >>> 0;
    rec.dirty = false;
    records.set(node, rec);
    stats.folds++;
    return rec;
  }

  // ---- chunking (§2) ----------------------------------------------------
  // A node is a chunk root when it fits the budget and its parent does not.
  // Emission walks down only until the predicate fires, so a settled region
  // is never descended into.
  function emitChunks(node, path, out) {
    var rec = records.get(node);
    if (!rec) return;
    if (rec.chars === 0) return;
    // `semantic` lets a block a reader thinks of as one thing stay one
    // thing: a list item or a table row may overrun the budget rather than
    // be cut in half. Bounded at twice the budget so a whole <main> cannot
    // swallow the page.
    var limit = BUDGET;
    if (USE_SEMANTIC && node.nodeType === 1 && SEMANTIC_TAGS[node.tagName]) {
      limit = BUDGET * 2;
    }
    // A leaf that overruns the budget has nowhere to descend to.
    //
    // The split-above, merge-below hysteresis this chunker is built around is
    // expressed entirely in elements: a node too big becomes several chunks
    // by recursing into its children. A text node has no children, so the
    // recursion has no base case for it and the node was never emitted at
    // all.
    //
    // Measured: arxiv 2005.14165's abstract is one text node of 1,789
    // characters against a budget of 1,200, and none of it reached the trie,
    // while the neighbouring paper's 1,136-character abstract did. Across the
    // corpus, 129 reader-visible text nodes on 14 pages, 326,820 characters
    // -- RFC 791 is a single 94,887-character node holding the whole
    // document.
    //
    // Worse than its share, because the budget is the knob the goal asks a
    // reader to turn for a small context window: as it stood, asking for a
    // smaller window silently deleted more of the page.
    //
    // So an oversize leaf is emitted as its own chunk. `collectLines` cuts
    // its text into budget-sized pieces, each addressed by an offset, so the
    // chunk contract still holds downstream.
    if (rec.chars > limit && node.nodeType === 3) {
      limit = rec.chars;
    }
    // A code block is one artifact (G-233): indivisible like an oversize
    // text node, so it is never cut into its highlighting spans. Planted
    // (run time): `plants.codespans`.
    if (rec.chars > limit && node.nodeType === 1 && node.tagName === 'PRE' && !RT_PLANTS.codespans) {
      limit = rec.chars;
    }
    if (rec.chars <= limit) {
      // A chunk is emitted only when its digest differs from the one last
      // sent. The digest is already maintained by the fold, so this costs a
      // comparison and turns the drain into a statement about what changed
      // rather than a re-description of the page.
      var prev = chunkOf.get(node);
      var here = pathKey(path);
      if (prev) prev.seen = stats.repairs;
      if (USE_GATE && prev && prev.digest === rec.digest
          && prev.path === here && prev.gen === EMIT_GEN) {
        stats.skipped++; return;
      }
      // Same content, new position: send where it went, not what it is.
      //
      // The receiver already holds this chunk -- the digest is unchanged, so
      // every line in it is a line it has -- and the only thing it does not
      // know is that the addresses moved. Re-sending the bodies to tell it
      // that cost 265 KB for one <li> inserted at the head of a 1600-item
      // list, because every sibling below the insertion shifted one ordinal.
      //
      // The trie is what makes this sound: it is keyed on the address and it
      // holds the value, so the receiver can rebuild the shifted units from
      // its own store. The wire carries the address change; the content stays
      // where it already is.
      if (USE_GATE && prev && prev.digest === rec.digest && prev.id && prev.gen === EMIT_GEN) {
        moves.push([prev.id, path]);
        prev.path = here;
        stats.movedChunks++;
        return;
      }
      // Read what is on screen first. This is the one emission rule that
      // changes *what arrives*, not merely how much or how fast, so it is
      // the one that has to be judged by `verify` rather than by `compare`:
      // a page read this way is a different reading, not a cheaper one.
      if (USE_VIEWPORT && node.getBoundingClientRect) {
        var r = node.getBoundingClientRect();
        var vh = window.innerHeight || 0;
        if (!(r.width === 0 && r.height === 0)
            && (r.bottom < -vh || r.top > vh * 2)) {
          stats.offscreen++; return;
        }
      }
      // The receiver already holds this content under some url. Skipping
      // here is the original serializer's `known_hashes` prune moved to the
      // side of the boundary where it saves the crossing rather than the
      // storage — boilerplate that repeats across a crawl is 15-30% of
      // consecutive pages by measurement.
      if (USE_CROSSPAGE && KNOWN[String(rec.content)]) {
        stats.knownSkips++; return;
      }
      out.push(makeChunk(node, path, rec));
      return;
    }
    // An interior node whose digest has not moved since the last emission
    // contains nothing that has moved — that is the Merkle property the fold
    // already maintains. Without this the walk descends to every chunk root
    // on every repair (measured: 89 gate-skips per idle drain on YouTube)
    // and only then finds nothing to say.
    var mine = pathKey(path);
    if (USE_SUBTREEGATE && rec.emit === rec.digest && rec.emitPath === mine && rec.emitGen === EMIT_GEN) {
      stats.pruned++; return;
    }
    var kids = childrenOf(node), nsh = kids.shadowCount;
    var counts = {}, scounts = {}, i, kid, seg;
    // `merge` is the other half of the hysteresis the budget was always
    // described as having: split above BUDGET, and gather back up below
    // MERGE_AT. Without it a parent that overruns the budget scatters into
    // one chunk per tiny child, and each one pays a whole path.
    var run = [], runChars = 0;
    function flushRun() {
      if (!run.length) return;
      if (run.length === 1) {
        emitChunks(run[0].node, run[0].seg, out);
      } else {
        var merged = makeMerged(run, path);
        if (merged) out.push(merged);
      }
      run = []; runChars = 0;
    }
    for (i = 0; i < kids.length; i++) {
      kid = kids[i];
      seg = stepFor(kid, path, i < nsh, counts, scounts);
      if (seg === null) continue;
      if (USE_MERGE) {
        var krec = records.get(kid);
        // A node with no content emits nothing, so it must not *interrupt* a
        // run either. Whitespace text nodes sit between every pair of
        // element siblings in real markup, and treating them as run-breakers
        // cut every run to length one — the axis measured as a perfect
        // no-op on a page where eleven siblings were waiting to be merged.
        if (!krec || krec.chars === 0) continue;
        if (krec.chars <= MERGE_AT
            && runChars + krec.chars <= BUDGET) {
          run.push({ node: kid, seg: seg, rec: krec });
          runChars += krec.chars;
          continue;
        }
        flushRun();
      }
      emitChunks(kid, seg, out);
    }
    if (USE_MERGE) flushRun();
    rec.emit = rec.digest;
    rec.emitPath = mine;
    rec.emitGen = EMIT_GEN;
  }

  // One chunk made of several adjacent siblings. Its identity is the first
  // member's, so a run that keeps its head keeps its chunk id across passes.
  function makeMerged(run, parentPath) {
    var first = run[0];
    var slot = chunkOf.get(first.node);
    if (!slot) {
      slot = { id: chunkSeq++, digest: 0, path: -1, tracked: false,
               node: first.node };
      chunkOf.set(first.node, slot);
      chunkRoots.push(slot);
      slot.tracked = true;
    }
    var d = 0, chars = 0, lines = [], i;
    if (!TAX_ROOT) TAX_ROOT = [intern('paragraph'), intern('text.visible'), 0];
    for (i = 0; i < run.length; i++) {
      d = mix(d, run[i].rec.digest);
      chars += run[i].rec.chars;
      collectLines(run[i].node, run[i].seg, run[i].rec, 0, lines, [], TAX_ROOT);
    }
    d = d >>> 0;
    // The run's last node, for `at` (the hover peripheral): a merged run is
    // keyed on its FIRST node only, and an element inside a later sibling of
    // the run has to be traced back to it. Bookkeeping beside the slot, never
    // in the payload.
    slot.tail = run[run.length - 1].node;
    // The slot is LIVE whatever the gates below decide: its head is this
    // run's first node, it is tracked, and it is seen. `at` resolved every
    // member of archive.org's field list to no chunk (2026-10-11: `slotOf` ->
    // tracked false, node null; `scripts/merge_at_probe.py`).
    if (slot.node !== first.node) { chunkOf.set(first.node, slot); slot.node = first.node; }
    if (!slot.tracked) { slot.tracked = true; if (chunkRoots.indexOf(slot) < 0) chunkRoots.push(slot); }
    // SEEN in this repair, as `makeChunk` marks its slots: the sweep at the
    // end of a fold untracks, nulls and reports REMOVED every slot not seen
    // -- so every merged run was swept by the very fold that emitted it.
    if (!PLANT_UNSEEN_MERGED) slot.seen = stats.repairs;
    var where = pathKey(parentPath);
    if (USE_GATE && slot.digest === d && slot.path === where && slot.gen === EMIT_GEN) {
      stats.skipped++; return null;
    }
    // The merged-run gate, and the same move rule as the one above it: the
    // run's digest is unchanged, so the receiver holds every line of it and
    // needs only the new address.
    if (USE_GATE && slot.digest === d && slot.id && slot.gen === EMIT_GEN) {
      moves.push([slot.id, parentPath]);
      slot.path = where;
      slot.node = first.node;
      stats.movedChunks++;
      return null;
    }
    slot.digest = d;
    slot.gen = EMIT_GEN;
    slot.path = where;
    slot.node = first.node;
    encodeLines(lines);
    stats.chunks++;
    stats.merged += run.length;
    return { id: slot.id, path: parentPath, digest: d, chars: chars,
             content: d, lines: lines };
  }

  // ---- transport encodings ----------------------------------------------
  // Applied once, over the finished line list, in a fixed order the decoder
  // mirrors in reverse. Kept out of `collectLines` on purpose: collection is
  // about what the page says, encoding is about how it travels, and mixing
  // the two is how a wire format starts deciding what content exists.
  //
  // A line is [depth, text, path, attr, seq, taxId, ruleId] and `path` is a
  // flat [tagId, ord, tagId, ord, ...] run. Only the line paths are
  // transformed; a chunk's own path is one per chunk and not worth the
  // asymmetry.
  var shapes = [], shapeIndex = new Map(), shapesSent = 0;

  function shapeIdOf(path) {
    var tags = [], i;
    for (i = 0; i < path.length; i += 2) tags.push(path[i]);
    var key = tags.join(',');
    var id = shapeIndex.get(key);
    if (id === undefined) {
      id = shapes.length;
      shapes.push(tags);
      shapeIndex.set(key, id);
    }
    return id;
  }

  // Landmark tag ids, resolved lazily because interning happens as the walk
  // proceeds and these may not exist yet at module load.
  var LANDMARK_IDS = null;
  function landmarkIds() {
    if (LANDMARK_IDS) return LANDMARK_IDS;
    LANDMARK_IDS = {};
    for (var t in LANDMARK_TAGS) LANDMARK_IDS[intern(t.toLowerCase())] = 1;
    return LANDMARK_IDS;
  }

  // `anchored`: keep everything down to the deepest landmark verbatim and
  // erase the ordinals below it. The address then names a *kind* of place
  // rather than one node, which is what makes two rows of a list comparable
  // — and what makes the address stop resolving to exactly one element.
  // That trade is the measurement.
  function anchorPath(path) {
    var ids = landmarkIds(), cut = -1, i;
    for (i = 0; i < path.length; i += 2) if (ids[path[i]]) cut = i;
    if (cut < 0) return path;
    var out = path.slice(0);
    for (i = cut + 2; i < out.length; i += 2) out[i + 1] = 0;
    return out;
  }

  function encodeLines(lines) {
    var prev = null, i, j, k, ln, path, out;
    for (i = 0; i < lines.length; i++) {
      ln = lines[i];
      if (USE_VALDICT && typeof ln[1] === 'string') ln[1] = intern(ln[1]);
      else if (USE_TEXTDICT && typeof ln[1] === 'string'
               && ln[1].length > 12) {
        // Prose is mostly unique; its words are not. `valdict` cannot help
        // where no two sentences match, but almost every noun repeats — so
        // intern per word and send a run of ids. Marked with a leading -1 so
        // the receiver can tell a word-run from a path.
        var ws = ln[1].split(' ');
        if (ws.length > 2) {
          var enc = [-1], wi;
          for (wi = 0; wi < ws.length; wi++) enc.push(intern(ws[wi]));
          stats.wordsInterned += ws.length;
          ln[1] = enc;
        }
      }
      path = ln[2];
      if (USE_ANCHORED) { path = anchorPath(path); ln[2] = path; }
      if (USE_SHAPE) {
        // The tag sequence repeats overwhelmingly — 15 distinct shapes for
        // 86 lines on one page, 29 for 290 on another — so it is sent once
        // in a table and each line carries an id plus its own ordinals.
        out = [shapeIdOf(path)];
        for (j = 1; j < path.length; j += 2) out.push(path[j]);
        ln[2] = out;
      } else if (USE_PATHDELTA) {
        // Consecutive lines in a post-order walk share nearly their whole
        // prefix, so each carries how much of the previous path it keeps
        // and only what differs after that.
        k = 0;
        if (prev) {
          while (k < path.length && k < prev.length && path[k] === prev[k]) k++;
        }
        out = [k];
        for (j = k; j < path.length; j++) out.push(path[j]);
        prev = path;
        ln[2] = out;
      }
      if (USE_PACKED && ln[2] && ln[2].join) ln[2] = ln[2].join(',');
    }
    return lines;
  }

  // `idanchor`: root the path at the nearest ancestor carrying an id or a
  // test id. An absolute path breaks when a sibling is inserted above it;
  // an id-rooted one survives, which matters because a stored address has to
  // still mean something in the next session, not only in this drain.
  var ID_SEG = null;

  // The path from an ancestor down to `node`, as (tag, ordinal) pairs. The
  // ordinal counts same-tag siblings, exactly as the descending walk does,
  // so an anchored path and an absolute one name the same node.
  function stepsBetween(anc, node) {
    var out = [], n = node, i, ord, sib;
    while (n && n !== anc && n.parentNode) {
      ord = 1;
      for (i = 0; i < n.parentNode.children.length; i++) {
        sib = n.parentNode.children[i];
        if (sib === n) break;
        if (sib.tagName === n.tagName) ord++;
      }
      out.push(intern(n.tagName.toLowerCase()), ord);
      n = n.parentNode;
    }
    if (n !== anc) return null;              // anchor was not an ancestor
    // collected leaf-upward; the path runs the other way
    var rev = [];
    for (i = out.length - 2; i >= 0; i -= 2) rev.push(out[i], out[i + 1]);
    return rev;
  }

  function idAnchorFor(node) {
    var n = node, hops = 0, v;
    while (n && n.nodeType === 1 && hops++ < 12) {
      if (n.getAttribute) {
        v = n.getAttribute('id') || n.getAttribute('data-testid')
            || n.getAttribute('data-test-id');
        if (v) {
          if (ID_SEG === null) ID_SEG = intern('#id');
          // The steps from the anchor down to this node must be kept.
          // Dropping them gave every chunk under one anchor the same
          // address: 276 distinct addresses collapsed to 213, and a
          // colliding address is worse than a fragile one.
          var rel = stepsBetween(n, node);
          if (rel === null) return null;
          return [ID_SEG, intern(String(v))].concat(rel);
        }
      }
      n = n.parentNode;
    }
    return null;
  }

  // What was last sent for a chunk, so the next send can be a difference.
  var lastLines = new WeakMap();

  // Line-level delta against the version the receiver holds. A chunk whose
  // digest moved is usually a chunk that gained or lost a line, not one that
  // was rewritten; sending the whole chunk to convey that is the same
  // mistake the original serializer makes at document scale, one level down.
  function deltaLines(node, lines) {
    var prev = lastLines.get(node);
    lastLines.set(node, lines.map(function (l) { return l[1]; }));
    if (!prev || prev.length === 0) return null;
    var keep = [], i, same = 0;
    for (i = 0; i < lines.length; i++) {
      if (i < prev.length && prev[i] === lines[i][1]) { same++; continue; }
      keep.push(i);
    }
    // Only worth it when most of the chunk is unchanged; otherwise the
    // index list costs more than the lines it saves.
    if (same < lines.length * 0.6) return null;
    var out = [];
    for (i = 0; i < keep.length; i++) out.push(lines[keep[i]]);
    return { keep: keep, lines: out, was: prev.length };
  }

  function makeChunk(node, path, rec) {
    var slot = chunkOf.get(node);
    if (!slot) {
      slot = { id: chunkSeq++, digest: 0, path: -1 };
      chunkOf.set(node, slot);
    }
    // Tracked so removals can be named. `chunkOf` is a WeakMap and cannot be
    // walked, so the live roots are kept alongside it; a node that leaves the
    // composed tree is swept in `repair` and its id reported.
    if (!slot.tracked) { slot.tracked = true; chunkRoots.push(slot); }
    slot.seen = stats.repairs;
    slot.node = node;
    slot.tail = node;
    slot.digest = rec.digest;
    slot.gen = EMIT_GEN;
    // Before the id-anchor rewrite below: the gate compares composed paths,
    // and an anchored address is stable under exactly the moves it needs to
    // notice.
    slot.path = pathKey(path);
    if (USE_PERCHUNK && !slot.watched) {
      try {
        var o = new MutationObserver(onMutations);
        o.observe(node, { subtree: true, childList: true,
                          characterData: !NO_CHARWATCH, attributes: true,
                          attributeOldValue: true });
        slot.watched = true;
        stats.observers++;
      } catch (e) { stats.errors++; }
    }
    var id = slot.id;
    var lines = [];
    textSeq = 0;
    if (USE_IDANCHOR) {
      var anc = idAnchorFor(node);
      if (anc) path = anc;
    }
    if (!TAX_ROOT) TAX_ROOT = [intern('paragraph'), intern('text.visible'), 0];
    collectLines(node, path, rec, 0, lines, [], TAX_ROOT);
    encodeLines(lines);
    stats.chunks++;
    // `content` travels alongside `digest`: the digest is positional and
    // identifies this node, the fingerprint is commutative and identifies
    // this *content* wherever it appears. Cross-page suppression needs the
    // second, and the receiver had no way to name it before.
    if (USE_CHUNKDELTA) {
      var dl = deltaLines(node, lines);
      if (dl) {
        stats.chunkDeltas++;
        return { id: id, path: path, digest: rec.digest, chars: rec.chars,
                 content: rec.content, lines: dl.lines, keep: dl.keep,
                 was: dl.was };
      }
    }
    return { id: id, path: path, digest: rec.digest, chars: rec.chars,
             content: rec.content, lines: lines };
  }

  // §7 in place: a child whose sketch is covered by an emitting ancestor and
  // whose tokens are exactly contained is not emitted again.
  // Two steps. The sketch rejects the overwhelming majority with a handful
  // of word comparisons and no strings touched; whatever it admits is then
  // confirmed exactly, so suppression only ever follows proven containment
  // and an approximate sketch cannot lose content.
  // A 32-bit simhash over the record's tokens. Near-duplicate rather than
  // exact containment: two lines that say almost the same thing collapse,
  // where the sketch-then-verify path requires one to literally contain the
  // other. Lossier by construction, which is why it is its own axis.
  function simOf(rec) {
    if (rec.sim !== 0) return rec.sim;
    var v = new Int16Array(32), i, b, h;
    var toks = rec.toks || [];
    for (i = 0; i < toks.length; i++) {
      h = fnv(toks[i]);
      for (b = 0; b < 32; b++) v[b] += (h >>> b) & 1 ? 1 : -1;
    }
    var out = 0;
    for (b = 0; b < 32; b++) if (v[b] > 0) out |= (1 << b);
    rec.sim = out >>> 0 || 1;
    return rec.sim;
  }
  function hamming(a, b) {
    var x = (a ^ b) >>> 0, n = 0;
    while (x) { n += x & 1; x >>>= 1; }
    return n;
  }

  function subsumed(rec, seen) {
    if (!rec.toks || !rec.toks.length) return false;
    if (USE_SIMHASH) {
      var mine = simOf(rec);
      for (var q = 0; q < seen.length; q++) {
        if (hamming(mine, simOf(seen[q])) <= 3) {
          stats.nearDups++; stats.deduped++; return true;
        }
      }
      return false;
    }
    for (var i = 0; i < seen.length; i++) {
      if (!covers(seen[i].sketch, rec.sketch)) continue;   // cheap reject
      stats.sketchHits++;
      var have = seen[i].text;
      if (have && have.indexOf(rec.text) !== -1) {          // exact confirm
        stats.deduped++;
        return true;
      }
    }
    return false;
  }

  var textSeq = 0;
  var TAX_ROOT = null;   // interned lazily: the default a chunk root inherits

  function collectLines(node, path, rec, depth, lines, seen, inh) {
    if (!rec || rec.chars === 0) return;
    if (node.nodeType === 3) {
      // A text node has no classification of its own — it takes the one that
      // descended to it, which is the nearest ancestor that said anything
      // specific about what this content is.
      if (rec.text && !(USE_DEDUP && subsumed(rec, seen))) {
        // -1, not 0: interned ids start at 0, so "no attribute" and "the
        // attribute interned first" were the same value on the wire. When
        // that happened to be `href`, every link decoded as a text line, the
        // addresses lost the attribute they came from, and the link graph —
        // and with it PageRank's only real edges — came out empty.
        // One line, unless the text itself overruns the budget.
        //
        // An oversize text node is now emitted as its own chunk rather than
        // lost, and a chunk of 94,887 characters -- RFC 791 is one -- is no
        // more use to a small context window than nothing was. So the value
        // is cut into budget-sized pieces here, at a space where one is near
        // the boundary, so a piece breaks between words rather than inside
        // one.
        //
        // Each piece is a distinct address: the trie is keyed on address, and
        // two pieces of one text node must be distinguishable or the second
        // overwrites the first. The `@offset` form already exists for exactly
        // this -- `data-mw@496` names one match inside a longer attribute --
        // so a piece carries its start offset and the address stays
        // resolvable to the node that holds it.
        if (rec.text.length <= BUDGET) {
          lines.push([depth, rec.text, path, -1, 0, inh[0], inh[1]]);
        } else {
          var at = 0;
          while (at < rec.text.length) {
            var end = Math.min(at + BUDGET, rec.text.length);
            if (end < rec.text.length) {
              var space = rec.text.lastIndexOf(' ', end);
              if (space > at + (BUDGET >> 1)) end = space;
            }
            // The offset goes into the interned accessor, the way a
            // multi-match attribute already does it (`data-mw@496`). One
            // shared `text()@` for every piece is one address: the trie is
            // keyed on it, so the pieces overwrote each other and a 94,887
            // character node came back as two leaves instead of eighty.
            lines.push([depth, rec.text.slice(at, end), path,
                        at === 0 ? -1 : intern('text()@' + at),
                        0, inh[0], inh[1]]);
            at = end === at ? rec.text.length : end;
            while (rec.text.charAt(at) === ' ') at++;
          }
        }
        seen.push(rec);
      }
      return;
    }
    // An element's own detections describe the *element* — an href inside a
    // heading is still a link — so they carry its local classification. Only
    // what descends to the text takes the region's, which is why these two
    // are computed separately rather than one being reused for the other.
    var own = taxOf(node, rec);
    var here = own[2] < inh[2] ? inh : own;
    if (rec.det) {
      for (var i = 0; i < rec.det.length; i++) {
        lines.push([depth, String(rec.det[i][1]), path, rec.det[i][0], 0,
                    own[0], own[1]]);
      }
    }
    // A collapsed control is one line, and its contents are behind it.
    //
    // Classifying the options `none` was not enough: a text node has no
    // class of its own and takes the nearest ancestor that said something
    // specific, so every country name under DuckDuckGo's region filter
    // inherited `choice` from the select and drew as `[ ] Argentina`. The
    // control has to be a leaf, not merely a parent of hidden children --
    // which is what it is on the rendered page.
    // An <svg> carrying <text> is a diagram, and its labels are the document.
    //
    // Folding it keeps geometry out, which is right for an icon: a few hundred
    // <path> elements are not content. sqlite.org's SELECT reference is the
    // case that rule was not made for -- 139 svgs holding 2,447 <text>
    // elements and 14,037 characters of SQL grammar, drawn as railroad
    // diagrams, and not one address of it reached the trie. A reader got the
    // prose around the diagrams and none of the grammar.
    //
    // Descent is by the ordinary path rather than a targeted query, so the
    // addresses are the composed tree's and match ground truth by
    // construction. Geometry is still walked and still emits nothing: a
    // <path> has no text child and no content attribute, so the cost is a
    // traversal and not a line.
    //
    // Guarded on actually containing <text>, so an icon stays a picture and
    // costs nothing. The risk this guards is the one DuckDuckGo's region
    // filter taught -- eighty option lines ahead of the first result --
    // and the number that would show it is `page->wireframe` precision.
    // A CODE BLOCK is one line: its text whole, newlines kept, at the
    // `pre`'s own address (G-233, PLUGIN_GOAL 162). Walked like prose, a
    // highlighted sample arrived as its syntax spans -- `pre/code`,
    // `pre/code/span[5]` -- split over two chunks, and its copy button was
    // the chunk a hover found (huggingface, 2026-10-18). The receiver
    // continues the address below the `pre` by the code's own syntax, as
    // `code://` files are addressed. Planted (run time): `plants.codespans`.
    if (node.tagName === 'PRE' && !RT_PLANTS.codespans) {
      var code = '';
      try { code = String(node.textContent || '').replace(/^[\r\n]+|\s+$/g, ''); } catch (e) { stats.errors++; }
      if (code && !(USE_DEDUP && subsumed(rec, seen))) {
        lines.push([depth, code, path, -1, 0, own[0], own[1]]);
        seen.push(rec);
      }
      return;
    }
    var diagram = node.tagName === 'svg' && node.querySelector
                  && node.querySelector('text');
    if (FOLDED[node.tagName] && !diagram) {
      // An <svg> is folded so its geometry stays out -- a few hundred <path>
      // elements are not content -- but `<title>` is how an inline SVG is
      // named, and it is a *child* element rather than an attribute. Folding
      // the svg put it out of reach: github.com names its customer logos that
      // way and "Ford", "Shopify", "Mercedes-Benz" and eighteen others never
      // entered the trie at all.
      //
      // Taken here, at the svg's own address, because that is the thing the
      // reader sees: one picture with a name. Descending for the name only,
      // never for the drawing.
      if (node.tagName === 'svg' && node.querySelector) {
        try {
          var named = node.querySelector('title, desc');
          var label = named && (named.textContent || '').trim();
          if (label) {
            lines.push([depth, label.slice(0, BUDGET), path,
                        SVG_TITLE_ID < 0
                          ? (SVG_TITLE_ID = intern('title'))
                          : SVG_TITLE_ID,
                        0, own[0], own[1]]);
          }
        } catch (e) { /* an unnameable picture is still a picture */ }
      }
      return;
    }
    // A text node is addressed by its own position among its parent's text
    // children, which is what `text()[n]` means. Inheriting the parent's path
    // put every text child of an element on one address, and a per-chunk
    // counter repeated that address in the next chunk; a child ordinal is
    // unique across the page because the parent path already is.
    var kids = childrenOf(node), nsh = kids.shadowCount;
    var counts = {}, scounts = {}, j, kid, kr, seg;
    for (j = 0; j < kids.length; j++) {
      kid = kids[j];
      kr = records.get(kid);
      if (!kr) continue;
      seg = stepFor(kid, path, j < nsh, counts, scounts);
      if (seg === null) continue;
      collectLines(kid, seg, kr, depth + 1, lines, seen, here);
    }
  }

  // ---- the scroller (§5: scrolling and pagination are one loop) ---------
  // Pagination is not an end-of-scroll fallback. A pager is enacted the
  // moment it is first detected and again whenever it re-enters view,
  // because a feed that alternates lazy loading with an explicit "more"
  // button only advances if both are driven.
  //
  // Two kinds of pager, and treating them alike is wrong in a way a reader
  // notices. A control that appends in place (a button, or an anchor with no
  // usable href) is *pressed while scrolling*. A control that navigates (an
  // anchor with a real href) replaces the document, so pressing it mid-read
  // would throw away the page you are reading; it is enacted only once the
  // scroll can go no further, which is §7.6's "stepping off the bottom
  // turns the page".
  //
  // This is the one place that reads layout. The fold must not — a fold that
  // measures forces synchronous style resolution on every mutation — but an
  // actuator has to know what is on screen, and it runs once per step rather
  // than once per node.
  var pagers = new WeakMap();     // element -> {fires, last, empties}
  var pagerList = [];             // insertion order; pruned when detached
  var firedLast = [];             // enacted by the previous step
  var lastEmit = 0, emptySteps = 0;
  // Takes `taxonomyOf`'s verdict, not the render class.
  //
  // It used to take the render class, compared against `intern('pagination')`,
  // and that comparison could not be true: the render-class vocabulary is
  // {group, button, link, field, item, ...} and 'pagination' is not in it.
  // So no node was ever registered, `pagerList` stayed empty for the life of
  // every page, and every gate below counted zero -- including `seen_pagers`,
  // which is how a dead registry reads exactly like a page with no pager.
  // Across 202 measured pages: zero candidates examined, against 41% of pages
  // finding one before the render classes were introduced.
  function notePager(node, verdict) {
    if (verdict !== 'pagination' || node.nodeType !== 1) return;
    if (pagers.has(node)) return;
    pagers.set(node, { fires: 0, last: 0, empties: 0 });
    pagerList.push(node);
  }

  function inView(el) {
    var r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    var h = window.innerHeight || document.documentElement.clientHeight || 0;
    return r.bottom > 0 && r.top < h;
  }

  // An anchor that would replace the document rather than extend it.
  function navigates(el) {
    if (el.tagName === 'A') {
      var href = el.getAttribute('href');
      if (!href) return false;
      href = href.trim();
      if (!href || href.charAt(0) === '#') return false;
      return !/^javascript:/i.test(href);
    }
    // Submitting a form replaces the document just as surely as following a
    // link, so a submit pager waits for the bottom like any other navigating
    // control. Classifying it as in-place would press it on every scroll
    // step and page past everything unread.
    var type = (el.getAttribute && el.getAttribute('type') || '').toLowerCase();
    return (type === 'submit' || type === 'image') && !!el.form;
  }

  // Detection and enactment are not the same question. `‹ Previous` and
  // `Last »` are pagination — the REPL renders them, and classifying them as
  // anything else would be wrong — but pressing them does not advance a
  // read. Backward controls undo progress, and a jump to the last page skips
  // everything between. So the scroller detects every pager and enacts only
  // the ones that move forward by one.
  var BACKWARD = /(^|\W)(prev|previous|newer|first|back|earlier)(\W|$)|[‹«←]/i;
  var JUMPS = /(^|\W)(last|newest|oldest|end)(\W|$)/i;
  var NEXTISH = /(^|\W)(next|more|older|continue)(\W|$)|[›»→]/i;

  // Never enacted, whatever it was classified as. The scroller clicks things
  // on a live page under a real session, so a misclassification is not a bad
  // reading — it is an action taken on the user's behalf. On one YouTube
  // results page the pager detector offered up "Sign in"; a classifier will
  // always be wrong sometimes, so the controls that must never be pressed
  // are refused independently of what any classifier concluded.
  var NEVER_LABEL = new RegExp(
    'sign\\s?(in|up|out)|log\\s?(in|out)|register|subscribe|unsubscribe' +
    '|checkout|buy|purchase|order|add to (cart|bag)|donate|pay\\b|upgrade' +
    '|delete|remove|discard|clear all|unfollow|block\\b|report\\b|flag\\b' +
    '|upload|publish|submit|send\\b|reply|confirm|accept|agree|consent' +
    '|install|download', 'i');
  var NEVER_HREF = new RegExp(
    '(^|\\.|/)(accounts?|auth|login|signin|signup|register|logout|signout' +
    '|checkout|cart|basket|billing|payment|donate|subscribe)(/|\\.|\\?|$)'
    + '|[?&](sign|log)in=', 'i');

  // A form is dangerous when submitting it sends something that cannot be
  // taken back — credentials, a card number, an identity. It is not
  // dangerous merely for being a form: search results paginate through the
  // search form, usually by POST, so refusing every `form[action]` and every
  // submit button refused the pager on the most ordinary page there is. The
  // label check already rejects "Sign in" and "Buy"; this narrows the form
  // rule to the fields that make a submission irreversible.
  var RISKY_FIELD = 'input[type=password], input[autocomplete^="cc-"], '
    + 'input[name*="card"], input[name*="cvv"], input[name*="cvc"], '
    + 'input[name*="ssn"], input[name*="iban"], input[autocomplete="one-time-code"]';

  function riskyForm(el) {
    if (!el.closest) return false;
    if (el.closest('dialog[open]')) return true;   // a modal is a decision
    var f = el.closest('form');
    if (!f || !f.querySelector) return false;
    return !!f.querySelector(RISKY_FIELD);
  }

  function refused(el) {
    var label = pagerLabel(el);
    if (label && NEVER_LABEL.test(label)) return true;
    var href = (el.getAttribute && el.getAttribute('href') || '');
    if (href && NEVER_HREF.test(href)) return true;
    return riskyForm(el);
  }

  function pagerLabel(el) {
    var t = (el.textContent || '').trim();
    if (!t && el.getAttribute) {
      t = el.getAttribute('aria-label') || el.getAttribute('title')
          || el.getAttribute('value') || '';
    }
    return t.slice(0, 80);
  }

  function advances(el) {
    if (refused(el)) return false;
    var label = pagerLabel(el);
    if (BACKWARD.test(label)) return false;
    if (JUMPS.test(label)) return false;
    return true;
  }

  function atBottom() {
    var doc = document.documentElement;
    var h = window.innerHeight || doc.clientHeight || 0;
    var y = window.scrollY || window.pageYOffset || 0;
    return (y + h) >= (doc.scrollHeight - 2);
  }

  function step(px) {
    // One counter per gate, not one total. A single `skipped` said six of
    // every seven detected pagers were declined and could not say by what —
    // and the gates disagree about what they are for: `empties` retires a
    // control that stopped working, `offscreen` is waiting for the reader,
    // `refused` is a safety decision, `notbottom` is a policy about when a
    // navigation is allowed. Only one of those is worth relaxing.
    // `fired` stays, always empty, because the scroller no longer presses.
    // `offered` is what replaces it: controls that came into view, for a
    // reader to act on rather than for us to act on.
    var out = { scrolled: 0, delta: 0, fired: [], offered: [],
                skipped: 0, pagers: 0,
                bottom: false, exhausted: false, errors: 0,
                sk_empties: 0, sk_disabled: 0, sk_offscreen: 0,
                sk_refused: 0, sk_backward: 0, sk_notbottom: 0,
                sk_scrolledto: 0,
                sk_lostrace: 0, seen_pagers: 0 };
    try {
      // What the previous step's presses actually produced. A pager is
      // judged by its deltas, not by its label (§7.8), and this is where
      // that judgement is recorded.
      var produced = stats.chunks - lastEmit;
      lastEmit = stats.chunks;
      out.delta = produced;
      for (var i = 0; i < firedLast.length; i++) {
        var st = pagers.get(firedLast[i]);
        if (!st) continue;
        st.last = produced;
        if (produced === 0) st.empties++; else st.empties = 0;
      }
      emptySteps = produced === 0 ? emptySteps + 1 : 0;
      firedLast = [];

      var before = window.scrollY || window.pageYOffset || 0;
      var amount = px > 0 ? px
        : Math.max(200, (window.innerHeight || 600) - 60);
      window.scrollBy(0, amount);
      out.scrolled = (window.scrollY || window.pageYOffset || 0) - before;
      out.bottom = atBottom();

      var keep = [], ready = [], nav = null, navCandidates = 0;
      for (i = 0; i < pagerList.length; i++) {
        var el = pagerList[i];
        if (!el.isConnected) continue;          // gone from the page
        keep.push(el);
        var s = pagers.get(el);
        if (!s) continue;
        // A control that has stopped producing deltas stops being pressed.
        out.seen_pagers++;
        if (s.empties >= 2) { out.skipped++; out.sk_empties++; continue; }
        if (el.disabled) { out.skipped++; out.sk_disabled++; continue; }
        // A pager below the fold is not a reason to wait — it is a
        // reason to scroll. Gating enactment on `inView` meant the scroller
        // declined a control it had already found, and on pages with a
        // detected pager that never advanced, 87% of every sighting was
        // refused for exactly this. Pagers live at the bottom; requiring one
        // to come to us inverts §5's "enacted the moment it is first
        // detected". Bring it into view instead, and only give up if it
        // cannot be brought.
        if (!inView(el)) {
          try {
            el.scrollIntoView({ block: 'center' });
            out.sk_scrolledto++;
          } catch (e) { out.sk_offscreen++; continue; }
          if (!inView(el)) { out.sk_offscreen++; continue; }
        }
        if (refused(el)) { out.skipped++; out.sk_refused++; continue; }
        if (!advances(el)) { out.skipped++; out.sk_backward++; continue; }
        if (!navigates(el)) { ready.push(el); continue; }
        // Navigating pagers wait for the end of the document, and exactly
        // one is taken: two navigations in one step race, and the loser's
        // delta is attributed to the winner.
        if (!out.bottom) { out.skipped++; out.sk_notbottom++; continue; }
        navCandidates++;
        if (nav === null || (!NEXTISH.test(pagerLabel(nav))
                             && NEXTISH.test(pagerLabel(el)))) {
          nav = el;
        }
      }
      pagerList = keep;
      if (nav !== null) ready.push(nav);
      out.sk_lostrace = navCandidates > 1 ? navCandidates - 1 : 0;
      // The scroller scrolls. It does not press.
      //
      // It used to, and the funnel that produced -- 41% of pages with a pager
      // found, 22% enacted, 16% actually advancing -- existed because *we*
      // were choosing which control to press. On YouTube that choice reached
      // for "Sign in", "My Ad Center" and the microphone, 37 false positives
      // on one results page, and the denylist that stopped it was patching a
      // decision that should not have been ours.
      //
      // The reader presses now, through `perform`. What survives here is the
      // observation: these are the controls that came into view, reported so
      // a reader can act on one, with the same `refused` gate in front of the
      // action wherever it originates.
      for (i = 0; i < ready.length; i++) {
        var target = ready[i], ts = pagers.get(target);
        if (ts) ts.seen = (ts.seen || 0) + 1;
        out.offered.push([target.tagName.toLowerCase(),
                          pagerLabel(target).slice(0, 40),
                          navigates(target) ? 'navigate' : 'in-place']);
      }
      out.pagers = pagerList.length;
      out.exhausted = emptySteps >= 2;
    } catch (e) { out.errors++; stats.errors++; }
    return out;
  }

  // ---- invalidation (§5 spans) -----------------------------------------
  function markDirty(node) {
    var n = node;
    while (n) {
      var rec = records.get(n);
      if (rec) { if (rec.dirty) break; rec.dirty = true; }
      // `assignedSlot` first: a slotted node's parent *in the fold* is the
      // slot that draws it, not the host it is written under. Climbing
      // `parentNode` walked straight past the slot and every shadow ancestor
      // between it and the host, leaving their records clean — so the fold
      // returned a cached subtree that no longer described the page.
      n = n.assignedSlot || n.parentNode || (n.host || null) ||
          (n.getRootNode && n.getRootNode().host) || null;
    }
  }

  // Record which children of a parent a mutation touched. The map existed
  // and was written, cleared, and never read — `stats.spans` counted
  // something nothing consumed. This makes it load-bearing.
  function noteSpan(m) {
    var parent = m.target.parentNode;
    if (m.type === 'childList') parent = m.target;
    if (!parent || parent.nodeType !== 1) return;
    var prec = records.get(parent);
    if (!prec) return;
    // The same array the fold walks, or the span names the wrong children:
    // a host's fold children are its shadow root's, and a slot's are the
    // nodes assigned to it. Indexing `childNodes` against either was off by
    // the shadow root's length, silently, for every shadow host on the page.
    var kids = parent.shadowRoot ? parent.shadowRoot.childNodes
                                 : composedKids(parent);
    var idx = -1, i;
    var probe = m.type === 'childList'
      ? (m.addedNodes[0] || m.previousSibling || null) : m.target;
    for (i = 0; i < kids.length; i++) {
      if (kids[i] === probe) { idx = i; break; }
    }
    if (idx < 0) { prec.lo = 0; prec.hi = kids.length; stats.spanWide++; return; }
    prec.lo = prec.lo < 0 ? idx : Math.min(prec.lo, idx);
    prec.hi = prec.hi < 0 ? idx + 1 : Math.max(prec.hi, idx + 1);
    stats.spans++;
  }

  // A link's class is not a function of its own subtree.
  //
  // `numericFamily` walks four ancestors up and counts the anchors it finds
  // there, so adding or removing an anchor anywhere in that scope can
  // re-classify a link that did not itself change. Nothing marks such a link
  // dirty, it is never re-folded, and `rec.tax` -- cleared only at the top of
  // a re-fold -- keeps the old verdict for the life of the page.
  //
  // Deleting one <li> from a Wikipedia citation list dropped a family below
  // three and re-classified four surviving links from `pagination.family` to
  // `link.anchor`. The trie held four addresses the page did not have and
  // missed the four it did. That this is a cache and not the wire was settled
  // by turning the gate off: all 6832 units were re-sent and the same four
  // were still wrong.
  //
  // Which links can be affected follows from the rule, so it is not guessed
  // at. A mutation at `T` changes the anchor set of `subtree(X)` for exactly
  // the `X` that are ancestors-or-self of `T`; a link's verdict depends only
  // on the same-mask anchors within its own scope. So a link can change iff
  //
  //   (a) its scope is an ancestor-or-self of the mutation, and
  //   (b) the anchor that entered or left carries its masked href.
  //
  // An earlier version invalidated `subtree(anc4(T))` and ignored masks
  // entirely. That missed every link satisfying (a) from more than four levels
  // above the change -- a link high in the document whose scope reaches down
  // to it -- and it ignored (b) outright, so `relocate` on the Wikipedia table
  // dropped 1198 verdicts to emit nothing.
  //
  // Both halves are now exact, and the pair is cheaper than the scoped version
  // it replaces. Widening to the document costs one query and a regex per
  // anchor: arithmetic, proportional to the page, and done once per repair
  // rather than once per mutation. Filtering by mask cuts what gets marked
  // dirty from every anchor in scope to the family alone, and marking dirty is
  // the part that costs a re-fold. O(delta) binds on the fold, not on the
  // scan, so this trades a page-sized scan for a family-sized fold.
  //
  // Document-wide *without* the mask filter would also be exact, and is
  // refused: it dirties every anchor's path, which makes any anchor-bearing
  // mutation cost a whole-page fold and gives up O(delta) to buy nothing.

  // The membership key, and deliberately the same expression `numericFamily`
  // uses. A family is hrefs that differ only in their digits, so an href with
  // no digits cannot belong to one and cannot disturb one either.
  function maskOf(href) {
    if (!href || !/\d/.test(href)) return null;
    return href.replace(/\d+/g, '#');
  }

  function noteMask(href) {
    var mask = maskOf(href);
    if (!mask) return;
    if (!pendingMasks) pendingMasks = {};
    pendingMasks[mask] = 1;
  }

  function noteMasksIn(list) {
    for (var i = 0; i < list.length; i++) {
      var n = list[i];
      if (!n || n.nodeType !== 1) continue;
      if (n.tagName === 'A') noteMask(n.getAttribute('href'));
      if (!n.querySelectorAll) continue;
      // A removed node is detached, not destroyed; it still answers queries,
      // so the anchors that left inside a subtree are countable here.
      var inner = n.querySelectorAll('a[href]');
      for (var k = 0; k < inner.length; k++) {
        noteMask(inner[k].getAttribute('href'));
      }
    }
  }

  // Once per repair, not once per mutation: a page that appends fifty rows
  // should pay for one sweep, and the masks accumulate until someone folds.
  function reclassify() {
    if (!pendingMasks) return;
    var masks = pendingMasks;
    pendingMasks = null;
    roots.forEach(function (_obs, root) {
      // Shadow roots are separate query scopes, and a family inside one is
      // still a family. Skipping them would make the sweep silently partial
      // exactly where the map already works hardest to be whole.
      var scope = root.nodeType === 9 ? root.documentElement : root;
      if (!scope || !scope.querySelectorAll) return;
      var links = scope.querySelectorAll('a[href]');
      for (var i = 0; i < links.length; i++) {
        var rec = records.get(links[i]);
        // No record, or no verdict yet: nothing cached to be stale.
        if (!rec || !rec.tax) continue;
        var mask = maskOf(links[i].getAttribute('href'));
        if (!mask || !masks[mask]) continue;
        // Drop the verdict and put the node back in the fold's path. The
        // re-fold recomputes the class; the class is in the digest, so the
        // chunk stops being skipped and the new address is drawn.
        rec.tax = null;
        markDirty(links[i]);
        stats.reclassified++;
      }
    });
  }

  function onMutations(recs) {
    try {
      for (var i = 0; i < recs.length; i++) {
        var m = recs[i];
        if (USE_SPANS) noteSpan(m);
        if (m.type === 'attributes' && m.attributeName === 'href') {
          // Membership is decided on the href itself, so an edit moves the
          // link between two families and both counts change. `oldValue` is
          // the only place the family it left is still named.
          noteMask(m.oldValue);
          noteMask(m.target.getAttribute && m.target.getAttribute('href'));
        }
        if (m.type === 'childList') {
          noteMasksIn(m.addedNodes);
          noteMasksIn(m.removedNodes);
          for (var a = 0; a < m.addedNodes.length; a++) {
            var an = m.addedNodes[a];
            if (an.nodeType === 1 && an.shadowRoot) observe(an.shadowRoot);
          }
        }
        markDirty(m.target);
        var parent = m.target.parentNode;
        if (parent) {
          var span = dirtySpans.get(parent);
          if (!span) { dirtySpans.set(parent, { lo: 0, hi: 0 }); stats.spans++; }
        }
      }
      schedule();
    } catch (e) { stats.errors++; }
  }

  function signalDirty() {
    if (!SAY || signalled) return;
    if (front.length === 0 && removedIds.length === 0) return;
    signalled = true;
    try { SAY(SIGNAL + 'dirty'); } catch (e) { stats.errors++; }
  }

  function schedule() {
    // `lazy`: no background work at all. The fold happens when someone
    // drains, which is the most literal reading of "passive sensor" — the
    // page pays nothing for being watched until it is asked.
    if (USE_LAZY) return;
    // `eager`: fold inside the mutation callback. The opposite bound, and
    // the one that shows what the debounce is worth.
    if (USE_EAGER) { repair(); return; }
    if (!dirtySince) dirtySince = Date.now();
    if (timer !== null) return;
    var run = function () {
      timer = null; repair();
      if (PUSH) flush(SIGNAL); else signalDirty();
    };
    // A pushing host folds in the SAME TASK as the mutation, not when the
    // page next idles. An idle callback on a busy page waited up to 4x the
    // debounce (320 ms); a frame or a timer waits behind whatever task the
    // page queued next (discourse queues its long render tasks back to back).
    // A microtask runs before any of them. In a burst -- folds closer than a
    // frame apart -- it falls back to the next frame, so a page animating an
    // attribute pays one fold per frame and not one per task.
    if (PUSH) {
      var clockNow = (typeof performance !== 'undefined' && performance.now)
        ? performance.now() : Date.now();
      if (clockNow - lastFoldAt >= 16 && typeof queueMicrotask === 'function') {
        timer = 1;
        queueMicrotask(function () { lastFoldAt = clockNow; run(); });
        return;
      }
      if (typeof requestAnimationFrame === 'function') {
        var fired = false;
        var once = function () {
          if (fired) return; fired = true;
          lastFoldAt = (typeof performance !== 'undefined' && performance.now)
            ? performance.now() : Date.now();
          run();
        };
        timer = requestAnimationFrame(once);
        setTimeout(once, DEBOUNCE);     // a hidden page gets no frames
        return;
      }
    }
    timer = (typeof requestIdleCallback === 'function')
      ? requestIdleCallback(function () { run(); }, { timeout: DEBOUNCE * 4 })
      : setTimeout(run, DEBOUNCE);
  }

  function repair() {
    // How long the mutation-chunking phase costs inside the page, kept apart
    // from the round trip. `drain_ms` on the Python side is the whole
    // crossing -- WebDriver toll, serialisation, transport -- and the fold
    // itself is a small fraction of it, so one number could never say
    // whether a variant made the *algorithm* faster or merely sent less.
    //
    // A duration, not a timestamp: it is a difference of two reads, so a
    // clamped clock (RFP quantises to 16.667ms) coarsens it without biasing
    // it, and nothing here depends on ordering between frames.
    //
    // `performance.now()` is not a layout read, so this does not touch the
    // property invariants.c2 enforces.
    var t0 = (typeof performance !== 'undefined' && performance.now)
      ? performance.now() : Date.now();
    // Before the walk, or the fold reads verdicts this pass has just learned
    // are stale. Inside the timed region, because it is fold work and a phase
    // timing that hides its own cost is not a phase timing.
    reclassify();
    familyMemo = (typeof Map === 'function') ? new Map() : null;
    try {
      stats.repairs++;
      var out = [];
      roots.forEach(function (_obs, root) {
        var host = root.host || root;
        var node = root.nodeType === 9 ? root.documentElement : root;
        if (!node || node.nodeType !== 1) return;
        var rec = fold(node);
        if (!rec) return;
        emitChunks(node, [], out);
      });
      // `rank` orders emission by subtree weight instead of document
      // order, so a reader receiving a stream sees substance before chrome.
      // `count` has been maintained on every fold since the beginning and
      // read by nothing; this is what it was named for.
      if (USE_RANK) {
        out.sort(function (a, b) { return (b.chars || 0) - (a.chars || 0); });
      }
      for (var i = 0; i < out.length; i++) front.push(out[i]);
      // Name what left. Without this the delta could only ever add: a chunk
      // whose node was deleted stayed in the store with an address that no
      // longer resolved, and on a page that re-renders its results — Bing
      // rewrites most of its list — the great majority of stored addresses
      // went dead while every one of them looked fine.
      var live = [];
      for (i = 0; i < chunkRoots.length; i++) {
        var slot = chunkRoots[i];
        if (slot.node && slot.node.isConnected) {
          // Connected, and still a chunk root?
          //
          // A node can stop being one without leaving the page: delete a
          // sibling and the budget re-splits the parent, so the run that was
          // rooted here is rooted one node along. The old slot keeps a live
          // node, so this sweep kept it, so its id was never reported gone --
          // and the receiver went on holding every address that id ever
          // claimed. On archive.org's details page that was 17 addresses the
          // page no longer has, invisible to every other channel: no unit, no
          // move, no removal, and the repaired fold emitting exactly the same
          // 600 addresses as a cold one.
          //
          // A full walk visits every live chunk root, so one that was not
          // visited is not a chunk root any more. Only sound when the walk is
          // full: `subtreegate` prunes unmoved subtrees, and there an
          // unvisited root is merely an unchanged one.
          if (USE_SUBTREEGATE || slot.seen === stats.repairs) {
            live.push(slot); continue;
          }
          stats.unrooted++;
        }
        slot.tracked = false;
        slot.node = null;
        removedIds.push(slot.id);
      }
      chunkRoots = live;
      sweepOpaque();
      sweepHosts();
      dirtySpans.clear();
      stats.nodes = 0;
    } catch (e) { stats.errors++; }
    familyMemo = null;
    var t1 = (typeof performance !== 'undefined' && performance.now)
      ? performance.now() : Date.now();
    stats.repairMs = (stats.repairMs || 0) + (t1 - t0);
  }

  // ---- observation (§3 of the injection doc: one per root) -------------
  // Slot assignment moves content without moving a node. The light child
  // stays exactly where it is written and only the slot that claims it
  // changes, so the composed tree reorders and *no mutation record describes
  // it* — the fold saw a page that had not changed, and drained nothing, on a
  // page whose reading order had just been rewritten. `slotchange` is the
  // only notification there is, and it bubbles inside the shadow root, so one
  // listener per root covers every slot in it.
  function onSlotChange(e) {
    try {
      markDirty(e.target);
      schedule();
    } catch (err) { stats.errors++; }
  }

  function observe(root) {
    if (!root || roots.has(root)) return;
    if (root.nodeType === 11) {
      try { root.addEventListener('slotchange', onSlotChange); }
      catch (e) { stats.errors++; }
    }
    var obs = new MutationObserver(onMutations);
    var opts = {
      // `perchunk` narrows the document-level observer and puts observers on
      // the chunk roots instead — the reference engine's arrangement.
      // Localised invalidation, many more observers, and a real risk of
      // missing content outside any chunk: exactly the trade worth pricing.
      subtree: !USE_PERCHUNK,
      childList: true,
      characterData: !NO_CHARWATCH,
      attributes: true,
      // Without this an edited href names the family it joined and not the
      // one it left, so the abandoned family keeps a count that is one too
      // high and every member of it keeps a stale verdict.
      attributeOldValue: true
    };
    if (ATTR_FILTER) opts.attributeFilter = ATTR_FILTER;
    obs.observe(root.nodeType === 9 ? root.documentElement : root, opts);
    roots.set(root, obs);
    stats.observers++;
    markDirty(root.nodeType === 9 ? root.documentElement : root);
    schedule();
  }

  // ---- flush: the drain, its boxes and pictures, pushed ----------------
  // What the streaming host takes from the page, in ONE place: the drain,
  // then the diff's boxes and largest rendered pictures (peripherals, read
  // after the fold, never inside it). With `push` it is sent on the console
  // channel and only `{pushed: v}` is returned; otherwise it is returned.
  // `expect` is the host's own signal: a handle booted by an EARLIER host
  // (the realm outlives a plugin reload) returns its payload instead of
  // pushing it where nobody is listening.
  function flush(expect) {
    var clock = (typeof performance !== 'undefined' && performance.now)
      ? function () { return performance.now(); } : Date.now;
    var since = dirtySince;
    var t0 = clock();
    var p = drain();
    var t1 = clock(), t2 = t1, t3 = t1;
    if (!p) return p;
    var ids = [];
    for (var i = 0; i < (p.chunks || []).length; i++) ids.push(p.chunks[i].id);
    if (ids.length) {
      p.boxes = boxes(ids); t2 = clock();
      p.pictures = pictures(ids); t3 = clock();
    }
    p.inpage = { drain: t1 - t0, boxes: t2 - t1, pictures: t3 - t2 };
    p.dirtyAt = since;
    p.sentAt = Date.now();
    if (PUSH && expect === SIGNAL && (ids.length || (p.removed || []).length || (p.moves || []).length
                 || (p.dict || []).length)) {
      try {
        SAY(SIGNAL + 'drain ' + JSON.stringify(p));
        return { pushed: p.v, url: p.url };
      } catch (e) { stats.errors++; }
    }
    return p;
  }

  // ---- drain (one round trip) ------------------------------------------
  var lastDrain = 0;
  function drain() {
    signalled = false;
    dirtySince = 0;
    if (USE_LAZY || front.length === 0 && removedIds.length === 0) repair();
    // `coalesce`: a crossing costs the same whether it carries one chunk or
    // forty. Holding a thin payload until it thickens — or until enough time
    // has passed that the reader deserves it — trades a little latency for
    // round trips, which measured as the fixed cost of a pass.
    if (USE_COALESCE && front.length && front.length < 4) {
      var nowms = (typeof performance !== 'undefined' && performance.now)
        ? performance.now() : Date.now();
      if (nowms - lastDrain < 400) {
        stats.coalesced++;
        return { v: version, url: '', dict: [], shapes: [], chunks: [],
                 removed: [], settled: false, stats: { held: true } };
      }
    }
    lastDrain = (typeof performance !== 'undefined' && performance.now)
      ? performance.now() : Date.now();
    var chunks = front; front = back.length ? back : []; back = chunks;
    var newDict = dict.slice(dictSent);
    dictSent = dict.length;
    var shapesBefore = shapesSent;
    shapesSent = shapes.length;
    var payload = {
      v: ++version,
      // Carried in the payload rather than asked for separately. An SPA route
      // change rewrites the address without destroying the realm, so the
      // handle survives and nothing else would notice the document is now a
      // different document; a second round trip to ask would cost the fixed
      // 5-11 ms toll on every drain to learn something almost always
      // unchanged.
      url: (function () {
        try { return String(location.href); } catch (e) { return ''; }
      })(),
      dict: newDict,
      // Append-only, exactly like the dictionary: a shape ships once and
      // every later payload sends only what was added since.
      shapes: USE_SHAPE ? shapes.slice(shapesBefore) : [],
      chunks: chunks,
      moves: moves,
      removed: removedIds,
      settled: timer === null,
      stats: {
        folds: stats.folds, repairs: stats.repairs, chunks: stats.chunks,
        observers: stats.observers, spans: stats.spans, errors: stats.errors,
        dictSize: dict.length, skipped: stats.skipped,
        // Chunk roots a full walk did not visit. They are still in the
        // document, so the connectedness sweep keeps them; their slot has
        // stopped being a chunk root, and their addresses would linger.
        unrooted: stats.unrooted, reclassified: stats.reclassified,
        deduped: stats.deduped, sketchHits: stats.sketchHits,
        // How much of the composed tree we could not see into. Reported
        // rather than left in the page, because a coverage figure that does
        // not name what it could not reach is not a coverage figure.
        closedRoots: stats.closedRoots,
        // What actually ran, not what was asked for — `shape` disables
        // `pathdelta`, and a decoder that believed the request rather than
        // the report would mis-read every path.
        variants: {dedup: USE_DEDUP, gate: USE_GATE,
                   cache: USE_CACHE, intern: USE_INTERN,
                   pathdelta: USE_PATHDELTA, shape: USE_SHAPE,
                   valdict: USE_VALDICT, packed: USE_PACKED,
                   subtreegate: USE_SUBTREEGATE, spans: USE_SPANS,
                   viewport: USE_VIEWPORT, merge: USE_MERGE,
                   semantic: USE_SEMANTIC, rank: USE_RANK,
                   attrs: USE_WIDEATTRS, charwatch: !NO_CHARWATCH,
                   perchunk: USE_PERCHUNK, lazy: USE_LAZY, eager: USE_EAGER,
                   anchored: USE_ANCHORED, idanchor: USE_IDANCHOR,
                   simhash: USE_SIMHASH, crosspage: USE_CROSSPAGE,
                   chunkdelta: USE_CHUNKDELTA, textdict: USE_TEXTDICT,
                   coalesce: USE_COALESCE, deepgate: USE_DEEPGATE},
        merged: stats.merged, knownSkips: stats.knownSkips,
        pruned: stats.pruned, offscreen: stats.offscreen,
        spanHits: stats.spanHits, nearDups: stats.nearDups,
        deduped: stats.deduped, skipped: stats.skipped,
        wordsInterned: stats.wordsInterned,
        chunkDeltas: stats.chunkDeltas, coalesced: stats.coalesced,
        deepPruned: stats.deepPruned,
        movedChunks: stats.movedChunks,
        // The mutation-chunking phase's own cost, so the algorithm can be
        // timed apart from the crossing that carries its result.
        repairMs: stats.repairMs,
        search: {seen: stats.sr_seen, hit: stats.sr_hit,
                 form: stats.sr_form, type: stats.sr_type,
                 badtype: stats.sr_badtype,
                 badname: stats.sr_badname,
                 novocab: stats.sr_novocab,
                 urlparam: stats.sr_url,
                 queryform: stats.sr_queryform}
      }
    };
    front = []; removedIds = []; moves = [];
    return payload;
  }

  observe(document);

  // ---- enactment: action chains, in the page ----------------------------
  //
  // Selenium's ActionChains is the model, not the runtime. Its grammar is a
  // W3C data structure -- input sources crossed with a tick timeline -- and
  // that structure has no dependency on being driven from outside. Built in
  // here it gains the one thing the outside version cannot have: targets
  // resolved through the composed tree, so a control three shadow roots deep
  // is addressed exactly like a top-level anchor and the boundary is not a
  // case in the executor, the same way it is not a case in the fold.
  //
  // There is one dispatcher. A gesture that does not take is reported as not
  // having taken; nothing quietly tries a second way, because a second way
  // that quietly succeeds is how you stop being able to tell whether the
  // first one works.

  function resolveStep(parent, seg, ordinal) {
    if (seg === '#shadow-root') return parent.shadowRoot || null;
    // The children the fold addressed, so an address it emitted resolves
    // back to the node it was taken from — through a slot included.
    var kids = composedKids(parent) || [], n = 0, i;
    for (i = 0; i < kids.length; i++) {
      var k = kids[i];
      if (seg === '#text') {
        if (k.nodeType !== 3) continue;
      } else {
        if (k.nodeType !== 1) continue;
        if ((k.tagName || '').toLowerCase() !== seg) continue;
      }
      if (++n === ordinal) return k;
    }
    return null;
  }

  // A path is the same [tag, ordinal, ...] the fold emits, so an address the
  // receiver holds resolves back to the node it was taken from without any
  // spelling being rebuilt on either side.
  function resolvePath(path) {
    var node = document.documentElement, i;
    if (!path || !path.length) return null;
    // The fold starts at documentElement, so a leading html step names the
    // node we are already standing on.
    var head = String(path[0] || '').toLowerCase();
    var start = (head === 'html') ? 2 : 0;
    for (i = start; i < path.length - 1; i += 2) {
      node = resolveStep(node, String(path[i]).toLowerCase(), path[i + 1] || 1);
      if (!node) return null;
    }
    return node;
  }

  // The receiver's spelling of a composed-tree address, walked back to its
  // node. Mirrors `sensing.Sensor._xpath`: `#shadow-root` for a boundary,
  // `text()[n]` for a text child, `tag` or `tag[n]` for an element, and
  // `*[@id='x']` where the fold re-rooted the address at an id.
  function resolveXPath(xpath) {
    if (!xpath || xpath.charAt(0) !== '/') return null;
    var steps = xpath.split('/'), node = document.documentElement, i, seg;
    for (i = 1; i < steps.length; i++) {
      seg = steps[i];
      if (!seg) continue;
      if (i === 1 && seg.toLowerCase() === 'html') continue;   // already here
      var anchored = /^\*\[@id=['"]?([^'"\]]*)['"]?\]$/.exec(seg);
      if (anchored) {
        try { node = document.getElementById(anchored[1]); } catch (e) { node = null; }
        if (!node) return null;
        continue;
      }
      if (seg === '#shadow-root') { node = resolveStep(node, '#shadow-root', 1); }
      else {
        var text = /^text\(\)\[(\d+)\]$/.exec(seg);
        if (text) { node = resolveStep(node, '#text', parseInt(text[1], 10)); }
        else {
          var m = /^([^\[\]]+)(?:\[(\d+)\])?$/.exec(seg);
          if (!m) return null;
          node = resolveStep(node, m[1].toLowerCase(),
                             m[2] ? parseInt(m[2], 10) : 1);
        }
      }
      if (!node) return null;
    }
    return node;
  }

  function nativeSet(el, value) {
    // A framework replaces the value property on the instance, so assigning
    // through it is invisible to that framework's own listener. The
    // prototype's setter is the one the browser installed, and the one a
    // change tracker watches.
    var proto = HTMLInputElement.prototype;
    try {
      if (typeof HTMLTextAreaElement !== 'undefined'
          && el instanceof HTMLTextAreaElement) proto = HTMLTextAreaElement.prototype;
      else if (typeof HTMLSelectElement !== 'undefined'
               && el instanceof HTMLSelectElement) proto = HTMLSelectElement.prototype;
      var d = Object.getOwnPropertyDescriptor(proto, 'value');
      if (d && d.set) { d.set.call(el, value); return; }
    } catch (e) { /* fall through */ }
    try { el.value = value; } catch (e2) {}
  }

  function fire(el, type, init) {
    // composed: true throughout. Without it an event stops at the shadow
    // boundary and a host-level listener never sees it, which is exactly the
    // case this executor exists to serve.
    var opts = { bubbles: true, cancelable: true, composed: true };
    var ev, k;
    if (init) for (k in init) if (init.hasOwnProperty(k)) opts[k] = init[k];
    try {
      if (type.indexOf('key') === 0) ev = new KeyboardEvent(type, opts);
      else if (type.indexOf('pointer') === 0) ev = new PointerEvent(type, opts);
      else if (type.indexOf('mouse') === 0 || type === 'click')
        ev = new MouseEvent(type, opts);
      else ev = new Event(type, opts);
    } catch (e) { ev = new Event(type, opts); }
    el.dispatchEvent(ev);
  }

  // One tick. The vocabulary is the subset of the W3C actions grammar a
  // reader can express from a terminal.
  function tick(t, out) {
    // A target is a `path` (the Selenium host's spelling) or an `xpath` (the
    // trie's own, which the browser cell holds: `#shadow-root`, `text()[n]` and
    // re-rooted `*[@id=..]` steps included). Same refusal, same dispatcher.
    var el = t.path ? resolvePath(t.path)
           : (t.xpath ? resolveXPath(String(t.xpath)) : null);
    if ((t.path || t.xpath) && !el) { out.failed.push([t.kind, 'unresolved']); return; }
    if (el && el.nodeType === 3) el = el.parentNode;
    // A <label> addressed for a field acts through the control it labels: the
    // store keys "Your word [ ]" at the label, and typing into the label did
    // nothing (G-111, 2026-10-07).
    if (el && el.tagName === 'LABEL' && (t.kind === 'type' || t.kind === 'check' || t.kind === 'choose')) {
      var lc = null;
      try { lc = el.control || null; } catch (e) { lc = null; }
      if (lc) el = lc;
    }
    if (el && refused(el)) { out.failed.push([t.kind, 'refused']); return; }
    try {
      switch (t.kind) {
        case 'pause':
          break;
        case 'scrollIntoView':
          el.scrollIntoView({ block: 'center' });
          break;
        case 'pointerDown':
          fire(el, 'pointerdown'); fire(el, 'mousedown');
          break;
        case 'pointerUp':
          fire(el, 'pointerup'); fire(el, 'mouseup');
          break;
        case 'click':
          try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
          if (typeof el.focus === 'function') { try { el.focus(); } catch (e) {} }
          if (typeof el.click === 'function') el.click();
          else {
            fire(el, 'pointerdown'); fire(el, 'mousedown');
            fire(el, 'mouseup'); fire(el, 'click');
          }
          break;
        case 'hover':
          fire(el, 'pointerover'); fire(el, 'mouseover'); fire(el, 'mousemove');
          break;
        case 'type':
          if (typeof el.focus === 'function') { try { el.focus(); } catch (e) {} }
          nativeSet(el, String(t.text == null ? '' : t.text));
          fire(el, 'input', { inputType: 'insertText', data: t.text });
          fire(el, 'change');
          break;
        case 'check':
          if ('checked' in el) el.checked = !el.checked;
          fire(el, 'click'); fire(el, 'change');
          break;
        case 'choose':
          if (el.options) {
            for (var oi = 0; oi < el.options.length; oi++) {
              var o = el.options[oi];
              if (o.value === t.text
                  || (o.textContent || '').trim() === t.text) {
                el.selectedIndex = oi; break;
              }
            }
          } else { nativeSet(el, String(t.text || '')); }
          fire(el, 'input'); fire(el, 'change');
          break;
        case 'key':
          var target = el || document.activeElement || document.body;
          var kinit = { key: t.text || 'Enter' };
          if (t.code) kinit.code = t.code;
          fire(target, 'keydown', kinit);
          fire(target, 'keypress', kinit);
          fire(target, 'keyup', kinit);
          break;
        case 'submit':
          var form = el.form || (el.closest ? el.closest('form') : null);
          if (!form) { out.failed.push([t.kind, 'no form']); return; }
          if (typeof form.requestSubmit === 'function') form.requestSubmit();
          else form.submit();
          break;
        case 'scroll':
          window.scrollBy(0, t.px || 0);
          break;
        default:
          out.failed.push([t.kind, 'unknown']);
          return;
      }
      out.done.push(t.kind);
    } catch (e) {
      out.failed.push([t.kind, String((e && e.message) || e)]);
    }
  }

  // A chain returns the moment its last tick is dispatched. It does not wait
  // for the page to be finished, because a page is never finished: the
  // listeners are sensors, they assume no terminal state, and whatever this
  // gesture causes arrives on the same stream as everything else the page
  // does on its own. Waiting here would be inventing a completion the DOM
  // does not have.
  function perform(chain) {
    var out = { done: [], failed: [], url: '' };
    var ticks = (chain && chain.ticks) || [];
    for (var i = 0; i < ticks.length; i++) tick(ticks[i], out);
    try { out.url = String(location.href); } catch (e) { out.url = ''; }
    out.version = version;
    return out;
  }

  // ---- the box peripheral ----------------------------------------------
  //
  // Where each named chunk root is drawn, for the host's diff overlay
  // (G-90). NOT part of the fold: the host calls it right after `drain()`,
  // in the SAME round trip, for exactly the chunks that drain emitted, so
  // the overlay needs no second crossing -- the second crossing is what made
  // it cost ~50 ms. Read on the terms `styles` is: on demand, for a
  // caller-named set, kept beside the trie and never in it. A merged run is
  // boxed at its first node; its siblings are not unioned here.
  function boxes(ids) {
    var want = {}, out = [], i, s, el, r;
    for (i = 0; i < ids.length; i++) { want[ids[i]] = i; out.push(null); }
    for (i = 0; i < chunkRoots.length; i++) {
      s = chunkRoots[i];
      if (!s || !s.node || !(s.id in want)) continue;
      el = s.node.nodeType === 3 ? s.node.parentNode : s.node;
      if (!el || !el.getBoundingClientRect) continue;
      r = el.getBoundingClientRect();
      out[want[s.id]] = [r.left, r.top, r.width, r.height];
    }
    return out;
  }

  // ---- the picture peripheral (2026-09-27) --------------------------------
  //
  // For each chunk, the picture a reader SEES most of: the largest rendered
  // <img> in its run (area on screen, css-scaled), not the first in the
  // markup -- which is often an icon or a spacer. Read on demand with the
  // boxes, after the fold, never in it. Returns [src, width, height] or null.
  function pictures(ids) {
    var want = {}, out = [], i, s, n, k, best, area, imgs, j, r, src;
    for (i = 0; i < ids.length; i++) { want[ids[i]] = i; out.push(null); }
    for (i = 0; i < chunkRoots.length; i++) {
      s = chunkRoots[i];
      if (!s || !s.node || !(s.id in want)) continue;
      best = null; area = 0; n = s.node; k = 0;
      // The chunk's pictures through OPEN SHADOW ROOTS too, and a CSS
      // background image counts as a picture (2026-10-07: `querySelectorAll`
      // stops at a shadow host, so archive.org's chunk nodes could show none
      // of the pictures inside its components; johnwick's hero images are CSS
      // backgrounds). At most 400 elements read per chunk; a peripheral read.
      var seen = 0;
      var consider = function (el) {
        var u = '', rr = null;
        if (el.tagName === 'IMG') u = el.currentSrc || el.src || '';
        else {
          var bi = '';
          try { bi = getComputedStyle(el).backgroundImage || ''; } catch (e) { bi = ''; }
          var m = bi.indexOf('url(') >= 0 ? /url\(["']?([^"')]+)/.exec(bi) : null;
          if (m) u = m[1];
        }
        if (!u || !/^https?:/.test(u)) return;
        rr = el.getBoundingClientRect();
        if (rr.width * rr.height > area) { area = rr.width * rr.height; best = [u, Math.round(rr.width), Math.round(rr.height)]; }
      };
      var walkPics = function (root) {
        var it = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT), el;
        if (root.nodeType === 1 && seen++ < 400) consider(root);
        while ((el = it.nextNode()) && seen++ < 400) {
          consider(el);
          if (el.shadowRoot) walkPics(el.shadowRoot);
        }
        if (root.nodeType === 1 && root.shadowRoot) walkPics(root.shadowRoot);
      };
      while (n && k++ < 400 && seen < 400) {
        if (n.nodeType === 1) walkPics(n);
        if (n === s.tail || !s.tail) break;
        n = n.nextSibling;
      }
      out[want[s.id]] = area >= 16 * 16 ? best : null;
    }
    return out;
  }

  // ---- the hover peripheral (D-35, G-92) ----------------------------------
  //
  // Which chunk draws the element under the pointer, and where it is: the
  // IN-PAGE chunking's answer, needing no store. The overlay used to wait for
  // the store's map of the page, so on a page the store did not hold yet --
  // and for seconds after every navigation -- hovering outlined nothing.
  // Called by the host on a hover, never during a drain; the walk is up the
  // composed tree from the element, and at each level back along its
  // siblings to a run that covers it.
  function covers(slot, n) {
    if (!slot.tail || slot.tail === n) return true;
    return !!(n.compareDocumentPosition(slot.tail) & 4);   // tail FOLLOWS n
  }
  // A chunk's box is what it DRAWS: the union of its text runs and its media
  // and controls, skipping any nested chunk's subtree (2026-10-06). It was
  // the CONTAINER's box -- on a full-bleed page (johnwick.movie) a chunk of
  // a few lines sits in a section several screens tall, and every hover
  // outline came out larger than the viewport (121 of 121 sampled points,
  // median 2.6 viewports). The container's own box is the fallback when the
  // chunk draws nothing measurable. At most 600 nodes read; a peripheral
  // read, never the fold's.
  var DRAWN = { IMG: 1, VIDEO: 1, AUDIO: 1, CANVAS: 1, SVG: 1, svg: 1, IFRAME: 1, INPUT: 1, BUTTON: 1,
                SELECT: 1, TEXTAREA: 1, PICTURE: 1, OBJECT: 1, EMBED: 1 };
  function runBox(slot) {
    var l = 1e9, t = 1e9, r = -1e9, b = -1e9, any = false, read = 0;
    function take(q) {
      if (!q || !(q.width > 0 || q.height > 0)) return;
      any = true;
      if (q.left < l) l = q.left; if (q.top < t) t = q.top;
      if (q.right > r) r = q.right; if (q.bottom > b) b = q.bottom;
    }
    var rg = document.createRange();
    function visit(n) {
      if (read++ > 600 || !n) return;
      if (n.nodeType === 3) {
        if (n.nodeValue && /\S/.test(n.nodeValue)) { rg.selectNodeContents(n); take(rg.getBoundingClientRect()); }
        return;
      }
      if (n.nodeType !== 1) return;
      var o = chunkOf.get(n);
      if (o && o.tracked && o.node === n && o !== slot) return;       // another chunk's
      if (DRAWN[n.tagName]) { take(n.getBoundingClientRect()); return; }
      var kids = n.shadowRoot ? n.shadowRoot.childNodes : n.childNodes;
      for (var i = 0; i < kids.length && read <= 600; i++) visit(kids[i]);
    }
    var n = slot.node, k = 0;
    while (n && k++ < 400) {
      visit(n);
      if (n === slot.tail || !slot.tail || read > 600) break;
      n = n.nextSibling;
    }
    // The run's own elements' box, for the fallback and as a CLIP: a text
    // run clipped by its card (`text-overflow: ellipsis`) still measures its
    // full width, so archive.org's card chunks drew 258 px wide over 177 px
    // cards (2026-10-07: "Still overlay oversizing").
    var cl = 1e9, ct = 1e9, cr = -1e9, cb = -1e9, own = false;
    n = slot.node; k = 0;
    while (n && k++ < 400) {
      if (n.nodeType === 1 && n.getBoundingClientRect) {
        var q = n.getBoundingClientRect();
        if (q && q.width > 0 && q.height > 0) {
          own = true;
          if (q.left < cl) cl = q.left; if (q.top < ct) ct = q.top;
          if (q.right > cr) cr = q.right; if (q.bottom > cb) cb = q.bottom;
        }
      }
      if (n === slot.tail || !slot.tail) break;
      n = n.nextSibling;
    }
    if (!any) {
      if (!own) return null;
      return [cl, ct, cr - cl, cb - ct];
    }
    if (own) {
      var il = Math.max(l, cl), it2 = Math.max(t, ct), ir = Math.min(r, cr), ib = Math.min(b, cb);
      if (RT_PLANTS.yclip) {
        if (ir > il && ib > it2) { l = il; t = it2; r = ir; b = ib; }
      } else {
        // Across, always: a run clipped by its card (an ellipsis) is clipped
        // sideways. Down, only where the run's own box really HOLDS its text:
        // a container laid out at zero height with its children floated or
        // positioned outside it (RFC 9110's metadata <dl>, height 0) clipped
        // the text to a 6 px sliver above it -- 21 of 84 points on that page
        // drew their outline off the element under the pointer (2026-10-11).
        if (ir > il) { l = il; r = ir; }
        if (ib > it2 && (ib - it2) >= 0.5 * (b - t)) { t = it2; b = ib; }
      }
    }
    return [l, t, r - l, b - t];
  }
  function at(el) {
    var n = el, depth = 0;
    while (n && depth++ < 200) {
      var s = chunkOf.get(n);
      if (s && s.tracked && s.node === n && n.isConnected) {
        return { id: s.id, box: runBox(s), depth: depth - 1 };
      }
      var p = n.previousSibling, k = 0;
      while (p && k++ < 200) {
        s = chunkOf.get(p);
        if (s && s.tracked && s.node === p) {
          if (covers(s, n)) return { id: s.id, box: runBox(s), depth: depth - 1 };
          break;
        }
        p = p.previousSibling;
      }
      n = n.parentNode || n.host || null;
    }
    return null;
  }

  // The pointer, pushed: which chunk it is over and that chunk's box, at most
  // once a frame and only when either changes. A passive listener -- it
  // cannot cancel or alter the page's own handling.
  var lastHoverKey = '', lastHoverAt = 0, lastHoverTarget = null;
  // Every element stacked at a point, THROUGH open shadow roots: the
  // document's own `elementsFromPoint` stops at a shadow host, so on
  // archive.org the stack was one host whose chunk spans the app (2026-10-07:
  // "Archive overlays do exist but are oversized"). Descends into the root
  // under the point, deepest first.
  function stackAt(x, y) {
    var out = [], root = document, guard = 0;
    while (root && root.elementsFromPoint && guard++ < 16) {
      var here = root.elementsFromPoint(x, y) || [];
      out = here.concat(out);
      var top = here[0];
      if (!top || !top.shadowRoot || top.shadowRoot === root) break;
      root = top.shadowRoot;
    }
    return out;
  }
  function onPointer(ev) {
    if (!SAY) return;
    var target = (ev.composedPath && ev.composedPath()[0]) || ev.target;
    // On the event itself, no frame waited for; at most one every 8 ms, and
    // not at all while the pointer stays on the same element.
    var now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
    if (target === lastHoverTarget || now - lastHoverAt < 8) return;
    lastHoverAt = now;
    lastHoverTarget = target;
    var got = null;
    try { got = target && target.nodeType ? at(target) : null; } catch (e) { stats.errors++; }
    // The MOST SPECIFIC chunk under the pointer, not the topmost element's
    // (2026-10-06, johnwick.movie: its backgrounds are <img> elements -- one
    // 8,109 px tall -- and the topmost element under text was often one of
    // them, so the outline drew a chunk ten viewports high: "overlays are
    // quite large and span lots of text"). Every element stacked at the
    // point is asked, and the chunk with the smallest box wins. A read of
    // the peripheral kind, never the fold's.
    try {
      if (typeof ev.clientX === 'number' && document.elementsFromPoint) {
        var stack = stackAt(ev.clientX, ev.clientY);
        var best = got, area = got && got.box ? got.box[2] * got.box[3] : Infinity;
        for (var si = 0; si < stack.length && si < 12; si++) {
          var cand = at(stack[si]);
          if (!cand || !cand.box) continue;
          var a2 = cand.box[2] * cand.box[3];
          if (a2 > 0 && a2 < area) { best = cand; area = a2; }
        }
        got = best;
      }
    } catch (e) { stats.errors++; }
    var key = hoverKey(got, target);
    if (key === lastHoverKey) return;
    lastHoverKey = key;
    try { SAY(SIGNAL + 'hover ' + key); } catch (e) { stats.errors++; }
  }
  // `<id> <box>` -- and the hovered element's OWN address: the page's chunk
  // can be coarser than the store's (a shadow-DOM result list is one in-page
  // chunk and six stored cards), and from the chunk id alone the host
  // resolved every card to the page header's stored chunk (2026-10-11, P-B7).
  function hoverKey(got, target) {
    if (!got || !got.box) return '-';
    var key = got.id + ' ' + got.box.map(Math.round).join(',');
    var addr = '';
    try { addr = hoverAddress(target); } catch (e) { stats.errors++; }
    return addr ? key + ' ' + addr : key;
  }
  // The composed-tree address of an element, spelled as the fold spells it
  // (`stepFor`): `tag[k]` for the k-th same-tag sibling (k > 1), and an
  // explicit `#shadow-root` step at a boundary. Read-only; a text node is
  // addressed by its element.
  //
  // A SLOTTED element's parent in the fold is the slot that draws it (the
  // last of a chain of slots, as `assignedNodes({flatten: true})` reads),
  // and its ordinal counts among that slot's assigned nodes -- not its light
  // parent and light siblings. Walking `parentNode` spelled a second address
  // for the same element: archive.org's search tiles sit in light children
  // of `tab-manager`, drawn through a slot in its shadow root, and every
  // hover there named a path the trie did not hold (2026-10-18, PLUGIN_GOAL
  // 149). Planted (run time): `plants.lightpath`.
  function hoverAddress(node) {
    if (node && node.nodeType === 3) node = node.parentNode;
    var steps = [], guard = 0;
    while (node && node.nodeType === 1 && guard++ < 200) {
      var top = null, sl = RT_PLANTS.lightpath ? null : node.assignedSlot;
      while (sl && guard++ < 200) { top = sl; sl = sl.assignedSlot; }
      if (top) {
        var an = null, j, kk = 1;
        try { an = top.assignedNodes({ flatten: true }); } catch (e) { stats.errors++; an = null; }
        if (an && an.length) {
          for (j = 0; j < an.length && an[j] !== node; j++) {
            if (an[j].nodeType === 1 && an[j].tagName === node.tagName) kk++;
          }
          var tg = node.tagName.toLowerCase();
          steps.unshift(kk > 1 ? tg + '[' + kk + ']' : tg);
          node = top;
          continue;
        }
      }
      var tag = node.tagName.toLowerCase(), k = 1, s = node.previousElementSibling;
      while (s) { if (s.tagName === node.tagName) k++; s = s.previousElementSibling; }
      steps.unshift(k > 1 ? tag + '[' + k + ']' : tag);
      var p = node.parentNode;
      if (p && p.nodeType === 11 && p.host) { steps.unshift('#shadow-root'); node = p.host; }
      else node = p;
    }
    return steps.length ? '/' + steps.join('/') : '';
  }
  function onPointerOut(ev) {
    if (!SAY || ev.relatedTarget) return;
    lastHoverKey = '-';
    // The pointer left the page: coming back to the SAME element is a new
    // hover. Kept, the dedupe swallowed it and nothing was outlined
    // (2026-10-11, P-B7's second arm).
    lastHoverTarget = null;
    try { SAY(SIGNAL + 'hover -'); } catch (e) { stats.errors++; }
  }
  // A scroll moves every box and mutates nothing, so no drain follows it and
  // the overlay stayed where the page used to be (2026-10-06: "Scrolls on
  // this page leave stale billboards"). Passive, capturing (an inner
  // scroller's scroll does not bubble), at most one every 8 ms: the host is
  // told to re-measure what it shows, and the hovered chunk's box is sent
  // again from its new place. Nothing is written into the page.
  var lastScrollAt = 0, scrollTrail = null;
  function onScroll() {
    if (!SAY) return;
    var now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
    if (now - lastScrollAt < 8) {
      // Throttled, with a TRAILING call: the last position after a smooth
      // scroll settles is the one the overlay must end on.
      if (scrollTrail === null) scrollTrail = setTimeout(function () { scrollTrail = null; onScroll(); }, 16);
      return;
    }
    lastScrollAt = now;
    try { SAY(SIGNAL + 'scroll'); } catch (e) { stats.errors++; }
    if (lastHoverTarget && lastHoverTarget.isConnected) {
      var got = null;
      try { got = at(lastHoverTarget); } catch (e) { stats.errors++; }
      var key = hoverKey(got, lastHoverTarget);
      if (key !== lastHoverKey) {
        lastHoverKey = key;
        try { SAY(SIGNAL + 'hover ' + key); } catch (e) { stats.errors++; }
      }
    }
  }
  if (SIGNAL && typeof document !== 'undefined' && document.addEventListener) {
    try {
      document.addEventListener('pointermove', onPointer, { passive: true, capture: true });
      document.addEventListener('pointerout', onPointerOut, { passive: true, capture: true });
      document.addEventListener('scroll', onScroll, { passive: true, capture: true });
      document.addEventListener('wheel', onScroll, { passive: true, capture: true });
      // A style or class change can move every box without changing any
      // chunk: a smooth-scroll library translates its container instead of
      // scrolling (johnwick.movie: scrollY 0 with the content 3,500 px up),
      // and no scroll event fires. Its own observer, so the fold's stays
      // filtered to content attributes; it only tells the host to re-measure.
      if (typeof MutationObserver === 'function' && document.documentElement) {
        new MutationObserver(function () { onScroll(); }).observe(document.documentElement,
          { attributes: true, subtree: true, attributeFilter: ['style', 'class'] });
        stats.observers++;
      }
    } catch (e) { stats.errors++; }
  }

  // ---- the style peripheral --------------------------------------------
  //
  // Layout facts, read on demand, for a caller-supplied set of paths. This
  // is deliberately NOT part of the fold: the fold reads no layout, which is
  // what keeps it O(delta), and computing style during it would make every
  // mutation pay for geometry nobody asked for. What comes back is kept
  // beside the trie, never in it.
  //
  // Geometry rather than CSS. Which elements form a row is answerable from
  // where they actually are -- overlapping vertically, disjoint
  // horizontally -- and that is one measurement. Reading `display:flex` and
  // `flex-direction` and `grid-template-columns` and float and inline-block
  // is a pile of rules that approximates the same answer and disagrees with
  // it whenever a site does something unusual. The browser already solved
  // this; the rect is the solution.
  function styles(paths) {
    var out = [];
    for (var i = 0; i < paths.length; i++) {
      var el = resolvePath(paths[i]);
      if (el && el.nodeType === 3) el = el.parentNode;
      if (!el || el.nodeType !== 1) { out.push(null); continue; }
      try {
        var r = el.getBoundingClientRect();
        var cs = window.getComputedStyle(el);
        // An element with no box of its own is not an element with nothing
        // in it.
        //
        // `display: contents` generates no box -- that is its definition --
        // and its children lay out in its parent's flow, so the rect comes
        // back 0x0 while the text is plainly on the screen. It is also the
        // UA default for `<slot>`, which makes this the normal shape of a
        // web component rather than an edge case: on salesforce.com, where
        // 194 shadow hosts carry two thirds of the page's text, treating
        // "no rect" as "not visible" removed a fifth of the drawn content
        // from the wireframe.
        //
        // A range over the element's own contents measures what was actually
        // laid out, which is the thing being asked for. A genuinely empty or
        // `display:none` element still measures 0x0 and still reads as not
        // visible, so nothing that should be hidden is admitted by this.
        if (r.width === 0 && r.height === 0
            && cs.display !== 'none' && cs.visibility !== 'hidden') {
          // A slot's drawn content is what is *assigned* to it, not what it
          // contains. `selectNodeContents` on a filled <slot> selects its
          // fallback children -- the ones the browser does not draw -- and
          // measures 0x0, so a slotted affordance had no geometry and the
          // wireframe dropped it: on lit.dev the consent button "Ok, got it"
          // was rendered in markdown, verified absent from the drawing, and
          // its owner measured 0x0 with `display: contents`.
          //
          // The same composed-tree rule the fold obeys, applied to geometry.
          try {
            if (el.tagName === 'SLOT' && el.assignedNodes) {
              var kids = el.assignedNodes({flatten: true}) || [];
              var box = null, j, kr;
              for (j = 0; j < kids.length; j++) {
                kr = null;
                if (kids[j].nodeType === 1) {
                  kr = kids[j].getBoundingClientRect();
                } else if (kids[j].nodeType === 3) {
                  var tr = document.createRange();
                  tr.selectNodeContents(kids[j]);
                  kr = tr.getBoundingClientRect();
                  tr.detach && tr.detach();
                }
                if (!kr || (kr.width === 0 && kr.height === 0)) continue;
                box = box ? {
                  left: Math.min(box.left, kr.left),
                  top: Math.min(box.top, kr.top),
                  right: Math.max(box.right, kr.right),
                  bottom: Math.max(box.bottom, kr.bottom)
                } : {left: kr.left, top: kr.top,
                     right: kr.right, bottom: kr.bottom};
              }
              if (box) {
                r = {left: box.left, top: box.top,
                     width: box.right - box.left,
                     height: box.bottom - box.top};
              }
            }
            if (r.width === 0 && r.height === 0) {
              var range = document.createRange();
              range.selectNodeContents(el);
              var rr = range.getBoundingClientRect();
              if (rr && rr.width > 0 && rr.height > 0) r = rr;
              range.detach && range.detach();
            }
          } catch (e) { /* keep the empty rect */ }
        }
        var weight = parseInt(cs.fontWeight, 10) || 400;
        var size = parseFloat(cs.fontSize) || 16;
        out.push({
          x: Math.round(r.left + window.scrollX),
          y: Math.round(r.top + window.scrollY),
          w: Math.round(r.width),
          h: Math.round(r.height),
          d: cs.display,
          // Emphasis, reduced to what a terminal can actually show.
          b: weight >= 600 ? 1 : 0,
          i: cs.fontStyle === 'italic' ? 1 : 0,
          u: (cs.textDecorationLine || cs.textDecoration || '')
               .indexOf('underline') >= 0 ? 1 : 0,
          s: Math.round(size),
          a: cs.textAlign,
          // A box a reader can see: something drew a border or a fill.
          box: ((parseFloat(cs.borderTopWidth) || 0) > 0
                || (parseFloat(cs.borderLeftWidth) || 0) > 0
                || (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)'
                    && cs.backgroundColor !== 'transparent')) ? 1 : 0,
          vis: (cs.visibility !== 'hidden' && cs.display !== 'none'
                && r.width > 0 && r.height > 0) ? 1 : 0
        });
      } catch (e) { out.push(null); }
    }
    return { styles: out, vw: window.innerWidth || 0,
             vh: window.innerHeight || 0,
             doc: (document.documentElement
                   && document.documentElement.scrollWidth) || 0 };
  }

  return {
    drain: drain,
    flush: flush,
    step: step,
    perform: perform,
    // `perform` accepts `{xpath}` targets. A handle booted by an earlier
    // build lacks this, and the host says "reload the page" rather than
    // reporting every target unresolved.
    xpathTicks: true,
    styles: styles,
    boxes: boxes,
    at: at,
    plants: RT_PLANTS,
    // Read-only: which chunk slot an element maps to, for instruments that
    // ask why `at` answers what it does (scripts/merge_at_probe.py).
    // The receiver lost what it was sent: send everything again, dictionary
    // and shapes from the start, every chunk as if new (see `EMIT_GEN`).
    resync: function () {
      dictSent = 0; shapesSent = 0; EMIT_GEN++;
      stats.resyncs = (stats.resyncs || 0) + 1;
      return EMIT_GEN;
    },
    slotOf: function (el) {
      var s = el ? chunkOf.get(el) : null;
      return s ? { id: s.id, tracked: !!s.tracked, own: s.node === el, tail: !!s.tail,
                   connected: !!(s.node && s.node.isConnected) } : null;
    },
    pictures: pictures,
    resolve: function (path) { return !!resolvePath(path); },
    // The address a hover on `el` reports (read-only), so a check can hold it
    // against the fold's own address for the same element.
    hoverAddress: function (el) { return hoverAddress(el); },
    // The node an address names, through shadow roots and slots -- read-only,
    // for instruments that check what the trie accounts for (2026-10-07:
    // media coverage read archive.org's shadow-DOM pictures as 0/115 because
    // `resolve` answers yes/no, not the node).
    node: function (xpath) { return resolveXPath(String(xpath || '')); },

    // Does each of these addresses still name a node?
    //
    // The receiver cannot answer this. It holds addresses and the values it
    // was told to put there; when a shift moves content out of an address,
    // nothing says whether the address is now empty or holding somebody
    // else's content, and guessing has gone wrong twice -- once in the trie
    // and once in this file's own chunk bookkeeping -- each time by deleting
    // content the page still had.
    //
    // Only the page knows, and only from in here: a composed-tree path
    // crosses shadow boundaries, which no XPath engine will do.
    //
    // Takes the spelling the receiver holds (`sensing._xpath`) rather than
    // the interned step arrays, because that is what it has, and answers in
    // one round trip because the caller asks about every orphaned address at
    // once.
    alive: function (paths) {
      var out = [], i;
      for (i = 0; i < (paths || []).length; i++) {
        out.push(!!resolveXPath(String(paths[i] || '')));
      }
      return out;
    },
    // One call that scrolls and reports. Two calls pay the round-trip toll
    // twice — measured at 1.46 ms each on this setup, against 0.05-0.25 ms
    // of actual in-page work — so the boundary, not the algorithm, is what
    // a pass mostly costs.
    pass: function (px) { var a = step(px); var b = drain(); return [a, b]; },
    settled: function () { return timer === null; },
    stats: function () { return stats; }
  };
})
