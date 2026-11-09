"""D-2 pilot: how faithful is a re-render of a stored page from its stored
addresses? Per page: chunks re-rendered with the same cid as stored (same
content, same order) vs changed vs gone. Read-only on the store.

    python scripts/d2_pilot.py build/corpus123_d2/graph.kuzu [N_PAGES]
"""
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.getcwd())
from domvec.address import ContentAddress  # noqa: E402
from domvec.graphstore import GraphStore  # noqa: E402
from domvec.markdown import render_trie  # noqa: E402
from domvec.trie import AddressTrie  # noqa: E402


def main():
    path, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10
    tot = Counter()
    with GraphStore(path, read_only=True) as s:
        urls = [u for (u,) in s._rows("MATCH (p:Page) WHERE p.url STARTS WITH 'http' RETURN p.url LIMIT $n", {"n": n})]
        for url in urls:
            rows = s._rows("MATCH (a:Address) WHERE a.url = $u RETURN a.akey, a.value", {"u": url})
            trie = AddressTrie()
            for k, v in rows:
                try:
                    a = ContentAddress.parse(k)
                except ValueError:
                    continue
                if a.md or "~" in a.accessor:
                    continue
                trie.insert(a, v or "")
            trie.rehash()
            newc = {c.cid: c.markdown for c in render_trie(trie, context_window=256)}
            oldc = dict(s._rows("MATCH (c:Chunk) WHERE c.url = $u RETURN c.cid, c.md", {"u": url}))
            old, new = set(oldc), set(newc)
            shared = old & new
            same_md = sum(1 for c in shared if (oldc[c] or "") == (newc[c] or ""))
            tot.update(stored=len(old), shared=len(shared), same_md=same_md, gone=len(old - new), added=len(new - old), pages=1)
            print("%-55s stored %4d  shared %4d  same_md %4d  gone %4d  new %4d" % (url[:55], len(old), len(shared), same_md, len(old - new), len(new - old)), flush=True)
    print("TOTAL", dict(tot))


if __name__ == "__main__":
    main()
