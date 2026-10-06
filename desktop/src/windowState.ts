import { screen, type BrowserWindow, type BrowserWindowConstructorOptions } from "electron";
import fs from "node:fs";
import { restoreBounds } from "./policy";

const DEFAULT_SIZE = { width: 1440, height: 900 };

interface SavedState {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  maximized?: boolean;
}

function read(file: string): SavedState | null {
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8")) as SavedState;
  } catch {
    return null;
  }
}

/** Bounds for a new window from the last session, checked against today's displays. */
export function savedWindowOptions(file: string): {
  bounds: Pick<BrowserWindowConstructorOptions, "x" | "y" | "width" | "height">;
  maximized: boolean;
} {
  const saved = read(file);
  const areas = screen.getAllDisplays().map((display) => display.workArea);
  return {
    bounds: restoreBounds(saved, areas, DEFAULT_SIZE),
    maximized: saved?.maximized === true,
  };
}

/** Write the window's normal (unmaximized) bounds when it closes. */
export function rememberWindowState(window: BrowserWindow, file: string): void {
  window.on("close", () => {
    const state: SavedState = { ...window.getNormalBounds(), maximized: window.isMaximized() };
    try {
      fs.writeFileSync(file, JSON.stringify(state), "utf-8");
    } catch {
      // Losing the window position is harmless.
    }
  });
}
