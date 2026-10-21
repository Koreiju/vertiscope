/**
 * The page-side snapshot reader, alone in its module so a Node test can run it
 * against a stubbed document (`tests/snapshot_tag.test.mjs`). It imports
 * nothing: it is a string of page script built from two arguments.
 */

/** The page-side reader. `xs` is the chunk's element xpaths. */
export function snapshotScript(xpaths: string[],
                               addrs: Record<string, [string, number]> = {}): string {
  return `(function (xs, ad) {
  var MAX = 2500, count = 0;
  var PROPS = ["display","position","box-sizing","color","background-color","background-image",
    "background-size","background-position","background-repeat","font-family","font-size","font-weight",
    "font-style","line-height","letter-spacing","text-transform","text-decoration-line","text-decoration-color",
    "text-align","vertical-align","white-space","word-break","overflow-wrap",
    "margin-top","margin-right","margin-bottom","margin-left",
    "padding-top","padding-right","padding-bottom","padding-left",
    "border-top-width","border-right-width","border-bottom-width","border-left-width",
    "border-top-style","border-right-style","border-bottom-style","border-left-style",
    "border-top-color","border-right-color","border-bottom-color","border-left-color",
    "border-top-left-radius","border-top-right-radius","border-bottom-left-radius","border-bottom-right-radius",
    "flex-direction","flex-wrap","justify-content","align-items","align-self","gap","column-gap","row-gap",
    "flex-grow","flex-shrink","flex-basis","grid-template-columns","grid-auto-flow",
    "list-style-type","object-fit","object-position","opacity","box-shadow","overflow-x","overflow-y",
    "-webkit-line-clamp","-webkit-box-orient","text-overflow","fill","stroke"];
  var SKIP = {"0px":1,"none":1,"normal":1,"auto":1,"rgba(0, 0, 0, 0)":1,"static":1,"visible":1,
              "start":1,"baseline":1,"repeat":1,"0% 0%":1,"content-box":1,"1":1,"0":1,"nowrap":1,
              "row":1,"stretch":1,"currentcolor":1};
  var KEEP_ZERO = {"flex-shrink":1,"flex-grow":1,"opacity":1};
  var DROP = {SCRIPT:1,STYLE:1,NOSCRIPT:1,TEMPLATE:1,IFRAME:1,OBJECT:1,EMBED:1,LINK:1,META:1,BASE:1,FORM:0};
  function esc(t) { return String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  function attr(t) { return esc(t).replace(/"/g,"&quot;"); }
  function safe(u) { u = String(u || ""); return /^(https?:|mailto:)/i.test(u) ? u : ""; }
  // The rendered box, kept as a RATIO: as wide as it was or the panel, and as
  // tall as that width implies. A fixed pixel height under max-width:100%
  // stretched every picture a narrower panel shrank (2026-10-10: "Image aspect
  // ratio rendering is weird on the HTML rendering panel forms ... correct in
  // markdown view, but not in HTML"), and a drawn shape whose size came from
  // width/height -- a round play button -- reflowed to a flat line.
  function ratio(r) {
    var w = Math.round(r.width), h = Math.round(r.height);
    if (!(w > 0 && h > 0)) return "";
    return "width:" + w + "px;max-width:100%;height:auto;aspect-ratio:" + w + " / " + h + ";";
  }
  function styleOf(el, cs) {
    var s = "";
    for (var i = 0; i < PROPS.length; i++) {
      var p = PROPS[i], v = cs.getPropertyValue(p);
      if (!v || (SKIP[v] && !KEEP_ZERO[p]) ) continue;
      if (p === "background-image" && !/url\\(/.test(v) && !/gradient/.test(v)) continue;
      if (p.indexOf("border-") === 0 && p.slice(-6) === "-color" && !/solid|dashed|dotted|double/.test(
          cs.getPropertyValue(p.replace("-color", "-style")))) continue;
      s += p + ":" + v.replace(/"/g, "'") + ";";
    }
    return s;
  }
  function pseudo(el, which) {
    var cs = getComputedStyle(el, which), c = cs.getPropertyValue("content");
    if (!c || c === "none" || c === "normal" || !/^["']/.test(c)) return "";
    var text = c.slice(1, -1);
    if (!text.trim()) return "";
    return '<span style="' + attr(styleOf(el, cs)) + '">' + esc(text) + "</span>";
  }
  function at(x) {
    try {
      var n = document.evaluate(x, document, null, 9, null).singleNodeValue;
      if (n && n.nodeType === 3) n = n.parentElement;
      return n && n.nodeType === 1 ? n : null;
    } catch (e) { return null; }
  }
  // A line joined from inline fragments keeps its FIRST fragment's address --
  // "<b>Trie</b> implementation based on ..." is addressed at the <b> -- so
  // each element found is widened to the block the browser lays its run out
  // in: up past every ancestor whose computed display is inline.
  function flow(n) {
    while (n.parentElement && n.parentElement !== document.body
           && /^inline/.test(getComputedStyle(n).display)) n = n.parentElement;
    return n;
  }
  var own = new Set(), path = new Set(), found = 0;
  for (var i = 0; i < xs.length; i++) { var n = at(xs[i]); if (n) { own.add(flow(n)); found++; } }
  if (!own.size) return null;
  // The trie's address for each element the chunk's lines name: xpath ->
  // [key, is-a-control]. Resolved here, read-only, into a Map that lives in
  // this closure -- nothing is written into the page. A control's own address
  // outranks the line's (an anchor's line is stored under a urls.* address).
  var tagged = new Map();
  for (var xk in ad) {
    var tn = at(xk);
    if (!tn) continue;
    var held = tagged.get(tn);
    if (!held || (ad[xk][1] && !held[1])) tagged.set(tn, [ad[xk][0], ad[xk][1], xk]);
  }
  // A LABEL the trie holds names the control it labels: the store draws
  // "Your word [ ]" as one line keyed at the <label>, so the empty input had
  // no address of its own and its card stayed inert (G-111, 2026-10-07: the
  // fill arm found no field to type into). The label's address goes to its
  // control (label.control, the browser's own association), as a control.
  tagged.forEach(function (v, el) {
    if (!el || el.tagName !== "LABEL") return;
    var c = null;
    try { c = el.control || null; } catch (e) { c = null; }
    if (!c) { var f = el.getAttribute && el.getAttribute("for"); if (f) c = document.getElementById(f); }
    if (!c) c = el.querySelector ? el.querySelector("input,textarea,select") : null;
    if (c && !tagged.has(c)) tagged.set(c, [v[0], 1, v[2]]);
  });
  // What a click or a change on this element should DO to the page, decided
  // by what the element is. "" is inert: no address, a field that must not be
  // typed into from outside (password, file, pickers), or disabled by the page.
  function actOf(el, ctl) {
    if (el.disabled) return "";
    var nm = el.tagName.toLowerCase();
    if (nm === "a" || nm === "button") return "press";
    if (nm === "select") return "choose";
    if (nm === "textarea") return "type";
    if (nm === "input") {
      var t = String(el.type || "text").toLowerCase();
      if (t === "checkbox" || t === "radio") return "toggle";
      if (/^(button|submit|reset|image)$/.test(t)) return "press";
      if (/^(hidden|password|file|color|range|date|datetime-local|month|week|time)$/.test(t)) return "";
      return "type";
    }
    return ctl ? "press" : "";
  }
  var list = Array.from(own);
  function chain(n) { var a = []; while (n) { a.unshift(n); n = n.parentElement; } return a; }
  var first = chain(list[0]), depth = first.length;
  for (i = 1; i < list.length; i++) {
    var a = chain(list[i]), k = 0;
    while (k < depth && k < a.length && a[k] === first[k]) k++;
    depth = k;
  }
  var root = first[Math.max(0, depth - 1)];
  for (i = 0; i < list.length; i++) {
    for (var p = list[i]; p && p !== root; p = p.parentElement) path.add(p);
  }
  function kids(el) {
    if (el.shadowRoot) return Array.from(el.shadowRoot.childNodes);
    if (el.tagName === "SLOT" && el.assignedNodes) {
      var got = el.assignedNodes({ flatten: true });
      if (got.length) return got;
    }
    return Array.from(el.childNodes);
  }
  function svg(el) {
    var c = el.cloneNode(true);
    var bad = c.querySelectorAll("script,foreignObject,a");
    for (var i = 0; i < bad.length; i++) bad[i].remove();
    var all = [c].concat(Array.from(c.querySelectorAll("*")));
    for (i = 0; i < all.length; i++) {
      for (var j = all[i].attributes.length - 1; j >= 0; j--) {
        var nm = all[i].attributes[j].name;
        if (/^on/i.test(nm) || /href$/i.test(nm)) all[i].removeAttribute(nm);
      }
    }
    var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    c.setAttribute("width", Math.round(r.width)); c.setAttribute("height", Math.round(r.height));
    c.setAttribute("style", "color:" + cs.color + ";fill:" + cs.fill + ";vertical-align:middle;" + ratio(r));
    return new XMLSerializer().serializeToString(c);
  }
  function clone(el, whole) {
    if (count++ > MAX) return "";
    if (el.nodeType === 3) return whole ? esc(el.nodeValue) : "";
    if (el.nodeType !== 1) return "";
    var tag = el.tagName;
    if (DROP[tag]) return "";
    var cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return "";
    if (el instanceof SVGElement) return tag.toLowerCase() === "svg" ? svg(el) : "";
    var name = tag.toLowerCase();
    if (name.indexOf("-") > 0 || name === "slot") name = /inline/.test(cs.display) ? "span" : "div";
    if (name === "form") name = "div";
    var s = styleOf(el, cs), extra = "";
    if (name !== "img" && name !== "video" && !(el.textContent || "").trim()
        && (/url\\(/.test(cs.backgroundImage) || cs.borderTopLeftRadius !== "0px"
            || cs.borderTopStyle !== "none" || cs.backgroundColor !== "rgba(0, 0, 0, 0)")) {
      s += ratio(el.getBoundingClientRect());
    }
    var ta = tagged.get(el), act = ta ? actOf(el, ta[1]) : "";
    if (ta) {
      extra += ' data-vertiscope-address="' + attr(ta[0]) + '" data-vertiscope-xpath="' + attr(ta[2]) + '"';
      if (act) extra += ' data-vertiscope-act="' + act + '"';
    }
    if (name === "a") { var h = safe(el.href); if (h) extra += ' href="' + attr(h) + '" data-href="' + attr(h) + '"'; }
    if (name === "img") {
      var src = safe(el.currentSrc || el.src), r = el.getBoundingClientRect();
      if (!src) return "";
      extra += ' src="' + attr(src) + '" alt="' + attr(el.alt || "") + '"';
      s += ratio(r);
    }
    if (name === "picture" || name === "source") { if (name === "source") return ""; }
    if (name === "video") {
      var poster = safe(el.poster), vr = el.getBoundingClientRect();
      return '<img src="' + attr(poster) + '" alt="video" style="' + attr(s + ratio(vr) +
             "object-fit:" + (cs.objectFit || "contain") + ";background:#000;") + '">';
    }
    if (name === "input" || name === "textarea" || name === "select" || name === "button") {
      // Live only where the trie holds this element's address AND the element
      // is one a reader acts on in place; everything else stays inert.
      if (!act) extra += " disabled";
      if (name === "input") {
        extra += ' type="' + attr(el.type || "text") + '"';
        if (el.type === "checkbox" || el.type === "radio") { if (el.checked) extra += " checked"; }
        else extra += ' value="' + attr(el.value || "") + '" placeholder="' + attr(el.placeholder || "") + '"';
      }
    }
    if (el.title) extra += ' title="' + attr(el.title) + '"';
    if (el.colSpan > 1) extra += ' colspan="' + el.colSpan + '"';
    if (el.rowSpan > 1) extra += ' rowspan="' + el.rowSpan + '"';
    if (name === "img" || name === "input" || name === "br" || name === "hr") {
      return "<" + name + ' style="' + attr(s) + '"' + extra + ">";
    }
    var inner = pseudo(el, "::before");
    if (name === "select") {
      var os = el.options;
      for (var j = 0; j < os.length && j < 100; j++) {
        inner += '<option value="' + attr(os[j].value) + '"' + (os[j].selected ? " selected" : "") + ">" +
                 esc(os[j].text || os[j].textContent || "") + "</option>";
      }
    } else if (name === "textarea") {
      inner += esc(el.value || "");
    } else {
      var ks = kids(el);
      for (var i = 0; i < ks.length; i++) {
        var c = ks[i];
        if (whole || own.has(c)) inner += clone(c, true);
        else if (path.has(c)) inner += clone(c, false);
      }
    }
    inner += pseudo(el, "::after");
    return "<" + name + ' style="' + attr(s) + '"' + extra + ">" + inner + "</" + name + ">";
  }
  var html = clone(root, own.has(root));
  var bg = "", q = root;
  while (q && q.nodeType === 1) {
    var b = getComputedStyle(q).backgroundColor;
    if (b && b !== "rgba(0, 0, 0, 0)" && b !== "transparent") { bg = b; break; }
    q = q.parentElement;
  }
  if (!bg) bg = getComputedStyle(document.body).backgroundColor || "rgb(255, 255, 255)";
  if (bg === "rgba(0, 0, 0, 0)") bg = "rgb(255, 255, 255)";
  var rc = getComputedStyle(root);
  return { html: html, bg: bg, color: rc.color, font: rc.fontSize + " " + rc.fontFamily,
           elements: count, found: found, url: location.href, at: Date.now() };
})(${JSON.stringify(xpaths.slice(0, 600))}, ${JSON.stringify(addrs)})`;
}
