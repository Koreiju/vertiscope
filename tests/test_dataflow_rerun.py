"""G-380: the re-run plan -- running a cell re-runs the cells that read its names.

Planted arm: PLANT_NO_READERS leaves the readers stale.
"""

from domvec import dataflow as df

F = "`" * 3
NOTE = "\n".join([
    "# a note", "",
    F + "python", "x = 21", F, "",                       # 2
    F + "python", "y = x * 2", F, "",                    # 6
    F + "python", "print('Y', y)", F, "",                # 10
    F + "python", "z = 5", F, "",                        # 14
])


def test_readers_rerun_in_order_and_unrelated_cells_do_not():
    plan = df.rerun_plan(NOTE, 2)
    assert [r["open_line"] for r in plan["rerun"]] == [6, 10]
    assert plan["rerun"][0]["reads"] == ["x"] and plan["rerun"][0]["source"] == "y = x * 2"
    assert df.rerun_plan(NOTE, 14)["rerun"] == []


def test_planted_no_readers_is_caught(monkeypatch):
    monkeypatch.setattr(df, "PLANT_NO_READERS", [True])
    assert df.rerun_plan(NOTE, 2)["rerun"] == []


def test_a_cell_in_a_problem_is_refused_not_run_around():
    twice = NOTE + "\n" + F + "python\nx = 3\n" + F + "\n"
    plan = df.rerun_plan(twice, 2)
    assert plan["rerun"] == [] and plan["problems"][0]["kind"] == "MultipleDefinitionError"


def test_no_cell_at_the_line():
    assert df.rerun_plan(NOTE, 0)["error"]


def test_the_route_answers_the_same_plan(tmp_path):
    import json
    import urllib.request
    from domvec.obsidian import sidecar as sc
    from domvec.workspace import Workspace
    with Workspace(tmp_path / "ws") as ws:
        srv = sc.serve(ws, port=0, block=False)
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/dataflow" % srv.server_address[1],
                                         data=json.dumps({"markdown": NOTE, "line": 2}).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                got = json.load(r)
        finally:
            srv.shutdown(); srv.server_close()
    assert [x["open_line"] for x in got["rerun"]] == [6, 10]
