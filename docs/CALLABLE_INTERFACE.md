# The callable interface: the Python REPL is the browser

## 0. The requirement, verbatim

> Not much improvement. How about this, perhaps we analyze this from the most
> convenient interface that a small language model could interact with safely?
> Perhaps we could keep the design simple and separable for the REPL and the
> *python* modules we are interacting with, including our browser interface.
>
> The real cool insight here is that we discover the best interface for SLMs is
> at the code terminal itself. It means that instead of injecting the whole
> engineered context into the small window, we do something even more extremely
> efficient; we make function-object modeling and navigation a callable-first
> interface. The two components of this idea stem from:
>
> When I type "help(_____)" in the Python REPL, I get a scrollable code-docs.
> This is a clever graph RAG hack, since the docs of the code are the primary
> descriptors of what the *code* does. The other thing about the REPL is that
> if we can find an easy way to display objects for their contents *and*
> interact with complex data structures, even better. If that means we do some
> object model design for our shadow dom deep serializer and change web
> interface to some convenient and interactive data object, then we can then
> use function and object calling as an expand-collapse interaction on the
> page, where we include inplace interactions like entering new search terms on
> a search page object. So the real pivot, I suppose, is the package design of
> our interactive serializer in the Python REPL directly. But the design of
> this package can emphasize navigating over interactive webpages for all
> content, their structures tracked fully in our vectorization-database
> pipeline. The focus should be on legibility and *nested interactivity*. If we
> want to view the markdown chunk or in the subtree, we can. If we want to see
> all the links we can click and other media, we can. If there is a structure
> with a search box, we can interact with it. If there is a nested HTML
> substructure within our content's patricia trie, it is immediately accessible
> as a composed data object. Some kind of design that makes legibility clear
> always, but interaction and ergonomics both designed together. How would we
> navigate to duckduckgo, find the search box on the page, enter a term and
> then 'enter', find the new page, access immediate chunk results without
> needing to scroll, open a result and see it completely, go back up, and so
> on...

The sketch supplied with it is reproduced in section 3, and the walkthrough it
asks for is answered in section 5.

## 1. Why this is the right shape

Two observations, and the second is what makes it more than a convenience.

**`help()` is retrieval that costs nothing.** A docstring is the primary
description of what code does, written where the code is, and the REPL already
pages it. A model that can call `help(obj)` does not need the interface
explained in its prompt: the interface explains itself, at the moment of use,
scoped to the one object in hand. That is graph RAG whose graph is the import
graph and whose index is `__doc__`.

**Calling is expand-collapse.** The trie is already a tree of addressable
nodes; a node is already a chunk of markdown; a chunk already knows its
children. Focus *is* descent, and descent is what a call expresses. The TUI
spent a screen to say what `Result(1)` says in nine characters, and the screen
has to be re-sent every turn while the expression does not.

For a small window the consequence is not marginal. A page is 400 lines; a
node's child list is eight. The model pays for the eight it is looking at, and
pays again only when it descends.

## 2. What this is built on, and what is new

Nearly all of it exists. This is a facade, not a rewrite, and that is the
argument for doing it.

| the objects need | already exists |
|---|---|
| the tree | `AddressTrie` — nodes, addresses, document order |
| a node's text | `render_trie` — markdown per chunk |
| what a node IS | render class (BROWSER_PIVOT section 3), tag plus interactivity |
| navigation | `WebNav.visit / click / type_into / back` |
| in-page retrieval | `ThreeFormIndex`, `Workspace.search` |
| history retrieval | `GraphStore`, over every trace ingested |
| the fold | `Sensor` plus `StreamingScan`, unchanged |
| safety | `refused()` in the sensor — but see section 6 |

What is new is one module of objects, their `__repr__`, and a cursor.

**Separability is a requirement, not a preference.** `domvec/live/` imports
from `trie`, `markdown`, `sensing` and `repl.nav`, and nothing imports back
into it. The TUI keeps working; the analytics keep measuring the same trie. An
`invariants` rule should hold the direction of that arrow the way `c4` holds
the REPL and analytics apart.

## 3. The sketch this comes from

```python
>>> Page()
Page("https://www.duckduckgo.com/")
|--- div("header/markdown text truncated...")
|--- input("another header/markdown text truncated...", script=True, input=True)
|--- div("header, markdown text truncated...")

>>> div("header/markdown text truncated...")  # calling changes the namespace
# Full Markdown text from full chunk
...
|---Button("any text in the button")
|---Input("any text in the input")

>>> Page("https://www.new url.com/")   # -> new page
>>> Page("natural language query")     # -> chunks on this page, sorted
>>> Browser("Natural language query")  # -> the whole history, url in the header
```

Three things in it are load-bearing and are kept exactly:

1. **The repr is the API.** Every line printed is an expression that can be
   typed back. Nothing has to be explained and nothing has to be remembered.
2. **Reading and acting are drawn apart.** Markdown above; `Button`, `Input`,
   `Script` listed below, strictly for navigation. This is the direct answer to
   "there is no specification on what each box is for".
3. **One name, three jobs, disambiguated by what it is given.** `Page(url)`
   navigates, `Page(query)` searches this page, `Page()` re-shows. The rule is
   BROWSER_PIVOT section 4's: it looks like a location, so visit it; otherwise
   it is a question.

## 4. The object model

**The sensor is agnostic to page structure, and so is this.** No class here
names what a thing is *for*. There is no `Nav`, no `Menu`, no `Search`, no
`Result`, no `Card`, no `Article` — a name of that kind is a claim about the
author's intent, and every one of them is a heuristic waiting to be wrong on
the page that does it differently.

An earlier draft of this file had exactly those, twice over:

* `Group` labelled `Nav` / `Main` / `Footer` from its landmark role. We had
  just stopped drawing `@role` as content on the grounds that it is a machine
  annotation rather than something on the page — and then reintroduced the same
  interpretation as a class name. Same claim, other door.
* `Result(n)`, justified by the dominant repeating shape being the row
  template. That is a pre-computed structural heuristic by definition. It is
  also the part of BROWSER_PIVOT section 5 that this constraint invalidates —
  see section 8.

### The object tree IS the trie

The way to guarantee agnosticism is not to be careful about naming. It is to
make the object tree **the trie's node tree, one to one**, so that no grouping
decision is available to get wrong.

That is the shape the indented view in the TUI already has: nesting by
indentation, one line per addressed unit, nothing named for its purpose. It was
noisy and duplicated — 129 surplus lines of 451, roles drawn as text, prose in
fragments — but those are defects in *what it drew*, not in the shape. The
shape was right and the shape is agnostic, because it is the fold's own output
with no projection applied.

So the two views are one projection at two depths:

```
the TUI's document view      the whole tree, flattened, every level at once
the callable interface       one level at a time, descending on call
```

`Page(depth=2)` is the former with a bound. Calling a node is `depth += 1`,
scoped to that node. Anything true of one is true of the other, and any fix to
what gets drawn — the role lines, the prose rejoining — lands in both at once
because there is only one renderer underneath.

### Names are tags, because tags are what the address holds

A trie segment is an xpath step. `div`, `ul`, `li`, `a`, `input`. Using the tag
as the class name is not merely agnostic, it is *the same string the address
already carries* — there is no mapping to be wrong about, and `where()` returns
the path built from exactly these.

An earlier draft here proposed render classes — `Link` for `a[href]`, `Field`
for `input`, `Item` for `li`. That is a rename, not an interpretation, and it
would probably survive scrutiny. It is dropped anyway: a rename is a place
where a mapping table has to be maintained and can drift, and the sketch this
came from used `div` and `input` directly. The tag is enough.

Interactivity is carried as **flags on the line, not as a class**:

```
|-- div(1)     "DuckDuckGo home ..."                     3a
|-- form(1)    "Search the web with DuckDuckGo"          1input 1button
|-- div(2)     "Protection. Privacy. Peace of mind. ..." 6a 2img
```

which is what the original sketch did with `input(..., script=True,
input=True)`. A `form` is not called a search box; it is called a `form`, and
the counts underneath say what is inside it. The reader draws the conclusion.

`div(2)` is the tag plus its xpath ordinal — the handle is a slice of the
address rather than anything invented. `div("Protection. Privacy")` resolves
the same node by the page's own text, as a convenience for typing.

Two reprs, and which one you get is the whole of the interaction:

* **A container reprs as its children** — one line each, truncated, with the
  affordances gathered underneath as `act:`.
* **A focused leaf reprs as its full markdown** — the entire chunk, because
  "open a result and see it completely" is the thing the TUI made you scroll
  for.

`help(node)` is generated: what it is, its address, how many children of what
kind, what may be done with it, and the two or three expressions most likely to
come next.

## 5. The walkthrough, as asked

```python
>>> from domvec.live import Page, Browser, up, top, back

>>> Page("https://duckduckgo.com")
Page("https://duckduckgo.com/") - 72 chunks, depth 9
|-- div(1)     "DuckDuckGo home ..."                     3a
|-- form(1)    "Search the web with DuckDuckGo"          1input 1button
|-- div(2)     "Protection. Privacy. Peace of mind. ..." 6a 2img
'-- footer(1)  "About - Privacy - Careers ..."          11a

>>> input(1) << "glacier retreat measurements"
input(1) = "glacier retreat measurements"

>>> button(1)()
Page("https://duckduckgo.com/?q=glacier+retreat+measurements") - 61 chunks
|-- form(1)    "Search the web with DuckDuckGo"          1input 1button
|-- div(1)     "All - Images - Videos - News ..."        6a
'-- ol(1)      "Satellite gravimetry of ice-sheet ..."  38li

>>> ol(1)
ol(1) - 38 li
|-- li(1)  "Satellite gravimetry of ice-sheet mass change - nasa.gov"
|-- li(2)  "Glacier mass balance datasets - wgms.ch"
|-- li(3)  "Ice loss measured from orbit - archive.org"          [local]

>>> li(1)
# Satellite gravimetry of ice-sheet mass change
nasa.gov > grace > data

Monthly solutions resolve basin-scale mass change from 2002 onward, with
[the GRACE-FO record](https://nasa.gov/grace-fo) continuing the series ...
act: Link("the GRACE-FO record")  Link("nasa.gov > grace > data")

>>> up()
Group(3) - 38 items
...

>>> Page("mass balance")          # retrieval within this page's chunks
>>> Browser("glacier retreat")    # retrieval across every trace ever folded
Browser("glacier retreat") - 12 hits
|-- Chunk("Ice loss measured from orbit")   archive.org/details/icelossorbit
|-- Chunk("WGMS annual report section 4")   wgms.ch/data/reports
```

Nothing in that transcript is named for what it is *for*. `ol(1)` holds 38 `li`
because the page wrote 38 `li`, not because anything decided it is a result
list. The reader sees `"Satellite gravimetry of ice-sheet ..."` — the page's
own words — and concludes what it is. That conclusion is theirs, and it is
available a full level before they descend, at the cost of one line.

Every handle in it is a slice of an address the trie already holds: `ol(1)`,
`li(3)`, `input(1)`. Nothing had to be named, so nothing can be named wrongly.

`[local]` marks a hit that came from our own store rather than the live page.
It is the only thing added to the page's own form, and it is a fact about
provenance rather than a reading of the page.

## 5b. The cartesian view

The tree says what contains what. It cannot say what sits **beside** what,
and that is a different fact about the same page -- a sidebar reads as a
column to a reader and as a deep branch in an indented listing, and only one
of those is what the page shows.

    >>> wire(96)
    https://duckduckgo.com/  362 rows x 96 cols
    ====================================================================
      0| - Main       /                             Search the web with DuckDuckGo
      1| navigation
      3| [ ] Search with DuckDuckGo     [ ] Search privately     ( Clear
      6| ( Search )                      navigation
     10| # Switch to DuckDuckGo. It is private        # and free!

Both views are the same trie. The drawing is built from the same rendered
lines, positioned by geometry read from the page -- so a fix to what gets
drawn lands in both, and every measurement that already watches the render
watches this too.

**The boxes are nodes.** `wire()[7]` is the nodes drawn on row 7, in the
order they are drawn, each one a `Node` with `.where()`, `.press()`,
`.text()`. A drawing you can only look at is a screenshot; the row number is
the handle that makes it usable.

**Geometry is read once, at the moment of drawing, and never in the fold.**
`invariants.c2` holds the fold to reading no layout -- a fold that measures
forces synchronous style resolution on every mutation -- and an actuator is
exactly where that rule stops applying. The scroller already makes the same
crossing for the same reason. The measurement is one round trip for the whole
page, cached for the fold and dropped when the page changes.

What is deliberately NOT here is section 5's melding of stored hits into the
page's row template. That is a pre-computed structural heuristic and section
8 rules it out; the drawing shows the page, and `Browser(query)` shows the
store, and neither pretends to be the other.

## 6. Safety, because this is an SLM-facing surface

`refused()` exists and is strict: labels matching sign-in, checkout, buy,
delete, subscribe, submit; hrefs under `/accounts`, `/checkout`, `/billing`;
any form holding a password, card, cvv, ssn or one-time-code field; any open
`<dialog>`, because a modal is a decision.

**It currently gates the autonomous scroller only.** Every enactment on this
interface — `Button()`, `Field <<`, `Link()` — must pass the same check, and
the check has to be answerable from Python rather than only from inside the
page. A model driving this surface is exactly the case the denylist was written
for, and it is the case it does not yet cover.

A refusal is a raised `Refused` carrying the matched reason, never a silent
no-op:

```python
>>> Button("Sign in")()
Refused: label matches the never-press set ("sign in").
```

## 7. What this does not settle

* **Handles.** A truncated label is not a stable identifier: two can match, and
  re-folding can change the text. Ordinals (`Result(1)`) are stable within a
  fold and meaningless across one. The repr must print the shortest form that
  is unambiguous *now*, and `.address` must always give the real one.
* **The cursor.** "Calling changes the namespace" is terse and is also global
  mutable state. Calling should both focus *and* return, so binding works for
  anyone who wants it while the terse form stays available in a small window.
* **Whether the TUI stays.** This subsumes most of it. Retiring it is a
  separate decision, and not one to take while it is the only working surface.

## 8. The tension this creates with BROWSER_PIVOT section 5

Section 5 of BROWSER_PIVOT proposes melding stored hits into the page by
finding the row template: group lines by shape digest, take the most frequent
shape with three or more instances under one parent, and render internal hits
through it.

**That is a pre-computed heuristic on page structure**, and the constraint in
section 4 above rules it out as a basis for naming or for classifying. It has
to be said plainly rather than left for someone to trip over, because section 5
is otherwise the best statement of what the view should be.

What survives, and what does not:

* **Survives** — rendering a stored hit *in the same form as the page's own
  rows*, so a reader sees one list. That is a formatting decision applied to
  our content, not a claim about the page's.
* **Does not survive** — naming anything `Result` on the strength of the
  template, or treating "matched the dominant shape" as a property of the node.
  The shape digest stays what it always was: a measurement of the chunker, used
  in analytics, never a label the map carries.

The distinction is the one the whole project keeps arriving at: it is
legitimate to measure structure and illegitimate to interpret it.
