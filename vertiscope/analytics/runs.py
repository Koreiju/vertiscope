"""One id per process, so a row can say which run produced it.

The artifacts are append-only and carried only a wall-clock `t`, which is not
a run boundary: `affine.jsonl` holds about forty runs and its last 136 rows
span 623 minutes across several of them. Any aggregate over "the last N rows"
therefore mixes runs silently -- it produced a dedup recall of 79.51% that
measured nothing, and this project has already blamed a code edit for a dedup
change whose real cause was a seven-hour gap spanning another commit.

The id is generated once at import and never changes for the life of the
process, so every row a single invocation writes shares it and
`rows_of_latest_run` can pick exactly one.
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, Iterable, List

#: This process's run. Short because it is read by a person in a jsonl line.
RUN_ID = uuid.uuid4().hex[:12]

#: When this process started, so a run can be ordered against another.
RUN_STARTED = time.time()


def stamp(row: Dict) -> Dict:
    """Add the run identity to a row about to be written."""
    row["run"] = RUN_ID
    row["run_started"] = RUN_STARTED
    return row


def rows_of_latest_run(rows: Iterable[Dict]) -> List[Dict]:
    """Just the rows from the most recent run in an append-only artifact.

    Falls back to every row when nothing carries a `run`, so files written
    before this existed still read -- but a caller that cares about a single
    run should check `runs_in`, because that fallback is exactly the mixing
    this exists to prevent.
    """
    rows = list(rows)
    stamped = [r for r in rows if r.get("run")]
    if not stamped:
        return rows
    newest = max(stamped, key=lambda r: (r.get("run_started") or 0,
                                         r.get("t") or 0))["run"]
    return [r for r in stamped if r.get("run") == newest]


def runs_in(rows: Iterable[Dict]) -> int:
    """How many distinct runs an artifact holds. 0 means none are stamped."""
    return len({r["run"] for r in rows if r.get("run")})
