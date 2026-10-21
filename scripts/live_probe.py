"""A small CDP harness for in-app checks that must stop when the reader acts.

`Probe.ev(js)` evaluates in Obsidian's renderer (awaiting promises);
`Probe.guard()` raises `ReaderActed` once `__vertiscope.reader.idleMs()` is
smaller than the time since the probe began -- the reader touched the app.
`Probe.metrics()` reads the renderer's Performance counters. Read-mostly:
what a check changes, it restores in a `finally`.
"""
import json
import time
import urllib.request

import websocket


class ReaderActed(Exception):
    pass


class Probe:
    def __init__(self, port: int = 9222):
        targets = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=10))
        # The workspace window, never the vault picker (also an app:// page).
        pages = [t for t in targets if t["type"] == "page"]
        page = next((t for t in pages if t.get("url", "").startswith("app://") and "/index.html" in t["url"]),
                    None) or next(t for t in pages if "Obsidian" in t["title"])
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=300, suppress_origin=True)
        self.n = 0
        self.t0 = time.time()
        self.call("Performance.enable")
        idle = self.ev("__vertiscope.reader.idleMs()")
        self.idle0 = float(idle or 0) / 1000.0

    def call(self, method, **params):
        self.n += 1
        i = self.n
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == i:
                return msg.get("result", msg)

    def ev(self, js):
        r = self.call("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", str(r)))
        return r.get("result", {}).get("value")

    def guard(self):
        # Idle shorter than this probe has been running: the reader acted.
        idle = float(self.ev("__vertiscope.reader.idleMs()") or 0) / 1000.0
        if idle + 1.0 < time.time() - self.t0:
            raise ReaderActed("reader active %.1fs ago" % idle)

    def metrics(self):
        return {m["name"]: m["value"] for m in self.call("Performance.getMetrics")["metrics"]}

    def script_seconds(self, seconds):
        a = self.metrics(); time.sleep(seconds); b = self.metrics()
        return round(b["ScriptDuration"] - a["ScriptDuration"], 2)
