# Ten defects in the interactive surface

*2026-08-14. Found by measuring what the code claims, one claim at a time:
`scripts/audit_controls.py` over the 54-page frozen corpus; asking who calls
`WebNav.html()`; counting how many form controls reach the screen named;
comparing stored urls against their own canonical forms; and enumerating the
mouse codes a terminal can send.*

None of them made anything crash. Every one produced a confident wrong answer
— a pager that was a stylesheet, a page that had already been navigated away
from, a field with no name, a link graph missing three quarters of its edges,
a document that scrolled when the hand moved sideways, a verification script
that deleted what it was verifying. The suite was green throughout, at 610
tests, because each defect lived in the gap between what a function was tested
with and what the program actually hands it.

Two further sections record suspicions that **measured to nothing** and were
not acted on, one that records a test of mine that was vacuous twice over, and
a last one on what the fixes themselves got wrong once they met a real page.
Those are here on purpose: a log of only the things that turned out to be bugs
would misrepresent the ratio.

## 1. The `controls` command found no controls

The REPL offers pagination, menus, filters and search boxes by name.
`classify_controls` reads those roles off the interactive addresses already
extracted — deliberately a reading rather than a new content category, so a bad
guess costs a mislabelled REPL command and nothing else.

Its unit test fed it five labels — "Next page", "Previous", "Search", "Filter
by category", "ordinary text" — and checked they landed in the buckets those
words name. It passed. It had always passed. What it proved was that the words
are spelled the same in the test and in the implementation.

Run over real pages, the function found **9 of 12** known controls **not at
all**, and invented a large number that were not there.

```
                       before   after
known controls missed     9/12    0/14
```

## Why: the classifier was reading URLs

A link's markdown rendering is `<href>`. `Document.from_chunks` carries that
through as the widget's label, so the classifier's input for every anchor on
every page was a path — and the words it looks for are words that appear in
prose, not in hrefs.

```
source     <li class="next"><a href="/page/2/">Next &rarr;</a></li>

detections text.visible    .../nav/ul/li      "Next →"
           urls.internal   .../nav/ul/li/a    "/page/2/"

classifier saw             "</page/2/>"
```

The label and the target are one level apart, because the extractor gives an
element's text to the deepest element containing *all* of it, and "Next →"
spans the `<a>` and its `<span>`. Nothing was lost — both lines are in the
markdown, adjacent — but the join between them had never been made.

The same substring test that missed every pager also fired constantly. A
Next.js page reported **84 stylesheets and scripts as pagination**, because
`"next" in "/_next/static/chunks/0-z_fk60u61~~.js"` is true. Every one of the
84 was a `<link>` or `<script>` in `<head>`.

## Three readings, not one

**Join the label to the target** (`attach_context`). Self, then descendant,
then ancestor, capped at three levels — far enough up, everything is inside
`<body>` and would inherit the page's first paragraph.

**Match whole words, and split the row.** Real contexts are not tidy: reddit's
next link reads `view more: next ›` and arxiv's page-size row reads
`Showing up to 50 entries per page: fewer | more | all`, because the aggregating
element holds its children's words too. Splitting on the separators such rows
are built from recovers the individual controls without loosening the rule back
into a substring search.

**Read the target when there are no words.** arxiv's pager is
`1-50  51-100  101-104` — every label a number, and only the href
(`?skip=50&show=50`) says what the links do. A query parameter from a small
list, or a `/page/N` path, is that reading. `p` and `count` are excluded:
`?p=123` is a WordPress permalink at least as often as page 123, and both of
those pagers are caught by their labels anyway, so including the ambiguous
spelling would buy nothing and cost precision.

## What it does now

```
openweathermap-org     84 pagination (all of them assets)  ->  0, and it finds
                                                               the search box
xkcd-com-353            0                                  ->  4  = "< Prev"
                                                               and "Next >",
                                                               top and bottom
books-toscrape-com      0                                  ->  1  = "next"
arxiv-org-list-cs-ir    0 useful                           -> 15  = date skips
                                                               + page sizes
```

Against the live workspace, through the real command:

```
$ vertiscope browse "https://books.toscrape.com" -w build --command controls
pagination:
  - next     /html/body/div/div/div/div/section/div[2]/div/ul/li[2]/a
```

That xpath is the click handle, which is the point: the address is the element
handle, so a classified control is directly actionable.

## The audit corrected me three times

`EXPECTED` in the audit is the load-bearing part — pages whose controls are
known from the HTML, so the report can say *missed* and not only *found*.
Three of my entries were wrong:

- **archive.org** and **gitlab** were listed as having a search box. Both
  frozen pages are JavaScript shells: **zero `<input>`, zero `<form>`** in the
  file. Nothing could have found a control that is not there, and tuning the
  classifier until those two passed would have been fitting to a mistake.
- **arxiv "all"** — the only `all` in the source is
  `<input type="hidden" name="searchtype" value="all">`, part of the search
  form, not a pager.

The corrections are left visible in the table. Two of the five surviving
"misses" were mine, which is the more useful half of the exercise: an audit
that can only be wrong in the direction of the code is not measuring the code.

A role mapped to an **empty list** now asserts the bucket is empty. Without it
the audit could only reward finding things, and a classifier that labelled
everything would have scored perfectly. Six pages carry that assertion.

## What is still approximate

10.8% of interactive lines get a role; the rest are `other`. That is not a
defect — most links on most pages are content — but it is not measured against
anything, so it is a number and not a result.

`menu` is the weakest reading: it fires on `/nav` appearing in the xpath, which
catches real navigation and also anything a site happened to put inside a `nav`
element. Unlike pagination it has no structural second reading to check it
against. It is left as-is and named here rather than tuned against intuition.

---

## 2. The browser moved and the terminal did not

`WebNav.html()` carries the docstring *"The settled DOM, for re-running the
pipeline after an action."* It had **no callers**.

Every live action in the REPL — `open` when the target is not in the store, a
click on a link, a click on a control, `back`, and typing into a search box
with submit — did the same two things: perform the action, and write the
`NavResult` into the status line. None of them touched the document. So the
browser navigated and the screen kept showing the page from before it:

```
 https://x.test/one                                     1-3/3
# Page One
</two>
Go

[ok] visit: https://x.test/two
```

Header says page one. Body is page one. The status line says the visit
succeeded, and it had. This is the same failure class as the purge that
reported success and deleted nothing: not a crash, not an error, a confident
wrong answer.

It is worse for a search box than for a link. Typing into a field and pressing
return is a request for the *results*; the results page loaded, was never
rendered, and the operator was looking at the form they had just submitted.

`Repl.render_live` now re-serialises the DOM, runs the pipeline over it and
loads the chunks, and the four call sites route through it. A failed action
keeps the document it could not replace — a dead click must not blank the
screen — and an offline REPL is untouched, since browsing scanned content
without a browser is the common case.

It renders; it does not ingest. Storing whatever a browse session wanders past
is `vertiscope scan`'s job, and doing it here would make every stray click a write.

### Why the tests did not catch it

`test_nav_uses_the_absolute_xpath` drives a fake driver and asserts the right
xpath reached `find_element`. True, and it stays true with the document never
updated, because it is a test of `WebNav` and the defect was in what the REPL
does with the result.

Nothing tested the pair. The new `FakeBrowser` is the smallest thing that can
see it: a driver with **two** pages, so "did the screen change" is a question
with an answer. Verified non-vacuous by mutation — stubbing `render_live` to a
no-op after the first call reproduces the transcript above.

---

## 3. Every text field was labelled `] `

Found by trying to measure something else. Counting how many form controls
reach the REPL without a name, the "named" ones came back looking like this:

```
'] Keyword Search...'      '] ابحث في ويكيبيديا'      '] enter URL or keywords'
```

`_render_unit` writes an input as `[ ] <label>`. `Document.from_chunks` strips
the marks back off so the widget can repaint from its own state, and for
inputs it did:

```python
label = label[2:].rstrip("]").strip()
```

`label[2:]` drops `[ ` and leaves `] Quick search`. The `rstrip("]")` then
removes a bracket that is at the **front** of what is left, so it removes
nothing. **868 inputs across the 54-page corpus, every one of them wrong**,
and each repainted as `[] Quick search]`.

The measurement I was taking counted `] input` as *labelled*, which would have
reported 0% unlabelled and hidden the whole thing. The prefix is only visible
because I printed the examples rather than trusting the count — the same
mistake as the classifier's unit test, one layer along.

### And typing erased the name

```python
shown = self.value or self.label
return f"{pad}[{shown}]"
```

The field and its name are two different things, and the markdown form already
says so. Collapsing them meant an empty field displayed its *name* as though
that were its *contents*, and the name vanished on the first keystroke:

```
before   [ ] Quick search   ->  [einstein]
after    [ ] Quick search   ->  [einstein] Quick search
```

A form with two fields filled in had nothing on screen saying which was which
— in a REPL whose stated job includes "entering inline values for input forms
and search boxes". `_with_cursor` had the same hole, so a field lost its name
precisely when it took focus.

Nothing failed when these were fixed, which is the point worth recording: 76
REPL tests and not one of them looked at what an input renders as.

---

## 4. Three quarters of the link edges never resolved

A page is stored under the url it was **scanned** with. Link targets are put
through `canonical_url` before use, and that function gives an empty path a
`/`. So `https://books.toscrape.com` on disk and `https://books.toscrape.com/`
coming out of the resolver are two strings, and `target not in known` dropped
the edge.

Measured on the live twenty-page workspace:

```
20 pages stored
 5 whose stored url is not its own canonical form
   https://apnews.com  ·  https://blog.codinghorror.com
   https://books.toscrape.com  ·  https://danluu.com  ·  https://example.com

same-host link targets pointing at a scanned page:
   1  matched the stored url exactly
   3  matched only after canonicalising the stored side
```

Three of four. Each is a missing `LinksTo` edge, so a missing PageRank
contribution, on the factor that exists precisely to say which pages matter —
and it is biased, because the urls it drops are exactly the **home pages**,
which are what a site's internal links point at most.

The same string mismatch is why clicking a link to a scanned site's front page
in the REPL reported "no local copy" and reached for the network to fetch a
page already on disk.

`GraphStore.resolve_page` now maps a url to its stored spelling — exact match
first, so a workspace holding both forms resolves each to itself rather than
collapsing them onto whichever was seen first — and both the edge builder and
the REPL's loader go through it.

**Matching rather than normalising at ingest is deliberate.** The url is a
component of a `ContentAddress` key, so rewriting it to a canonical form would
change every `aid` in every existing workspace in order to fix a comparison.

### The half of the fix I reverted

The obvious follow-on is to normalise at ingest, so newly stored pages agree
with link targets by construction. I wrote it, and nine tests failed — every
caller that passes a url to `purge`, `links_from` or `chunks` was suddenly
using a spelling the store no longer held.

That is the change telling me which half is real. The duplication it guards
against measures **zero** on the live workspace (`pages that canonicalise
together: none`), the url is a component of every `ContentAddress` key so
rewriting it would change every `aid` on disk, and the defect that was
actually measured is fixed without it. Reverted, and the reason is recorded in
`Workspace.page_url` so the next person to reach for it reads the measurement
first — the same discipline that removed `settle_order`.

What survived from that direction is the forgiving *read* path: `purge`,
`links_from` and the REPL's loader now resolve whatever spelling the caller
used, so `vertiscope purge --url https://a.test/` reaches the page held as
`https://a.test` instead of reporting success over nothing.

### The test that let it through

```python
assert ws.stats()["links"] >= 0     # the mechanism exists and does not raise
```

That is true of a function that returns without doing anything. It now asserts
an edge, and the new bare-host case is verified non-vacuous by mutation:
restoring the exact-match lookup gives `edges=[]`.

---

## 5. What the address round-trip did not change

`vertiscope where` is new, and it prints an xpath. By COR-10.7 that is the kind of
change that has to be checked rather than assumed: enlarging the observation
alphabet refines observational equivalence and can invalidate an identity
analysis stated against the smaller one.

Re-measured after the change, `scripts/audit_observables.py` returns the table
in `CONTENT_EXTRACTION_RULES §9.8.1` unchanged — position observable through
exactly one surface, `vertiscope show`:

```
  identity       OBSERVABLE      Retriever.search -> Hit, cli: search, --json, show
  position       OBSERVABLE      cli: show
  pattern        OBSERVABLE      Retriever.search -> Hit, cli: search, --json
  multiplicity   not observable
  content        OBSERVABLE      Retriever.search -> Hit, cli: search, --json, show
  url            OBSERVABLE      Retriever.search -> Hit, cli: ls, search, --json, show
```

Two reasons it did not move. The audit measures the *home store's* surfaces,
and `where` reads the workspace. And on the workspace side position was
already observable — `find --addresses` has always printed `address.xpath`, as
has the REPL's `where`. The new command is a second spelling of a fact already
escaping, not a new escape.

Worth naming rather than leaving implied: **the workspace surfaces are not
measured by that audit at all.** The identity analysis in MODEL §8.3 is stated
against the home store's `InstanceRecord`, so nothing is currently wrong; but
an equivalent reading for the address-trie store does not exist, and the
alphabet argument would have to be redone before it could be claimed there.

Naming the store on stderr rather than stdout is what kept this a
non-question. Advice about the machine is not an observation of the store.

---

## 6. Swiping sideways scrolled the page

SGR mouse reporting puts the wheel in codes 64 and up, with the low two bits
selecting axis and direction: 0 up, 1 down, **2 and 3 the horizontal wheel**.
The decoder read them as

```python
"wheel_up" if (code & 3) == 0 else "wheel_down"
```

so both horizontal codes became scroll-down. A trackpad emits horizontal ticks
during any diagonal swipe, which makes this continuous rather than occasional:
the more sideways the gesture, the further the document scrolled down, and
scrolling with a trackpad drifts in a direction the hand did not ask for.

There is nothing to pan — lines are truncated, not scrolled sideways — so the
tick is now decoded as its own action and ignored. Decoded rather than dropped,
because the decoder is meant to be total over what a terminal can send; a
gesture the model has no answer for should reach the model and be declined
there, not vanish in the parser.

Found by enumerating the codes a terminal can emit and printing what each one
decoded to. The mouse tests covered press, release, drag, wheel up and wheel
down — every code anyone had thought to send — which is why an exhaustive
parser test over a small integer range is worth more here than another case.

---

## 7. An arrow key typed a letter

The decoder's docstring states the rule plainly: unrecognised escape sequences
are dropped rather than surfaced as text, because *"emitting the raw bytes of
an unknown sequence would type garbage into whatever field has focus, which is
worse than ignoring a key nobody bound."*

`_skip_escape` kept that promise for CSI (`ESC [ … final`) and broke it for
SS3. `ESC O A` is three characters; it consumed two:

```
'\x1b[A'   CSI arrow up            -> ['up']
'\x1bOA'   SS3 arrow up            -> ['A']       <- typed into the field
'\x1bOF'   SS3 end                 -> ['F']
'\x1bOP'   F1                      -> ['P']
```

SS3 is what a terminal sends for the cursor keys in **application cursor
mode**, which a previous program leaving the terminal in that state is enough
to produce. The four arrows are now bound to the same names as their CSI
spellings, and `_skip_escape` consumes the whole three-byte form so unbound
function keys stay silent instead of leaking their last byte.

Found by reading the docstring and checking it against the code — the promise
was specific enough to test, which is most of what a docstring is for.

## Cursor placement, pinned against the paint

While in the area: the click path subtracts `2 * widget.depth + 1` to turn a
screen column into an index in the field's value, and the renderer introduces
that offset by indenting and then drawing the opening bracket. Two modules,
one number, and no test — asserting one against the other would only have
repeated whichever was wrong.

The new test locates the field in the **painted output**, clicks a real column
of it, and asserts the cursor index. It was already correct at every depth;
dropping the depth term from the offset now fails at depths 1 and 3, so the
agreement is held rather than assumed.

---

## 8. The verification script deleted the workspace

`scripts/build_index.py` is listed in the README under **Verifying**. Its
`--out` defaulted to `build/` — the directory `vertiscope` uses when no `-w` is
given — and it opened with

```python
if out.exists():
    shutil.rmtree(out)
```

no message, no flag. Running the script the documentation tells you to run
destroys whatever you had scanned. I did it to myself while checking the
corpus build end to end: twenty live-scanned pages replaced by the 54-page
corpus index, and the only sign was that `vertiscope status` afterwards described
a different corpus with the same confident formatting.

Same family as the purge that reported success — destructive, and
indistinguishable from harmless.

`--out` now defaults to `build-corpus/`, so it cannot collide with the
workspace at all, and a non-empty target is listed and refused unless
`--force` is given:

```
build already holds something:
    chunks
    corpus
    freq
    graph.kuzu

refusing to delete it. Pass --force, or --out <dir>.
```

The generalisation worth keeping: three of today's eight defects were a
destructive or lossy operation that reported success. A command that removes
something should say what it removed and refuse to guess, and that is cheaper
to build in than to notice.

---

## A suspicion that measured to nothing

The corpus build's printed results looked bad. Two of the top three hits for
`book prices in stock` were bare URLs (`<https://schema.org/Book>`), and the
Wikipedia query returned `<mw-data:TemplateStyles:r1333433106>`. The obvious
reading is the classic short-document bias of cosine TF-IDF: a chunk holding
one URL has a vector dominated by two or three terms, and `https://…/Book`
tokenises to include "book".

Measured over the whole ranking rather than the three lines that were printed:

```
corpus                       6,229 chunks   lines/chunk  median 8   mean 12.2
top-10 over the five queries    50 hits     lines/hit    median 6   mean 12.7

every line a url/image/code    6/50  (12%)
single-line hits               9/50  (18%)   vs 14% of the corpus
```

The hits are marginally shorter at the median and marginally *longer* at the
mean. An 18%-against-14% skew toward single-line chunks is not a bias worth
reweighting for; it is close to what a corpus with that many one-line chunks
should produce.

So there is nothing to fix, and the impression came from reading the top three
lines of five queries — a sample chosen by what happened to print. Recorded
because the next person to read that output will have the same suspicion, and
because a length-normalisation term added on this evidence would have been a
change to the ranking rule justified by nothing.

## A second suspicion that measured to nothing

At a small context window the overflow rate looks alarming:

```
window   chunks   over the window   worst
   300      977   198  (20%)         3150
   600      627    63                3150
  1200      371     7                3150
  2400      170     1                3150
```

Twenty per cent of chunks past the bound, and a worst case ten times it.

All 198 are a **single element**. The rule is that an element whose own units
exceed the window is emitted whole, because cutting it would leave a chunk
whose root address claims more than the chunk holds — so 20% overflow at
window 300 is the rule working, not failing. Checked directly: of the 45
oversized chunks that render to more than one *line*, every one has all its
lines at the same xpath (several detections on one element — `src`, `srcset`,
`alt`), and **zero** span several elements.

What was worth changing is the test. `test_oversized_chunks_are_indivisible_
not_lazy` ran only at the default window, where **seven** chunks exercise the
case at all — thin evidence for a structural claim. It now sweeps 300 / 600 /
1200 / 2400, so the assertion is made where the case is common.

The window is a soft bound with a principled exception, and the exception is
fully accounted for. Recorded so the number stops looking like a bug.

---

## The vacuity trap, twice

The spec is explicit that deduplication **cannot** be computed with
embeddings. The test standing for that constraint was:

```python
def test_duplicate_content_collapses_without_embeddings(built):
    hits = index.search("books", k=10)
    assert len({h.markdown for h in hits}) == len(hits)
```

It checks the *outcome* — hits come back distinct — which a semantic collapse
would also achieve. It passes whether or not the constraint holds.

So I wrote one that compares the collapse decision with and without vectors
loaded, using a deterministic hash-of-the-text embedder. Then mutated
`search.py` to key the collapse on the embedding, and **the mutant passed**.

Of course it did. A hash embedder makes the vector a function of the exact
string, so an embedding-keyed collapse and a text-keyed one agree on every
input. The double was faithful to the real thing in the one respect that made
it useless: it could not tell the two policies apart.

The test double that discriminates is a **degenerate** one — every text maps
to the same vector. Under it a collapse that reads a vector merges everything
and a collapse that reads the text merges only real duplicates, so the two
policies separate maximally. Re-run against the same mutation:

```
adding vectors changed how many duplicates collapsed (0 -> 21);
the dedup decision is reading an embedding
```

Twice in one day, then: the `controls` unit test proved that two spellings of
a word matched, and this one proved that a function of a string equals a
function of the same string. Both were written by choosing an input that
looked realistic. The input a constraint test needs is not the realistic one —
it is the one on which a violation would look *different*, which is usually
degenerate, and often looks like a bad test until you mutate the code and
watch it fail.

## A small one, same shape

`Buffers` bounds `history`, `trail` and `marks` at 500 and truncates the
oldest. For the first two that is right — they are logs, and nobody asked for
the five-hundredth command back.

`marks` are different in kind. Each one is an address the user chose to keep,
so evicting the oldest to make room is a small loss of their work, and it
happened without a word. The bound stays; the eviction now says so in the
status line, naming the address that went.

Not a bug anyone would have hit at 500 marks. It is here because it is the
same shape as most of what today turned up: an operation that loses something
and reports as though it had not.

---

## 9. A click split across two reads typed six characters

`decode` is a pure function of one chunk, and `RawTerminal.read` returns
`stdin.read(1)` plus whatever `select` says is already buffered. Where `select`
cannot be used on the handle — a Windows console — that second part returns
nothing, so **every** byte arrives on its own.

A click is a dozen bytes. Split anywhere inside it:

```
'\x1b[<0;10;5M'   whole                -> press
                  split after 4 chars  -> ; 1 0 ; 5 M      (six keystrokes)
                  split after 7        -> ; 5 M
                  split after 9        -> M
```

Typed into whatever field had focus — the exact behaviour the module docstring
promises never happens, arrived at from the other direction: not an unknown
sequence emitted as text, but a known one that had not finished arriving.

`decode_stream(data, pending) -> (events, tail)` holds an unterminated escape
sequence for the next chunk, and `Repl.feed` carries it. `decode` stays as it
was, which is the right shape for a test that hands over a whole sequence and
the wrong one for a loop reading whatever showed up.

### The lone ESC

The first version refused to hold a bare trailing `ESC`, reasoning that it is
genuinely ambiguous — the Escape key and the start of a sequence are the same
byte — and that holding it would break Escape. That left `cut=1` still
producing garbage, which is *the* case on the platform the fix was for.

So it is held, and resolved on the next chunk rather than by a timer: if what
follows does not continue a sequence, Escape fires then. The extra care is
emitting it *separately* — merged as `\x1b` + `x` the pair decodes as one
unknown sequence and both bytes vanish, so someone who pressed Escape and kept
typing would lose a letter.

Escape is now one keystroke late. That is the whole cost, against a pointer
that was unusable wherever the terminal could not batch.

Verified through the real path, one byte at a time:

```
for ch in "\x1b[<0;2;2M": repl.feed(ch)
focus: 0   field value: ''   rendered: '[ ] Search'
```

`scripts/mouse_probe.py` still passes both stages, including the one that
pipes real click bytes into a separate `vertiscope browse` process.

---

## 10. What the classifier got wrong, once it was used

The `controls` fix was measured against the corpus and reported zero misses.
Running it on a live workspace page immediately showed two false positives the
audit's *positive* assertions could not see:

```
pagination:
  home page   /html/body/div[2]/div[1]/bsp-header/div[1]/div[1]/a
  MORE        /html/body/div[2]/div[1]/bsp-header/div[1]/div[2]/bsp-nav/
```

**`home page`** was mine. `page` was in the direction set *and* the unit set,
so "a direction word and a unit word" was satisfied by that one word, and
every label containing it classified as pagination. It belongs in the unit set
only; "page 2" is now caught by a separate rule that also requires a number.

**`MORE`** is Associated Press's section dropdown. Hacker News's pager is
literally "More" and nothing in the label separates them — so the ambiguous
words (`more`, `all`, `first`, `last`, `back`, `forward`) now fire only when
the *target* also looks like paging. That is what the two readings were for.

Then the target reading turned out to be wrong in the same way:

```
_is_paging_target("https://hn.algolia.com/?query=x&page=0")  ->  True
```

Its docstring says "the same listing at a different position" and it never
checked the first half. Hacker News's "past" links go to Algolia's search with
`page=0`, so **32 story rows on one page** were pagination. The query-parameter
reading now requires the target to resolve to the same host and path; the
path-shaped reading (`/page/2/`) does not, because that is precisely the case
where the path legitimately differs.

And one more, from the same run: `/p/25-years-of-blogitude` matched `/p/` plus
digits. The digits must be the whole segment, and `/p/` is gone — as a path it
is more often "post" than "page".

```
                       before   after
news-ycombinator-newest    32        1   (the real "More")
apnews (live)               9        0
theguardian                 3        0
wikidata                    8        0
misses over 14 pages        0        0
```

The audit could not catch any of this. Every one is a *false positive* on a
page with no `EXPECTED` entry, and its only negative assertions are six pages
asserted empty — none of which happened to be a news site with a nav bar.
Positive assertions and a handful of negative ones on quiet pages measure
recall well and precision barely at all.

The thing that caught it was running the command on a real page and reading
the output. Which is the plainest lesson available and the one easiest to skip
once the numbers look green.

### The same bug, one bucket over

Looking at the biggest pages to check precision turned up the *filter* rule
still doing what the pager rule had just been fixed for:

```
pkg.go.dev/net/http    filter = 134   all of them
                       '`type Transport struct { // Request. If the func…'
apnews.com             filter =  26   all of them
                       'Todd Blanche is narrowly confirmed as attorney…'
```

`any(word in text for word in _FILTER_WORDS)` over the joined context. One
doc comment containing "filter" labelled every address that comment covered;
one headline containing "**narrow**ly" did the same. 160 false positives from
two words in two paragraphs.

A filter control names its action first — "Filter by category", "Sort by
price", "Refine search" — so the rule is now a **leading** word from a small
set, in a label of at most five words. That admits the realistic labels
(including the one the old hand-written unit test used, which the first,
too-narrow exact-set version rejected — the test was right and the rule was
wrong) and rejects prose, which leads with a name or a noun.

### One control, listed once

While there: a link is several addresses — the anchor, its `<picture>`, its
`<img>`, each `srcset` candidate — which nest and share a label. So the same
nav item appeared eight times and Associated Press's front page reported
**807 menu items**. Entries in the named roles now collapse when one is inside
another and they read the same, keeping the outermost, which is the element a
click should land on.

```
                     pagination  search  filter   menu
apnews  before                9       4      26    807
        after                 0       4       0    689
pkg.go.dev before             4       1     134    323
        after                 0       2       0    292
```

`menu` is still large, and honestly so: 689 entries over 196 distinct labels,
because Associated Press's header really does contain that many links and the
extractor attributes one ancestor's text to many descendants. It remains the
weakest reading, with no structural second opinion to check it against — named
here rather than tuned until the number looks nice.
