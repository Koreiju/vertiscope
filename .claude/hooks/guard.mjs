// PreToolUse guard for Bash / PowerShell in the domvec vault.
//
// Blocks the three ad-hoc moves this repo has paid for (CLAUDE.md):
//   cdp    -- talking to Obsidian's raw debug port outside the harness
//             ("no one-off scratch or smoke scripts against the app");
//   store  -- opening a Kuzu store from an inline script instead of through
//             a harness module (`python -m domvec...`, tests/);
//   rename -- moving or renaming a folder under build/ (the vault's metadata
//             cache froze Obsidian for 30+ minutes, 2026-11-14).
// The harness itself is whitelisted and short-circuits: pytest,
// domvec.analytics.design_state, npm run build, npx tsc, confirm.mjs, and
// obsidian-plugin/cdp.mjs / checks/.
//
// Exit 2 blocks the call and hands stderr back as the reason. Anything this
// script fails to parse is let through: a guard that crashes must not wedge
// the session.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export const WHITELIST = [
  /(^|[\s;&|(])(python(3)?(\.exe)?\s+-m\s+)?pytest\b/,
  /domvec\.analytics\.design_state\b/,
  /\bnpm\s+run\s+build\b/,
  /\bnpx\s+tsc\b/,
  /obsidian-plugin[\\/]confirm\.mjs\b/,
  /obsidian-plugin[\\/]cdp\.mjs\b/,
  /obsidian-plugin[\\/]checks[\\/]/,
];

const INLINE = /(python(3)?(\.exe)?\s+(-I\s+)?(-c|-)\b|<<\s*['"]?\w+|node\s+(-e|--eval)\b)/;

export const RULES = [
  {
    id: "cdp",
    test: (c) => /(127\.0\.0\.1|localhost):9222|\/json\/(list|version)\b|remote-debugging-port/.test(c),
    why: "raw CDP access to Obsidian outside the harness; use the domvec MCP tools, obsidian-plugin/cdp.mjs or checks/live.mjs (CLAUDE.md: Verification)",
  },
  {
    id: "store",
    test: (c) => INLINE.test(c) && /(\bimport\s+kuzu\b|\bkuzu\.(Database|Connection)\b|\bGraphStore\s*\()/.test(c),
    why: "an inline script opening a Kuzu store; build the probe into a harness module (python -m domvec.analytics.* or tests/) with a planted arm",
  },
  {
    id: "rename",
    test: (c) => /(^|[\s;&|])(mv|Move-Item|Rename-Item|ren|move)\s+[^;&|]*\bbuild[\w.-]*([\\/][^\s;&|]*)?(\s|$|["'])/i.test(c)
              || /\bos\.(rename|replace)\([^)]*\bbuild/.test(c) || /shutil\.move\([^)]*\bbuild/.test(c),
    why: "moving/renaming a folder under the vault's build/; switch a store by PATH instead (CLAUDE.md: the repo root is the Obsidian vault)",
  },
];

export function verdict(command) {
  const c = String(command || "");
  // The harness legitimately touches the debug port and the store, so the
  // whitelist exempts those two rules -- never the rename rule: a harness
  // command chained to a `mv build/...` is still a rename.
  const rename = RULES.find((r) => r.id === "rename");
  if (rename.test(c)) return { allow: false, rule: rename.id, why: rename.why };
  if (WHITELIST.some((w) => w.test(c))) return { allow: true, rule: "whitelist" };
  for (const r of RULES) if (r.test(c)) return { allow: false, rule: r.id, why: r.why };
  return { allow: true, rule: null };
}

function main() {
  let input;
  try {
    input = JSON.parse(readFileSync(0, "utf8"));
  } catch {
    process.exit(0);
  }
  const cmd = input?.tool_input?.command;
  const v = verdict(cmd);
  if (!v.allow) {
    process.stderr.write(`domvec guard [${v.rule}]: ${v.why}\n`);
    process.exit(2);
  }
  process.exit(0);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
