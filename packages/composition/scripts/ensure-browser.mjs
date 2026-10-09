// Downloads the Chrome Headless Shell that Remotion renders with, if it is missing.
//
// Usage: node scripts/ensure-browser.mjs
//
// Remotion stores the browser under the `node_modules/.remotion` folder next to the nearest
// `package.json` above the working directory, so the backend runs this script (and the
// renderer) from a writable folder in the app's data dir.
//
// Reports newline-delimited JSON events on stdout:
//   {"event":"progress","fraction":0.42}
//   {"event":"done","path":"...","type":"local-puppeteer-browser"}
//   {"event":"error","message":"..."}   (then exits with code 1)
import os from "node:os";
import { syncBuiltinESMExports } from "node:module";
import { ensureBrowser } from "@remotion/renderer";

function emit(event) {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

// Remotion refuses to download the browser under an arm64 Node on Windows, although it
// always fetches the `win64` build there and that build runs emulated on ARM64. Report x64
// so the download goes through; this script only installs the browser.
if (process.platform === "win32" && os.arch() === "arm64") {
  os.arch = () => "x64";
  syncBuiltinESMExports();
}

try {
  let lastReported = -1;
  const status = await ensureBrowser({
    logLevel: "error",
    onBrowserDownload: () => ({
      version: null,
      onProgress: ({ percent }) => {
        const rounded = Math.floor(percent * 100);
        if (rounded !== lastReported) {
          lastReported = rounded;
          emit({ event: "progress", fraction: percent });
        }
      },
    }),
  });
  emit({ event: "done", path: status.path ?? null, type: status.type });
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stdout.write(`${JSON.stringify({ event: "error", message })}\n`, () => process.exit(1));
}
