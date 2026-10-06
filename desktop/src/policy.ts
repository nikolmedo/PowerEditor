/** Pure rules of the shell: which URLs the window may show or open, and window bounds. */

/** Sites a link in the app may open in the default browser (https only). */
export const EXTERNAL_HOSTS: ReadonlySet<string> = new Set([
  "github.com",
  "www.remotion.dev",
  "code.claude.com",
  "geminicli.com",
  "learn.chatgpt.com",
  "platform.openai.com",
  "console.anthropic.com",
  "nolmedo.dev",
]);

function parse(url: string): URL | null {
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

/** True for a page of the sidecar itself: the only content the window may load. */
export function isAppUrl(url: string, appOrigin: string): boolean {
  return parse(url)?.origin === appOrigin;
}

export function isAllowedExternal(url: string): boolean {
  const parsed = parse(url);
  return parsed !== null && parsed.protocol === "https:" && EXTERNAL_HOSTS.has(parsed.hostname);
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type Size = Pick<Rect, "width" | "height">;

const MIN_VISIBLE = 64;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function overlaps(rect: Rect, area: Rect): boolean {
  const width = Math.min(rect.x + rect.width, area.x + area.width) - Math.max(rect.x, area.x);
  const height = Math.min(rect.y + rect.height, area.y + area.height) - Math.max(rect.y, area.y);
  return width >= MIN_VISIBLE && height >= MIN_VISIBLE;
}

/**
 * Bounds to open the window with, from saved state that may be stale or corrupt: sizes are
 * capped to the largest display, and a position is kept only when the window would still be
 * visible on one of `workAreas` (otherwise the window opens centered).
 */
export function restoreBounds(saved: unknown, workAreas: Rect[], fallback: Size): Size | Rect {
  const state = (saved ?? {}) as Partial<Record<keyof Rect, unknown>>;
  if (!isFiniteNumber(state.width) || !isFiniteNumber(state.height)) return fallback;
  const maxWidth = Math.max(...workAreas.map((area) => area.width), fallback.width);
  const maxHeight = Math.max(...workAreas.map((area) => area.height), fallback.height);
  const size = {
    width: Math.round(Math.min(Math.max(state.width, 640), maxWidth)),
    height: Math.round(Math.min(Math.max(state.height, 480), maxHeight)),
  };
  if (!isFiniteNumber(state.x) || !isFiniteNumber(state.y)) return size;
  const rect = { x: Math.round(state.x), y: Math.round(state.y), ...size };
  return workAreas.some((area) => overlaps(rect, area)) ? rect : size;
}
