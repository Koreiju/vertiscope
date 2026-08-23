"""Harvest a broad URL corpus by scoping DuckDuckGo searches.

Real variability, not a hand-picked list: the queries span registers (news,
docs, commerce, forums, reference, media, government, academic) so the corpus
contains the structural variety the chunker has to survive — not fifty
variations of one CMS.

The html endpoint is used deliberately. It paginates with a submit button,
returns real outbound links, and does not require executing a search-engine
SPA to read its own results.
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Dict, Iterable, List, Set
from urllib.parse import parse_qs, urlsplit

TOPICS = [
    "university library", "climate model", "recipe chicken", "python asyncio",
    "supreme court ruling", "guitar tablature", "protein folding",
    "vintage synthesizer", "municipal budget", "bird migration",
    "film noir criticism", "kubernetes operator", "medieval manuscript",
    "solar panel efficiency", "jazz discography", "tax deduction rules",
    "earthquake early warning", "mushroom foraging", "typography history",
    "open source license", "coral reef restoration", "chess endgame",
    "railway signalling", "vaccine trial results", "urban planning zoning",
    "quantum error correction", "textile weaving patterns", "flood mapping",
    "archive digitisation", "linguistics morphology", "board game design",
    "wildfire smoke health", "satellite imagery analysis", "opera libretto",
    "bicycle infrastructure", "antibiotic resistance", "museum collection",
    "compiler optimisation", "ocean acidification", "folk song archive",
]
MODIFIERS = ["", " guide", " 2024", " research", " forum", " documentation",
             " news", " database", " tutorial", " archive"]

_SKIP_EXT = (".pdf", ".jpg", ".png", ".gif", ".zip", ".mp4", ".mp3", ".svg",
             ".css", ".js", ".xml", ".rss", ".ico", ".webp", ".doc", ".xls")


def _clean(href: str) -> str:
    """DuckDuckGo wraps outbound links; unwrap to the real destination."""
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href or href.startswith("/l/"):
        q = parse_qs(urlsplit(href).query)
        if "uddg" in q:
            return q["uddg"][0]
    return href


def usable(url: str) -> bool:
    if not url.startswith("http"):
        return False
    parts = urlsplit(url)
    if not parts.netloc or "duckduckgo" in parts.netloc:
        return False
    low = parts.path.lower()
    return not low.endswith(_SKIP_EXT)


def harvest(driver, out_path, target: int = 5000, per_query: int = 30,
            progress=None) -> int:
    """Fill `out_path` with distinct URLs until `target`. Resumable."""
    out = pathlib.Path(out_path)
    seen: Set[str] = set()
    hosts: Dict[str, int] = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seen.add(line.strip())
                hosts[urlsplit(line).netloc] = \
                    hosts.get(urlsplit(line).netloc, 0) + 1
    fh = out.open("a", encoding="utf-8")
    try:
        for mod in MODIFIERS:
            for topic in TOPICS:
                if len(seen) >= target:
                    return len(seen)
                q = (topic + mod).strip().replace(" ", "+")
                for page in range(0, 3):          # depth via the site's pager
                    url = f"https://html.duckduckgo.com/html/?q={q}"
                    if page:
                        url += f"&s={page * 30}"
                    try:
                        driver.get(url)
                        time.sleep(1.1)
                        hrefs = driver.execute_script(
                            "return Array.from(document.querySelectorAll("
                            "'a.result__a, a.result__url, .result__title a'))"
                            ".map(function(a){return a.getAttribute('href');});"
                        ) or []
                    except Exception:
                        continue
                    added = 0
                    for h in hrefs[:per_query]:
                        u = _clean(h or "")
                        if not usable(u) or u in seen:
                            continue
                        host = urlsplit(u).netloc
                        # cap per host so one site cannot dominate the corpus
                        if hosts.get(host, 0) >= 12:
                            continue
                        seen.add(u)
                        hosts[host] = hosts.get(host, 0) + 1
                        fh.write(u + "\n")
                        added += 1
                    fh.flush()
                    if progress:
                        progress(f"{len(seen):5d} urls / {len(hosts):4d} hosts"
                                 f"  +{added:2d}  {topic + mod!r} p{page}")
                    if not added:
                        break
    finally:
        fh.close()
    return len(seen)
