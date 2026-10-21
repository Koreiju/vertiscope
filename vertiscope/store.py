"""Persistence: SQLite for records, ``GlobalTfidfStore`` for the vector index.

The original backend persisted to Kuzu (a graph DB) because chunks were
nodes in a wider concept graph. Nothing in the scrape/chunk/retrieve loop
needs graph traversal, so this uses SQLite: zero setup, one file, and
``rendered_text`` / ``html_raw`` land in the same place the ranking scores
point at.

Two stores are kept in step by :class:`Store`:

* ``vertiscope.sqlite3``  — pages, scans, instances (the record of truth)
* ``tfidf_index/``    — the incremental TF-IDF matrix (the ranking surface)

``Store`` is a context manager; use it as ``with Store(cfg) as st:``.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .config import Config
from .core.global_tfidf_store import ChunkMeta, GlobalTfidfStore, SearchHit

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url             TEXT PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT '',
    first_scraped   REAL NOT NULL,
    last_scraped    REAL NOT NULL,
    scrape_count    INTEGER NOT NULL DEFAULT 0,
    instance_count  INTEGER NOT NULL DEFAULT 0,
    html_path       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS scans (
    scan_id         TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    snapshot_id     TEXT NOT NULL,
    started_at      REAL NOT NULL,
    elapsed_ms      REAL NOT NULL DEFAULT 0,
    html_bytes      INTEGER NOT NULL DEFAULT 0,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    instance_count  INTEGER NOT NULL DEFAULT 0,
    pattern_count   INTEGER NOT NULL DEFAULT 0,
    stages_json     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS instances (
    instance_id     TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    scan_id         TEXT NOT NULL,
    chunk_id        TEXT NOT NULL DEFAULT '',
    pattern         TEXT NOT NULL DEFAULT '',
    absolute_xpath  TEXT NOT NULL DEFAULT '',
    instance_idx    INTEGER NOT NULL DEFAULT 0,
    rendered_text   TEXT NOT NULL DEFAULT '',
    html_raw        TEXT NOT NULL DEFAULT '',
    fields_json     TEXT NOT NULL DEFAULT '{}',
    char_count      INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_instances_url     ON instances(url);
CREATE INDEX IF NOT EXISTS idx_instances_scan    ON instances(scan_id);
CREATE INDEX IF NOT EXISTS idx_instances_pattern ON instances(pattern);
CREATE INDEX IF NOT EXISTS idx_scans_url         ON scans(url);
"""


@dataclass
class InstanceRecord:
    """One rendered chunk instance as persisted."""

    instance_id: str
    url: str
    scan_id: str
    chunk_id: str
    pattern: str
    absolute_xpath: str
    instance_idx: int
    rendered_text: str
    html_raw: str
    fields_json: str
    char_count: int
    created_at: float

    @property
    def fields(self) -> Dict[str, Any]:
        try:
            return json.loads(self.fields_json or "{}")
        except json.JSONDecodeError:
            return {}


class Store:
    """SQLite + TF-IDF index, kept transactionally in step."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.ensure_dirs()
        self.conn = sqlite3.connect(str(cfg.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._tfidf: Optional[GlobalTfidfStore] = None

    # -- lifecycle --------------------------------------------------------
    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._tfidf is not None:
                self._tfidf.save()
        finally:
            self.conn.close()

    @property
    def tfidf(self) -> GlobalTfidfStore:
        """Lazily open the TF-IDF index (cold load costs real time).

        ``GlobalTfidfStore.__init__`` already loads from disk and treats a
        missing index as an empty first-run store, so we must NOT call
        ``load()`` again here — that second call bypasses the constructor's
        ``FileNotFoundError`` guard and blows up on a fresh install.
        """
        if self._tfidf is None:
            self._tfidf = GlobalTfidfStore(str(self.cfg.index_dir))
        return self._tfidf

    # -- writes -----------------------------------------------------------
    def record_scan(
        self,
        *,
        scan_id: str,
        url: str,
        snapshot_id: str,
        elapsed_ms: float,
        html_bytes: int,
        chunk_count: int,
        instance_count: int,
        pattern_count: int,
        stages: Optional[Dict[str, float]] = None,
        html_path: str = "",
        title: str = "",
    ) -> None:
        now = time.time()
        self.conn.execute(
            "INSERT OR REPLACE INTO scans (scan_id, url, snapshot_id, started_at,"
            " elapsed_ms, html_bytes, chunk_count, instance_count, pattern_count,"
            " stages_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (scan_id, url, snapshot_id, now, elapsed_ms, html_bytes, chunk_count,
             instance_count, pattern_count, json.dumps(stages or {})),
        )
        row = self.conn.execute(
            "SELECT first_scraped, scrape_count FROM pages WHERE url = ?", (url,)
        ).fetchone()
        first = row["first_scraped"] if row else now
        count = (row["scrape_count"] if row else 0) + 1
        total = self.conn.execute(
            "SELECT COUNT(*) c FROM instances WHERE url = ?", (url,)
        ).fetchone()["c"]
        self.conn.execute(
            "INSERT OR REPLACE INTO pages (url, title, first_scraped, last_scraped,"
            " scrape_count, instance_count, html_path) VALUES (?,?,?,?,?,?,?)",
            (url, title, first, now, count, total, html_path),
        )
        self.conn.commit()

    def upsert_instances(self, records: Sequence[InstanceRecord]) -> int:
        """Write instance rows; return the number of rows actually written.

        Records sharing an ``instance_id`` collapse to one row — by
        THEORY-22.5.7 that is forced, since a content-keyed identifier cannot
        distinguish content-identical siblings. The count returned is therefore
        the number of *distinct* identifiers, not the number of records offered.

        This previously returned ``len(records)``, which over-reported whenever
        any collapse occurred — measured at 9.2% on a real page. The collapse
        itself is a separate matter: by THEORY Remark 22.5.9 it is lossless only
        if the multiplicity is retained somewhere, and it currently is not.
        """
        if not records:
            return 0
        self.conn.executemany(
            "INSERT OR REPLACE INTO instances (instance_id, url, scan_id, chunk_id,"
            " pattern, absolute_xpath, instance_idx, rendered_text, html_raw,"
            " fields_json, char_count, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (r.instance_id, r.url, r.scan_id, r.chunk_id, r.pattern,
                 r.absolute_xpath, r.instance_idx, r.rendered_text, r.html_raw,
                 r.fields_json, r.char_count, r.created_at)
                for r in records
            ],
        )
        self.conn.commit()
        return len({r.instance_id for r in records})

    def index_instances(self, records: Sequence[InstanceRecord]) -> int:
        """Feed instances into the TF-IDF index. Returns rows touched.

        Empty ``rendered_text`` is skipped — an unindexable row would only
        dilute IDF.
        """
        texts: List[str] = []
        metas: List[ChunkMeta] = []
        for r in records:
            text = (r.rendered_text or "").strip()
            if not text:
                continue
            texts.append(text)
            metas.append(
                ChunkMeta(
                    chunk_id=r.instance_id,
                    url=r.url,
                    snapshot_id=r.scan_id,
                    absolute_xpath=r.absolute_xpath,
                    instance_idx=r.instance_idx,
                    pattern=r.pattern,
                    text_preview=text[:280],
                )
            )
        if not texts:
            return 0
        touched = self.tfidf.add_chunks(texts, metas)
        self.tfidf.save()
        return touched

    def save_html(self, snapshot_id: str, html: str) -> str:
        """Archive the raw scanned HTML; returns the path written."""
        path = self.cfg.html_dir / f"{snapshot_id}.html"
        path.write_text(html, encoding="utf-8", errors="replace")
        return str(path)

    # -- reads ------------------------------------------------------------
    def search(
        self, query: str, k: int = 10, urls: Optional[Sequence[str]] = None
    ) -> List[SearchHit]:
        return self.tfidf.search(query, k=k, urls=urls)

    def get_instance(self, instance_id: str) -> Optional[InstanceRecord]:
        row = self.conn.execute(
            "SELECT * FROM instances WHERE instance_id = ?", (instance_id,)
        ).fetchone()
        return _row_to_instance(row) if row else None

    def get_instances(self, instance_ids: Iterable[str]) -> Dict[str, InstanceRecord]:
        ids = list(instance_ids)
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM instances WHERE instance_id IN ({marks})", ids
        ).fetchall()
        return {r["instance_id"]: _row_to_instance(r) for r in rows}

    def instances_for_url(self, url: str, limit: int = 0) -> List[InstanceRecord]:
        sql = "SELECT * FROM instances WHERE url = ? ORDER BY instance_idx"
        params: List[Any] = [url]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [_row_to_instance(r) for r in self.conn.execute(sql, params)]

    def list_pages(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pages ORDER BY last_scraped DESC"
        ).fetchall()

    def stats(self) -> Dict[str, Any]:
        c = self.conn.execute
        return {
            "pages": c("SELECT COUNT(*) n FROM pages").fetchone()["n"],
            "scans": c("SELECT COUNT(*) n FROM scans").fetchone()["n"],
            "instances": c("SELECT COUNT(*) n FROM instances").fetchone()["n"],
            "patterns": c(
                "SELECT COUNT(DISTINCT pattern) n FROM instances"
            ).fetchone()["n"],
            "indexed_rows": self.tfidf.doc_count,
            "vocab_size": self.tfidf.vocab_size,
            "db_bytes": self.cfg.db_path.stat().st_size
            if self.cfg.db_path.exists() else 0,
            "home": str(self.cfg.home),
        }

    # -- deletes ----------------------------------------------------------
    def purge_url(self, url: str) -> int:
        """Drop one URL from both stores. Returns instances removed."""
        ids = [
            r["instance_id"]
            for r in self.conn.execute(
                "SELECT instance_id FROM instances WHERE url = ?", (url,)
            )
        ]
        if ids:
            self.tfidf.remove_chunks(ids)
            self.tfidf.save()
        self.conn.execute("DELETE FROM instances WHERE url = ?", (url,))
        self.conn.execute("DELETE FROM scans WHERE url = ?", (url,))
        self.conn.execute("DELETE FROM pages WHERE url = ?", (url,))
        self.conn.commit()
        return len(ids)

    def purge_all(self) -> int:
        n = self.conn.execute("SELECT COUNT(*) c FROM instances").fetchone()["c"]
        self.tfidf.clear_all()
        self.tfidf.save()
        for table in ("instances", "scans", "pages"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        return n


def _row_to_instance(row: sqlite3.Row) -> InstanceRecord:
    return InstanceRecord(
        instance_id=row["instance_id"],
        url=row["url"],
        scan_id=row["scan_id"],
        chunk_id=row["chunk_id"],
        pattern=row["pattern"],
        absolute_xpath=row["absolute_xpath"],
        instance_idx=row["instance_idx"],
        rendered_text=row["rendered_text"],
        html_raw=row["html_raw"],
        fields_json=row["fields_json"],
        char_count=row["char_count"],
        created_at=row["created_at"],
    )
