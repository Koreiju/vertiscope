/**
 * Build the plugin, and put it where Obsidian actually reads it.
 *
 * The bundle is written to `main.js` here, because `harness.mjs` imports it
 * directly and that is the local artifact. But Obsidian loads a plugin from
 * `<vault>/.obsidian/plugins/<id>/`, and for most of this project's life
 * nothing copied it there. The installed plugin sat three days stale while
 * every CDP probe reported on it as though it were current -- a whole session
 * of measurements taken against code that was not the code being edited.
 *
 * So the copy is part of the build, not a step someone remembers. `manifest.json`
 * and `styles.css` go too: Obsidian reads those from the plugin directory as
 * well, and they were being hand-copied under exactly the same risk.
 *
 * Every build SAYS where it wrote. A silent deploy is how a stale artifact
 * hides, and this build exists because one did.
 */

import esbuild from "esbuild";
import builtins from "builtin-modules";
import { copyFile, mkdir, readFile, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const production = process.argv[2] === "production";

/** Files Obsidian reads out of a plugin directory. `data.json` is deliberately
 *  absent: it holds the user's SETTINGS, written by the app, and copying a
 *  source copy over it would reset the sidecar url on every build. */
const DEPLOY = ["main.js", "manifest.json", "styles.css"];

const manifest = JSON.parse(
  await readFile(join(HERE, "manifest.json"), "utf8"));

/**
 * Where to install. `VERTISCOPE_VAULT` overrides; the default is this repo, which
 * is itself the vault (`.obsidian/` sits at the repo root).
 *
 * The two cases fail differently on purpose. An explicit `VERTISCOPE_VAULT` that
 * does not exist is a typo in something the operator just typed, and guessing
 * past it would install nowhere and report success. A missing DEFAULT vault is
 * an ordinary build outside a vault -- CI, a fresh clone -- where refusing to
 * build would be wrong.
 */
async function target() {
  const explicit = process.env.VERTISCOPE_VAULT;
  const vault = resolve(HERE, explicit || "..");
  const dir = join(vault, ".obsidian", "plugins", manifest.id);
  try {
    const s = await stat(join(vault, ".obsidian"));
    if (!s.isDirectory()) throw new Error("not a directory");
  } catch {
    const why = `no .obsidian/ under ${vault}`;
    if (explicit) throw new Error(`VERTISCOPE_VAULT is set but ${why}`);
    console.log(`  deploy skipped: ${why} (set VERTISCOPE_VAULT to install)`);
    return null;
  }
  return dir;
}

const dest = await target();

/** Copy the built plugin into the vault, and say so. */
async function deploy() {
  if (!dest) return;
  try {
    await mkdir(dest, { recursive: true });
    for (const f of DEPLOY) {
      await copyFile(join(HERE, f), join(dest, f));
    }
    const { size } = await stat(join(dest, "main.js"));
    console.log(`  deployed ${DEPLOY.join(", ")} -> ${dest} ` +
                `(main.js ${size} bytes)`);
    // Obsidian does not notice a changed plugin file on its own, so a deploy
    // that did not say this reads as "the change did nothing".
    console.log("  reload the plugin to pick it up: " +
                "app.plugins.disablePlugin('" + manifest.id + "') then " +
                "enablePlugin — or `node cdp.mjs` with the same");
  } catch (err) {
    // Loud. A build that produced a bundle nobody loads is the failure this
    // file exists to prevent, and it must not pass quietly.
    console.error(`  DEPLOY FAILED -> ${dest}: ${err.message}`);
    process.exitCode = 1;
  }
}

/**
 * CodeMirror must come from OBSIDIAN's instance, never from a bundled copy.
 *
 * `@codemirror/state` and `@codemirror/view` are obsidian's peerDependencies,
 * so they resolve in node_modules and esbuild will happily inline them. That
 * produces a SECOND CM6 instance, and a `Decoration` built by one instance is
 * silently ignored by the other's editor — no error, no warning, a ViewPlugin
 * that simply never draws. Marking them external makes the bundle `require()`
 * them at runtime, where Obsidian hands back the instance its own editor uses.
 *
 * Listed in full rather than as the two we import today, so the next one to be
 * imported does not reintroduce the bug.
 */
const CODEMIRROR = [
  "@codemirror/autocomplete", "@codemirror/collab", "@codemirror/commands",
  "@codemirror/language", "@codemirror/lint", "@codemirror/search",
  "@codemirror/state", "@codemirror/view",
  "@lezer/common", "@lezer/highlight", "@lezer/lr",
];

const ctx = await esbuild.context({
  entryPoints: ["src/main.ts"],
  bundle: true,
  external: ["obsidian", "electron", ...CODEMIRROR, ...builtins],
  format: "cjs",
  target: "es2018",
  logLevel: "info",
  sourcemap: production ? false : "inline",
  treeShaking: true,
  outfile: "main.js",
  plugins: [{
    name: "deploy-to-vault",
    setup(build) {
      // `onEnd` rather than after `rebuild()`, so WATCH mode deploys on every
      // rebuild too -- which is the mode where a stale install is most likely,
      // because nobody is watching for a build step to finish.
      build.onEnd(async (result) => {
        if (result.errors.length) {
          console.log("  deploy skipped: build failed");
          return;
        }
        await deploy();
      });
    },
  }],
});

if (production) {
  await ctx.rebuild();
  await ctx.dispose();
  process.exit(process.exitCode ?? 0);
} else {
  await ctx.watch();
}
