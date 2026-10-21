# OBSERVATION — the DOMAIN split is 4.1% and localised to five attributes

**Date** 2026-08-09 · **Bears on** CONTENT_EXTRACTION_RULES §9.1, ERRATA B2,
MODEL §11 · **Command** `python scripts/measure_domain_split.py`

## What was measured

§9.1 records that the host tagger and the in-page engine detect different
spaces, citing set sizes (81 skip attributes against 15; 25 interactive roles
against none). Set sizes are the wrong quantity: a vocabulary difference matters
only where the contested attributes actually carry content. This measures the
symmetric difference of the vocabularies and then weights it by observed yield
on real pages.

## Result

Vocabulary symmetric differences:

| vocabulary | host | in-page | shared | host only | in-page only |
|---|---:|---:|---:|---:|---:|
| URL-bearing | 13 | 10 | 8 | 5 | 2 |
| text-bearing | 28 | 20 | 19 | 9 | 1 |
| never-content | 81 | 16 | 13 | 68 | 3 |

Weighted by yield over `catalog.html` and an archived Wikipedia article:

```
detections from contested attributes: 39 / 944   (4.1%)

  content            22   host only     (meta tags)
  role                9   in-page only  (JS skips role; host emits it)
  srcset              6   in-page only  (host reaches it agnostically)
  type                1   host only
  aria-description    1   host only
```

## Reading

The split is real — these detections exist under one detector and not the other
— but it is **bounded and localised**. Five attributes account for the entire
observed disagreement, and 95.9% of detections are unaffected.

This changes what ERRATA B2 is. It had been recorded as a structural blocker
requiring a decision about which detector *is* DOMAIN, on the strength of a
81-against-15 comparison. The measurement says the two detectors agree about
almost everything they actually find, and reconciling **five attributes** would
close the split outright. That is a tractable change rather than an
architectural fork.

The largest single contributor, `content` at 22 detections, is the `meta`
element's attribute — page-level metadata, which the in-page engine has no
reason to see because it chunks rendered content. So part of the 4.1% is a
*scope* difference rather than a disagreement, and may be resolvable by
declaring that page-level metadata is outside the in-page detector's remit
rather than by adding it.

## Caveats

- Two pages, one of them a synthetic fixture. The 4.1% is not a corpus-wide
  figure and the sample is not frozen (`notes/questions/OPEN.md`).
- Only *attribute* vocabularies were compared. The interactive-role difference
  (25 against none) is not attribute-keyed and is not in this measurement; its
  yield is unmeasured.
- Yield was computed with the host tagger only. A symmetric measurement would
  run the in-page engine over the same pages in a browser and compare detection
  sets directly rather than inferring from vocabularies.
