// Renders the ProjectVideo composition to an MP4.
//
// Usage: node scripts/render.mjs --props <props.json> --output <file.mp4> [--concurrency <n>]
//          [--scale <0..1>] [--crf <n>] [--x264-preset <preset>] [--jpeg-quality <0..100>]
//
// The quality flags come from the backend's presets (`render/quality.py`); a flag left out
// keeps Remotion's default.
//
// Reports newline-delimited JSON events on stdout so the backend can forward progress:
//   {"event":"bundled","ms":...}
//   {"event":"progress","fraction":0.42}
//   {"event":"done","ms":...,"frames":...}
//   {"event":"error","message":"..."}   (then exits with code 1)
// The output is video only: the backend rebuilds the audio sample-accurately with ffmpeg.
// Run it with the Node binary that matches the installed Remotion compositor (x64 on Windows).
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

const packageDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function emit(event) {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

const { values } = parseArgs({
  options: {
    props: { type: "string" },
    output: { type: "string" },
    concurrency: { type: "string" },
    scale: { type: "string" },
    crf: { type: "string" },
    "x264-preset": { type: "string" },
    "jpeg-quality": { type: "string" },
  },
});
if (!values.props || !values.output) {
  process.stderr.write(
    "usage: render.mjs --props <props.json> --output <file.mp4> [--concurrency <n>]\n",
  );
  process.exit(2);
}

/** Remotion options for the flags given, as numbers; absent flags are left out. */
function qualityOptions() {
  const numbers = [
    ["concurrency", "concurrency"],
    ["scale", "scale"],
    ["crf", "crf"],
    ["jpeg-quality", "jpegQuality"],
  ];
  const options = {};
  for (const [flag, option] of numbers) {
    const value = values[flag];
    if (value === undefined) continue;
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error(`--${flag} must be a number, got ${value}`);
    options[option] = number;
  }
  if (values["x264-preset"]) options.x264Preset = values["x264-preset"];
  return options;
}

async function render() {
  const { id: compositionId } = JSON.parse(
    await readFile(path.join(packageDir, "src", "composition.json"), "utf8"),
  );
  const inputProps = JSON.parse(await readFile(values.props, "utf8"));

  const bundleStart = performance.now();
  const serveUrl = await bundle({ entryPoint: path.join(packageDir, "src", "entry.ts") });
  emit({ event: "bundled", ms: Math.round(performance.now() - bundleStart) });

  const renderStart = performance.now();
  const composition = await selectComposition({ serveUrl, id: compositionId, inputProps });
  let lastReported = -1;
  await renderMedia({
    composition,
    serveUrl,
    codec: "h264",
    inputProps,
    outputLocation: values.output,
    overwrite: true,
    // Remotion changes volume only per video frame, which clicks at cuts.
    muted: true,
    ...qualityOptions(),
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
    concurrency: values.concurrency ?? null,
  });
}

try {
  await render();
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  const message = error instanceof Error ? error.message : String(error);
  // Pipes are asynchronous on Windows: exit only once the error event is flushed.
  process.stdout.write(`${JSON.stringify({ event: "error", message })}\n`, () => process.exit(1));
}
