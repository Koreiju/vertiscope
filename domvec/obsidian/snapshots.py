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


def coverage(workspace, url: str) -> Dict:
    """How many of a page's chunks have a saved page form."""
    rows = workspace.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.snap", {"u": url})
    return {"url": url, "chunks": len(rows), "saved": sum(1 for (h,) in rows if h)}
