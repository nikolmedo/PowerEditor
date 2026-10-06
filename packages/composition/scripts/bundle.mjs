// Bundles the composition once, ahead of time, into `dist/bundle` (a Remotion serve URL folder).
//
// Usage: node scripts/bundle.mjs [--out <dir>]
//
// `render.mjs --bundle dist/bundle` then renders without webpack: faster (no cold bundle on
// every render) and the packaged app ships `@remotion/renderer` only. The bundle gets a copy
// of `src/composition.json` so the renderer knows the composition id without the sources.
import { copyFile, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import { bundle } from "@remotion/bundler";

const packageDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { values } = parseArgs({ options: { out: { type: "string" } } });
const outDir = path.resolve(values.out ?? path.join(packageDir, "dist", "bundle"));

const started = performance.now();
await rm(outDir, { recursive: true, force: true });
await bundle({ entryPoint: path.join(packageDir, "src", "entry.ts"), outDir });
await copyFile(
  path.join(packageDir, "src", "composition.json"),
  path.join(outDir, "composition.json"),
);
process.stdout.write(
  `${JSON.stringify({ event: "bundled", ms: Math.round(performance.now() - started), outDir })}\n`,
);
