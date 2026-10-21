# The extraction, judged against the pages it came from

*2026-08-15. `scripts/audit_quality.py` over a corpus grown from 54 to **136
frozen pages** (160 urls attempted, 4 dead).*

Every measurement here until now was **internal**: addresses are unique,
chunks partition the addresses, the accounting balances, the invariants hold.
All of that can be perfect while the markdown is garbage, because none of it
compares the output to the input.

So: for each page, build a reference reading of the source — visible text,
regex-stripped of script/style/comments with entities resolved — and ask what
the pipeline did with it.

**As first measured**, with two metrics that turned out to be measuring the
audit rather than the extraction, and one page that produced nothing:

```
                 median    mean     min      max
recall           100.0%   98.7%     0.0%   100.0%    of the page's content words
heading recall   100.0%   91.3%     0.0%   100.0%    of its h1-h6
link recall      100.0%   95.0%     6.7%   100.0%    of its anchors, addressed
anchored         100.0%  100.0%   100.0%   100.0%    output lines with an address
noise             45.9%   45.8%     0.0%    94.9%    lines that are urls/images
duplication       20.8%   23.1%     0.0%    72.6%    lines repeating an earlier one
density           35.2%   35.5%     0.0%    96.2%    output chars per source char
```

**After every fix and metric correction below**, over the same 136 pages, none
failing:

```
                 median    mean     min      max
recall           100.0%   99.9%    97.6%   100.0%
heading recall   100.0%  100.0%   100.0%   100.0%
link recall      100.0%   99.5%    83.3%   100.0%
anchored         100.0%  100.0%   100.0%   100.0%
plumbing           3.2%    8.1%     0.0%    66.7%
duplication       20.4%   22.8%     0.0%    85.6%
density           33.9%   35.3%     1.4%    96.2%
```

**Heading recall is 100% on every axis** — median, mean, minimum, maximum,
across all 136 pages. It read 91.3% mean with a 0% floor when this audit was
first written.

`link_recall` is the number that verifies the url-boundary fix took nothing
real: it measures the source's own anchors against what was addressed, and it
did not move — 99.2% mean, 82.1% worst, before and after removing 13,098
slash-bearing non-urls.

**No page loses more than 2.4% of its words.** Worst link recall 82%, where it
read 6.7%. Worst heading recall 19%, where it read 0% — and the pages that
moved most were card grids that had been served as paragraphs.

Duplication is the one number that went slightly *up*, from 20.1% to 20.8%
median. That is the card fix working: a card whose heading, link and body were
one flattened line is now three addressed lines, and a grid of cards repeats
its labels. Structure recovered at the cost of repetition, which is the right
trade — the repetition is in the page.

The reference is deliberately crude — a regex strip, not a second extractor. A
sophisticated reference would encode its own opinions about boilerplate, and
the audit would then measure agreement between two opinions rather than
coverage of the page.

**Word recall is essentially total.** On 136 pages of every shape — wikis,
specs, news, forums, package registries, government portals, thirteen scripts,
JavaScript shells — the median page loses no content words at all. Whatever
else is wrong, the extraction is not dropping the page.

**Every output line carries an address, on every page, without exception.**
That is the property the whole design exists for, and it is the one that came
back cleanest.

---

## The two pages that failed outright

```
www-ietf-org-rfc-rfc791-txt          1,020 reference words  ->     0 lines
www-rfc-editor-org-rfc-rfc8259-txt     724 reference words  ->    18 lines (33%)
```

Both are `text/plain`. The tagger walks *elements*, and a document with none
emitted nothing — while holding all 94,909 characters on the parse root the
whole time.

RFC 8259 did marginally *worse* than nothing. Its prose contains angle
brackets, so `html.parser` produced 18 "elements" named `douglas`, `iesg` and
`http:`, and the output depended on whether the text happened to look like
markup.

Two fixes. A document with **no recognised HTML element** (tested against the
actual HTML vocabulary, not "any element", or a stray bracket defeats it) is
treated as text. Its content is addressed at `/html/body/pre`, which is not an
invention — browsers wrap a `text/plain` response in exactly that, so the
address resolves in a live scan the same way. Paragraphs split on blank lines
and carry their character offset as the intrinsic sub-address, the same
`@<offset>` spelling a stylesheet's several urls already use, so a paragraph is
individually addressable instead of the file being one indivisible chunk.

```
rfc791     0 lines   0.0% recall  ->  368 lines  100% recall
rfc8259   18 lines  33.0% recall  ->  160 lines  100% recall
```

Getting this right took three passes, and the two wrong ones are instructive.
The first read the **parsed root** rather than the source — but `html.parser`
has already eaten the angle-bracketed prose by then, so RFC 8259 came back as
*"See for the grammar, and for the process"*, missing spans and out of order.
The second ran the element walk first and appended plain text to its results,
which kept the accidental detections at `/douglas` and `/douglas/http:`
alongside the real ones. The check belongs **before** the walk, reading the
**bytes**: when a document is not markup there is nothing to merge with.

---

## An element's tail, twice

`get_text(recursive=True)` walks `iter_all()`, which yields **self** first and
appends each node's text *and tail*. The tagger appended `node.tail` again on
top:

```
<h1>World Wide Web</h1>The W3 is a wide-area…
  -> 'World Wide Web The W3 is a wide-area The W3 is a wide-area'
```

Any element with a tail — any inline element followed by text, the ordinary
shape of prose with links in it.

### The number I nearly reported

Counting elements that *could* be affected gave **18.5%** of text-bearing
elements and an 18.5% text inflation. That figure is wrong, and I had it
written down before checking it against the output.

Most of those elements never emit a detection: a parent that covers them has
already been tagged, and they are on `_skip_text_ids`. Measured on the actual
rendered output, before against after, over all 136 pages:

```
rendered characters   13,525,149 -> 13,502,025   (-0.17%)
pages affected at all          49 of 136
```

Concentrated entirely on loose or ancient markup, where it is large:

```
info.cern.ch  (the first web page)   density 79.4% -> 70.4%
tools.ietf.org/html/rfc2119          density 35.3% -> 26.7%
plato.stanford.edu/…/computability   density 82.6% -> 80.8%
```

A real defect, worth fixing, an order of magnitude smaller than the first
estimate. The lesson is the one this repository keeps relearning: a count of
*candidates* is not a count of *effects*, and the difference is a factor of a
hundred here.

---

## The numbers that are not yet good

**Duplication, median 20.8%, worst 72.6%.** A fifth of output lines repeat an
earlier line verbatim — and the tail fix did not touch it, because that
duplication is *across* lines, not within one. An anchor's text appears both
on the anchor and inside its parent's aggregate. `_dedupe` is element-scoped by
deliberate design (chunk scope was deleting distinct nodes that shared a
string), so cross-element repetition survives on purpose. Whether the design is
right at this rate is a real question and is **not settled here**; it is
recorded with a number for the first time.

**Noise, median 45.9%.** Nearly half of output lines are a url or an image
rather than prose. Every one is a true fact about the page and each is
separately addressable, which is the point — but a reader browsing the markdown
wades through them.

**Heading recall, mean 91.3%, min 0%.** The 0% is `info.cern.ch`, where the
`<h1>` and the following prose are one text node in the source, so the heading
is real but its rendered line carries the paragraph too.

## Two of the metrics were measuring the audit

**Link recall, reported at 95% mean and 6.7% worst.** The source's hrefs carry
raw entities and the extractor resolves them, so `skip=0&amp;show=50` on the
page is `skip=0&show=50` once parsed, and comparing the strings scored arxiv at
47% while every one of its 460 links was addressed correctly.

```
                    before   after
news.google.com       6.7%   96.7%
arxiv cs.IR listing  47.4%  100.0%
news.ycombinator.com 69.0%   99.5%
```

**Noise counted code spans.** A `<pre>` block is the page's own content, and a
`text/plain` document renders entirely as one — so RFC 791 scored **100%
noise** while being 100% content. Asset urls and images are noise; the page's
preformatted text is not.

Neither was a defect in the pipeline. Both were mine, in an audit written that
morning, and both flattered nothing — they made the extraction look worse than
it is, which is the direction that wastes a day chasing a bug that is not
there.

## A pin that was measuring the corpus

`test_ri2_failure_is_pinned` asserted `<= 50 pages`, taken when the corpus had
54. Growing it to 136 failed the test while the defect was unchanged: 50/54 and
126/136 are both **92.6%**. Re-pinned as a rate, since a count is the wrong
shape for a bound whose denominator can move.

---

## The window meant nothing on that shape of document

Fixing the `text/plain` path exposed the next thing. RFC 791 now produced 505
addressed paragraphs — and **one chunk of 65,890 characters, at every window
setting**:

```
window   600  ->  1 chunk, 65,890 chars
window  1200  ->  1 chunk, 65,890 chars
window  4000  ->  1 chunk, 65,890 chars
```

`_descend` splits a subtree by its *element* children. A plain-text document
addresses every paragraph under one element, so there are none, and the branch
that handles "no element children" treated the whole thing as **indivisible**.

That rule is right for one unit and wrong for many. Cutting a single value
would leave a chunk whose root address over-claims — that is the rule, and it
stands. Several units are a different case, and splitting them is safe by
exactly the argument the sibling merge already relies on: the chunk stays
rooted at the element and `anchors` names what is inside, so it under-claims.
`MarkdownChunk.part` already exists to distinguish chunks sharing a root.

```
window   600  ->  136 chunks, largest 1,211
window  1200  ->   62 chunks, largest 1,211
window  4000  ->   18 chunks, largest 3,997
                  zero unaccounted addresses at every setting
```

The 13 chunks still over the window at 600 are single paragraphs longer than
600 characters, which is the indivisible rule doing its job.

Worth noting where this was hiding: on ordinary HTML the units of a page are
spread across many elements, so the descent always found something to split
and the branch was never reached with more than one unit in it. It took a
document shaped differently to show that a hyperparameter had no effect.

---

## Taking the duplication number apart

20.8% median, 72.6% worst, and the note above left it as "a real question, not
settled here". Decomposing it on the two worst pages turns one number into
three different things:

```
apnews.com              5,692 lines   4,002 duplicates (70%)
  same element, more than once                    1,474
  media placeholders naming a tag, not a url        923
  distinct elements that genuinely share text     the rest
```

**Distinct elements sharing text is correct and must stay.** Nineteen books
each showing "In stock" is nineteen addressable facts, and collapsing them
would delete eighteen addresses — the exact defect that moved `_dedupe` from
chunk scope to element scope in the first place.

**The same element, more than once, is mostly correct too.** An `<a>` yields
its href *and* its anchor text; an `<img>` yields its src *and* its alt. Two
facts, two addresses, both wanted.

Two of them were not.

### A control and its own text

```
( Add to basket )
Add to basket
```

both at `.../form/button`, nineteen times. `_dedupe` compares the *raw*
values — `"button"` and `"Add to basket"` — and keeps both, correctly on what
it can see. The duplication is created afterwards, when `_render_unit` draws
the control **using the text unit's value**. The control keeps its line, since
the marks are what make it a button in the REPL; the plain repeat goes.

Narrowly, though: `interactive.links` and `interactive.elements` are
suppressed renderings, and there the text *is* the content, so it must not be
treated as consumed. That distinction is a test.

### A placeholder that invented a target

```
![images](svg)     x384
![video](source)   x331
```

Some detections carry the element's **tag name** as their value, because the
element is the finding and there is nothing else to record. Rendered through
the media form, that reads as an image located at "svg". There is now no
target when there is nothing to name: `![images]`.

I also dropped the placeholder outright where the same element yielded a real
url — an `<img>` producing both `![images](img)` and `![images](media/cache/…)`
being one image described twice. That was wrong, and an existing guard said so:
`test_suppressed_units_are_a_deliberate_choice_not_a_leak` failed on 20 units.
They are two *addresses* with different accessors (`text()` and `src`), and a
url or media address vanishing from the output is precisely what that test
exists to prevent. Reverted; the honest rendering was the half that mattered.

```
                     lines   dup    noise
books.toscrape  391 -> 351   40->34%  37->35%
wikipedia      1709 -> 1668  25->24%  51->51%
apnews         5692 -> 5540  70->70%
```

Word recall stays at 100% on all three and the accounting still balances, so
nothing was lost — but the honest summary is that this removed the two
*wrong* kinds of repetition and barely moved the headline number, because on
a page like Associated Press's front page most of the repetition is a nav bar
that really does say "More" a hundred times. **The remaining duplication is
mostly the page, not the extraction.** That is worth knowing and was not
knowable before the decomposition.

---

## Where it ended

136 pages, none failing, after everything above:

```
                 median    mean     min      max
recall           100.0%   99.9%    97.6%   100.0%
heading recall   100.0%   91.3%     0.0%   100.0%
link recall      100.0%   99.2%    82.1%   100.0%
anchored         100.0%  100.0%   100.0%   100.0%
noise             42.9%   41.8%     0.0%    85.6%
duplication       20.1%   21.6%     0.0%    72.1%
density           34.2%   35.6%     1.4%    96.2%
```

Seven documents of deliberately different shape, as a sanity read on the
aggregate:

```
                              size   lines  recall  head  link  noise  dup
Pride and Prejudice          778KB    2880   100%    47%  100%    11%   5%
grep(1) man page              45KB     134   100%   100%  100%    63%  27%
Hebrew Wikipedia (RTL)       251KB    2416   100%   100%   99%    42%  15%
Thai Wikipedia (no spaces)   290KB    2573  99.4%   100%  100%    39%  19%
GNU ftp directory index       75KB    2290   100%   100%  100%    34%  47%
info.cern.ch (1991)            2KB      61   100%     0%  100%    41%   0%
RFC 791 (text/plain)          93KB     368   100%   100%  100%     0%   0%
```

The two low numbers there are both understood rather than mysterious.
Gutenberg's 47% heading recall is chapter headings wrapped in anchors, so the
rendered line carries the link too. The ftp index's 47% duplication is a
directory listing in which many rows genuinely repeat a size or a date — the
page, not the extraction.

**What this exercise was for.** Every prior measurement in this repository was
internal, and internal measurements cannot see a page that produces nothing.
Two did. A third produced one chunk whatever the window said. None of that was
visible from uniqueness, partition, accounting or invariants — all of which
were green throughout, on all 136 pages, before and after.

## A third thing that measured to nothing

Tripling the corpus should have made the suite much slower: `corpus_metrics`
runs the whole pipeline *plus* a SQLite ingest once per page, and the pages
now include several over 2 MB. Watching a run crawl at 6% after minutes, I was
composing the fix — sample the per-page sweep, put the full corpus behind an
opt-in flag.

Measured:

```
 703 tests over  54 pages   5:28
1126 tests over 136 pages   4:59
```

Faster. The crawl was contention from three of my own background jobs sharing
four cores, not the corpus. Nothing to fix, and the fix would have traded away
breadth — the one thing the corpus is for — to solve a problem that did not
exist.

That is the third speculative change this pair of sessions has stopped at the
measurement, after `settle_order` and normalising urls at ingest. The pattern
is consistent enough to state plainly: **the interval between noticing
something and believing a number about it is where the wasted work lives.**

---

## The heading number was two things

Heading recall sat at 91.3% mean, 0% floor, and I had it filed as "understood"
— the CERN page's `<h1>` sharing a text node with its prose. Chasing it
properly found that it was one metric error stacked on one real defect, and
the real defect was the largest single finding of the exercise.

### The metric, a third time

Gutenberg's *Pride and Prejudice* scored 47%. Its chapter headings look like

```html
<h2><a id="PREFACE"></a><span class="pagenum">{ix}</span>
    <img src="i_010.jpg" alt="PREFACE."></h2>
```

The heading's *visible text* is `{ix}`; the word "PREFACE." is in an image's
`alt`. The pipeline reads `alt` and produced `## PREFACE. {ix}` — **better**
than the source's own text — and my exact-string comparison scored that a
miss. The reference regex also occasionally spans from one heading to a
distant close tag, producing run-ons like
`'He rode a black horse. CHAPTER III.'` that are not headings at all.

Comparing by *containment* — a source heading is found when its words are
inside some rendered heading — takes Gutenberg to 100% and the corpus mean
from 91.3% to **94.5%**.

That is the third of seven metrics that was measuring my audit rather than the
extraction. All three erred against the code. A crude reference cuts both
ways, and it is worth saying plainly that the extraction was better than my
first measurement of it on every axis where we disagreed.

### The defect underneath

With the metric fixed, one page stood at **3.7%**: stackexchange.com/sites,
189 headings, **6 rendered heading lines**. Minimally:

```html
<a href="/sf"><div class="card"><div class="wrap">
    <h2>Server Fault</h2><img><p>Q&A for sysadmins</p>
</div></div></a>

  ->  /html/body   'Server Fault Q&A for sysadmins'
```

One detection. The whole card, flattened.

`has_block_children` inspected only the element's **direct** children. An
inline `<a>` wrapping block content — the whole-card-is-a-link pattern, which
is most of the modern web — showed only `<a>`, so the subtree was judged
text-like, `get_text(recursive=True)` swallowed it, and every descendant went
on `_skip_text_ids`.

It now descends *through* inline children until it finds a block element.
Prose with links in it still stays one line, which is the property the
original rule was protecting.

```
                            heading recall     lines
stackexchange.com/sites      3.7% -> 100%   1,630 -> 4,008
bbc.com/news                12.5% -> 100%   1,216 -> 1,328
cbc.ca/news                 28.6% -> 100%     636 ->   741
theguardian.com             18.8% ->  30%   3,146 -> 3,172
```

Word recall never moved — it was 98–100% before and after. **The words were
always there; the structure was not.** Every internal check passed throughout,
because a heading absorbed into its parent's text is still addressed, still
partitioned, still accounted for. Only a comparison against the page could see
that a card grid had been served as a paragraph.

The Guardian's remaining 70% is a different cause and is not diagnosed here.

### And the Guardian, which I had left flagged

I closed the last write-up with "the Guardian's remaining 70% is a different
cause and is not diagnosed here". It was two more causes, one real:

**A heading that delegates all its text to children produced no heading at
all.** The branch handling an element with block children emits only that
element's *own* text, and the Guardian's headlines are

```html
<h3><div>Technology</div><span>The backlash against Meta smartglasses</span></h3>
```

so 124 of its 181 headings arrived as ordinary text — every word present, no
structure. Corpus-wide, 161 of 3,867 headings are shaped this way (4.2%), 124
of them the Guardian's; the rest are a handful each on NOAA, ABC, Docker Hub
and Eurostat.

Everything inside a heading is part of that heading, so the label now carries
down to its children, with a nested heading taking over.

```
                              heading recall
theguardian.com    18.8% -> 29.8% (card fix) -> 43.1% (this)
noaa.gov              25% -> 75%
hub.docker.com                  -> 94.1%
abc.net.au/news                 -> 100%
```

Line counts did not move on any page, and wikipedia, books.toscrape and the
grep man page stayed at 100% throughout.

**And the fourth metric artifact.** The remaining Guardian gap was every word
of every "missing" heading appearing across **two consecutive heading lines** —
the kicker and the headline, rendered correctly as two. My check demanded one
line. Allowing a run of up to three takes it to 100%, and three is narrow
enough that this cannot decay into "the words appear somewhere".

That is four of seven metrics that were measuring the audit rather than the
extraction, all four erring against the code. Stated once more because the
ratio is the finding: **on every axis where my reference and the pipeline
disagreed, the pipeline was right.**

---

## The live probe's gate was at the wrong scope

`probe_live_delta.py` asserts *"the page actually changed while being driven"*,
and the reasoning is exactly right: everything it measures below that is
vacuous otherwise, because a static page yields an enormous "saving" that is
really the cost of confirming nothing happened.

It applied that **per page**, across two urls. `quotes.toscrape.com/js-delayed/`
races its own JavaScript delay against the scanner's first settle and had
finished loading before pass 1 — so the probe failed a run in which `/scroll`
had exercised the incremental path perfectly well.

Whether a *given* page mutates inside the scan window is a fact about that
site's JavaScript. Whether *any* did is a fact about the run, and that is what
the O(delta) claim rests on. A page that did not change is now reported and
skipped; `main` fails only if nothing changed anywhere.

```
  [skip] quotes.toscrape.com/js-delayed/ did not change during the scan
         (5 steady pass(es)) — not exercised
  [PASS] some page changed while being driven
         (1 of 2 page(s) exercised the incremental path)
  ...
  PROBE PASSED
```

The anti-flattery guarantee is intact — a run where nothing moved anywhere
still fails — and the dependence on a third party's timing is gone.

**This is the fourth check this pair of sessions whose reasoning was right and
whose scope was wrong**, next to the `<= 50 pages` pin that was measuring
corpus size, the `>= 45 clean pages` floor that would have passed with 91
mangled, and `has_block_children` looking one level down instead of through.
A correct rule evaluated over the wrong domain does not announce itself: it
passes, or it fails, for reasons that have nothing to do with what it is
about.

---

## "Noise", the fifth metric that was measuring the wrong thing

I reported noise at 41-46% median through this whole write-up, described it as
"a reader wades", and listed it as one of the two numbers that are "genuinely
about the design rather than about a bug". Decomposing it — 9,442 lines over
five pages — it is not one thing:

```
   38.2%   a url in the page body        <- the payload
   13.2%   an image in the page body     <- the payload
    6.0%   a <script> or <link> in the body
    2.4%   an asset in <head>
```

Body links and images are precisely what a **content-addressing scraper**
exists to capture. Calling them noise is calling the output of the system
noise. Only the last two categories are plumbing — a reference to a resource
rather than a fact about the content — and they are **8.4%**, not 41%.

Renamed and re-measured:

```
books.toscrape.com                plumbing  2.7%
apnews.com                                  3.1%
grep(1) man page                            2.2%
RFC 791 (text/plain)                        0.0%
en.wikipedia.org/wiki/Web_scraping         16.5%
```

Wikipedia's 16.5% is real — its `<head>` and inline resource hints are a
genuinely large share of a Wikipedia page — and that is now a number about
resource references rather than a number about content.

That is **five of seven metrics** that were measuring the audit rather than
the extraction. Every one of them erred against the code, and this one erred
by mistaking the deliverable for the debris.

The reference being crude is the design, and it was the right design — a
second extractor would have encoded its own opinions. But crude means wrong in
both directions, and it is worth being explicit that the direction it was
wrong in here was *pessimistic*, five times running. The extraction was better
than my measurement of it, every time we disagreed.

---

## Duplication, settled

The last number left hanging. After the two wrong kinds were removed, over six
of the most repetitive pages in the corpus:

```
17,838 lines, 9,523 duplicates (53.4%)

   9,523  100.0%  the same text at *different* elements
       0    0.0%  the same element, emitted twice
```

Not one case of an element saying the same thing twice. Every remaining
duplicate is a distinct addressable element that happens to carry the same
words as another — nineteen books each reading "In stock", a nav bar with
"More" a hundred times, a directory index whose rows repeat a size.

Collapsing them would delete addresses, which is the defect that moved
`_dedupe` from chunk scope to element scope in the first place. **The
duplication is the page, not the extraction**, and that is now measured rather
than argued.

That closes every quality number the audit raised. Of the seven metrics, five
were measuring the audit and have been corrected; of the two that were real,
both were fixed and the fixes carry regression tests with the measured numbers
in them.

---

## Uniqueness, re-proved at 3.2x the scale

The completeness-uniqueness result was established over 54 pages, after
THEORY Prop. 10.2's proof lemma turned out to be false and 402 addresses on a
single page collided. The intrinsic sub-accessor — a candidate index, a
character offset, a JSON pointer — was designed against that corpus and has
read zero collisions since, *on that corpus*.

Re-run over 136 pages, including 82 chosen partly because they are hostile to
it — Thai and Korean Wikipedia, the WHATWG multipage spec, `ftp.debian.org`
and `ftp.gnu.org` directory indexes of near-identical rows, a 2.6 MB
browser-comparison table, and the two `text/plain` RFCs now routed through the
`/html/body/pre` + `@offset` path added today, which had never been through
this audit at all:

```
pages                    136 / 136
A1 detections            344,876
   distinct addresses    342,939   (1,937 exact-duplicate detections collapsed)
   COLLIDING addresses         0   uniqueness holds
A2 invented / lost        0 / 0    bijection holds
A3 mis-ordered parents    0 of 50,146 compared (0.00%)
   pages exact           136 / 136
trie nodes               898,773 for 342,939 leaves (2.62 nodes/leaf)
```

Against the previous run: **344,876 detections where there were 106,789**, and
still not one address carrying two different values. Walk order reproduces the
DOM on every page, exactly, including the ones with no DOM.

### The audit died after passing

It also crashed on the last line. `print(f"wrote {args.json.relative_to(ROOT)}")`
raises when the path is not under `ROOT` — which a *relative* `--json` never
is, because it resolves against the working directory. So

```
python scripts/audit_addressing.py --json notes/observations/_addressing.json
```

did every page, wrote the file, printed the result, and then exited with a
traceback: a passing audit reporting failure, over cosmetic path formatting.
It is exactly the shape this session keeps finding — the work succeeds and the
report lies — and it would have made the audit unusable as a CI gate in the
one invocation that produces the artifact.

---

## What the O(delta) claim actually depends on

The addressing audit reports "one-leaf delta visits" per page — how many trie
nodes a single-leaf change costs. Median 62. The maximum is 2,175, and the
distribution turns out to be governed by one thing.

```
trie shape (nodes per leaf)      pages   median share visited   worst
flat      (< 1.5)                    2              100.00%    100.00%
shallow   (1.5 – 2.2)                2                0.99%      1.21%
nested    (> 2.2)                  122                2.82%     28.16%
```

Merkle pruning skips **subtrees**. A document with no subtrees has nothing to
skip, so the walk is linear in the page. The two flat pages are the two
`text/plain` RFCs, and they are flat *because of the change I made this
morning*: every paragraph is addressed at `/html/body/pre` with an `@offset`
accessor, which makes 505 siblings under one parent and a trie of 513 nodes
for 505 leaves. A one-leaf delta costs all 513.

Against the other end of the same table:

```
27,534 leaves  ->   110 nodes visited     en.wikipedia.org/…/Comparison_of_web_browsers
24,430 leaves  ->   266                   w3.org/TR/wai-aria-1.2
14,806 leaves  ->    73                   rfc-editor.org/rfc/rfc9110.html
```

A 27,534-leaf page costs **110** visits; a 505-leaf flat one costs **513**.
That is a much stronger statement than the README was making, and a sharper
caveat than it was making too. The claim is not "the work tracks the change,
not the page size" without qualification — it is:

> the work tracks the change *divided by the tree's branching structure*, and
> a document with no branching has nothing to prune.

**Whether the flat case matters in practice is a separate question, and the
answer is mostly no.** A `text/plain` document is static — no script, no
scroll-loading, nothing to re-scan — so its delta path never fires outside a
benchmark. The cost is real and is worth knowing; it is not worth restructuring
the address scheme to avoid, and doing so would mean inventing intermediate
xpath steps that no browser would resolve.

Recorded rather than fixed, with the number, because the alternative is a
headline claim that is true on 122 of 126 pages and silently false on the
shape I introduced.

---

## Two defects a real crawl found that no fixture would

Running `vertiscope scan https://books.toscrape.com --follow 3` — the first actual
crawl this session — produced four pages, three of which reported *identical*
statistics:

```
[1/4] depth 0  https://books.toscrape.com                 501 addr, 20 chunks, 366 lines
[2/4] depth 1  https://books.toscrape.com/html              3 addr,  1 chunk,   3 lines
[3/4] depth 1  https://books.toscrape.com/index.html      501 addr, 20 chunks, 366 lines
[4/4] depth 1  .../catalogue/category/books_1/index.html  501 addr, 20 chunks, 366 lines
```

**`/` and `/index.html` are the same document.** `canonical_url` does not
collapse them, and it is right not to — they are genuinely different urls and
the address scheme stores what it scanned. But a *crawl budget* is a different
question and the budget is the scarce thing: half of it went on one page, and
PageRank then saw two nodes where there is one document. The dedup key now
folds `/index.html`, `/index.htm`, `/index.php` and friends onto the
directory, case-insensitively, leaving `notindex.html` and any url with a
query alone. Crawl-local: nothing stored is rewritten.

**`/html` is not a page.** Tracing it back:

```
value='/html;'   xpath=/html/head/meta[1]   accessor=content
```

from

```html
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
```

The absolute-path branch of the url regex treated the `/` in a MIME type as a
path root. That put a non-url in the address space, a `</html;>` line in the
markdown, and — because `canonical_url('/html;', base)` is a perfectly
well-formed url — a junk page in the crawl frontier, which cost a real page
fetch to discover was nothing. The branch now requires the leading `/` not to
follow a letter or digit, so `text/html`, `application/ld+json` and `text/css`
stop yielding `/html`, `/json` and `/css`.

Measured over the `content` attributes of all 136 pages, the branch was
producing **70 urls that are not urls** — and MIME types are only part of it:

```
before 269   after 199   removed 70

/html;            text/html; charset=UTF-8
/png              image/png
/05/28  /06/12    a date, 2026/05/28
/D7BwPKMQzBiD     a token with a slash in it
/presentation
```

Dates are the interesting ones. `2026/05/28` in a `content` attribute yielded
`/05/28`, a well-formed relative url pointing nowhere, indistinguishable from
a real path once it is in the address space. That is the whole class: the
regex was matching *any* slash-bearing text, and a leading-boundary check is
what separates a path from the middle of something else.

After the fix the same crawl reaches `mystery_3/index.html` — a genuinely new
page — instead of scanning the home page twice.

Neither of these could have come from the frozen corpus. One is about how a
budget is spent across pages, and the other only becomes visible when
something *fetches* the url a false detection produced. A fixture can hold a
`<meta>` tag; only a crawl goes and asks the server for `/html`.

---

## A heading that is also a button

With heading recall at 99.2%, the remaining floor was 42.9% on
`webscraper.io/test-sites/tables`. Four of its seven headings were "missing",
and the output shows why:

```
want 'Products'     got '( Products )'
want 'Resources'    got '( Resources )'
want 'Contact us'   got '</contact>'
want 'Company'      got '<https://lv.linkedin.com/company/web-scraper>'
```

A footer accordion: the `<h5>` holds a toggle. So the heading label propagated
correctly to the child (today's fix), and then `_render_unit`'s interactive
branch — which had never looked at the label — rendered a button. The heading
marker was the casualty of the two changes meeting.

**34.1% of the corpus's headings contain a control or a link** (1,320 of
3,867), so this is not a corner:

```
   309  rfc-editor.org/rfc/rfc9110.html
   184  pkg.go.dev/net/http
   163  apnews.com
    91  abc.net.au/news
    63  Pride and Prejudice
```

Most were already right, because the label reaches an `<a>` inside a heading
and prose renders with the marker. Only the ones whose rendering *consumed*
the text lost it. A control inside a heading now carries both:

```
<h5><button>Products</button></h5>   ->  ##### ( Products )
<h2><a href="/c">Contact us</a></h2> ->  ## Contact us
```

It is a level-N heading and it is a button; there is no reason for the line to
pick one. A control outside a heading gains nothing, which is a test.

```
webscraper.io/test-sites/tables       42.9% -> 100%
webscraper.io/…/e-commerce/allinone   69.2% -> 100%
apnews.com                                  -> 100%
```

Worth noticing that this defect was *created* today, by the heading-label
propagation, and found the same day by the metric that motivated it. The audit
paying for itself twice is the argument for keeping it cheap enough to re-run.

---

## Two more from the heading floor, one fixed and one open

With heading recall at 99.9%, the floor was `letterboxd.com/films/popular` at
83.3%. Its rendered "headings" were:

```
#14181C
#445566
# Letterboxd — Your life in film
##### Add to your films… I watched… Edit
## Films
##### Upgrade to removeads
```

**A hex colour is not a heading.** `<meta name="theme-color" content="#14181C">`
put two colours at the top of the output as lines opening with `#`, which *is*
a markdown heading and which anything keying on `startswith("#")` — including
this repo's own `Document.from_chunks` — reads as one. Hashtags, `#1
bestseller` and `#include` are the same shape. Text values opening with `#`
are now escaped, and a real heading is untouched.

**`Upgrade to remove ads` came out as `Upgrade to removeads`.** Two text
fragments concatenated with no separator, fusing two words into one. It costs
more than tidiness: "ads" is no longer a term, so the page's word recall reads
**99.6% instead of 100%**, and a search for "ads" cannot find the line.

I looked for it in the source markup with regexes, decided the fragments must
be split across elements, and wrote it up as undiagnosed. That was the wrong
instrument. Asking the *parsed DOM* what the node actually held took one
command:

```
<h5> text='Upgrade to remove ads'
```

There is no split. It is a **non-breaking space**, and `_INVISIBLE_TRANS` was
deleting it:

```python
_INVISIBLE_TRANS = str.maketrans('', '', '​‌‍﻿ ')
                                                                  ^^^^^^^^
```

U+00A0 was sitting in the zero-width set beside the zero-width space, the
joiners and the BOM. The other four are genuinely invisible and deleting them
is right. **A non-breaking space is a space** — it is what `&nbsp;` produces —
and deleting it fuses the words on either side.

Across the corpus: **250 word-joining occurrences on 25 of 136 pages**, with
Russian Wikipedia alone at 82, Hacker News at 28, and the PostgreSQL `SELECT`
reference at 18. Every one of them was a term that could not be searched for
and a pair of words that had silently become one.

```
letterboxd.com/films/popular   heading recall 83.3% -> 100%
                                  word recall 99.6% -> 100%
```

The lesson is about instruments, again: I spent three attempts grepping HTML
source for a boundary that was not there, when the object that actually knew
the answer — the parse tree — was one call away. "Not diagnosed" was the
honest report of a bad search, not of a hard problem.

---

## Heading recall, closed

```
heading_recall   median 100.0%   mean 100.0%   min 100.0%   max 100.0%
```

Every heading on all 136 pages. It read 91.3% mean with a 0% floor when the
audit was first written this morning. Four things got it there — two real
defects (an inline `<a>` swallowing the card it wraps; headings delegating
their text to children), one regression those introduced (a heading that is a
control losing its marker), and two metric corrections (exact-match, then
single-line matching).

## Word recall's floor, still open

97.6% on en.wikipedia.org's Python article, 69 words of 2,877: `afaik`,
`nalso`, `cygwin`, `emscripten`, `msvc`, `musl`. Editor chatter and platform
names out of the raw wikitext Wikipedia ships in its config payload, with
newlines as literal `\n` — which is where `nalso` comes from, `\nAlso` read as
characters.

A browser renders none of it. **The extraction is right not to emit it and the
reference is wrong to ask for it** — so this is the seventh metric artifact,
not an extraction defect. But *where* the payload survives `_DROP` is not
established.

I guessed escaped comments (`&lt;!--…--&gt;`), wrote the fix, and measured it:
**0 characters removed** from that page. Reverted. The reasoning was plausible
and the measurement said no, which is the only thing that decides it — and it
is the fifth speculative change this pair of sessions has stopped at exactly
that point, after `settle_order`, ingest-time url normalisation, suite
sampling, and dropping the media placeholder.

Recorded in `visible_text`'s own docstring, so the next person to look at 97.6%
starts from what has been ruled out rather than from the same guess.


---

## Two regexes, one bug, two different right answers

The last two numbers to move were both the reference's own quote handling, and
what to do about them was not the same.

**`_ANCHOR` used `[^"']+`**, which stops at *either* quote — so
`href="workers.html#the-worker's-lifetime"` was read as
`workers.html#the-worker`. The whatwg and w3 specs are full of anchors like
`#writing-a-form's-user-interface`, and both scored **82.1%** link recall
while every link had been addressed in full. Fixed exactly, with a
backreference to the quote that opened the value: `(["'])(.*?)`.

**`_TAGS` uses `<[^>]+>`**, which has the same shape of flaw — it stops at the
first `>`, so Wikipedia's `data-mw` JSON attribute leaks 5,825 characters of
raw wikitext out of one `<span>`. The obvious fix is much *worse*: an
apostrophe in ordinary prose opens a phantom quote, and corpus recall falls to
63.0%.

The difference is what the delimiter is. An `href` is one attribute whose
opening quote can be captured; a whole tag is an arbitrary run of attributes,
and matching that needs a tokenizer — a second HTML parser, which is precisely
what this reference exists not to be. So one is fixed and one is a priced
design choice, and both reasons now live in the code rather than in my head.

```
link recall      82.1% -> 100%   (whatwg, w3)      99.2% -> 99.5% mean
word recall      97.6% floor, diagnosed, not fixed
```

That closes the audit at **eight corrections across seven metrics** — more
corrections than metrics — every one of which had made the extraction look
worse than it is.
---

## The last link, and it is not the reference's fault

`kubernetes.io/docs/concepts` at 83.3% link recall — six anchors, one
unmatched. Six is small enough to read, which is the right instrument for a
six-item discrepancy, and the prior after today was that it would be a ninth
reference artifact. It is not.

The unmatched anchor is **1,046 characters long**: a GitHub "create new file"
link with an entire page template URL-encoded into its query string. The
extractor caps url values at 500 (`u[:500]`), so the stored address holds the
first half of it.

That cap is deliberate and the reason for it is good — an unbounded value from
an untrusted page is a real hazard. But a **truncated url is not a shortened
url, it is a wrong one**: the address no longer resolves to the thing it
names, `vertiscope where` hands back a target that does not exist, and clicking it
in the REPL goes somewhere unintended. It is the same shape as the rest of
today's list — a lossy operation that does not say it was lossy.

Measured, before deciding anything about it:

```
anchors longer than the 500-char cap:  6, on 5 of 136 pages
longest:                               835 chars
pages:  archive.org · MDN (css, html) · kubernetes.io · news.google.com
```

Six links out of tens of thousands. Not worth raising the cap for, and
certainly not worth removing it — but worth knowing that those six addresses
are unresolvable rather than merely abbreviated, which nothing said before.

The cheap honest fix, if it is ever wanted, is a marker on the value rather
than a bigger number: a truncated address that *knows* it is truncated can be
refused by `where` instead of silently resolving wrong. Recorded, not built,
because six is not yet a reason.

---

## The two worst-case columns, explained

Both remaining maxima turn out to be the corpus telling the truth about
itself.

**Plumbing, 66.7% max.** The three worst pages are `archive.org/details/texts`
(21 lines), `gitlab.com/explore/projects` (76) and `reddit.com/r/…` (18) — all
JavaScript shells. A page that server-renders almost nothing emits almost
nothing but its `<head>`, so two thirds of fourteen lines being resource
references is the metric working, not failing. The pages with the worst
plumbing ratio are the pages with the least content, which is what that ratio
should say.

**Duplication, 85.6% max**, on `sqlite.org/lang_select.html`:

```
2,786 lines   0 same-element duplicates   2,385 different-element

   312x 'expr'          grammar terminals, repeated by every railroad diagram
   139x '![images]'     139 separate SVG syntax diagrams
   133x '[show]'        each diagram's show/hide toggle
    69x 'PRECEDING'
```

Not one case of an element emitting the same text twice — the same result as
the earlier six-page check, now confirmed on the single worst page in the
corpus. A SQL syntax reference repeats `expr` three hundred times because the
grammar does. Collapsing those would delete 311 addresses pointing at 311
distinct places in the document.

So every column of the audit is now either at 100% or has a named reason:

```
recall        97.6% floor   `data-mw` json leaking past `<[^>]+>` in the reference
headings        100%        everywhere
links         83.3% floor   six urls over the 500-char cap, on five pages
anchored        100%        everywhere
plumbing      66.7% max     javascript shells with almost no content to dilute it
duplication   85.6% max     a grammar reference repeating its own terminals
```

None of the six is an unexamined number, which was not true of any of them
this morning.

---

## `![images]` × 139, and why there is nothing to do about it

This morning I changed a media placeholder from `![images](svg)` to
`![images]`, because naming "svg" as the target invented a url that does not
exist. I checked that the individual line was honest. I never looked at what
139 of them in a row reads like — and `sqlite.org/lang_select.html` has
exactly that.

The obvious improvement: the extractor already reads `alt` and `aria-label`
into `text_at`, so a diagram with `alt="SELECT syntax"` could render
`![images] SELECT syntax`. Measured first, for once, before writing it:

```
139 <svg> tags
  0 carrying aria-label, alt or role
  1 <title> element in the whole document (the page's own)
```

There is no accessible name to render. `![images]` is not
honest-but-useless — it is the *complete* truth available about those
elements, and the improvement would have had nothing to put in it.

Then the better question, which the duplication decomposition had already
handed me without my noticing: if the diagrams are opaque, where do 312
occurrences of `expr` come from?

```
'expr' detections: 313
   text.visible   /html/body/div[2]/div[2]/div[1]/svg/text[15]
   text.visible   /html/body/div[2]/div[2]/div[1]/svg/text[18]
```

Inside the SVGs. These are `pikchr`-generated railroad diagrams, and every
grammar terminal in them is a `<text>` element — so the diagrams are not
opaque images at all. Each terminal is extracted as its own addressed line,
pointing at its exact position *within* the diagram.

So a SQL syntax diagram comes out of this pipeline as readable, addressable
text, and the `![images]` marker sits where the diagram is. That is not a
quality problem; it is the best case for a content-addressing scraper, and I
was two steps from "fixing" it.

The number that looked worst on the worst page — 85.6% duplication — turns out
to be the signature of the thing working unusually well.

---

## The renderer moved and the parser did not — again

Checking that today's rendering changes survive the JSONL checkpoint. They
round-trip byte-identically, which is what I was testing. The widget they
produce does not:

```
('button', '##### ( Products )')
```

The button's *label* is the entire rendered string. `Document.from_chunks`
strips the control marks with `label.startswith("( ")`, and the heading marker
I added a few hours ago moved them off the front, so the strip stopped firing
and `Widget.render` re-wrapped the lot as `( ##### ( Products ) )`.

This is the same defect as the `] Quick search` input bug found this morning,
in the same function, introduced by me, hours after fixing the first one: **a
renderer changed without its parser.** The marker now comes off first and
lives on the widget as its own field, so the label is what a reader wants and
the marker is put back when painting.

Nothing in the audit could see it. Heading recall reads the *markdown*, where
`##### ( Products )` is correct; the corruption only exists after
`from_chunks`, in the REPL. It took feeding the artifact back through the
consumer that reads it.

That is the third instrument-shaped lesson of the day, and the cleanest:

```
internal checks      cannot see a page that produces nothing
the corpus           cannot see a budget spent twice on one document
the crawl            cannot see a widget built from correct markdown
```

Each one is blind to the layer above it, and every layer had a real defect
waiting in it.
