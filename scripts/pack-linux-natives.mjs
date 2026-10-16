// Packs the Linux x64 builds of every native package the frontend toolchain uses,
// matching the exact versions installed on this machine, into vendor/npm-linux/.
import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const nm = join("frontend", "node_modules");
const want = [
  ["esbuild", (v) => `@esbuild/linux-x64@${v}`],
  ["rollup", (v) => `@rollup/rollup-linux-x64-gnu@${v}`],
  ["lightningcss", (v) => `lightningcss-linux-x64-gnu@${v}`],
  ["@tailwindcss/oxide", (v) => `@tailwindcss/oxide-linux-x64-gnu@${v}`],
];
for (const [pkg, linux] of want) {
  const pj = join(nm, pkg, "package.json");
  if (!existsSync(pj)) { console.log(`skip ${pkg} (not installed)`); continue; }
  const v = JSON.parse(readFileSync(pj, "utf8")).version;
  const spec = linux(v);
  console.log(`packing ${spec}`);
  execSync(`npm pack ${spec} --pack-destination vendor/npm-linux`, { stdio: "inherit" });
}
