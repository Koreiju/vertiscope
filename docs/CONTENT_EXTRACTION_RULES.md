# Content extraction rules — the complete detectable-content space

The exhaustive enumeration of what the pipeline can detect. Everything
downstream — chunking, distillation to markdown, deduplication, vectorization —
derives its meaning from this space and from nothing else. A unit that is not
detectable here does not exist to any later stage.

**Sources.** `REAL_TIME_SCAN_UPDATE.md` §5 (the canonical vocabulary),
`HTML_DEDUP_CONTENT_TREE_GOAL.md` §2.1 (unit kinds), and the two implementations:
`vertiscope/core/content_tagger.py` (host) and `vertiscope/core/js/wfh_chunk_engine.js`
(in-page). Where doc and code disagree, the code is recorded as authoritative and
the divergence is listed in §9.

**Provenance.** Every constant in §3–§6 is dumped from the live module by
`scripts/dump_extraction_rules.py`; §2's subcategory space is verified both
structurally and empirically by the same script. Re-run it after any change to
the tagger; drift between this document and the code is a test failure, not a
documentation lapse.

---

## 1. The shape of a detection

```python
@dataclass
class ContentTag:
    xpath:       str   # absolute address of the bearing node
    category:    str   # one of 5 (§2)
    subcategory: str   # one of 18 (§2)
    value:       str   # the extracted string
    source_attr: str   # attribute it came from; '' for a text node
```

Four facts are recorded per detection: *where* (xpath), *what kind*
(category.subcategory), *what* (value), and *by what evidence* (source_attr).
`source_attr` is the audit trail — it is what allows a later stage to prefer one
surface form over another, and it is the only field that records provenance.

---

## 2. The category space — 5 categories, 18 subcategories

Complete. There are no others; `TaggedContent` has exactly five buckets and each
is a fixed-key dictionary.

| category | subcategories | count |
|---|---|---|
| `urls` | `internal`, `external`, `resource` | 3 |
| `media` | `images`, `video`, `audio`, `archives` | 4 |
| `text` | `visible`, `accessible`, `metadata` | 3 |
| `interactive` | `links`, `buttons`, `inputs`, `forms`, `event_handlers` | 5 |
| `json_data` | `ld_json`, `data_attrs`, `inline` | 3 |
| | | **18** |

### 2.1 Observed coverage

Counts from two real pages (the `catalog.html` fixture and an archived Wikipedia
article), produced by the generator script:

| bucket | count | | bucket | count |
|---|---:|---|---|---:|
| `text.visible` | 392 | | `interactive.links` | 248 |
| `urls.external` | 284 | | `text.accessible` | 224 |
| `urls.internal` | 97 | | `interactive.inputs` | 66 |
| `interactive.forms` | 57 | | `interactive.buttons` | 50 |
| `media.images` | 46 | | `json_data.data_attrs` | 44 |
| `text.metadata` | 16 | | `interactive.event_handlers` | 8 |
| `media.video` | 2 | | `urls.resource` | 2 |
| `json_data.ld_json` | 1 | | | |

**Never exercised on these pages:** `media.audio`, `media.archives`,
`json_data.inline`. The first two are simply absent from the sample; the third
is marked *(future)* in the source vocabulary and has no detector — see §9.4.

---

## 3. Text

### 3.1 `text.visible`

Direct child text nodes only, never the recursive text of the subtree. Empty and
whitespace-only runs are discarded. Zero-width and non-breaking characters are
stripped before the emptiness test: `U+200B`, `U+200C`, `U+200D`, `U+FEFF`,
`U+00A0`.

The restriction to *direct* text is load-bearing: recursive text would attribute
every character to each of its ancestors, so a node's contribution would depend
on its depth rather than its content.

### 3.2 `text.accessible` — 16 attributes

```
abbr, acronym, alt, aria-describedby, aria-description, aria-errormessage,
aria-label, aria-labelledby, aria-placeholder, aria-roledescription,
aria-valuetext, caption, label, placeholder, summary, title
```

### 3.3 `text.metadata` — 12 attributes

```
content, data-alt, data-caption, data-description, data-label, data-name,
data-placeholder, data-text, data-title, data-tooltip, data-value, datetime
```

---

## 4. URLs

### 4.1 The pattern

Applied to attribute values. Five alternatives:

```
https?://[^\s"'<>(){}\[\]]+          http and https
//[^\s"'<>(){}\[\]]+                 protocol-relative
data:[a-zA-Z0-9+/.-]+;[^\s"'<>]+     data URI
blob:[^\s"'<>]+                      blob URI
/[a-zA-Z0-9_.~:/?#@!$&'()*+,;=%-]+   absolute path
```

Relative paths without a leading solidus are **not** matched by the general
pattern; they are reached only through the explicit URL-bearing attributes of
§4.3. This is a deliberate precision/recall trade: an unanchored relative path is
indistinguishable from ordinary prose.

CSS URLs are extracted separately from `style` values by
`url\s*\(\s*['"]?([^'"\)]+)['"]?\s*\)`.

### 4.2 Classification

- `resource` — value begins `data:` or `blob:`.
- `internal` — same host as the document, or an absolute/relative path.
- `external` — a different host.

### 4.3 URL-bearing attributes — 13, always scanned

```
action, cite, data, data-image, data-lazy-src, data-original,
data-original-src, data-src, formaction, href, longdesc, poster, src
```

### 4.4 Attributes never scanned for URLs — 48, plus the `aria-` prefix

```
abbr, alt, autocapitalize, autocomplete, autocorrect, checked, class, cols,
colspan, contenteditable, datetime, dir, disabled, draggable, enterkeyhint,
headers, hidden, id, inputmode, label, lang, max, maxlength, min, minlength,
multiple, name, pattern, placeholder, pubdate, readonly, required, reversed,
role, rows, rowspan, scope, selected, size, spellcheck, start, step, tabindex,
title, translate, type, value, wrap
```

Outside §4.3 and §4.4 the scan is **attribute-agnostic**: the pattern is applied
to every remaining attribute value. This is what recovers URLs from
site-specific attributes nobody enumerated — `data-mw`, `resource` and `typeof`
all yielded content on the sample pages and appear in no list.

---

## 5. Media

Classified by the extension of a detected URL, by tag, or by `data:` MIME prefix.
Extension matched by `\.([a-zA-Z0-9]{2,5})(?:[?#]|$)`, so query strings and
fragments do not defeat it.

| subcategory | extensions |
|---|---|
| `images` (15) | `.apng .avif .bmp .gif .ico .jfif .jpeg .jpg .pjp .pjpeg .png .svg .tif .tiff .webp` |
| `video` (13) | `.3gp .avi .flv .m3u8 .m4v .mkv .mov .mp4 .ogg .ogv .ts .webm .wmv` |
| `audio` (11) | `.aac .flac .m4a .mid .midi .mp3 .oga .ogg .opus .wav .wma` |
| `archives` (14) | `.7z .bz2 .cab .dmg .gz .iso .rar .tar .tar.bz2 .tar.gz .tar.xz .tgz .xz .zip` |

`.ogg` appears in both `video` and `audio`; the container is genuinely ambiguous
and tag context decides. `srcset` yields multiple URLs per attribute and each is
classified independently.

---

## 6. Interactive

| subcategory | detection |
|---|---|
| `inputs` | tags `datalist, input, meter, optgroup, option, output, progress, select, textarea` |
| `buttons` | tag `button`; also `input` whose type is `button, submit, reset, image` |
| `forms` | tags `fieldset, form, label, legend` |
| `links` | tag `a` with `href` |
| `event_handlers` | any `on*` attribute (`onclick`, `onchange`, …) |

Additionally, any element whose `role` is one of these 25 counts as interactive:

```
button, checkbox, combobox, grid, gridcell, link, listbox, menu, menubar,
menuitem, menuitemcheckbox, menuitemradio, option, radio, radiogroup,
searchbox, slider, spinbutton, switch, tab, tablist, textbox, tree, treegrid,
treeitem
```

`contenteditable` also marks a node interactive.

---

## 7. Embedded JSON

| subcategory | detection |
|---|---|
| `ld_json` | `script` whose type is `application/ld+json`, `application/json`, or `importmap` |
| `data_attrs` | any `data-*` attribute whose value parses as JSON |
| `inline` | **no detector** — reserved (§9.4) |

Candidate values are pre-filtered by `^\s*[\[{]` before parsing, so the parser is
attempted only on plausible payloads.

Parsed JSON is flattened to leaf paths and each leaf emitted with
`source_attr = "ld_json:<key>"`. Observed on the sample: `ld_json:name`,
`ld_json:url`, `ld_json:headline`, `ld_json:sameAs`, `ld_json:mainEntity`,
`ld_json:@context`. Consequently **embedded JSON enters the same flat
address-to-value space as markup-derived content**; it is not a separate
sub-language requiring its own consumer.

---

## 8. Global exclusions and structure

### 8.1 Attributes never treated as content — 81

```
aria-activedescendant, aria-atomic, aria-busy, aria-checked, aria-colcount,
aria-colindex, aria-colspan, aria-controls, aria-current, aria-disabled,
aria-expanded, aria-flowto, aria-haspopup, aria-hidden, aria-invalid,
aria-level, aria-live, aria-modal, aria-multiline, aria-multiselectable,
aria-orientation, aria-owns, aria-posinset, aria-pressed, aria-readonly,
aria-relevant, aria-required, aria-rowcount, aria-rowindex, aria-rowspan,
aria-selected, aria-setsize, aria-sort, aria-valuemax, aria-valuemin,
aria-valuenow, autocapitalize, autocomplete, autocorrect, class, clip-path,
clip-rule, d, data-automation-id, data-component, data-cy, data-qa,
data-reactid, data-testid, dir, enctype, fill, fill-rule, filter, for, height,
id, is, lang, method, name, opacity, points, slot, spellcheck, stroke,
stroke-linecap, stroke-linejoin, stroke-width, style, tabindex, target,
transform, translate, type, version, viewbox, width, xmlns, xmlns:svg,
xmlns:xlink
```

Three families are represented: ARIA *state* (as opposed to ARIA *labelling*,
which is content and lives in §3.2), SVG presentation, and test/framework hooks.

### 8.2 Attribute prefixes never treated as content — 11

```
data-testid, data-cy-, data-qa-, data-automation, data-react, data-radix,
data-state, data-orientation, data-side, data-align, data-disabled
```

### 8.3 Inline tags — 35

Used to decide line-joining during rendering, not detection:

```
a, abbr, audio, b, bdi, bdo, br, canvas, cite, code, data, dfn, em, i, img,
kbd, mark, picture, q, rp, rt, ruby, s, samp, small, span, strong, sub, sup,
svg, time, u, var, video, wbr
```

Everything else is block-level.

### 8.4 Shadow DOM

Open shadow roots are traversed and their content is detected identically; the
address of a shadow child is `HOST/#shadow-root/tag[n]`, so shadow content is
addressable in the same space as light content. Closed shadow roots are not
reachable from script and are outside the detectable space entirely — a hard
boundary, not a gap to be closed.

### 8.5 Skipped subtrees

`head`, `style`, and `script` other than the JSON types of §7 are not traversed.

---

## 9. Known divergences and gaps

Recorded because completeness includes knowing where the space is ragged.

### 9.1 The two implementations do not agree

**Magnitude, measured** (`scripts/measure_domain_split.py`, recorded in
`notes/observations/2026-08-09-domain-split-magnitude.md`): the vocabularies
differ substantially in size, but the disagreement accounts for **4.1% of
detections** on the sample pages and is confined to five attributes — `content`
(22 detections, host only), `role` (9), `srcset` (6), `type` (1),
`aria-description` (1). The two detectors agree about 95.9% of what they find.
The set sizes below are therefore a poor guide to the practical divergence, and
are retained because they describe the *vocabularies*, not the outcome.

The in-page engine carries its own, much smaller sets:

| set | host (`content_tagger.py`) | in-page (`wfh_chunk_engine.js`) |
|---|---:|---:|
| URL-bearing attributes | 13 | 10 |
| text/accessible attributes | 16 + 12 metadata | 20 (merged) |
| skip attributes | 81 + 11 prefixes | 15 |
| interactive roles | 25 | none |

Notable: the in-page set includes `srcset` and `data-href` which the host's
explicit list omits (the host reaches `srcset` by the agnostic scan of §4.4, and
observed 6 detections that way); the host has no `xml:space` or
`preserveaspectratio` in its skip list. The in-page engine has no role-based
interactivity detection at all.

Consequence: the two producers do not detect the same content space, so any
comparison between their outputs measures the union of an algorithmic difference
and a vocabulary difference.

### 9.2 Anchoring vocabularies differ

The in-page `ANCHOR_TAGS` is `main, nav, aside, header, footer, article,
section, form` — eight tags, including `form` and an unconditional `section`.
The landmark set specified in `REAL_TIME_SCAN_UPDATE.md` §7.8 is six tags plus a
role list plus `section` **only when it has an accessible name**. The host
implements neither.

### 9.3 `.ogg` is ambiguous

Present in both video and audio extension sets; resolution depends on tag
context. Not a defect, but it means extension alone does not determine
subcategory.

### 9.4 `json_data.inline` has no detector

Declared in the vocabulary and in `TaggedContent`, marked *(future)* in the
source table, never populated. The bucket exists and is always empty.

### 9.5 Relative paths without a leading solidus

Unreachable except through the 13 explicit attributes (§4.1). A `data-*`
attribute holding `images/foo.png` yields nothing.

### 9.6 Detection is per-node and context-free

Every rule above reads one node's own tag, attributes and direct text. No rule
consults an ancestor, a sibling, or the document as a whole. Anything requiring
context — that a heading titles the card below it, that a list is navigation —
is not part of this space and must be recovered by a later stage from structure.

---

### 9.7 This document's own completeness is not proven

The title says "complete" and §2 says "there are no others". Both claims are
scoped to the **host** implementation, and are verified against it by §10's
generator — the categories are read from `TaggedContent`'s fixed buckets, so the
eighteen are complete *for that detector*. Neither claim is established for the
in-page engine, which has no equivalent enumeration and whose detectable space
has never been extracted.

What is verified: the constant sets and the category space match the host module
(§10). What is observed: three buckets — `media.audio`, `media.archives`,
`json_data.inline` — populated on no sample page, the last having no detector at
all. What is not established: that the host's eighteen subcategories exhaust
what *either* implementation can detect, or that the sample pages exercise the
space representatively. Coverage of `content_tagger.py` by the test suite is
**61%** (`notes/observations/2026-08-09-test-adequacy.md`), so 39% of the
detector that defines this document is unexecuted by any test.

## 9.8 This document is a *detection* alphabet, not an *observation* alphabet

§1–§8 enumerate what the extractor can find in a page. That is the detection
alphabet of THEORY DEF-10.4, and by PROP-10.5 it is **not** the same thing as
the set of facts an observer of the running system can distinguish. Equalities
between system states — MODEL §4.1's observational equivalence, and through
COR-22.5.8 the entire identity design — depend on the second, which nothing here
described until now.

The gap is specifically *instance-level* facts. Identity, position and
multiplicity are properties of an occurrence rather than of content, so none is a
content category and none appears above; yet whether each is exposed decides
which stored states are equal.

### 9.8.1 The observation alphabet, measured

The observation alphabet is a property of the output surfaces, so it is read off
them rather than declared. Produced by `scripts/audit_observables.py`:

| surface | identity | position | pattern | multiplicity | content | url |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `Retriever.search` → `Hit` | yes | – | yes | – | yes | yes |
| `Store.get_instance` → record | – | – | – | – | – | – |
| `vertiscope search` | yes | – | yes | – | yes | yes |
| `vertiscope search --json` | yes | – | yes | – | yes | yes |
| **`vertiscope show`** | yes | **yes** | – | – | yes | yes |
| `vertiscope ls` | – | – | – | – | – | yes |
| `vertiscope info` | – | – | – | – | – | – |

**Verdict.** Identity, pattern, content and url are observable through several
surfaces. **Position is observable through exactly one — `vertiscope show`.**
Multiplicity is observable through none, because nothing records it (§9.9).

The narrowness matters. Position being observable is what makes
content-identical siblings distinguishable, which by COR-22.5.8 makes reshuffle
stability and discrimination incompatible, which is why three passes of
comparing identity schemes produced no winner. That entire consequence rests on
one field printed by one command.

`Store.get_instance` shows no marks because it returns a record object rather
than rendering it; its fields become observable only through a surface that
prints them. The distinction is real — a library consumer can read anything, but
the observation alphabet of the *system* is what its outputs expose.

### 9.9 Multiplicity is not observable because it is not recorded

820 rendered instances across three archived pages collapse to 746 stored rows —
**74 lost, 9.0%** — and no column carries the count
(`notes/observations/2026-08-09-identity-collapse.md`). By THEORY REM-22.5.9 the
collapse is lossless only if multiplicity is retained, so this is a loss rather
than a normalisation. It is recorded here because a fact that is neither
detected nor observed is, for every purpose in this workspace, absent.

## 10. Regenerating and checking this document

```bash
python scripts/dump_extraction_rules.py
```

Prints every constant set, the declared subcategory space, and the observed
buckets over the sample pages. The output is the ground truth for §2–§8; if it
disagrees with this document, this document is wrong.
