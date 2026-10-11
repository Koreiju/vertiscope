"""A page for when there is no connection (`G-59`..`G-62`).

The reader's words (PLUGIN_GOAL, the second long statement): *"we could
toggle the option to save the full webpage as it is presented live in the
electron browser for offline use ... infill offline-saved pages with what we
have traced when saving the page source with our traced chunks (should saved
offline page sources not provide their full layout), or if internet is
disabled, instead opening the fully rendered scrollable page reconstructed
from the scan trace."*

Two forms, both read from the workspace and nothing else:

* **saved** -- the page as the Electron cell PRESENTED it, its scripts already
  run, serialised by Chromium as MHTML (`webContents.savePage`), with the
  page's visible text beside it so its coverage of the trace can be judged;
* **traced** -- the page rebuilt from the scan trace alone: every stored chunk
  of the url in document order, drawn by its saved page form where it has one
  (`snapshots`) and by its markdown where it does not, pictures inlined from
  the saved media so the page renders with nothing reachable at all.

The infill rule is a COVERAGE test, read as: a saved source that "does not
provide its full layout" is one whose text holds too little of what the scan
traced (`page_info`'s `coverage`). Then the SAVED page still opens, with its
own layout, and the chunks it lacks are drawn into it (`infill`) -- the first
cut threw it away for the trace, which is replacing, not infilling.
"""

from __future__ import annotations

import base64
import hashlib
import html as _html
import json
import quopri
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import snapshots

#: A saved page at most this large (MHTML carries every resource inline).
PAGE_MAX = 96 << 20
#: Below this share of the trace's words, a saved page is not the page:
#: the traced form opens instead (`G-61`).
INFILL_BELOW = 0.9
#: A chunk is missing from a saved page when at least this share of its words is.
CHUNK_MISSING = 0.5
#: Planted (`G-61`): a thin saved page is thrown away for the trace instead of
#: being infilled -- the first cut, which lost the saved page's own layout.
PLANT_REPLACE_NOT_INFILL = False
#: Planted: any document Chromium serialised counts as the page, its own
#: error page included.
PLANT_ANY_SNAPSHOT = False


def _dir(workspace) -> Optional[Path]:
    base = getattr(workspace, "path", None)
    return Path(base) / "offline_pages" if base else None


def page_key(url: str) -> str:
    return hashlib.sha1(str(url or "").encode("utf-8")).hexdigest()


_TOKENS = re.compile(r"[^\W_]+", re.U)


def _words(text: str) -> set:
    """Words, as a reader would count them: a link's text, never its
    destination; and only tokens made of letters -- `3Akev`, `2Fen` are
    URL-encoded citation metadata (COinS), not words a page shows."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    t = re.sub(r"\]\([^)]*\)", "] ", t)
    t = re.sub(r"(?:https?:)?//\S+", " ", t)
    return set(w.lower() for w in _TOKENS.findall(t) if len(w) >= 3 and w.isalpha())


_SNAPSHOT_AT = re.compile(rb"^Snapshot-Content-Location:\s*(\S+)", re.I | re.M)


def snapshot_of(mhtml: bytes) -> str:
    """The document Chromium says it serialised: its `Snapshot-Content-Location`."""
    m = _SNAPSHOT_AT.search((mhtml or b"")[:2048])
    return m.group(1).decode("latin-1") if m else ""


def is_the_page(mhtml: bytes) -> bool:
    """A web document, not Chromium's own error page. A failed load saved
    `chrome-error://chromewebdata/` -- 744 bytes, an empty body -- as Axolotl
    (2026-10-11), which then opened as Axolotl, infilled. A file with no such
    header is taken at its word (not every writer adds it)."""
    at = snapshot_of(mhtml)
    return not at or at.startswith(("http://", "https://")) or PLANT_ANY_SNAPSHOT


def save_page(workspace, url: str, mhtml: bytes, text: str) -> Dict:
    """Keep the page as presented. Idempotent per url: the latest save wins."""
    root = _dir(workspace)
    if root is None or not url or not mhtml:
        return {"saved": False, "why": "nothing to save"}
    if not is_the_page(mhtml):
        return {"saved": False, "why": "not the page: %s" % snapshot_of(mhtml)[:80]}
    if len(mhtml) > PAGE_MAX:
        return {"saved": False, "why": "too large: %d" % len(mhtml)}
    root.mkdir(parents=True, exist_ok=True)
    k = page_key(url)
    tmp = root / (k + ".tmp")
    tmp.write_bytes(mhtml)
    tmp.replace(root / (k + ".mhtml"))
    meta = {"url": url, "at": time.time(), "bytes": len(mhtml), "text": text or ""}
    (root / (k + ".json")).write_text(json.dumps(meta), encoding="utf-8")
    return {"saved": True, "key": k, "bytes": len(mhtml)}


def load_page(workspace, url: str) -> Optional[bytes]:
    root = _dir(workspace)
    if root is None:
        return None
    path = root / (page_key(url) + ".mhtml")
    return path.read_bytes() if path.exists() else None


def _chunk_words(c, snap) -> set:
    if snap and snap.get("html"):
        return _words(_html.unescape(re.sub(r"<[^>]+>", " ", snap["html"])))
    return _words(c.md or "")


def page_info(workspace, url: str) -> Dict:
    """What there is to show offline for `url`, and which form opens."""
    root = _dir(workspace)
    chunks = workspace.store.chunks(url)
    # The trace as the page DISPLAYED it: each chunk's saved page form, its
    # markdown only where it has none. Against the markdown, a complete saved
    # Okapi read 54% -- link titles, alt text and citation marks are in the
    # markdown and on no page -- so the infill fired on a page that was whole.
    traced = set()
    forms = snapshots.load_page_forms(workspace, url)
    for c in chunks:
        traced |= _chunk_words(c, forms.get(c.cid))
    out: Dict = {"url": url, "chunks": len(chunks), "saved": False, "coverage": None,
                 "snapshots": snapshots.coverage(workspace, url)["saved"] if chunks else 0}
    meta_path = root / (page_key(url) + ".json") if root is not None else None
    page = root / (page_key(url) + ".mhtml") if root is not None else None
    if page is not None and page.exists() and not is_the_page(page.read_bytes()[:2048]):
        # Kept on disk, never opened as the page (the store is the reader's).
        out["rejected"] = snapshot_of(page.read_bytes()[:2048])
        meta_path = None
    if meta_path is not None and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        have = _words(meta.get("text") or "")
        out.update(saved=True, at=meta.get("at"), bytes=meta.get("bytes"),
                   coverage=(round(len(traced & have) / len(traced), 3) if traced else None),
                   # Why a page would be infilled: what the trace holds that it does not.
                   missing=sorted(traced - have)[:40])
    # Which form opens: the saved page when it holds the trace; the saved
    # page INFILLED with the traced chunks it lacks when it does not (`G-61`);
    # the trace alone when nothing was saved (`G-62`); nothing without either.
    if out["saved"] and (out["coverage"] is None or out["coverage"] >= INFILL_BELOW or not chunks):
        out["opens"] = "saved"
    elif out["saved"] and not PLANT_REPLACE_NOT_INFILL:
        out["opens"] = "infilled"
    elif chunks:
        out["opens"] = "traced"
    else:
        out["opens"] = None
    return out


# -- the page rebuilt from the scan trace ------------------------------------

_LINK = re.compile(r"(!?)\[([^\]]*)\]\(<?([^)>\s]+)>?\)")


def _md_line_html(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    m = re.match(r"^(#{1,6})\s+(.*)$", t)
    tag, body = ("h%d" % len(m.group(1)), m.group(2)) if m else ("div", re.sub(r"^[-*]\s+", "", t))
    out, last = "", 0
    for lm in _LINK.finditer(body):
        out += _html.escape(body[last:lm.start()])
        bang, label, dest = lm.groups()
        if bang:
            out += '<img alt="%s" src="%s">' % (_html.escape(label), _html.escape(dest))
        elif dest.startswith("#"):
            out += _html.escape(label)
        else:
            out += '<a href="%s">%s</a>' % (_html.escape(dest), _html.escape(label))
        last = lm.end()
    out += _html.escape(body[last:])
    return "<%s>%s</%s>" % (tag, out, tag)


def _inline_media(workspace, html: str, tally: Optional[Dict] = None) -> str:
    """Saved pictures as data URIs, so the page renders with nothing reachable.
    `tally` counts what was asked for and what the store held: a picture the
    scan never saved cannot be drawn offline, and the banner says how many."""
    def swap(m):
        u = m.group(2)
        if tally is not None and not u.startswith("data:"):
            tally["asked"] = tally.get("asked", 0) + 1
        got = snapshots.load_media(workspace, snapshots.media_key(u)) if snapshots.has_media(workspace, u) else None
        if not got:
            return m.group(0)
        data, ct = got
        if tally is not None:
            tally["held"] = tally.get("held", 0) + 1
        return m.group(1) + "data:%s;base64,%s" % (ct, base64.b64encode(data).decode("ascii")) + m.group(3)
    return re.sub(r"""(<(?:img|video|audio|source)\b[^>]*?\bsrc=["'])([^"']+)(["'])""", swap, html or "")


def _chunk_html(workspace, c, snap, pics) -> tuple:
    """One chunk drawn by its saved page form, else by its markdown."""
    if snap and snap.get("html"):
        style = []
        for k, css in (("bg", "background"), ("color", "color"), ("font", "font")):
            if snap.get(k):
                style.append("%s:%s" % (css, snap[k]))
        return ('<section class="dv-chunk" data-cid="%s" style="%s">%s</section>'
                % (c.cid, _html.escape(";".join(style)), _inline_media(workspace, snap["html"], pics)), "form")
    if (c.md or "").strip():
        body = "".join(_md_line_html(l) for l in c.md.split("\n"))
        return ('<section class="dv-chunk dv-md" data-cid="%s">%s</section>'
                % (c.cid, _inline_media(workspace, body, pics)), "markdown")
    return "", ""


def reconstruct(workspace, url: str) -> Dict:
    """The page from the scan trace alone (`G-62`): HTML, and how it was made."""
    t0 = time.perf_counter()
    chunks = sorted(workspace.store.chunks(url), key=lambda c: (c.row, c.xpath, c.part))
    saved_forms = snapshots.load_page_forms(workspace, url)
    parts: List[str] = []
    forms = marks = 0
    pics: Dict = {"asked": 0, "held": 0}
    for c in chunks:
        drawn, how = _chunk_html(workspace, c, saved_forms.get(c.cid), pics)
        if drawn:
            parts.append(drawn)
            forms += how == "form"
            marks += how == "markdown"
    head = ('<!doctype html><html><head><meta charset="utf-8"><title>%s (offline)</title>'
            '<style>body{font:15px/1.5 system-ui,sans-serif;max-width:1000px;margin:20px auto;'
            'padding:0 16px;background:#fff;color:#202122}.dv-chunk{margin:0 0 14px}'
            'img,video{max-width:100%%;height:auto}.dv-banner{font:12px system-ui;color:#555;'
            'border-bottom:1px solid #ddd;padding:4px 0 8px;margin-bottom:14px}</style></head><body>'
            % _html.escape(url))
    banner = ('<div class="dv-banner">Offline: rebuilt from the scan trace of %s -- %d chunks, '
              '%d from their saved page form, %d from markdown; %d of %d pictures held</div>'
              % (_html.escape(url), len(chunks), forms, marks, pics["held"], pics["asked"]))
    return {"html": head + banner + "".join(parts) + "</body></html>",
            "chunks": len(chunks), "forms": forms, "markdown": marks, "pictures": pics,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


# -- the saved page infilled from the trace (`G-61`) -------------------------

_BOUNDARY = re.compile(rb'boundary="([^"]+)"', re.I)


def infill(workspace, url: str) -> Optional[Dict]:
    """The saved page with the traced chunks it lacks drawn into it.

    The saved MHTML stays byte-for-byte what Chromium wrote, except its main
    HTML part, which gains -- before `</body>` -- every chunk of which the
    saved page's own text holds less than half (`CHUNK_MISSING`), in document
    order and marked as traced. The saved layout is kept; only what it does
    not carry is added. Nothing here touches a live page: the file is ours."""
    t0 = time.perf_counter()
    raw = load_page(workspace, url)
    root = _dir(workspace)
    if raw is None or root is None:
        return None
    meta = json.loads((root / (page_key(url) + ".json")).read_text(encoding="utf-8"))
    have = _words(meta.get("text") or "")
    chunks = sorted(workspace.store.chunks(url), key=lambda c: (c.row, c.xpath, c.part))
    forms = snapshots.load_page_forms(workspace, url)
    pics: Dict = {"asked": 0, "held": 0}
    added: List[str] = []
    for c in chunks:
        w = _chunk_words(c, forms.get(c.cid))
        if len(w) < 3 or len(w - have) / len(w) < CHUNK_MISSING:
            continue
        drawn, _how = _chunk_html(workspace, c, forms.get(c.cid), pics)
        if drawn:
            added.append(drawn)
    block = ('<div class="dv-infill" style="border-top:2px dashed #888;margin:24px 0 0;padding:8px 16px;'
             'font:15px/1.5 system-ui,sans-serif"><div class="dv-infill-note" style="font:12px system-ui;color:#555">'
             'Offline: %d chunks the saved page did not carry, infilled from the scan trace</div>%s</div>'
             % (len(added), "".join(added)))
    body = _put_in_html_part(raw, block) if added else raw
    return {"mhtml": body if body is not None else raw, "added": len(added), "chunks": len(chunks),
            "pictures": pics, "placed": body is not None,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


def _put_in_html_part(raw: bytes, block: str) -> Optional[bytes]:
    """`block` inserted before `</body>` of the MHTML's FIRST part (Chromium
    writes the main document first), re-encoded as the part was."""
    m = _BOUNDARY.search(raw[:4096])
    if not m:
        return None
    sep = b"--" + m.group(1)
    first = raw.find(sep)
    second = raw.find(sep, first + len(sep))
    if first < 0 or second < 0:
        return None
    part = raw[first + len(sep):second]
    nl = b"\r\n"
    hdr_end = part.find(nl + nl)
    if hdr_end < 0:
        nl = b"\n"
        hdr_end = part.find(nl + nl)
    if hdr_end < 0:
        return None
    cut = hdr_end + 2 * len(nl)
    head, payload = part[:cut], part[cut:]
    if b"text/html" not in head.lower():
        return None
    qp = b"quoted-printable" in head.lower()
    doc = quopri.decodestring(payload) if qp else payload
    i = doc.lower().rfind(b"</body>")
    ins = block.encode("utf-8")
    doc = doc[:i] + ins + doc[i:] if i >= 0 else doc + ins
    enc = quopri.encodestring(doc) if qp else doc
    if qp and nl == b"\r\n":
        enc = enc.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return raw[:first + len(sep)] + head + enc.rstrip(b"\r\n") + nl + raw[second:]
