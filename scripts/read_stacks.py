"""The sidecar's latest stall dump (`stacks.log`), one block per thread that
is serving a request or matches `--grep`, its top frames shortened.

  python scripts/read_stacks.py [workspace] [--grep=layout] [--frames=10]
"""
import re, sys
from pathlib import Path

ws = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), r"<home>\Documents\domvec\build\corpus123"))
grep = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--grep=")), "do_GET|do_POST")
frames = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--frames=")), "10"))
s = (ws / "stacks.log").read_text(encoding="utf-8", errors="replace")
last = s.rsplit("\n==== ", 1)[-1]
print(last.splitlines()[0][:220])
short = re.compile(r'File ".*?[\\/](?=(?:domvec|Lib|site-packages)[\\/])')
for block in re.split(r"\n(?=Thread 0x|Current thread 0x)", last):
    fr = [line.strip() for line in block.splitlines() if line.strip().startswith("File ")]
    if fr and any(re.search(grep, x) for x in fr[:25]):
        print("----")
        for x in fr[:frames]:
            print(short.sub('File "', x)[:150])
