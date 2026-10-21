/*
 * wfh_chunk_engine.js — In-browser content tagger + bottom-up chunker + delta streamer.
 *
 * Boot sequence (one-time IIFE):
 *   1. Read window._wfhCharBudget and window._wfhDebounceMs.
 *   2. Walk document.documentElement once (single-pass post-order DFS) and
 *      emit chunks bottom-up, each chunk a maximal subtree whose
 *      content-budget fits HARD_CHAR_LIMIT.
 *   3. Attach a MutationObserver to *each emitted chunk's root* with
 *      attributeFilter scoped to URL/text/media attrs. Mutations inside
 *      a chunk re-chunk THAT subtree only.
 *   4. Attach a single global MutationObserver on documentElement that
 *      detects mutations OUTSIDE any existing chunk (newly-injected
 *      content) and queues a targeted re-chunk on the highest unclaimed
 *      ancestor.
 *   5. After every batch of mutations settles (debounce window),
 *      processDirty() drains the dirty-set and emits delta events.
 *
 * Public API on window._wfhEngine:
 *   getDeltaQueue()  → array of {type, chunkId, ...} events accumulated
 *                      since the last call; clears the queue.
 *   isSettled()      → true when no debounce timer is pending.
 *   getStats()       → instrumentation counters (chunkSubtreeRuns,
 *                      lastLeafCount, totalChunks, bodyTextLen,
 *                      pendingDirty, charBudget, errors).
 *
 * Output schema (camelCase by JS convention; Python normalises at
 * _apply_js_deltas to snake_case):
 *   chunk_added / chunk_replaced:
 *     {type, chunkId, pattern, memberXpaths[], sampleIds[], renderedText,
 *      contentFieldsFull{xpath:attr → string}, charCount, htmlRaw,
 *      commutationCount, representative_xpath}
 *   chunk_removed: {type, chunkId}
 */
(function() {
    if (window._wfhEngine) return;

    // -----------------------------------------------------------------
    // Tunables (overridable via window globals before injection)
    // -----------------------------------------------------------------
    const HARD_CHAR_LIMIT = (typeof window._wfhCharBudget === 'number' && window._wfhCharBudget > 0)
        ? window._wfhCharBudget
        : 2048;
    const DEBOUNCE_MS = (typeof window._wfhDebounceMs === 'number' && window._wfhDebounceMs > 0)
        ? window._wfhDebounceMs
        : 80;
    const MIN_CHUNK_CHARS = 8;
    // Cap how often the global MO can run a full re-walk pass within one
    // settle window — avoids feedback loops when the page is animating.
    const MAX_PASSES_PER_SETTLE = 4;

    // -----------------------------------------------------------------
    // Tag / attribute classification
    // -----------------------------------------------------------------
    const SKIP_TAGS = new Set([
        'head', 'style', 'script', 'noscript', 'meta', 'link',
        'svg', 'path', 'defs', 'use', 'title', 'br', 'hr',
    ]);
    const VOID_TAGS = new Set([
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    ]);
    // Region-anchor tags. Above the nearest anchor in an xpath, segments
    // are kept verbatim (with their indices) so cards in the sidebar
    // never collide with cards in main. Below the anchor, indices are
    // stripped so all repeated card instances share one pattern.
    const ANCHOR_TAGS = new Set([
        'main', 'nav', 'aside', 'header', 'footer', 'article', 'section', 'form',
    ]);
    const SKIP_ATTRS = new Set([
        'style', 'class', 'id', 'tabindex', 'role',
        'width', 'height', 'viewbox', 'd', 'points', 'fill', 'stroke',
        'xmlns', 'xmlns:xlink', 'xml:space', 'preserveaspectratio',
    ]);
    // Attrs that contribute to text/budget AND are kept as content_fields
    const TEXT_ATTRS = new Set([
        'alt', 'title', 'aria-label', 'aria-describedby', 'aria-labelledby',
        'aria-roledescription', 'aria-valuetext', 'placeholder', 'label',
        'summary', 'caption', 'datetime', 'data-title', 'data-tooltip',
        'data-caption', 'data-description', 'data-text', 'data-name',
        'abbr', 'value',
    ]);
    // Attrs that are URL-like — kept as fields, but do NOT contribute to
    // the prose-budget (so a long src= can't single-handedly bust the
    // chunk budget).
    const URL_ATTRS = new Set([
        'href', 'src', 'srcset', 'data-src', 'data-original', 'data-image',
        'poster', 'cite', 'action', 'data-href',
    ]);
    // Attribute filter for per-chunk MOs. Limited to what we actually
    // surface so every random class/style flip doesn't re-chunk.
    const MO_ATTR_FILTER = [
        'href', 'src', 'srcset', 'data-src', 'data-original', 'data-image',
        'alt', 'title', 'aria-label', 'aria-describedby', 'placeholder',
        'datetime',
    ];

    // -----------------------------------------------------------------
    // Engine state
    // -----------------------------------------------------------------
    /** @type {Map<string, object>}        chunkId → chunk record (with element ref) */
    const chunksById = new Map();
    /** @type {Map<string, Set<string>>}    pattern → Set<chunkId>                   */
    const chunksByPattern = new Map();
    /** @type {Map<string, string>}        absoluteXpath → owning chunkId            */
    const claimedXpaths = new Map();
    /** @type {Map<Element, string>}        chunk root element → chunkId             */
    const elementToChunkId = new Map();
    /** @type {Map<string, MutationObserver>}                                       */
    const perChunkObservers = new Map();
    /** @type {Set<Element>}                pending re-chunk roots                   */
    const dirtySubtrees = new Set();
    /** @type {Array<object>}               outgoing delta events                    */
    let deltaQueue = [];

    let moTimer = null;
    let isSettled = true;
    let passesThisSettle = 0;

    const stats = {
        chunkSubtreeRuns: 0,
        lastLeafCount: 0,
        totalChunks: 0,
        bodyTextLen: 0,
        pendingDirty: 0,
        charBudget: HARD_CHAR_LIMIT,
        errors: [],
    };

    function logErr(where, e) {
        try {
            stats.errors.push({where, msg: String(e && e.message || e), at: Date.now()});
            if (stats.errors.length > 16) stats.errors.shift();
        } catch (_) {}
    }

    // -----------------------------------------------------------------
    // Tree helpers — both light DOM and shadow DOM aware.
    //
    // The legacy EXTRACT_UNIFIED_JS extractor recursed into el.shadowRoot
    // and prefixed shadow-rooted segments with `#shadow-root/`. This engine
    // ports that convention so xpaths remain stable across light/shadow
    // boundaries: a card rendered inside <app-root>'s shadow root gets a
    // member xpath like `/html/body[1]/app-root[1]/#shadow-root/.../article[1]`,
    // never confusable with a light-DOM-only sibling at the same depth.
    // -----------------------------------------------------------------
    function eachChildElement(el, callback) {
        if (el.shadowRoot) {
            const sr = el.shadowRoot;
            for (let i = 0; i < sr.children.length; i++) {
                callback(sr.children[i], true);
            }
        }
        for (let i = 0; i < el.children.length; i++) {
            callback(el.children[i], false);
        }
    }

    // Per-pass xpath cache. Cleared at the start of every rechunkSubtree
    // call so cached entries can never disagree with the live DOM (we run
    // synchronously inside a settle window — no mutations during the pass).
    // Without this cache, a 1,000-node subtree paid ~10× the cost of
    // walking parentElement to root on every visit (extractElementFields,
    // collectMemberXpaths, global-MO callback, etc. each call it).
    let _xpathCache = new WeakMap();

    function getAbsoluteXpath(el) {
        if (!el || el.nodeType !== 1) return '';
        if (el === document.documentElement) return '/html';
        const cached = _xpathCache.get(el);
        if (cached !== undefined) return cached;
        const segs = [];
        let cur = el;
        while (cur && cur.nodeType === 1 && cur !== document.documentElement) {
            // If we hit a cached ancestor mid-walk, prepend its xpath and stop.
            const cachedAnc = _xpathCache.get(cur);
            if (cachedAnc !== undefined) {
                const result = cachedAnc + (segs.length ? '/' + segs.join('/') : '');
                _xpathCache.set(el, result);
                return result;
            }
            const tag = cur.tagName.toLowerCase();
            let idx = 1;
            let sib = cur.previousElementSibling;
            while (sib) {
                if (sib.tagName.toLowerCase() === tag) idx++;
                sib = sib.previousElementSibling;
            }
            segs.unshift(tag + '[' + idx + ']');
            const parent = cur.parentElement;
            if (parent) { cur = parent; continue; }
            const root = cur.getRootNode && cur.getRootNode();
            if (root && root.host) {
                segs.unshift('#shadow-root');
                cur = root.host;
                continue;
            }
            break;
        }
        const result = '/html/' + segs.join('/');
        _xpathCache.set(el, result);
        return result;
    }

    /**
     * Region-anchored generalized xpath: keep segments at and above the
     * deepest anchor verbatim (with indices), strip indices below.
     *   /html/body[1]/main[1]/div[3]/section[1]/article[2]/h2[1]
     *   → anchor=section → /html/body[1]/main[1]/div[3]/section[1]/article/h2
     */
    function generalizedXpath(absXpath) {
        const parts = absXpath.split('/').filter(Boolean);
        let anchorIdx = -1;
        for (let i = parts.length - 1; i >= 0; i--) {
            const tag = parts[i].replace(/\[\d+\]$/, '');
            if (ANCHOR_TAGS.has(tag)) { anchorIdx = i; break; }
        }
        const out = [];
        for (let i = 0; i < parts.length; i++) {
            if (i <= anchorIdx) out.push(parts[i]);                // verbatim
            else out.push(parts[i].replace(/\[\d+\]$/, ''));        // strip index
        }
        return '/' + out.join('/');
    }

    function getRelXpath(absXpath, baseAbsXpath) {
        if (absXpath === baseAbsXpath) return '.';
        if (absXpath.indexOf(baseAbsXpath + '/') === 0) {
            return absXpath.slice(baseAbsXpath.length).replace(/\[\d+\]/g, '');
        }
        return absXpath;
    }

    function djb2(s) {
        let h = 5381;
        for (let i = 0; i < s.length; i++) {
            h = ((h << 5) + h + s.charCodeAt(i)) & 0xFFFFFFFF;
        }
        return Math.abs(h);
    }

    /**
     * chunk_id is INSTANCE-unique: hashed on absoluteXpath, not pattern.
     *
     * Originally hashed on pattern alone, which collided whenever a card
     * had sibling `<p>` elements: both shared the same generalized pattern
     * (`/anchor/.../div/p`), the second emit clobbered the first via
     * chunk_replaced, and we lost 470+ chunks of content per scan. Pattern
     * is now metadata for grouping/commutation; identity is the xpath.
     */
    function generateChunkId(url, absXpath) {
        return 'c_' + djb2(url + '|' + absXpath).toString(16);
    }

    function clip(s, n) {
        s = (s == null) ? '' : String(s);
        return s.length <= n ? s : s.slice(0, n);
    }

    // -----------------------------------------------------------------
    // Field extraction
    // -----------------------------------------------------------------
    function isSkippedTag(tag) {
        return SKIP_TAGS.has(tag);
    }

    function extractDirectText(el) {
        let buf = '';
        for (let cn = el.firstChild; cn; cn = cn.nextSibling) {
            if (cn.nodeType === 3) {
                const t = cn.nodeValue;
                if (t && t.trim()) buf += (buf ? ' ' : '') + t.trim();
            }
        }
        return buf;
    }

    // -----------------------------------------------------------------
    // Content-vs-noise classification for attribute values.
    //
    // Without this filter the audit fills up with rows like
    // ``@aria-disabled=false``, ``@aria-haspopup=false``,
    // ``@target=_blank``, ``@rel=nofollow``, ``@items-per-row=3``,
    // ``@lockup=true``, ``@force-new-state=true``. None of those are
    // human-readable content — they're framework state for Angular/Lit
    // component bindings. We drop them by default and only keep an
    // unclassified attr when:
    //   1. The whole value looks URL-like (http://, //, data:, blob:,
    //      or root-absolute path), OR
    //   2. It contains whitespace AND has at least one alphabetic
    //      character (likely a multi-word prose snippet that some
    //      site shoves into data-* / role-* attrs as a label), OR
    //   3. It's long (≥ 24 chars) AND not a pure number / hex /
    //      boolean / single token.
    // -----------------------------------------------------------------
    const BOOLEAN_OR_TRIVIAL = new Set([
        'true', 'false', 'auto', 'none', 'null', 'undefined', '',
        '0', '1', '-1', 'yes', 'no', 'on', 'off',
        '_blank', '_self', '_parent', '_top',
        'nofollow', 'noopener', 'noreferrer', 'sponsored', 'ugc',
        'application/json', 'text/html', 'text/plain',
        'button', 'link', 'menuitem', 'tab',
        'left', 'right', 'center', 'top', 'bottom',
        'horizontal', 'vertical', 'fill', 'fixed', 'static',
    ]);
    const URL_LIKE_RE = /^(?:https?:\/\/|\/\/|data:|blob:|mailto:|tel:|\/[^\s]{2,})/i;
    const HEX_OR_HASH_RE = /^[#0-9a-f-]+$/i;

    function looksLikeContent(val) {
        if (!val) return false;
        const v = val.trim();
        if (!v) return false;
        const low = v.toLowerCase();
        if (BOOLEAN_OR_TRIVIAL.has(low)) return false;
        if (URL_LIKE_RE.test(v)) return true;
        // Multi-word strings with at least one letter look like prose.
        if (/\s/.test(v) && /[a-z]/i.test(v)) return true;
        // Single-token short stuff: drop. Single-token long stuff (e.g.,
        // a slug or hash id): keep if it contains both letters and
        // digits / punctuation that hint at human meaning.
        if (v.length >= 24 && /[a-z]/i.test(v) && !HEX_OR_HASH_RE.test(v)) return true;
        return false;
    }

    /**
     * Compute fields + budget for a SINGLE element relative to baseAbsXpath.
     * Returns null when the element is skip-tagged.
     */
    function extractElementFields(el, baseAbsXpath) {
        const tag = el.tagName.toLowerCase();
        if (isSkippedTag(tag)) return null;
        const absXpath = getAbsoluteXpath(el);
        const rel = getRelXpath(absXpath, baseAbsXpath);
        const fields = {};
        let budget = 0;

        // Direct text node — keyed under <rel>/text()
        const direct = extractDirectText(el);
        if (direct) {
            fields[rel + '/text()'] = clip(direct, 240);
            budget += direct.length;
        }

        // Attributes
        for (let i = 0; i < el.attributes.length; i++) {
            const a = el.attributes[i];
            const name = a.name;
            if (SKIP_ATTRS.has(name) || name.indexOf('data-wfh') === 0) continue;
            const val = a.value;
            if (!val) continue;
            const key = rel + '/@' + name;
            if (URL_ATTRS.has(name)) {
                fields[key] = clip(val, 320);
            } else if (TEXT_ATTRS.has(name)) {
                // Drop empty/boolean text-attr values (e.g. title="" or
                // aria-label="true") so they don't pollute the table.
                if (!looksLikeContent(val)) continue;
                fields[key] = clip(val, 200);
                budget += val.length;
            } else {
                // Unclassified attr — keep ONLY if value looks like real
                // content (URL, multi-word prose, or long meaningful slug).
                // This is what was filling the audit with rows like
                // @aria-disabled=false, @target=_blank, @lockup=true.
                if (!looksLikeContent(val)) continue;
                // Whether to treat as URL-styled or text-styled in the
                // audit table — drives the link cell class.
                const isUrl = URL_LIKE_RE.test(val.trim());
                fields[key] = clip(val, isUrl ? 320 : 200);
            }
        }
        return { fields, budget, absXpath, tag };
    }

    /**
     * Walk a subtree once, accumulating {fields, budget, hasContent}.
     * Descends through both light-DOM children AND el.shadowRoot.children,
     * so component-tree pages (Angular/Lit/web-components) are visible.
     * Skip-tag descendants short-circuit. Counts every visited element.
     */
    function walkSubtree(rootEl, baseAbsXpath, out) {
        const own = extractElementFields(rootEl, baseAbsXpath);
        if (!own) { return false; }
        let hasOwnContent = Object.keys(own.fields).length > 0;
        if (hasOwnContent) {
            for (const k in own.fields) out.fields[k] = own.fields[k];
            out.budget += own.budget;
        }
        let hasDescContent = false;
        eachChildElement(rootEl, function(child) {
            if (walkSubtree(child, baseAbsXpath, out)) {
                hasDescContent = true;
            }
        });
        return hasOwnContent || hasDescContent;
    }

    function summariseSubtree(rootEl) {
        const baseAbsXpath = getAbsoluteXpath(rootEl);
        const out = { fields: {}, budget: 0 };
        const hasContent = walkSubtree(rootEl, baseAbsXpath, out);
        return Object.assign(out, { absXpath: baseAbsXpath, hasContent });
    }

    function collectMemberXpaths(rootEl) {
        const members = [];
        function rec(el) {
            const t = el.tagName.toLowerCase();
            if (isSkippedTag(t)) return;
            members.push(getAbsoluteXpath(el));
            eachChildElement(el, rec);
        }
        rec(rootEl);
        return members;
    }

    function buildChunkHtml(rootEl) {
        function ser(el) {
            const tag = el.tagName.toLowerCase();
            if (isSkippedTag(tag)) return '';
            let attrStr = '';
            for (let i = 0; i < el.attributes.length; i++) {
                const a = el.attributes[i];
                if (SKIP_ATTRS.has(a.name) || a.name.indexOf('data-wfh') === 0) continue;
                attrStr += ' ' + a.name + '="' + a.value.replace(/"/g, '&quot;') + '"';
            }
            if (VOID_TAGS.has(tag)) return '<' + tag + attrStr + '/>';
            let inner = '';
            // Shadow DOM is serialised first via declarative <template
            // shadowrootmode>, mirroring the legacy serializer so the
            // saved htmlRaw round-trips into Python's ShadowDOM parser.
            if (el.shadowRoot) {
                inner += '<template shadowrootmode="' + el.shadowRoot.mode + '">';
                for (let i = 0; i < el.shadowRoot.children.length; i++) {
                    inner += ser(el.shadowRoot.children[i]);
                }
                inner += '</template>';
            }
            for (let cn = el.firstChild; cn; cn = cn.nextSibling) {
                if (cn.nodeType === 3) {
                    inner += cn.textContent.replace(/&/g, '&amp;')
                                          .replace(/</g, '&lt;')
                                          .replace(/>/g, '&gt;');
                } else if (cn.nodeType === 1) {
                    inner += ser(cn);
                }
            }
            return '<' + tag + attrStr + '>' + inner + '</' + tag + '>';
        }
        return ser(rootEl);
    }

    function renderTextFromFields(fields) {
        const parts = [];
        for (const k in fields) {
            if (k.endsWith('/text()') || k === 'text()' || k === '/text()' || k === './text()') {
                parts.push(fields[k]);
            }
        }
        return parts.join(' ');
    }

    // -----------------------------------------------------------------
    // Anchor fusion — semantic-anchor tags get a 2× budget. Without
    // this, a DDG / Google / Tarot.com search result whose <article>
    // is ~400 chars splits into 4 sibling div-chunks under the user's
    // 256-char budget. With fusion, the article emits as ONE chunk
    // for the whole search result (title + link + snippet + image
    // all live in one record). The hard limit is still respected
    // outside semantic anchors so non-card pages don't blow up.
    // -----------------------------------------------------------------
    const ANCHOR_FUSION_TAGS = new Set([
        'article', 'section', 'aside',
        'li',                    // list items in <ol>/<ul> are typically one result
        'tr',                    // table rows
        'dt', 'dd',              // definition list items
        'figure', 'blockquote',  // standalone media / quote units
    ]);
    // 4× allows a typical DDG / Google search result (~600-800 chars
    // including title + snippet + URL + breadcrumb + favicon attr +
    // "block this site" sub-block) to live in one card-shaped chunk.
    // Smaller multipliers split DDG results across 3-4 sibling div
    // chunks (one for the title link, one for the snippet, one for
    // the breadcrumb, one for the "block this site" affordance) which
    // is exactly the over-separation the user reported. Articles
    // bigger than 4× (e.g. archive.org's rich-sitelinks card with
    // nested ul lists, ~1700 chars) still split — that's correct,
    // they're genuinely too big to live in one chunk under a 256-
    // char user budget.
    const ANCHOR_FUSION_MULTIPLIER = 4.0;

    function budgetFor(el) {
        const tag = el.tagName.toLowerCase();
        if (ANCHOR_FUSION_TAGS.has(tag)) {
            return Math.floor(HARD_CHAR_LIMIT * ANCHOR_FUSION_MULTIPLIER);
        }
        return HARD_CHAR_LIMIT;
    }

    // -----------------------------------------------------------------
    // Top-down chunk discovery on a subtree.
    //
    // For each candidate root in DFS order, summarise its subtree.
    //   - If no content → skip.
    //   - If subtree budget ≤ budgetFor(rootEl) → emit as chunk root
    //     (and stop descending into it). Anchor tags use a 2× budget.
    //   - Otherwise → recurse into children to find smaller chunks.
    //
    // Top-down with monotonically-increasing-up budgets is equivalent
    // to bottom-up (walk-up-from-leaf-until-bust) but cheaper to
    // implement: every element is visited at most twice.
    // -----------------------------------------------------------------
    function findChunkRoots(rootEl, results) {
        if (!rootEl || rootEl.nodeType !== 1) return;
        const tag = rootEl.tagName.toLowerCase();
        if (isSkippedTag(tag)) return;

        const summary = summariseSubtree(rootEl);
        if (!summary.hasContent) return;

        if (summary.budget <= budgetFor(rootEl)) {
            // This whole subtree fits — but only emit if it has real
            // content (not just structural noise).
            if (summary.budget < MIN_CHUNK_CHARS && Object.keys(summary.fields).length < 2) return;
            results.push({ element: rootEl, summary });
            return;
        }

        // Too big — descend into children, including any shadow-root
        // children. Without the shadow descent, custom-element hosts
        // (Angular <app-root>, Lit components, etc.) appear as a single
        // oversized non-emitting subtree because their visible content
        // lives behind shadowRoot rather than in light children.
        eachChildElement(rootEl, function(child) {
            findChunkRoots(child, results);
        });
    }

    // -----------------------------------------------------------------
    // Per-chunk MutationObserver
    //
    // `subtree:true` does NOT pierce shadow boundaries — observing on
    // the host element only fires for light-DOM mutations. We attach a
    // SECOND observer to the shadowRoot when present so changes inside
    // the component (the Angular/Lit case) actually trigger a re-chunk.
    // -----------------------------------------------------------------
    function attachChunkObserver(chunk) {
        if (!chunk.element || !chunk.element.isConnected) return;
        const callback = function(mutations) {
            dirtySubtrees.add(chunk.element);
            scheduleSettle();
        };
        const observers = [];
        try {
            const lightObs = new MutationObserver(callback);
            lightObs.observe(chunk.element, {
                childList: true,
                subtree: true,
                characterData: true,
                attributes: true,
                attributeFilter: MO_ATTR_FILTER,
            });
            observers.push(lightObs);
            // Walk the chunk's subtree and observe every nested shadow
            // root the same way. Cheap: most chunks have at most one host.
            const stack = [chunk.element];
            while (stack.length) {
                const n = stack.pop();
                if (!n || n.nodeType !== 1) continue;
                if (n.shadowRoot) {
                    const shadowObs = new MutationObserver(callback);
                    shadowObs.observe(n.shadowRoot, {
                        childList: true,
                        subtree: true,
                        characterData: true,
                        attributes: true,
                        attributeFilter: MO_ATTR_FILTER,
                    });
                    observers.push(shadowObs);
                    for (let i = 0; i < n.shadowRoot.children.length; i++) {
                        stack.push(n.shadowRoot.children[i]);
                    }
                }
                for (let i = 0; i < n.children.length; i++) stack.push(n.children[i]);
            }
            perChunkObservers.set(chunk.chunkId, observers);
        } catch (e) {
            logErr('attachChunkObserver', e);
        }
    }

    function detachChunkObserver(chunkId) {
        const observers = perChunkObservers.get(chunkId);
        if (!observers) return;
        if (Array.isArray(observers)) {
            for (const o of observers) { try { o.disconnect(); } catch (_) {} }
        } else {
            try { observers.disconnect(); } catch (_) {}
        }
        perChunkObservers.delete(chunkId);
    }

    // -----------------------------------------------------------------
    // Chunk ledger ops
    // -----------------------------------------------------------------
    // -----------------------------------------------------------------
    // Specialized detector vocabularies (search inputs + pagination
    // controls), ported from backend/dom/web_distiller_freq.py:
    //   - SearchInputCollector.VOCABULARY
    //   - SearchInputCollector._EXCLUDED_TYPE_TOKENS
    //   - SearchInputCollector._EXCLUDED_NAME_RE
    //   - PaginationCollector.VOCABULARY
    //   - PaginationCollector._NEGATIVE_ATTR_TOKENS
    //   - PaginationCollector._WIDGET_TAG_DENYLIST
    //
    // The JS-side detectors annotate chunks with a ``detectorTags``
    // array (e.g. ["search"] or ["pagination"]). The mapper threads
    // those tags through to the audit so a chunk's role on the page
    // is visible without inferring it from xpaths.
    // -----------------------------------------------------------------
    const SEARCH_VOCAB = ['search', 'query', 'find', 'keyword', 'lookup', 'srch', 'buscar', 'recherche', 'suche'];
    const SEARCH_BAD_TYPES = new Set(['hidden', 'email', 'checkbox', 'radio', 'file',
        'image', 'color', 'date', 'range', 'password']);
    const SEARCH_BAD_NAME_RE = /(first.?name|last.?name|subbox|subscribe|signup|newsletter|password|captcha|token|nonce|csrf|turnstile)/i;
    const SEARCH_INPUT_TAGS = new Set(['input', 'textarea', 'select']);

    const PAGINATION_VOCAB = ['next', 'prev', 'previous', 'pagination', 'pager',
        'load more', 'show more', 'see more', 'view more', 'read more',
        'older', 'newer', 'paginat'];
    const PAGINATION_NEG = new Set(['playable', 'player', 'volume', 'mute',
        'fullscreen', 'pip', 'rewind', 'scrub', 'playback', 'audio', 'video',
        'cart', 'wishlist', 'addtocart', 'reply', 'repost', 'retweet',
        'bookmark', 'dropdown', 'haspopup', 'favorite', 'share', 'social']);
    const PAGINATION_TAGS = new Set(['a', 'button']);

    function lowerAttrSoup(el) {
        // Concatenate every attribute name + value to one lowercased
        // blob so detectors can search for vocab tokens cheaply.
        let s = el.tagName.toLowerCase();
        for (let i = 0; i < el.attributes.length; i++) {
            const a = el.attributes[i];
            s += ' ' + a.name.toLowerCase() + '=' + (a.value || '').toLowerCase();
        }
        return s;
    }

    /**
     * Probe one element (root or any descendant) for the search and
     * pagination signatures defined in web_distiller_freq.py. Returns
     * the matched tag names or an empty array.
     */
    function probeElement(el) {
        const out = [];
        if (!el || el.nodeType !== 1) return out;
        const tagName = el.tagName.toLowerCase();
        const soup = lowerAttrSoup(el);
        // Search
        let isSearch = false;
        if (SEARCH_INPUT_TAGS.has(tagName)
            || /role="?(?:search|searchbox|textbox|combobox)"?/.test(soup)
            || tagName.indexOf('search') >= 0
        ) {
            let bad = false;
            for (let i = 0; i < el.attributes.length; i++) {
                const v = (el.attributes[i].value || '').toLowerCase().trim();
                if (v.length < 30 && SEARCH_BAD_TYPES.has(v)) { bad = true; break; }
                if (SEARCH_BAD_NAME_RE.test(v)) { bad = true; break; }
            }
            if (!bad) {
                for (const tok of SEARCH_VOCAB) {
                    if (soup.indexOf(tok) >= 0) { isSearch = true; break; }
                }
                if (!isSearch && /type="?search"?/.test(soup)) isSearch = true;
            }
        }
        if (isSearch) out.push('search');
        // Pagination
        let isPagination = false;
        if (PAGINATION_TAGS.has(tagName) || tagName.indexOf('paginat') >= 0) {
            let negative = false;
            for (const nt of PAGINATION_NEG) {
                if (soup.indexOf(nt) >= 0) { negative = true; break; }
            }
            if (!negative) {
                let txt = '';
                for (let cn = el.firstChild; cn; cn = cn.nextSibling) {
                    if (cn.nodeType === 3 && cn.nodeValue) txt += ' ' + cn.nodeValue.toLowerCase();
                }
                txt = txt.trim();
                for (const tok of PAGINATION_VOCAB) {
                    if (txt.indexOf(tok) >= 0 || soup.indexOf(tok) >= 0) {
                        isPagination = true; break;
                    }
                }
            }
        }
        if (isPagination) out.push('pagination');
        return out;
    }

    /**
     * Walk the chunk's subtree (light + shadow) and union every
     * descendant's detector tags. Cheaply bounded — most chunks are
     * tiny. Stops at MAX_PROBE_NODES to avoid pathological pages.
     */
    function detectChunkTags(rootEl) {
        const MAX_PROBE_NODES = 64;
        const seen = new Set();
        let count = 0;
        const stack = [rootEl];
        while (stack.length && count < MAX_PROBE_NODES) {
            const n = stack.pop();
            if (!n || n.nodeType !== 1) continue;
            count++;
            for (const t of probeElement(n)) seen.add(t);
            if (n.shadowRoot) {
                for (let i = 0; i < n.shadowRoot.children.length; i++) {
                    stack.push(n.shadowRoot.children[i]);
                }
            }
            for (let i = 0; i < n.children.length; i++) stack.push(n.children[i]);
        }
        return Array.from(seen).sort();
    }

    function buildChunkRecord(rootEl, summary) {
        const url = window.location.href.split('?')[0];
        const absXpath = summary.absXpath;
        const pattern = generalizedXpath(absXpath);
        // chunk_id MUST hash on absXpath, not pattern — otherwise sibling
        // cards under the same generalized pattern (e.g. all twelve
        // <media-subnav>/#shadow-root/div items in archive.org's nav
        // slider) collapse to one id and the TF-IDF index ends up with
        // 12 rows under the same chunk_id, all with stale text.
        const cid = generateChunkId(url, absXpath);
        const members = collectMemberXpaths(rootEl);
        const html = buildChunkHtml(rootEl);
        const detectorTags = detectChunkTags(rootEl);
        return {
            chunkId: cid,
            pattern: pattern,
            memberXpaths: members,
            sampleIds: [cid],
            renderedText: renderTextFromFields(summary.fields),
            contentFieldsFull: summary.fields,
            charCount: summary.budget,
            htmlRaw: html,
            commutationCount: 1,
            representative_xpath: absXpath,
            detectorTags: detectorTags,
            element: rootEl,  // internal
            _signatureHash: djb2(html + '|' + detectorTags.join(',')),
        };
    }

    function emitEvent(chunk, eventType) {
        deltaQueue.push({
            type: eventType,
            chunkId: chunk.chunkId,
            pattern: chunk.pattern,
            memberXpaths: chunk.memberXpaths,
            sampleIds: chunk.sampleIds,
            renderedText: chunk.renderedText,
            contentFieldsFull: chunk.contentFieldsFull,
            charCount: chunk.charCount,
            htmlRaw: chunk.htmlRaw,
            commutationCount: chunk.commutationCount,
            representative_xpath: chunk.representative_xpath,
            detectorTags: chunk.detectorTags,
        });
    }

    function emitRemoval(chunkId) {
        deltaQueue.push({ type: 'chunk_removed', chunkId: chunkId });
    }

    function registerChunk(rootEl, summary) {
        const rec = buildChunkRecord(rootEl, summary);
        const existed = chunksById.has(rec.chunkId);
        if (existed) {
            const prev = chunksById.get(rec.chunkId);
            if (prev._signatureHash === rec._signatureHash) {
                // Identical content — skip the emit, keep the old record so
                // the existing observer remains attached.
                return null;
            }
            // Replacing — release prior claims and detach observer.
            for (const mxp of prev.memberXpaths) {
                if (claimedXpaths.get(mxp) === rec.chunkId) claimedXpaths.delete(mxp);
            }
            if (prev.element && elementToChunkId.get(prev.element) === rec.chunkId) {
                elementToChunkId.delete(prev.element);
            }
            detachChunkObserver(rec.chunkId);
        }
        // Claim every member xpath so sibling chunks don't double-count.
        for (const mxp of rec.memberXpaths) {
            claimedXpaths.set(mxp, rec.chunkId);
        }
        chunksById.set(rec.chunkId, rec);
        elementToChunkId.set(rec.element, rec.chunkId);
        if (!chunksByPattern.has(rec.pattern)) {
            chunksByPattern.set(rec.pattern, new Set());
        }
        chunksByPattern.get(rec.pattern).add(rec.chunkId);
        attachChunkObserver(rec);
        emitEvent(rec, existed ? 'chunk_replaced' : 'chunk_added');
        return rec;
    }

    function unregisterChunk(chunkId) {
        const rec = chunksById.get(chunkId);
        if (!rec) return;
        for (const mxp of rec.memberXpaths) {
            if (claimedXpaths.get(mxp) === chunkId) claimedXpaths.delete(mxp);
        }
        if (rec.element && elementToChunkId.get(rec.element) === chunkId) {
            elementToChunkId.delete(rec.element);
        }
        detachChunkObserver(chunkId);
        chunksById.delete(chunkId);
        const set = chunksByPattern.get(rec.pattern);
        if (set) {
            set.delete(chunkId);
            if (set.size === 0) chunksByPattern.delete(rec.pattern);
        }
        emitRemoval(chunkId);
    }

    // -----------------------------------------------------------------
    // Re-chunk a subtree
    // -----------------------------------------------------------------
    function elementInSubtree(el, rootEl) {
        if (!el) return false;
        if (el === rootEl) return true;
        if (rootEl.contains && rootEl.contains(el)) return true;
        // Cross-shadow check: walk up via getRootNode().host until we hit
        // rootEl or run out. Without this, chunks rooted inside a shadow
        // tree look "outside" the host's subtree to plain Node.contains.
        let cur = el;
        while (cur) {
            if (cur === rootEl) return true;
            const parent = cur.parentElement
                || (cur.getRootNode && cur.getRootNode() && cur.getRootNode().host);
            if (!parent || parent === cur) return false;
            cur = parent;
        }
        return false;
    }

    /**
     * Diff-based re-chunk on a dirty subtree.
     *
     * Old behaviour was: unregister every chunk in this subtree (firing a
     * chunk_removed for each), then re-discover and register fresh (firing
     * a chunk_added for each). For an unchanged subtree that produced two
     * full event waves per scroll — 712 emits resolving to 179 actual
     * chunks last run.
     *
     * New behaviour: discover, then compare each result's signature against
     * the existing record at the same chunkId. Identical → no emit. Changed
     * content at the same chunkId → chunk_replaced. New chunkId not seen
     * before → chunk_added. Existing chunks whose chunkId is no longer in
     * the discovered set get a single chunk_removed.
     */
    function rechunkSubtree(rootEl) {
        // Fresh xpath cache for this pass. The DOM is synchronously stable
        // for the duration of the call, so cached entries can't disagree
        // with the live tree, and this saves ~10× on repeated parent walks
        // (extractElementFields, collectMemberXpaths, registerChunk all
        // call getAbsoluteXpath multiple times per element).
        _xpathCache = new WeakMap();

        // Enumerate chunks rooted in or under this branch in O(branch_size)
        // by walking the branch tree (light + shadow) and probing the
        // elementToChunkId map at each node, instead of scanning all
        // chunksById entries (was O(N_chunks × depth)).
        const existingInBranch = new Map();   // chunkId → prev record
        const stack = [rootEl];
        while (stack.length) {
            const n = stack.pop();
            if (!n || n.nodeType !== 1) continue;
            const cid = elementToChunkId.get(n);
            if (cid) {
                const prev = chunksById.get(cid);
                if (prev) existingInBranch.set(cid, prev);
            }
            if (n.shadowRoot) {
                for (let i = 0; i < n.shadowRoot.children.length; i++) {
                    stack.push(n.shadowRoot.children[i]);
                }
            }
            for (let i = 0; i < n.children.length; i++) stack.push(n.children[i]);
        }
        // Pick up any chunks whose roots have been disconnected from the
        // tree entirely — they need a chunk_removed event regardless of
        // which branch we're working on.
        for (const [cid, rec] of chunksById) {
            if (!rec.element) continue;
            if (!rec.element.isConnected) existingInBranch.set(cid, rec);
        }

        const results = [];
        findChunkRoots(rootEl, results);
        stats.lastLeafCount = results.length;

        const seenIds = new Set();
        for (const r of results) {
            const rec = buildChunkRecord(r.element, r.summary);
            seenIds.add(rec.chunkId);
            const prev = chunksById.get(rec.chunkId);
            if (prev && prev._signatureHash === rec._signatureHash) {
                // Unchanged — keep prev wholesale; no emit, no observer churn.
                continue;
            }
            if (prev) {
                // Same chunkId, different content → in-place replace.
                for (const mxp of prev.memberXpaths) {
                    if (claimedXpaths.get(mxp) === rec.chunkId) claimedXpaths.delete(mxp);
                }
                detachChunkObserver(rec.chunkId);
                for (const mxp of rec.memberXpaths) claimedXpaths.set(mxp, rec.chunkId);
                chunksById.set(rec.chunkId, rec);
                if (!chunksByPattern.has(rec.pattern)) chunksByPattern.set(rec.pattern, new Set());
                chunksByPattern.get(rec.pattern).add(rec.chunkId);
                attachChunkObserver(rec);
                emitEvent(rec, 'chunk_replaced');
            } else {
                // Brand new chunk under this branch.
                for (const mxp of rec.memberXpaths) claimedXpaths.set(mxp, rec.chunkId);
                chunksById.set(rec.chunkId, rec);
                if (!chunksByPattern.has(rec.pattern)) chunksByPattern.set(rec.pattern, new Set());
                chunksByPattern.get(rec.pattern).add(rec.chunkId);
                attachChunkObserver(rec);
                emitEvent(rec, 'chunk_added');
            }
        }

        // Anything that USED to live in this branch but no longer appears
        // in the fresh discovery is a true removal.
        for (const [cid, prev] of existingInBranch) {
            if (!seenIds.has(cid)) unregisterChunk(cid);
        }
    }

    function processDirty() {
        passesThisSettle = 0;
        try {
            stats.bodyTextLen = document.body ? (document.body.innerText || '').length : 0;
        } catch (_) { stats.bodyTextLen = 0; }

        if (dirtySubtrees.size === 0) {
            // First-pass or full re-walk.
            rechunkSubtree(document.documentElement);
            stats.chunkSubtreeRuns++;
            stats.totalChunks = chunksById.size;
            return;
        }

        // Snapshot then clear.
        const branches = Array.from(dirtySubtrees);
        dirtySubtrees.clear();
        // Sort ancestor-first so we don't re-chunk the same subtree twice.
        branches.sort(function(a, b) {
            if (a === b) return 0;
            // a comes first (ancestor) if b is contained in a.
            if (a.contains && a.contains(b)) return -1;
            if (b.contains && b.contains(a)) return 1;
            return 0;
        });
        const processed = [];
        for (const el of branches) {
            if (!el.isConnected) {
                // Removed entirely — drop any chunks rooted under it.
                rechunkSubtree(document.documentElement);
                processed.length = 0;
                processed.push(document.documentElement);
                break;
            }
            let coveredByAncestor = false;
            for (const p of processed) {
                if (p === el) { coveredByAncestor = true; break; }
                if (p.contains && p.contains(el)) { coveredByAncestor = true; break; }
            }
            if (coveredByAncestor) continue;
            rechunkSubtree(el);
            processed.push(el);
        }
        stats.chunkSubtreeRuns++;
        stats.totalChunks = chunksById.size;
    }

    function scheduleSettle() {
        isSettled = false;
        if (moTimer) clearTimeout(moTimer);
        moTimer = setTimeout(function() {
            try {
                processDirty();
            } catch (e) {
                logErr('processDirty', e);
            }
            isSettled = true;
            moTimer = null;
            // Bound runaway feedback when mutations happen during processDirty.
            if (dirtySubtrees.size > 0 && passesThisSettle < MAX_PASSES_PER_SETTLE) {
                passesThisSettle++;
                scheduleSettle();
            }
        }, DEBOUNCE_MS);
    }

    // -----------------------------------------------------------------
    // Global "uncovered subtree" observer.
    //
    // The per-chunk observers handle mutations INSIDE existing chunks.
    // This global one handles mutations OUTSIDE every chunk — typically
    // newly-injected content (lazy load, route change, late hydration).
    // It marks the *highest unclaimed ancestor* of the mutation target
    // as dirty so processDirty can re-chunk that branch.
    // -----------------------------------------------------------------
    /**
     * Walk to the highest ancestor whose parent is NOT inside any
     * existing chunk. Crosses shadow boundaries via getRootNode().host
     * so a mutation deep inside a custom element's shadow root still
     * resolves to a sensible re-chunk root.
     */
    function highestUncoveredAncestor(targetEl) {
        let cur = targetEl;
        while (cur) {
            // Determine the next "parent" in tree order — light parent
            // first, falling back to shadow host when we sit at the top
            // of a shadow root.
            let parent = cur.parentElement;
            if (!parent) {
                const root = cur.getRootNode && cur.getRootNode();
                if (root && root.host) parent = root.host;
            }
            if (!parent) break;
            const parentXp = getAbsoluteXpath(parent);
            if (claimedXpaths.has(parentXp)) return cur;
            cur = parent;
        }
        return cur || document.documentElement;
    }

    /**
     * Install the global "outside every chunk" MO on every shadow root
     * we currently know about, plus document.documentElement. New shadow
     * roots created later are discovered when their host's per-chunk MO
     * fires (or the next full re-walk picks them up).
     */
    const globalObservers = [];
    const globalCallback = function(mutations) {
        // Fast-path: a mutation is "inside an existing chunk" iff the
        // target (or any ancestor) is the registered root of some chunk —
        // i.e. it appears in elementToChunkId. The previous version computed
        // getAbsoluteXpath(target) + Map lookup on EVERY mutation, which on
        // busy pages (YouTube hover effects, archive.org carousel ticks)
        // burned milliseconds of string allocation in the MO hot loop.
        // Walking ~10 ancestors via parentElement is cheaper than one
        // xpath rebuild + Map<string> lookup.
        let queued = false;
        for (let i = 0; i < mutations.length; i++) {
            const m = mutations[i];
            let target = m.target;
            if (!target) continue;
            if (target.nodeType !== 1) target = target.parentElement;
            if (!target) continue;
            // Skip if target OR any ancestor is a known chunk root — the
            // per-chunk MO already handles those.
            let cur = target, insideChunk = false;
            for (let hops = 0; cur && hops < 24; hops++) {
                if (elementToChunkId.has(cur)) { insideChunk = true; break; }
                const parent = cur.parentElement
                    || (cur.getRootNode && cur.getRootNode() && cur.getRootNode().host);
                if (!parent || parent === cur) break;
                cur = parent;
            }
            if (insideChunk) continue;
            const branch = highestUncoveredAncestor(target);
            if (branch) {
                dirtySubtrees.add(branch);
                queued = true;
            }
        }
        if (queued) scheduleSettle();
    };

    function installGlobalObserversOn(root) {
        try {
            const obs = new MutationObserver(globalCallback);
            obs.observe(root, { childList: true, subtree: true });
            globalObservers.push(obs);
        } catch (e) {
            logErr('installGlobalObserversOn', e);
        }
    }

    function installGlobalObservers() {
        installGlobalObserversOn(document.documentElement);
        // Sweep once for already-attached shadow roots (Angular hosts,
        // web components) so mutations inside them are not missed.
        const stack = [document.documentElement];
        while (stack.length) {
            const n = stack.pop();
            if (!n || n.nodeType !== 1) continue;
            if (n.shadowRoot) {
                installGlobalObserversOn(n.shadowRoot);
                for (let i = 0; i < n.shadowRoot.children.length; i++) {
                    stack.push(n.shadowRoot.children[i]);
                }
            }
            for (let i = 0; i < n.children.length; i++) stack.push(n.children[i]);
        }
    }
    installGlobalObservers();

    // -----------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------
    window._wfhEngine = {
        getDeltaQueue: function() {
            const q = deltaQueue;
            deltaQueue = [];
            return q;
        },
        isSettled: function() { return isSettled; },
        getStats: function() {
            try {
                stats.bodyTextLen = document.body ? (document.body.innerText || '').length : 0;
            } catch (_) {}
            // Deep-walk count of shadow roots and total content text so
            // diagnostics distinguish "page never rendered" from "page
            // rendered into shadow DOM that the chunker reaches".
            try {
                let shadowRoots = 0;
                let deepTextLen = 0;
                const stack = [document.documentElement];
                while (stack.length) {
                    const n = stack.pop();
                    if (!n || n.nodeType !== 1) continue;
                    for (let cn = n.firstChild; cn; cn = cn.nextSibling) {
                        if (cn.nodeType === 3 && cn.nodeValue) deepTextLen += cn.nodeValue.length;
                    }
                    if (n.shadowRoot) {
                        shadowRoots++;
                        for (let i = 0; i < n.shadowRoot.children.length; i++) {
                            stack.push(n.shadowRoot.children[i]);
                        }
                    }
                    for (let i = 0; i < n.children.length; i++) stack.push(n.children[i]);
                }
                stats.shadowRoots = shadowRoots;
                stats.deepTextLen = deepTextLen;
            } catch (_) {}
            stats.pendingDirty = dirtySubtrees.size;
            stats.totalChunks = chunksById.size;
            return Object.assign({}, stats);
        },
        // Diagnostic — force a full re-walk.
        forceRescan: function() {
            dirtySubtrees.clear();
            rechunkSubtree(document.documentElement);
            stats.chunkSubtreeRuns++;
            stats.totalChunks = chunksById.size;
        },
    };

    // Initial pass.
    try {
        rechunkSubtree(document.documentElement);
        stats.chunkSubtreeRuns++;
        stats.totalChunks = chunksById.size;
    } catch (e) {
        logErr('initialChunk', e);
    }
})();
