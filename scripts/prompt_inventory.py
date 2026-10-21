"""The reader's own messages since 2026-10-04 -> docs/PROMPT_INVENTORY.md.

Four stages, each a script in `scripts/prompt_inventory/`, run in order with
a scratch directory between them:
  s1_extract     every message typed in the transcript (queued ones too),
                 de-duplicated across rewound branches
  s2_match_goal  where its words are recorded verbatim in PLUGIN_GOAL.md and
                 the item numbers near them
  s3_cross_ref   the PRD rows citing those items or quoting the message, and
                 code that quotes it
  s4_write       the table, with the hand-written readings for messages no
                 row could be found for

  python scripts/prompt_inventory.py [transcript.jsonl]
Statuses are read with design_state's own row parser; s3 recomputes them.
"""
import os, runpy, sys, tempfile

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_inventory")
work = tempfile.mkdtemp(prefix="prompt_inventory_")
if len(sys.argv) > 1:
    os.environ["VERTISCOPE_TRANSCRIPT"] = sys.argv[1]
for stage, argv in (("s1_extract.py", [os.path.join(work, "prompts.json")]), ("s2_match_goal.py", [work]),
                    ("s3_cross_ref.py", [work]), ("s4_write.py", [work])):
    sys.argv = [stage] + argv
    runpy.run_path(os.path.join(HERE, stage), run_name="__main__")
