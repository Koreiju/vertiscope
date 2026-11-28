import { test } from "node:test";
import assert from "node:assert/strict";
import esbuild from "esbuild";
import { migrateDeprecatedSlateText, titleOfNote } from "../src/egolinks.ts";

async function loadFencecode() {
  const res = await esbuild.build({
    entryPoints: ["obsidian-plugin/src/fencecode.ts"],
    bundle: true,
    format: "esm",
    write: false,
  });
  const code = res.outputFiles[0].text;
  return import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));
}

test("migrateDeprecatedSlateText retires slate_N variable stubs and preserves real content", () => {
  const raw = "---\ndomvec: slate\n---\nslate_6\n\tvalue\n";
  const res = migrateDeprecatedSlateText("domvec/graph/slate 6.md", raw);
  assert.equal(res.migrated, true);
  assert.equal(res.text, "# slate 6\n");

  const withCode = "---\ndomvec: slate\n---\nslate_5\n\tvalue\n\n```python\nx = 42\n```\n";
  const res2 = migrateDeprecatedSlateText("domvec/graph/slate 5.md", withCode);
  assert.equal(res2.migrated, true);
  assert.match(res2.text, /^# slate 5\n\n```python\nx = 42\n```\n$/);

  assert.equal(migrateDeprecatedSlateText("domvec/ego.md", raw).migrated, false);
  assert.equal(migrateDeprecatedSlateText("domvec-checks/g415 slate.md", raw).migrated, false);
});

test("titleOfNote unwraps markdown link titles cleanly", () => {
  assert.equal(titleOfNote("domvec/graph/slate 7.md", "# [Psychic](https://example.com)\n"), "Psychic");
  assert.equal(titleOfNote("domvec/graph/notebook 9.md", "# Solar Data\n\n```python\na = 1\n```\n"), "Solar Data");
});

test("extractNotePyDefsRefs extracts top-level Python defs and external refs across fences", async () => {
  const { extractNotePyDefsRefs } = await loadFencecode();
  const md = [
    "# Downstream",
    "",
    "```python",
    "import numpy as np",
    "local_scale = 3",
    "result = upstream_matrix * local_scale + np.ones(2)",
    "```",
  ].join("\n");
  const got = extractNotePyDefsRefs(md);
  assert.ok(got.defs.has("np"));
  assert.ok(got.defs.has("local_scale"));
  assert.ok(got.defs.has("result"));
  assert.ok(got.refs.has("upstream_matrix"));
  assert.ok(!got.refs.has("local_scale"));
  assert.ok(!got.refs.has("np"));
  assert.ok(!got.refs.has("ones"));
});
