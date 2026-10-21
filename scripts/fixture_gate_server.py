"""A local fixture for G-247 / G-249: a page that is sometimes a bot check.

    python scripts/fixture_gate_server.py [port]       (default 8793)

  GET /gate/page?k=K     the real page (30 numbered paragraphs of prose) --
                         unless K is ARMED, in which case ONE response is a
                         DDoS-Guard-style interstitial ("Checking your browser
                         before accessing ...", title "DDoS-Guard") whose own
                         script reloads the same url after 2 s, as such a check
                         does once it passes. Nothing about the check is real:
                         it is our page imitating the shape.
  POST /gate/arm?k=K     arm K: the next /gate/page?k=K is the interstitial
  GET /gate/502?k=K      502 Bad Gateway, with a small error page
  GET /gate/hits         how many of each were served, per key (JSON)

Local only (127.0.0.1); nothing leaves the machine.
"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ARMED, HITS = set(), {}

REAL = """<!doctype html><html><head><meta charset="utf-8"><title>Gate fixture: the real page</title></head>
<body><h1>The real page</h1>%s</body></html>""" % "".join(
    "<p>Paragraph %d of the real page: the archive's catalogue lists the item, its editions and where each copy is kept.</p>" % i
    for i in range(1, 31))
CHECK = """<!doctype html><html><head><meta charset="utf-8"><title>DDoS-Guard</title></head>
<body><div id="h"><h2>Checking your browser before accessing 127.0.0.1</h2>
<p>This process is automatic. Your browser will redirect to your requested content shortly.</p>
<p>DDoS-Guard</p></div>
<script>setTimeout(function () { location.reload(); }, %d);</script></body></html>"""
BAD = """<!doctype html><html><head><title>502 Bad Gateway</title></head>
<body><center><h1>502 Bad Gateway</h1></center><hr><center>nginx</center></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path); k = parse_qs(u.query).get("k", [""])[0]
        if u.path == "/gate/page":
            kind = "check" if k in ARMED else "real"
            ARMED.discard(k)
            HITS.setdefault(k, {}).setdefault(kind, 0); HITS[k][kind] += 1
            delay = int(parse_qs(u.query).get("d", ["2000"])[0])
            return self._send(200, (CHECK % delay) if kind == "check" else REAL)
        if u.path == "/gate/502":
            HITS.setdefault(k, {}).setdefault("502", 0); HITS[k]["502"] += 1
            return self._send(502, BAD)
        if u.path == "/gate/hits":
            return self._send(200, json.dumps(HITS), "application/json")
        self._send(404, "not found")

    def do_POST(self):
        u = urlparse(self.path); k = parse_qs(u.query).get("k", [""])[0]
        if u.path == "/gate/arm":
            ARMED.add(k)
            return self._send(200, json.dumps({"armed": k}), "application/json")
        self._send(404, "not found")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8793
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
