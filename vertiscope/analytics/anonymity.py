"""What each anti-tracking measure costs in fidelity, as a number.

`vertiscope.privacy` protects the STORE from the page: `redact_url` strips
campaign tags and credentials before a url reaches the database. Nothing
protects the session from the page. Loading a document runs its JavaScript --
which is how the composed tree and the layout come to exist at all -- and its
telemetry fires with it. The corpus is the evidence: 44 of its saved pages
carry live Sentry DSNs and CSRF tokens, which exist only because that
telemetry ran while the page was read.

So "never tracked" and "what a reader sees is what the REPL gets" are in real
tension, and the tension is not uniform. Some measures the page cannot
detect. Others change what the page *does*, and a page that behaves
differently is a different document -- `build_driver` already says it: "the
profile is a measuring instrument and a corpus read under two different
profiles is two corpora."

This decides which is which by measuring instead of arguing. Each arm folds
the same page twice -- once with the baseline profile, once hardened -- and
diffs the two folds. An arm whose addresses and values are identical is free.
An arm that moves them has a price, and the price is reported rather than
assumed.

The comparison needs no ground truth, which is the point: it is the same
question `drift` asks of a sensor against a second sensor, pointed at a
profile instead.

    python -m vertiscope.analytics --anonymity
    python -m vertiscope.analytics --anonymity --arm resist_fingerprinting
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from typing import Dict, List, Optional, Sequence

from .runs import stamp

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")

#: Each arm is a set of Firefox preferences and a claim about what it buys.
#: Ordered from what should be free toward what should not be.
ARMS: Dict[str, Dict[str, object]] = {
    "null": {
        "_buys": "NOTHING -- the control. Any arm must beat this to count.",
    },
    "offline": {
        "_buys": "a saved page is read as saved, reaching no server at all",
        # Firefox's own offline mode. On a `file://` corpus page this is the
        # difference between reading the snapshot and re-hydrating it from
        # whatever those hosts serve today.
        "network.dns.offline-localhost": True,
        "browser.offline": True,
        "network.online": False,
    },
    "no_referer": {
        "_buys": "the page is not told which page sent us",
        "network.http.sendRefererHeader": 0,
    },
    "do_not_track": {
        "_buys": "an explicit request not to be tracked (advisory only)",
        "privacy.donottrackheader.enabled": True,
        "privacy.globalprivacycontrol.enabled": True,
    },
    "no_cookies": {
        "_buys": "nothing can be stored to recognise us on a later visit",
        "network.cookie.cookieBehavior": 2,
    },
    "block_trackers": {
        "_buys": "known trackers never load, so beacons never fire",
        "privacy.trackingprotection.enabled": True,
        "privacy.trackingprotection.socialtracking.enabled": True,
        "privacy.trackingprotection.cryptomining.enabled": True,
        "privacy.trackingprotection.fingerprinting.enabled": True,
    },
    "resist_fingerprinting": {
        "_buys": "screen, timezone, canvas and fonts stop identifying us",
        "privacy.resistFingerprinting": True,
    },
    "first_party_isolate": {
        "_buys": "state cannot be joined across sites",
        "privacy.firstparty.isolate": True,
    },
    "no_beacons": {
        "_buys": "sendBeacon and ping cannot report on the way out",
        "beacon.enabled": False,
        "browser.send_pings": False,
    },
    "no_prefetch": {
        "_buys": "we do not fetch pages we never read, telling a site we "
                 "intended to",
        "network.prefetch-next": False,
        "network.dns.disablePrefetch": True,
        "network.predictor.enabled": False,
        "network.http.speculative-parallel-limit": 0,
    },
    "no_webrtc": {
        "_buys": "no STUN candidate can reveal the real address behind a "
                 "proxy",
        "media.peerconnection.enabled": False,
    },
    "partition_state": {
        "_buys": "cache, ETags and connections cannot be reused as an "
                 "identifier across sites",
        "privacy.partition.network_state": True,
        "privacy.partition.serviceWorkers": True,
    },
    "no_sensors": {
        "_buys": "location, camera list and battery stop being readable",
        "geo.enabled": False,
        "media.navigator.enabled": False,
        "dom.battery.enabled": False,
    },
    "dns_over_https": {
        "_buys": "the resolver stops learning every host we visit",
        "network.trr.mode": 3,
    },
    "hide_webdriver": {
        "_buys": "the page stops being told outright that this is automation",
        "dom.webdriver.enabled": False,
        "useAutomationExtension": False,
    },
}

#: Everything above is a browser preference, and the two strongest
#: identifiers are not preferences at all. Recorded here so the harness
#: cannot be mistaken for a complete answer.
#:
#: * **The IP address.** Every arm in this file leaves it untouched, and it
#:   identifies the reader across sites, sessions and profiles regardless of
#:   what the browser is told to do. Only a proxy, VPN or Tor changes it, and
#:   that is infrastructure rather than a flag.
#: * **Behaviour.** The scroller steps and the REPL presses at machine
#:   cadence, from a viewport that never varies. That is a fingerprint no
#:   preference removes, and unlike the others it is produced BY the design:
#:   a reader who never moves the mouse is unusual.
#:
#: A third is only half a browser question: what we type. `Field << text`
#: sends that text to the site, and the refusal set governs which controls
#: may be enacted, not what a query reveals about the reader.
NOT_A_PREFERENCE = ("ip_address", "interaction_cadence", "typed_queries")


def _fold(driver, url: str, window: int):
    """One fold, as the interface would do it. Returns address -> value."""
    from ..sensing import Sensor
    from ..stream import StreamingScan
    import time as clock

    driver.get("about:blank")
    driver.get(url)
    clock.sleep(1.4)
    sensor = Sensor(driver, url, budget=window)
    sensor.boot()
    clock.sleep(0.5)
    spine = StreamingScan(url, context_window=window)
    for _ in range(10):
        delta = sensor.drain(0)
        spine.absorb(delta.units, delta.passno,
                     removed=delta.removed_addresses,
                     moved=delta.moved_addresses)
        if delta.settled and not delta.units:
            break
        clock.sleep(0.25)
    return {leaf.address.key(): (leaf.value or "")
            for leaf in spine.trie.leaves() if leaf.address is not None}


def score_arm(base: Dict[str, str], armed: Dict[str, str]) -> dict:
    """How much of the fold the hardening moved.

    Three numbers because they mean different things. An address the arm
    LOSES is content a reader would have had; one it GAINS is usually a
    consent wall or a placeholder appearing in place of something blocked;
    a value that CHANGED is the same address saying something else.
    """
    lost = set(base) - set(armed)
    gained = set(armed) - set(base)
    shared = set(base) & set(armed)
    changed = [k for k in shared if base[k] != armed[k]]
    total = len(base) or 1
    return {
        "baseline_addresses": len(base),
        "armed_addresses": len(armed),
        "lost": len(lost),
        "gained": len(gained),
        "value_changed": len(changed),
        "identical": not (lost or gained or changed),
        "drift_pct": round(100.0 * (len(lost) + len(gained) + len(changed))
                           / total, 3),
        "lost_sample": sorted(lost)[:4],
        "changed_sample": sorted(changed)[:4],
    }


def measure_anonymity(urls: Sequence[str], *, window: int = 1200,
                      arms: Optional[Sequence[str]] = None) -> dict:
    """Fold every page once per arm, against a baseline fold of the same page."""
    from ..browser import browser_session
    from ..config import load_config

    wanted = list(arms) if arms else list(ARMS)
    cfg = load_config()
    rows: List[dict] = []

    # The null arm first, so its figure is available to read every other
    # against. An instrument without a control reports the page's own
    # movement as its own effect -- `drift` learned this the hard way and
    # this harness shipped without it.
    if "null" in ARMS and "null" not in wanted:
        wanted = ["null"] + wanted

    for name in wanted:
        arm = ARMS[name]
        prefs = {k: v for k, v in arm.items() if not k.startswith("_")}
        for url in urls:
            row: Dict[str, object] = {"arm": name, "url": url,
                                      "buys": arm.get("_buys", "")}
            try:
                # A fresh browser for each side, because a preference cannot
                # be changed on a live profile and a reused one would carry
                # the first read's state into the second.
                with browser_session(cfg) as driver:
                    base = _fold(driver, url, window)
                with browser_session(cfg, prefs=prefs) as driver:
                    armed = _fold(driver, url, window)
                row.update(score_arm(base, armed))
            except Exception as exc:                   # noqa: BLE001
                row["error"] = "%s: %s" % (type(exc).__name__, exc)[:160]
            rows.append(row)
            print("  [%-22s] %-44s %s" % (
                name, url.rsplit("/", 1)[-1][:44],
                row.get("error") or "drift %.2f%%" % row["drift_pct"]),
                file=sys.stderr, flush=True)
    return {"rows": rows, "t": time.time(), "context_window": window}


def render_anonymity_table(report: dict) -> str:
    rows = [r for r in report.get("rows", []) if not r.get("error")]
    if not rows:
        return "  no anonymity measurements"

    by_arm: Dict[str, List[dict]] = {}
    for row in rows:
        by_arm.setdefault(str(row["arm"]), []).append(row)

    out = ["", "  what each anti-tracking measure costs the fold", ""]
    out.append("  %-24s %7s %8s %8s %9s %9s"
               % ("arm", "pages", "lost", "gained", "changed", "drift"))
    for name, group in by_arm.items():
        lost = sum(r["lost"] for r in group)
        gained = sum(r["gained"] for r in group)
        changed = sum(r["value_changed"] for r in group)
        base = sum(r["baseline_addresses"] for r in group) or 1
        out.append("  %-24s %7d %8d %8d %9d %8.2f%%"
                   % (name, len(group), lost, gained, changed,
                      100.0 * (lost + gained + changed) / base))
    # Everything is read against the null arm: two folds of the same page
    # with nothing changed. A page that fetches live resources moves between
    # reads, so an arm that drifts no more than the control has not been
    # shown to do anything at all.
    null = by_arm.get("null")
    floor = 0.0
    if null:
        base = sum(r["baseline_addresses"] for r in null) or 1
        floor = 100.0 * sum(r["lost"] + r["gained"] + r["value_changed"]
                            for r in null) / base
        out.append("")
        out.append("  the page's own movement, with NOTHING changed: %.2f%%"
                   % floor)
        out.append("  An arm at or under that has not been shown to cost "
                   "anything.")
    out.append("")
    free = [n for n, g in by_arm.items() if all(r["identical"] for r in g)]
    if free:
        out.append("  FREE (the fold is byte-identical): %s" % ", ".join(free))
    else:
        out.append("  No arm was free on every page.")
    out.append("")
    out.append("  What each arm buys:")
    for name in by_arm:
        out.append("    %-24s %s" % (name, ARMS[name].get("_buys", "")))
    out.append("")
    out.append("  A page reads its own profile, so hardening can change what")
    out.append("  the page DOES -- a consent wall, an anti-adblock gate, a")
    out.append("  different layout under a spoofed viewport. `lost` is content")
    out.append("  a reader would have had; `gained` is usually a wall")
    out.append("  appearing where content was. Both are the price, and the")
    out.append("  point of measuring is that some arms have none.")
    return chr(10).join(out)


def write_anonymity_artifact(report: dict,
                             out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
                             ) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "anonymity.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = stamp(dict(row))
            record["t"] = report.get("t")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
