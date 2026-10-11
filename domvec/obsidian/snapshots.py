"""Each chunk's PAGE FORM, saved at scan time (2026-10-10, PLUGIN_GOAL 51).

"I should also never see the notification that something that we have
already chunked and tracked is inaccessible. All the data must be saved and
mapped fully and comprehensively across representations in our graph
database ... so that even when the connection isn't present, we still can
render the originally scanned chunk before the shadow scripts removed the
informations."

In the trie's terms: a chunk is a span of `url : xpath` leaves, and its page
form is how the page drew that span when it was scanned -- the cloned
elements with their computed styles (`snapshotscript.ts`). The browser cell
takes it while the elements are on the page and hands it here; it is kept as
a content-addressed blob under the workspace and MAPPED in the graph by one
property, `Chunk.snap` (the blob's hash). A panel asks the live page first and
this second, so a chunk that scrolled out of a list, a page that is gone, or a
page whose scripts removed the elements still renders as scanned.

Blobs, not a Kuzu column, because the store is the slow side: a capture's
address upserts already take tens of seconds on the 40 GB store (G-121), and
a page form is 2-50 KB of HTML per chunk. The graph holds the 40-character
mapping; the bytes sit beside it, gzipped, written once per distinct form.
"""

import gzip
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

#: The fields a saved page form keeps (`Snapshot` in snapshot.ts).
FIELDS = ("html", "bg", "color", "font", "elements", "found", "url", "at")
#: A form larger than this is not kept: a chunk that big is a page's whole app
#: root, and its clone is not a panel anyone can read.
MAX_BYTES = 2 << 20


def _dir(workspace) -> Optional[Path]:
    base = getattr(workspace, "path", None)
    return Path(base) / "snapshots" if base else None


def _blob(root: Path, h: str) -> Path:
    return root / h[:2] / (h + ".json.gz")


def save(workspace, items: Iterable[Dict]) -> Dict:
    """Write each `{cid, snap}` and map it on its Chunk. Returns counts.

    Idempotent: an unchanged form re-hashes to the blob already written."""
    root = _dir(workspace)
    out = {"asked": 0, "written": 0, "same": 0, "skipped": 0, "mapped": 0}
    if root is None:
        return dict(out, error="no workspace path")
    rows: List[Dict] = []
    for it in items:
        out["asked"] += 1
        cid, snap = (it or {}).get("cid"), (it or {}).get("snap")
        if not cid or not isinstance(snap, dict) or not snap.get("html"):
            out["skipped"] += 1
            continue
        doc = {k: snap.get(k) for k in FIELDS}
        data = json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(data) > MAX_BYTES:
            out["skipped"] += 1
            continue
        h = hashlib.sha1(data).hexdigest()
        path = _blob(root, h)
        if path.exists():
            out["same"] += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(data, 6))
            tmp.replace(path)
            out["written"] += 1
        rows.append({"cid": cid, "h": h})
    if rows:
        workspace.store._batch(
            "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.snap = r.h", rows)
        out["mapped"] = len(rows)
    return out


def load(workspace, cid: str) -> Optional[Dict]:
    """The saved page form of `cid`, or None if it was never saved."""
    root = _dir(workspace)
    if root is None or not cid:
        return None
    rows = workspace.store._rows("MATCH (c:Chunk {cid: $cid}) RETURN c.snap", {"cid": cid})
    h = rows[0][0] if rows and rows[0] else None
    if not h:
        return None
    path = _blob(root, h)
    if not path.exists():
        return None
    try:
        doc = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except Exception:                               # noqa: BLE001
        return None
    doc["saved"] = h
    return doc


def load_page_forms(workspace, url: str) -> Dict[str, Dict]:
    """Every saved page form of a page, by cid -- ONE query, not one a chunk.

    The offline page read each chunk's form with its own query: 15-36 s to
    open a page of 183-228 chunks (2026-10-11, `G-62`)."""
    root = _dir(workspace)
    out: Dict[str, Dict] = {}
    if root is None or not url:
        return out
    for cid, h in workspace.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.cid, c.snap", {"u": url}):
        if not h:
            continue
        path = _blob(root, h)
        if not path.exists():
            continue
        try:
            doc = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        except Exception:                           # noqa: BLE001
            continue
        doc["saved"] = h
        out[cid] = doc
    return out


def coverage(workspace, url: str) -> Dict:
    """How many of a page's chunks have a saved page form."""
    rows = workspace.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.snap", {"u": url})
    return {"url": url, "chunks": len(rows), "saved": sum(1 for (h,) in rows if h)}


# -- media: the pictures a saved page form draws ---------------------------
#
# "Even media" (2026-10-10). A page form keeps each picture's absolute url,
# so with the connection down it drew empty frames. The pictures themselves
# are kept as blobs keyed by their url's hash, and a saved form read back
# points every picture that has one at the sidecar's own copy.

#: One picture at most this large; a page's pictures at most this many bytes.
MEDIA_MAX = 8 << 20
_MEDIA_TYPES = ("image/", "video/", "audio/")


def _media_dir(workspace) -> Optional[Path]:
    base = getattr(workspace, "path", None)
    return Path(base) / "media" if base else None


def media_key(url: str) -> str:
    return hashlib.sha1(str(url or "").encode("utf-8")).hexdigest()


def save_media(workspace, url: str, data: bytes, content_type: str) -> Dict:
    root = _media_dir(workspace)
    if root is None or not url or not data:
        return {"saved": False, "why": "nothing to save"}
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ct.startswith(_MEDIA_TYPES):
        return {"saved": False, "why": "not media: %s" % ct}
    if len(data) > MEDIA_MAX:
        return {"saved": False, "why": "too large: %d" % len(data)}
    h = media_key(url)
    path = root / h[:2] / (h + ".bin")
    if path.exists():
        return {"saved": True, "same": True, "key": h}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    (root / h[:2] / (h + ".ct")).write_text(ct, encoding="utf-8")
    return {"saved": True, "key": h, "bytes": len(data)}


def load_media(workspace, key: str):
    """(bytes, content type) of a saved picture, or None."""
    root = _media_dir(workspace)
    if root is None or not key or not all(c in "0123456789abcdef" for c in key):
        return None
    path = root / key[:2] / (key + ".bin")
    if not path.exists():
        return None
    ct_path = root / key[:2] / (key + ".ct")
    ct = ct_path.read_text(encoding="utf-8") if ct_path.exists() else "application/octet-stream"
    return path.read_bytes(), ct


def has_media(workspace, url: str) -> bool:
    root = _media_dir(workspace)
    if root is None:
        return False
    h = media_key(url)
    return (root / h[:2] / (h + ".bin")).exists()


def localize(workspace, doc: Dict, sidecar_base: str) -> Dict:
    """A saved form whose pictures point at the sidecar's copies where it has
    them; the page's own url where it does not."""
    import re
    html = str(doc.get("html") or "")
    count = {"local": 0, "remote": 0}

    def swap(m):
        u = m.group(2)
        if has_media(workspace, u):
            count["local"] += 1
            return m.group(1) + sidecar_base.rstrip("/") + "/media/" + media_key(u) + m.group(3)
        count["remote"] += 1
        return m.group(0)

    doc = dict(doc)
    doc["html"] = re.sub(r"""(<(?:img|video|audio|source)\b[^>]*?\bsrc=["'])([^"']+)(["'])""", swap, html)
    doc["media"] = count
    return doc


def media_urls(html: str) -> List[str]:
    """The absolute picture urls a page form draws."""
    import re
    return sorted({u for u in re.findall(r"""<(?:img|video|audio|source)\b[^>]*?\bsrc=["'](https?://[^"']+)["']""", html or "")})
