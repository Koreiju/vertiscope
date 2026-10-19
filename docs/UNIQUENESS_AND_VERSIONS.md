# Uniqueness, and keeping earlier states

*For PLUGIN_GOAL 183 (2026-10-18): "look through our diff, docs, and prompt
transcript a little closer to get a better understanding of managing
uniqueness and diff streaming/updates that preserve previous states
presented from earlier times should sufficient uniqueness constraints hold
for the two independently." What was found, and a proposal for you to rule
on. Nothing below is built.*

## The two identities, as they stand

**The view (the streamed grey nodes) is unique by CONTENT per element.**
`ForceTree` (G-216, `563a9ae`, 2026-10-17, on your "track the full set of
unique chunks"): a chunk the page removes is RETAINED; an element the page
reuses for new content gets a new node, its id carrying a generation
(`f:<url>#<sensor id>.<gen>`), and the old content stays as its own node;
retained content seen again elsewhere is dropped, so each content keeps one
node.

**The store is unique by POSITION.** A chunk's id is
`sha1(url | xpath | part)` (`markdown.py`, `MarkdownChunk.cid`), and that
was a deliberate choice: content-keyed identity was tried and rejected --
ERRATA B10/B12: on the 54-page corpus a content hash collapsed **18.8%** of
instances (empty payloads all hash alike), the address collapsed **0%**, "by
construction rather than by luck". The partition test
(`tests/test_content_boundaries.py::test_the_page_is_still_partitioned`)
holds the store to one chunk per address.

**Where they meet, G-216 already chose union for one case and not the
other.** A chunk whose POSITION leaves the render (archive.org's list
scrolling past) is KEPT in the store for the visit ("only renamed retire",
`session["kept"]`, `complete=False`). A chunk whose position STAYS but whose
content is rewritten in place -- bandcamp's rotating feed, archive.org's
recycled tiles -- has the same id, so the store overwrites it: the earlier
content is gone from the store while the view still holds it.

That is the 95 of 170 grey nodes measured on bandcamp (G-253): earlier
contents the view keeps and the store, by its identity, cannot.

## Does uniqueness hold for each, independently?

Yes, each alone: the view never shows one content twice, the store never
holds one address twice. They are different equivalences -- the same split
CLAUDE.md 5b draws for the two Merkles ("is this the same content?" vs
"does this draw the same?"). Neither is wrong. What is missing is a third
identity for an EARLIER state, which neither can supply alone:

- by content alone it degenerates (B10: empty contents collapse);
- by position alone it is the current chunk, which has moved on.

**A version is keyed by both:** `sha1(url | xpath | part | content_hash)`.
Unique wherever either part is: two contents at one position differ by
hash; two empty contents differ by position. It never competes with the
current chunk for an address, so the partition test is untouched.

## Proposal

1. When a capture rewrites a chunk in place within a visit (same cid, new
   content hash), the previous content is written as a **version chunk**
   (id as above) before the current one is overwritten: its markdown, its
   vector, its place by the projector -- and NO anchors (its addresses now
   draw the new content), a `VersionOf` edge to the current chunk instead.
   Identical content seen again maps to the same version (dedup by
   construction).
2. The capture reply names the versions it wrote; the view's retained node
   for that content is covered by its version and leaves grey for its
   projected place, as every other scanned chunk does (G-253).
3. Bounded: versions per position per visit capped (a ticker rewriting every
   second would otherwise mint thousands); past the cap the oldest versions
   fold into their current chunk. The cap is yours to set.

The alternative (fade): an old version folds into its page once the current
content at its position is stored -- the view matches the store, earlier
states are not kept.

Which -- keep versions (with what cap), or fade?
