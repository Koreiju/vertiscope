"""Bridge a :class:`~vertiscope.pipeline.PipelineResult` into the store.

Kept separate from both sides so ``pipeline`` stays a pure function and
``store`` stays ignorant of pipeline types.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

from .pipeline import PipelineResult
from .store import InstanceRecord, Store


@dataclass
class IngestReport:
    url: str
    scan_id: str
    instances_written: int
    rows_indexed: int
    html_path: str
    instances_rendered: int = 0
    instances_collapsed: int = 0
    """Rendered instances that shared an identifier with another and so did not
    become their own row. Forced by THEORY-22.5.7; lossless only if the
    multiplicity is retained (Remark 22.5.9), which it currently is not."""

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "scan_id": self.scan_id,
            "instances_rendered": self.instances_rendered,
            "instances_written": self.instances_written,
            "instances_collapsed": self.instances_collapsed,
            "rows_indexed": self.rows_indexed,
            "html_path": self.html_path,
        }


def _page_title(result: PipelineResult) -> str:
    """Best-effort <title>, falling back to the first heading-ish text."""
    try:
        for node in result.dom.iter_all():
            if getattr(node, "tag", "").lower() == "title":
                text = (node.get_text() or "").strip()
                if text:
                    return text[:200]
    except Exception:
        pass
    return ""


def ingest(
    store: Store,
    result: PipelineResult,
    *,
    save_html: bool = True,
    scan_id: Optional[str] = None,
) -> IngestReport:
    """Persist a pipeline result's instances and add them to the index."""
    scan_id = scan_id or result.snapshot_id
    now = time.time()

    records = [
        InstanceRecord(
            instance_id=inst.instance_id(result.url),
            url=result.url,
            scan_id=scan_id,
            chunk_id=inst.chunk_id,
            pattern=inst.pattern,
            absolute_xpath=inst.absolute_xpath,
            instance_idx=inst.instance_idx,
            rendered_text=inst.rendered_text or "",
            html_raw=inst.html_raw or "",
            fields_json=json.dumps(inst.fields or {}, ensure_ascii=False),
            char_count=len(inst.rendered_text or ""),
            created_at=now,
        )
        for inst in result.instances
    ]

    written = store.upsert_instances(records)
    indexed = store.index_instances(records)

    html_path = store.save_html(result.snapshot_id, result.html) if save_html else ""

    store.record_scan(
        scan_id=scan_id,
        url=result.url,
        snapshot_id=result.snapshot_id,
        elapsed_ms=result.elapsed_ms,
        html_bytes=len(result.html),
        chunk_count=len(result.chunks),
        instance_count=written,
        pattern_count=result.trie.version.pattern_count,
        stages=result.stage_ms,
        html_path=html_path,
        title=_page_title(result),
    )

    return IngestReport(
        url=result.url,
        scan_id=scan_id,
        instances_written=written,
        rows_indexed=indexed,
        html_path=html_path,
        instances_rendered=len(records),
        instances_collapsed=len(records) - written,
    )
