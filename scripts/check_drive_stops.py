"""G-135 live: a harness drive stops at the first sign of the reader.

Runs `practice_drive.py` on a page the store already holds, marks the reader
as back (the stamp the app's own listeners write) `after_s` seconds in, and
times how long the drive takes to say it stopped. Run only while the reader
is idle; the stamp is a simulation of the reader, nothing else changes."""
import subprocess, sys, time, json
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

URL = sys.argv[1] if len(sys.argv) > 1 else "https://en.wikipedia.org/wiki/Comparison_of_web_browsers"
AFTER = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0


def main():
    L = Live()
    if (L.evaluate("window.__vertiscope.reader.idleMs()") or 0) < 60000:
        print("reader active -- not running"); return
    t0 = time.time()
    proc = subprocess.Popen([sys.executable, "scripts/practice_drive.py", URL], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            env={**__import__("os").environ, "PYTHONPATH": "."})
    time.sleep(AFTER)
    stamped = time.time()
    L.evaluate("window.__vertiscopeReaderAt = Date.now(); 1")
    lines, stopped_at = [], None
    for line in proc.stdout:
        lines.append(line.rstrip())
        if "STOPPED" in line:
            stopped_at = time.time(); break
    try: proc.wait(timeout=60)
    except subprocess.TimeoutExpired: proc.kill()
    print(json.dumps({"stamped_after_s": round(stamped - t0, 1),
                      "stopped_after_stamp_s": round(stopped_at - stamped, 1) if stopped_at else None,
                      "stage_lines_before_stop": [l[:80] for l in lines if not l.startswith("STOPPED")][-4:]}, indent=1))


if __name__ == "__main__":
    main()
