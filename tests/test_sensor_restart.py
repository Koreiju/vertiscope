"""A capture session notices that the page's sensor started over.

Reloading a page injects a new sensor whose tag dictionary restarts at 0. A
capture session that kept the old dictionary decoded the new ids against it:
every tag past the old dictionary became "?", and addresses like
``/html/*[name()='?'][1]/...`` reached the store (2026-09-27, Radix tree).
"""

from types import SimpleNamespace

from vertiscope.obsidian.sidecar import sensor_restarted


def _session(dict_len):
    return {"sensor": SimpleNamespace(_dict=["t%d" % i for i in range(dict_len)])}


def _body(size, new):
    return {"payload": {"dict": ["n%d" % i for i in range(new)], "stats": {"dictSize": size}}}


def test_a_continuing_sensor_is_not_a_restart():
    assert not sensor_restarted(_session(40), _body(45, 5))
    assert not sensor_restarted(_session(40), _body(40, 0))


def test_a_reloaded_page_is_a_restart():
    # A new sensor ships its dictionary from 0: size == what this payload adds.
    assert sensor_restarted(_session(40), _body(12, 12))


def test_settle_and_payload_free_bodies_are_left_alone():
    assert not sensor_restarted(_session(40), {"settle": True, "payload": {"dict": [], "stats": {"dictSize": 3}}})
    assert not sensor_restarted(_session(40), {"payload": None})


def test_planted_decoding_without_the_check_names_unknown_tags():
    """Non-vacuity: the defect is real -- the old dictionary cannot decode the new ids."""
    from vertiscope.sensing import Sensor
    s = Sensor(None, "https://x.test/p")
    s._dict = ["html", "body", "div"]              # the old sensor's dictionary
    fresh = ["html", "body", "main", "section", "h2"]
    s._dict.extend(fresh)                          # what appending the new one does
    # The new sensor's id 3 ("section") now names the OLD dictionary's entry 3.
    assert s._seg(3) != "section"
