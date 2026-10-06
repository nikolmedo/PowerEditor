// Stages a standalone renderer for the packaged app into one folder:
//
//   <out>/scripts/render.mjs, scripts/ensure-browser.mjs
//   <out>/dist/bundle/            (from `scripts/bundle.mjs`, which must have run first)
//   <out>/node_modules/           (@remotion/renderer and its runtime dependencies, flat)
//
// Usage: node scripts/stage-renderer.mjs --out <dir> [--compositor <suffix>]
//
// The dependencies are copied from this workspace's install (the pnpm store, resolved through
// its symlinks), so the staged versions are exactly the locked ones and no network is needed.
// Only the compositor for `--compositor` (default `win32-x64-msvc`) is kept; the workspace
// installs it on every Windows host because pnpm-workspace.yaml adds x64 to
// `supportedArchitectures`. Chrome Headless Shell is not staged: it is downloaded at first run
// (`powereditor runtime install browser`).
import { cp, mkdir, readFile, realpath, rm, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const packageDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { values } = parseArgs({
  options: { out: { type: "string" }, compositor: { type: "string" } },
});
if (!values.out) {
  process.stderr.write("usage: stage-renderer.mjs --out <dir> [--compositor <suffix>]\n");
  process.exit(2);
}
const outDir = path.resolve(values.out);
const compositor = `@remotion/compositor-${values.compositor ?? "win32-x64-msvc"}`;
const ROOT_PACKAGES = ["@remotion/renderer"];

async function exists(file) {
  try {
    await stat(file);
    return true;
  } catch {
    return false;
  }
}

/** Node's lookup without `exports`: the nearest `node_modules/<name>` above `fromDir`. */
async function locate(name, fromDir) {
  for (let dir = fromDir; ; dir = path.dirname(dir)) {
    const candidate = path.join(dir, "node_modules", name);
    if (await exists(path.join(candidate, "package.json"))) return realpath(candidate);
    if (path.dirname(dir) === dir) return null;
  }
}

/** Every package `@remotion/renderer` needs at runtime, by name, with its folder. */
async function closure() {
  const found = new Map();
  const queue = ROOT_PACKAGES.map((name) => ({ name, from: packageDir, optional: false }));
  while (queue.length > 0) {
    const { name, from, optional } = queue.shift();
    const dir = await locate(name, from);
    if (dir === null) {
      if (optional) continue;
      throw new Error(`${name} is not installed (needed from ${from})`);
    }
    const manifest = JSON.parse(await readFile(path.join(dir, "package.json"), "utf8"));
    const previous = found.get(name);
    if (previous) {
      if (previous.version !== manifest.version) {
        throw new Error(`${name} is needed as ${previous.version} and ${manifest.version}`);
      }
      continue;
    }
    found.set(name, { dir, version: manifest.version });
    const optionalDeps = Object.keys(manifest.optionalDependencies ?? {}).filter(
      (dep) => !dep.startsWith("@remotion/compositor-") || dep === compositor,
    );
    const peers = Object.keys(manifest.peerDependencies ?? {}).filter(
      (dep) => !manifest.peerDependenciesMeta?.[dep]?.optional,
    );
    for (const dep of Object.keys(manifest.dependencies ?? {})) {
      queue.push({ name: dep, from: dir, optional: false });
    }
    for (const dep of [...optionalDeps, ...peers]) {
      queue.push({ name: dep, from: dir, optional: true });
    }
  }
  if (!found.has(compositor)) {
    throw new Error(`${compositor} is not installed; run corepack pnpm install on Windows`);
  }
  return found;
}

const bundleDir = path.join(packageDir, "dist", "bundle");
if (!(await exists(path.join(bundleDir, "index.html")))) {
  throw new Error("dist/bundle is missing: run `node scripts/bundle.mjs` first");
}
const packages = await closure();
await rm(outDir, { recursive: true, force: true });
await mkdir(path.join(outDir, "scripts"), { recursive: true });
for (const script of ["render.mjs", "ensure-browser.mjs"]) {
  await cp(path.join(packageDir, "scripts", script), path.join(outDir, "scripts", script));
}
await cp(bundleDir, path.join(outDir, "dist", "bundle"), { recursive: true });
for (const [name, { dir }] of packages) {
  await cp(dir, path.join(outDir, "node_modules", name), {
    recursive: true,
    dereference: true,
    filter: (source) => !source.slice(dir.length).split(path.sep).includes("node_modules"),
  });
}
process.stdout.write(
  `${JSON.stringify({ event: "staged", outDir, packages: [...packages.keys()].sort() })}\n`,
);
