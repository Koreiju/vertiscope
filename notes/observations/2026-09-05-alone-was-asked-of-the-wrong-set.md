# `alone` was asked of what arrived, not of what survived

2026-09-05, found by checking whether the REPL sees the affordances the
render carries.

## The defect

`_render_unit` suppresses `interactive.links` unless it is `alone` — the
escape added so that an anchor with nothing else at its element still draws.
The comment names the case it was written for: "arxiv's `Disable MathJax` is
an `<a>` with no href, no handler, and its words folded into an all-inline
parent, so this unit is all there is and suppressing it drew the control
nowhere."

`alone` was computed from `units_at`, which counts the units **collected**.
But `_dedupe` runs between the two, and at an href-less anchor it has work to
do: `interactive.links` and `text.visible` carry the identical string, the
exact-tie branch keeps the first and drops the second. The survivor then
asked `alone`, got told it had company that no longer existed, and suppressed
itself.

Neither unit drew. `<a>Disable MathJax</a>` rendered as **nothing at all** —
the words the page shows were absent from the output. Not an unpressable
control: no line.

```
tagger:   interactive.links  ctl=True   'Disable MathJax'
          text.visible       ctl=False  'Disable MathJax'
dedupe:   interactive.links  kept=True
          text.visible       kept=False
render:   (no line)
```

## The fix

Count from `kept` instead of from `units`:

```python
drawn_at[owner] = drawn_at.get(owner, 0) + 1   # over kept, post-dedupe
...
alone=drawn_at.get(owner, 0) <= 1
```

The same function had already learned this once, ten lines away, for
`consumed`: "taken from `kept`, not from `units`, so the text is only dropped
when the line that will speak for it actually survives. This is the trap
`_dedupe` records above... Whichever is dropped, exactly one has to remain,
and reading `kept` is what makes that structural rather than hopeful."

`alone` is the same question and did not get the same treatment. Two rules
each assuming the other's unit stayed is the shape to look for here; it has
now appeared three times in this file.

## Measured

Over the 136-page corpus, isolating this change on top of `_carry_affordance`:

| | before | after |
|---|---:|---:|
| lines | 167,866 | **167,891** |
| words | 1,059,693 | **1,059,793** |
| chars | 13,192,031 | 13,192,536 |

25 lines and 100 words recovered — small, and every one of them words a page
displays that the render was dropping.

**Not** confirmed: the count coincides with the "25 collapsed controls"
recorded as an open item, and that looked like a closure. It is not. Reach
reports `collapsed` at 43 for the corpus at window 4000, and the documented 25
was taken at another window, so the two numbers are not comparable and the
coincidence is just that until someone measures the same window twice.

Reach at window 4000 after the change: captured 79,186, drawn 78,799
(99.51%), labelled/markable 86.32%, collapsed 43, empty 164.

## Why it stayed hidden

The loss is invisible from every direction that was being watched. Reach
takes the PARSE as arbiter and counts an address as drawn or not — but both
addresses here are legitimately accounted for, one deduped and one
suppressed, and the confusion matrix has a bucket for each. Nothing asked the
question this needed: *does the element the page shows words for have a line
at all?*
