"""Nothing outside the graph store touches its kuzu connection (`D-23`).

`GraphStore._execute` and `_rows` hold `_db_lock` around every statement so
that "is this safe from another thread" has one answer. `ingest_chunks` wrote
the page row with `store.conn.execute(...)` directly: it held the sidecar's
work lock, which GET handlers do not take, so a read could be inside kuzu on
the same connection at the same time, and the result was never drained. The
sidecar segfaults natively in kuzu under load; this was the one hole in the
serialisation. Checked on the SOURCE, so a new bypass fails here before it
can fail in a crash with no traceback.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "vertiscope"
#: The kuzu store itself, and `store.py`, which is a separate sqlite store.
ALLOWED = {"graphstore.py", "store.py"}
RAW = re.compile(r"\.conn\.(execute|executemany)\s*\(")


def test_no_module_calls_the_kuzu_connection_directly():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if path.name in ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RAW.search(line):
                offenders.append("%s:%d" % (path.relative_to(ROOT.parent), n))
    assert not offenders, (
        "raw kuzu calls bypass the store's lock (use store._execute / "
        "store._rows): %s" % offenders)
