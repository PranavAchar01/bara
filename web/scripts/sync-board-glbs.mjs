// Copies each open-source board's 3D model from a local board-library checkout into public/explore/glb/<slug>.glb,
// so the Library's board view reads them from this site instead of the published library. Not committed
// (~150 MB); the page falls back to the published copy for any board missing here.
// Usage: node scripts/sync-board-glbs.mjs <world dir with boards/<slug>/board.glb>
import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const world = process.argv[2];
if (!world) throw new Error("usage: node scripts/sync-board-glbs.mjs <world dir>");
const here = new URL("../public/explore/", import.meta.url).pathname;
const { boards } = JSON.parse(readFileSync(join(here, "index.json"), "utf8"));
mkdirSync(join(here, "glb"), { recursive: true });
let copied = 0;
const missing = [];
for (const b of boards) {
  const src = join(world, "boards", b.slug, "board.glb");
  if (!existsSync(src)) {
    missing.push(b.slug);
    continue;
  }
  copyFileSync(src, join(here, "glb", `${b.slug}.glb`));
  copied++;
}
console.log(`${copied} of ${boards.length} board models copied`);
for (const m of missing) console.log(`  missing: ${m}`);
