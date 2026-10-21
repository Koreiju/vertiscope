"""D-48 probe (2026-10-07). Usage: python scripts/store_set_blanks.py 40 300

Does SETting OTHER columns of a Chunk blank its md string (kuzu 0.11.3)?

Scratch store with the working store's Chunk columns. Seeds pages of chunks
with long md, checkpoints, then applies the per-page writes the sidecar makes
without a browser -- the merge layer's group SETs, the embedding SET -- with
and without checkpoints between, and counts empty md after each step.
"""
import os, random, shutil, string, sys, json
import kuzu


def main():

    import tempfile
    D = os.path.join(tempfile.gettempdir(), "vertiscope_set_blanks_db")
    shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
    db = kuzu.Database(os.path.join(D, "g.kuzu"), buffer_pool_size=1 << 30)
    c = kuzu.Connection(db)
    c.execute("CREATE NODE TABLE Chunk(cid STRING, url STRING, xpath STRING, part INT64, md STRING, chars INT64, "
              "line_count INT64, row INT64, dup_of STRING, dup_n INT64, group_of STRING, group_n INT64, "
              "embedding FLOAT[64], group_embedding FLOAT[64], PRIMARY KEY(cid))")
    rng = random.Random(7)
    PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    PER = int(sys.argv[2]) if len(sys.argv) > 2 else 300


    def txt(n):
        return "".join(rng.choice(string.ascii_letters + " ") for _ in range(n))


    rows = []
    for p in range(PAGES):
        for i in range(PER):
            md = "page %d chunk %d " % (p, i) + txt(rng.randint(20, 1200))
            rows.append({"cid": "p%03dc%05d" % (p, i), "url": "https://site/%d" % p, "xp": "/html/body/div[%d]" % i,
                         "md": md, "chars": len(md), "lines": md.count(" ") // 8 + 1})
    for i in range(0, len(rows), 2000):
        c.execute("UNWIND $rows AS r MERGE (x:Chunk {cid: r.cid}) SET x.url = r.url, x.xpath = r.xp, x.part = 0, "
                  "x.md = r.md, x.chars = r.chars, x.line_count = r.lines, x.dup_of = '', x.dup_n = 1, x.row = -1",
                  {"rows": rows[i:i + 2000]})
    c.execute("CHECKPOINT")


    def empties(step):
        r = c.execute("MATCH (x:Chunk) RETURN count(x), sum(CASE WHEN x.md IS NULL OR size(x.md)=0 THEN 1 ELSE 0 END), "
                      "count(DISTINCT CASE WHEN x.md IS NULL OR size(x.md)=0 THEN x.url END)").get_next()
        print(json.dumps({"step": step, "rows": int(r[0]), "empty_md": int(r[1] or 0), "pages_hit": int(r[2] or 0)}), flush=True)


    empties("seeded")
    for p in range(PAGES):                       # merge layer: reset, then groups
        u = "https://site/%d" % p
        c.execute("MATCH (x:Chunk {url: $url}) SET x.group_of = '', x.group_n = 1", {"url": u})
        grp = [{"cid": "p%03dc%05d" % (p, i), "lead": "p%03dc%05d" % (p, i - i % 4), "n": 4} for i in range(PER)]
        c.execute("UNWIND $rows AS r MATCH (x:Chunk {cid: r.cid}) SET x.group_of = r.lead, x.group_n = r.n", {"rows": grp})
    empties("group SETs")
    c.execute("CHECKPOINT")
    empties("group SETs + checkpoint")
    emb = [{"cid": r["cid"], "emb": [rng.random() for _ in range(64)]} for r in rows]
    for i in range(0, len(emb), 2000):
        c.execute("UNWIND $rows AS r MATCH (x:Chunk {cid: r.cid}) SET x.embedding = r.emb", {"rows": emb[i:i + 2000]})
    empties("embedding SETs")
    c.execute("CHECKPOINT")
    empties("embedding SETs + checkpoint")
    for p in range(PAGES):
        c.execute("MATCH (x:Chunk {url: $url}) SET x.group_embedding = $v", {"url": "https://site/%d" % p, "v": [0.5] * 64})
    c.execute("CHECKPOINT")
    empties("group_embedding SETs + checkpoint")
    del c, db
    db = kuzu.Database(os.path.join(D, "g.kuzu"), buffer_pool_size=1 << 30); c = kuzu.Connection(db)
    empties("reopened")



if __name__ == "__main__":
    main()
