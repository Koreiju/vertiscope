"""Tool calls as runs of the dependency graph (THROUGH_STACK_SYNTHESIS 1c)."""

from domvec.obsidian import sidecar


class _Store:
    def __init__(self):
        self.runs = []

    def record_run(self, note, line, code, inputs, ok, output):
        self.runs.append((note, line, code, list(inputs), ok, output))
        return "rid%d" % len(self.runs)


class _WS:
    read_only = False

    def __init__(self):
        self.store = _Store()


def test_a_call_is_a_run_keyed_by_its_caller_with_its_chunks():
    ws = _WS()
    rid = sidecar.record_call(ws, "mcp://browse", "browse(query='trie')", [("result1", "c1"), ("result2", None)], True, "ok")
    assert rid == "rid1"
    note, line, code, inputs, ok, _ = ws.store.runs[0]
    assert (note, line, code, ok) == ("mcp://browse", -1, "browse(query='trie')", True)
    assert inputs == [("result1", "c1")]                      # a missing chunk is no input


def test_planted_no_call_runs_records_nothing():
    ws = _WS()
    sidecar.PLANT_NO_CALL_RUNS[0] = True
    try:
        assert sidecar.record_call(ws, "mcp://browse", "browse()", [("r", "c")], True, "") is None
    finally:
        sidecar.PLANT_NO_CALL_RUNS[0] = False
    assert ws.store.runs == []


def test_a_read_only_store_and_a_failing_store_never_fail_the_call():
    ws = _WS()
    ws.read_only = True
    assert sidecar.record_call(ws, "x", "y()", [], True, "") is None

    class _Bad(_WS):
        def __init__(self):
            self.store = self

        def record_run(self, *a):
            raise RuntimeError("store busy")
    assert sidecar.record_call(_Bad(), "x", "y()", [], True, "") is None


def test_call_text_names_only_what_was_given():
    assert sidecar._call_text("browse", {"query": "trie", "scope": "web", "of": "", "up": False, "k": 10}) == \
        "browse(query='trie', scope='web', k=10)"
