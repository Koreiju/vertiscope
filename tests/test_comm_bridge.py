"""G-408, the comm bridge (spec 13e): a live object's comm traffic reaches the
plugin, and the plugin's messages reach the object.

In trie terms: nothing is written; the log is a kernel's live state, read by
sequence number. Planted arm: the iopub pump drops comm traffic, and the log
stays empty while the cell itself still runs.
"""
import time

import pytest

from domvec.obsidian import kernel as K

pytestmark = pytest.mark.skipif(not K.jupyter_available(), reason="needs a Jupyter kernel")

OPEN = (
    "from comm import create_comm\n"
    "got = {}\n"
    "c = create_comm(target_name='domvec.test', data={'v': 1})\n"
    "c.on_msg(lambda m: got.update(m['content']['data']))\n"
    "c.send({'v': 2})\n"
    "c.comm_id"
)


def _bridge(planted: bool):
    K.PLANT_NO_COMM_READER[0] = planted
    pool = K.KernelPool(timeout=30.0, max_kernels=1)
    try:
        reply = pool.run("n.md", OPEN)
        assert reply["ok"], reply
        log = pool.comm("n.md", since=0, wait=2.0)
        cid = reply["value"].strip("'")
        pool.comm("n.md", send={"comm_id": cid, "data": {"v": 3}})
        seen = None
        for _ in range(40):                       # the kernel handles it when idle
            seen = pool.run("n.md", "got.get('v')")["value"]
            if seen == "3":
                break
            time.sleep(0.1)
        return log, seen
    finally:
        pool.shutdown()
        K.PLANT_NO_COMM_READER[0] = False


def test_comm_traffic_both_ways():
    log, seen = _bridge(planted=False)
    kinds = [m["type"] for m in log["messages"]]
    assert "comm_open" in kinds and "comm_msg" in kinds, log
    assert any(m["type"] == "comm_open" and m["target"] == "domvec.test" for m in log["messages"])
    assert [m["data"] for m in log["messages"] if m["type"] == "comm_msg"][0] == {"v": 2}
    assert seen == "3"                            # the plugin's message reached the object


def test_planted_pump_drops_comm_traffic():
    log, _ = _bridge(planted=True)
    assert log["messages"] == [], log
