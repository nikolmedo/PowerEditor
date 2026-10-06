// Renders the ProjectVideo composition to an MP4.
//
// Usage: node scripts/render.mjs --props <props.json> --output <file.mp4> [--concurrency <n>]
//
// Reports newline-delimited JSON events on stdout so the backend can forward progress:
//   {"event":"bundled","ms":...}
//   {"event":"progress","fraction":0.42}
//   {"event":"done","ms":...,"frames":...}
// Run it with the Node binary that matches the installed Remotion compositor (x64 on Windows).
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

const COMPOSITION_ID = "ProjectVideo";
const packageDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function emit(event) {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

const { values } = parseArgs({
  options: {
    props: { type: "string" },
    output: { type: "string" },
    concurrency: { type: "string" },
  },
});
if (!values.props || !values.output) {
  process.stderr.write(
    "usage: render.mjs --props <props.json> --output <file.mp4> [--concurrency <n>]\n",
  );
  process.exit(2);
}

const inputProps = JSON.parse(await readFile(values.props, "utf8"));

const bundleStart = performance.now();
const serveUrl = await bundle({ entryPoint: path.join(packageDir, "src", "entry.ts") });
emit({ event: "bundled", ms: Math.round(performance.now() - bundleStart) });

const renderStart = performance.now();
const composition = await selectComposition({ serveUrl, id: COMPOSITION_ID, inputProps });
let lastReported = -1;
await renderMedia({
  composition,
  serveUrl,
  codec: "h264",
  inputProps,
  outputLocation: values.output,
  overwrite: true,
  ...(values.concurrency ? { concurrency: Number(values.concurrency) } : {}),
  onProgress: ({ progress }) => {
    const percent = Math.floor(progress * 100);
    if (percent !== lastReported) {
      lastReported = percent;
      emit({ event: "progress", fraction: progress });
    }
  },
});
emit({
  event: "done",
  ms: Math.round(performance.now() - renderStart),
  frames: composition.durationInFrames,
});
