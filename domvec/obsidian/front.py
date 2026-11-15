"""The sidecar's FRONT process (PLUGIN_GOAL 143/148, step 1 of the split).

"Youll have to fix the way the sidecar is run too" (2026-11-08); the shape
the reader approved (148): "one small process always answers the plugin and
never waits; separate worker processes own the store, the embedding encoder,
and the UMAP fit".

This is that small process. It runs INSIDE the supervisor, which already
outlives every crash and restart of the working process, and it owns the
public port. The working process (`serve`) listens on an internal port.

- `/health` is answered at once from the last health the front read from
  the worker (a poller thread, every few seconds). While the worker is
  starting, restarting or stuck behind the store, the plugin still gets an
  answer -- marked `backend: starting|busy` -- instead of a refused port or a
  20 s timeout, and the launch it reports is the SUPERVISOR's (so the plugin
  never records the internal port as the sidecar to restart).
- Everything else is passed through to the worker unchanged and streamed
  back as it arrives. A worker that is down answers 503 at once.

Writes nothing, reads no store: a proxy and a cache.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional

#: The worker's port, relative to the public one.
BACKEND_OFFSET = 100

_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade"}


class _State:
    def __init__(self, backend_port: int, launch: Dict) -> None:
        self.backend_port = backend_port
        self.launch = launch
        self.health: Optional[Dict] = None
        self.health_at = 0.0
        self.backend = "starting"
        self.stats = {"proxied": 0, "health_served": 0, "refused": 0, "polls": 0}


def _poll(state: _State, stop: threading.Event, every: float = 3.0) -> None:
    while not stop.is_set():
        state.stats["polls"] += 1
        try:
            c = http.client.HTTPConnection("127.0.0.1", state.backend_port, timeout=30)
            c.request("GET", "/health")
            r = c.getresponse()
            body = json.loads(r.read() or b"{}")
            c.close()
            state.health, state.health_at, state.backend = body, time.time(), "up"
        except ConnectionRefusedError:
            state.backend = "starting"
        except Exception:                               # noqa: BLE001 -- a timeout: up, busy
            state.backend = "busy" if state.health is not None else "starting"
        stop.wait(every)


def health_body(state: _State) -> Dict:
    """The /health the front answers: the worker's last, marked with what the
    front knows now. `backend: dead` when the supervisor has seen the worker's
    fatal dump (`supervise.WORKER`) and the worker has not answered since --
    a cached `ok` from before the crash otherwise read "busy" for twenty
    minutes (2026-11-14). Planted `DOMVEC_PLANT_NO_FATAL_WATCH=1`: as before."""
    body = dict(state.health or {"ok": True})
    backend = state.backend
    from . import supervise as _sv
    w = dict(_sv.WORKER)
    fatal_at = w.get("fatal_at")
    if fatal_at and backend != "up" and state.health_at <= fatal_at and os.environ.get("DOMVEC_PLANT_NO_FATAL_WATCH") != "1":
        backend = "dead"
        body["ok"] = False
        body["worker"] = {"pid": w.get("pid"), "fatal_s_ago": round(time.time() - fatal_at, 1),
                          "unkillable": bool(w.get("unkillable_at"))}
    body.update({"backend": backend, "front": True,
                 "front_age_s": round(time.time() - state.health_at, 1) if state.health_at else None,
                 "launch": state.launch})
    return body


def _handler(state: _State):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a) -> None:          # the worker keeps the request log
            pass

        def _json(self, code: int, body: Dict) -> None:
            raw = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(raw)

        def _proxy(self) -> None:
            if self.path.split("?", 1)[0].rstrip("/") in ("", "/health") and self.command == "GET":
                state.stats["health_served"] += 1
                self._json(200, health_body(state))
                return
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP and k.lower() != "host"}
            try:
                c = http.client.HTTPConnection("127.0.0.1", state.backend_port, timeout=900)
                c.request(self.command, self.path, body=data, headers=headers)
                r = c.getresponse()
            except ConnectionRefusedError:
                state.stats["refused"] += 1
                self._json(503, {"error": "sidecar worker starting", "backend": "starting"})
                return
            state.stats["proxied"] += 1
            self.send_response(r.status)
            length = r.getheader("Content-Length")
            for k, v in r.getheaders():
                if k.lower() not in _HOP:
                    self.send_header(k, v)
            if length is None:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            while True:
                chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
            c.close()

        do_GET = do_POST = do_PUT = do_DELETE = _proxy

        def do_OPTIONS(self) -> None:
            self._proxy()

    return H


def start_front(public_port: int, backend_port: int, launch: Dict) -> _State:
    """Serve the public port from a thread of the calling (supervisor) process."""
    state = _State(backend_port, launch)
    stop = threading.Event()
    threading.Thread(target=_poll, args=(state, stop), name="domvec-front-poll", daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", public_port), _handler(state))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="domvec-front", daemon=True).start()
    state.server = srv  # type: ignore[attr-defined]
    return state


def supervisor_launch(workspace: str) -> Dict:
    return {"python": sys.executable, "argv": list(sys.argv[1:]), "cwd": os.getcwd(),
            "workspace": workspace, "supervised": True, "front": True}
