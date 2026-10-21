"""The first hand-authored tree: the scanning pipeline, as pg-062 orders it,
with pg-095's harness and pg-098's 3D proportion folded in. Each claim is
written here individually (not from one template): its own domain, range,
falsifier and current evidence. Writes only files that do not exist yet or are
still stubs, so later hand edits are never clobbered.

    python .design/tools/build_l1_pipeline.py
"""
import os, re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L1 = os.path.join(ROOT, ".design", "L1-trees")

NODES = [
 # id, title, from, produces, requires, domain, range, wrong, evidence
 ("pg-062", "The pipeline runs in the dictated order, each step drawing before the next persists",
  ["L0.pg-062", "L0.pg-095", "L0.pg-098"], "pipeline", [],
  "a page open in the browser cell, the sensor booted in it, the sidecar and the 3D pane running",
  "every mutation's content is outlined, drawn, saved, folded, vectorized and placed -- in that order, each within its own bound",
  "the order is right but a later stage starves an earlier one (a store backlog that stalls the stream, a render that blocks hover): order alone does not make the chain hold",
  "PRD G-92 (stream order check, run in the app: 380/380 saved nodes folded at once, 2026-09-28)"),
 ("pg-062.diff", "A mutation becomes a deduplicated chunk diff inside the page, in O(delta)",
  ["L0.pg-062", "L0.am-001"], "chunk-diff", [],
  "the sensor observes the document and its open shadow roots",
  "a payload naming only the chunks whose content changed, each chunk at most 256 tokens, no chunk emitted twice for one change",
  "O(delta) holds for the fold but not for the classification scan, which walks every anchor when an anchor enters (CLAUDE.md 5d); a list page is exactly that case",
  "sensor fold 30-50 ms per 30 forum topics before the family memo; memo: 6/6 pager tests, planted leak 3/6 fail"),
 ("pg-062.overlay", "The chunk under the pointer, and each new diff, is outlined in single-digit milliseconds",
  ["L0.pg-062", "L0.pg-095"], "overlay-drawn", ["chunk-diff"],
  "a chunk diff exists and the pointer or the diff has a box on screen",
  "the reader sees a faint, near-white, still-translucent outline of the chunk within ~10 ms of the change",
  "the page's own main thread delays the pointer event itself; our share can be milliseconds while what the reader feels is not -- the page's delay has to be measured beside ours",
  "D-40 on the Julia forum: our share of hover 8 ms p50 but 824 ms p95 (host busy); colours lightened 2026-09-28, not yet seen"),
 ("pg-062.stream-3d", "The same diff reaches the 3D view force-directed, before the store, at the overlay's latency and in its proportion",
  ["L0.pg-062", "L0.pg-098", "L0.pg-091"], "force-diff-drawn", ["chunk-diff", "scene-in-budget"],
  "a chunk diff exists; the 3D scene can draw a frame within budget",
  "every chunk the scanner emitted as new appears as a translucent node near its parent in the next frames; nothing already drawn is re-shaken",
  "counts can match (pushed = applied) while nothing is DRAWN: a page whose content is all stored draws no new node, and an overloaded renderer draws late -- proportion must be of drawn nodes, latency to the painted frame",
  "stress on the forum: 12/12 pushed drains applied, 0 new drawn (all content already stored), diff -> scene 157-298 ms p50, 508 ms p95"),
 ("pg-062.render", "The 3D view draws every stored chunk of an open page within a frame budget",
  ["L0.pg-095", "Q.001"], "scene-in-budget", [],
  "the graph holds the nodes and links to draw; pictures are known for some of them",
  "a frame is drawn in a bounded time however many chunks a page has stored, so the stream and the hover keep their latency",
  "the budget is met by drawing less (culling, dropping history) -- the ruling in [[Q.001]] forbids that; or it is met on a small page and not on the forum's 1,000-topic history",
  "2,467 nodes / 1,476 textures on the forum: ~1,800 draw calls a frame, host timers 3-5x late (stress, 2026-09-28)"),
 ("pg-062.store", "The diff is saved after the GUI drew it, and saving keeps up with the page",
  ["L0.pg-062", "L0.pg-092"], "saved-diff", ["chunk-diff"],
  "a chunk diff has been drawn; the sidecar is running",
  "every drawn diff is confirmed saved within about one capture's time, however fast the page drains",
  "merging a page's queued drains could change what is stored; the equivalence has to be shown on the stored addresses, not assumed",
  "forum before merging: drawn -> saved 9.6 s p50 / 12.6 s p95; D-42 (merged vs serial, same store) written, not yet run"),
 ("pg-062.dedup", "The store holds each piece of content once, wherever on the page it moved",
  ["L0.pg-062", "L0.pg-088", "L0.pg-095"], "deduped-store", ["saved-diff"],
  "a diff is being saved for a page the store already holds",
  "a row that shifted, or was regrouped with its neighbours, is recognised as content already held -- as the reference serializer recognised an identical subtree by its Merkle signature wherever it sat",
  "address-level dedup reads clean (1 of 14,146 addresses claimed twice) while search shows the same topic row under two groupings: the duplicate is in OVERLAPPING chunks, not identical ones",
  "search 'consultancy': results 1 and 3 the same topic row (77 and 118 tokens); content-identical chunks 1 of 1,177"),
 ("pg-062.fold", "A node the store confirms saved folds into its page's root at once",
  ["L0.pg-062"], "folded", ["saved-diff", "force-diff-drawn"],
  "a streaming node is drawn and the capture reply names the stored chunk that covers it",
  "that node leaves the force tree into its root (projected page, or the page's own force root) within a frame of the reply",
  "folding on the reply is right only if the reply means SAVED; a reply that means 'received' would fold nodes the store later drops",
  "G-92 in the app: 380 saved, 380 folded, 0 out of order, fold p95 0 ms; planted old order: 0/268 folded"),
 ("pg-062.vectorize", "Saved chunks are vectorized after the save, once each",
  ["L0.pg-062"], "vectors", ["deduped-store"],
  "a chunk is saved and not yet embedded",
  "it has one vector; a chunk already embedded is not embedded again",
  "a regrouped row (overlapping chunk) is new content by hash and is embedded again -- dedup below the chunk level decides this",
  "40 chunks without vectors after reboot; no check yet"),
 ("pg-062.project", "Each new chunk is placed through the current fit at once, on the GPU, and its move is observable",
  ["L0.pg-062", "L0.pg-071", "L0.pg-072", "L0.pg-073", "L0.pg-087"], "projected", ["vectors"],
  "a chunk has a vector and a fit exists",
  "the chunk is drawn at its fit position (collision only spaces it); the transform's time and scope are readable",
  "the pane overriding the fit with its own geometry (it did: disc, radial tree, force seeding) makes this false while the sidecar is right",
  "G-97 written; in the app the page node's collider pushed chunks 5 colliders off (fixed, not re-run)"),
 ("pg-062.refit", "A refit or an online update() moves every stored chunk to fresh UMAP coordinates, on the GPU, scoped by its measured cost",
  ["L0.pg-062", "L0.pg-072", "L0.pg-073", "L0.pg-077", "L0.pg-095"], "refit", ["projected"],
  "a fit exists and new pages or changed pages have arrived",
  "the model trains on the diff with earlier placements held; chunks move through the stream; the choice of every-chunk vs page-centroid scope and its timing are observable",
  "the online update moves only pages, never the chunks inside a page, and the scope is always pages whatever the GPU could afford",
  "parametric UMAP on CUDA, page-centroid scope only; G-106 open"),
 ("pg-062.persist", "UMAP coordinates are persisted per chunk, force positions never",
  ["L0.pg-062"], "coords-persisted", ["projected"],
  "chunks have fit positions",
  "after a restart the same chunks draw at the same fit positions; no force position is in the store",
  "persisting page positions only, with chunk offsets recomputed, would pass a restart test on a static corpus and fail after a refit",
  "PRD G-96, no live check"),
 ("pg-062.root-toggle", "Clicking a root expands its whole patricia tree; clicking again collapses it",
  ["L0.pg-062"], "root-toggle", ["projected"],
  "a page root is drawn",
  "all the page's chunks appear as its complete tree, and disappear on the second click",
  "an expansion capped by a node budget shows part of the tree while reading as whole",
  "PRD G-95, no live check"),
 ("pg-095", "One plugin-in-the-loop harness times and memory-profiles every stage, rendering included, each against its own bound",
  ["L0.pg-095", "L0.pg-097"], "pipeline-profile", ["pipeline"],
  "the pipeline runs in the app under the Verifier",
  "for any run, each stage (fold, overlay, 3D, render, store, vectors, fit) reports its latency AND the memory it holds, readable over MCP, with a planted arm per bound",
  "a harness that times stages but not memory missed the D-38 crash entirely -- it was an out-of-memory, not a slow stage",
  "stress.py (segmented rapid scroll+hover), oomwatch/stuckwatch (debugger armed); none yet a harness gesture"),
 ("pg-095.stability", "Rapid scrolling and hovering on the original site never freezes the app",
  ["L0.pg-094", "L0.pg-096", "L0.pg-097"], "no-freeze", ["scene-in-budget"],
  "the forum is open and the reader scrolls and hovers fast",
  "the window and the page keep answering; memory stays bounded for the session",
  "the host is fixed but the PAGE's own renderer still runs out of memory on an endless scroll (Discourse keeps every row)",
  "D-38 root cause fixed (in-place array growth -> NaN -> octree loop); 2-min stress: 0 guard catches; page OOM still possible"),
]


def main():
    os.makedirs(L1, exist_ok=True)
    kids = {}
    for n in NODES:
        parent = n[0].rsplit(".", 1)[0] if "." in n[0] else None
        if parent:
            kids.setdefault(parent, []).append(n[0])
    wrote = 0
    for ident, title, frm, produces, requires, domain, rng, wrong, evidence in NODES:
        path = os.path.join(L1, ident + ".md")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                if not re.search(r"^status:\s*stub", f.read(), re.M):
                    continue
        down = ["L2.%s" % ident] + ["L1.%s" % k for k in kids.get(ident, [])]
        fm = ["---", "id: L1.%s" % ident, "layer: L1", "title: '%s'" % title.replace("'", "’"),
              "status: drafted", "projected_from:"] + ["  - %s" % x for x in frm] + \
             ["projects_to:"] + ["  - %s" % x for x in down] + \
             ["produces: %s" % produces, "requires: [%s]" % ", ".join(requires), "---", ""]
        body = ["| | |", "|---|---|",
                "| **Domain** | %s |" % domain,
                "| **Range** | %s |" % rng,
                "| **produces** | `%s` |" % produces,
                "| **requires** | %s |" % (", ".join("`%s`" % r for r in requires) or "--"), "",
                "**How this could be wrong.** %s." % wrong, "",
                "**Where it stands.** %s." % evidence, ""]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(fm + body))
        wrote += 1
    print("L1 pipeline: wrote", wrote)


if __name__ == "__main__":
    main()
