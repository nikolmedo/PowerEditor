import { TRIM_STEP_SECONDS, type Edge } from "../edit/operations";

export type EditorCommand =
  | { type: "undo" }
  | { type: "redo" }
  | { type: "move"; step: -1 | 1 }
  | { type: "toggleRemoved" }
  | { type: "trim"; edge: Edge; deltaSec: number }
  | { type: "zoom"; direction: -1 | 1 }
  | { type: "zoomFit" };

type KeyInput = Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey">;

/** `[` / `]` shorten the selected clip at its start / end; with Shift (`{` / `}`) they extend it. */
const TRIM_KEYS: Record<string, { edge: Edge; deltaSec: number }> = {
  "[": { edge: "start", deltaSec: TRIM_STEP_SECONDS },
  "{": { edge: "start", deltaSec: -TRIM_STEP_SECONDS },
  "]": { edge: "end", deltaSec: -TRIM_STEP_SECONDS },
  "}": { edge: "end", deltaSec: TRIM_STEP_SECONDS },
};

/** `=` / `+` zoom the timeline in, `-` out and `\` fits the whole video, as in Premiere. */
const ZOOM_KEYS: Record<string, EditorCommand> = {
  "=": { type: "zoom", direction: 1 },
  "+": { type: "zoom", direction: 1 },
  "-": { type: "zoom", direction: -1 },
  "\\": { type: "zoomFit" },
};

/** The editor command for a key press, if it is one of the review step's shortcuts. */
export function editorCommand(event: KeyInput): EditorCommand | null {
  const key = event.key.toLowerCase();
  // Ctrl / Cmd with `=` or `-` stays the browser's page zoom.
  if (event.ctrlKey || event.metaKey) {
    if (key === "z") return event.shiftKey ? { type: "redo" } : { type: "undo" };
    if (key === "y") return { type: "redo" };
    return null;
  }
  if (event.altKey) return null;
  if (key === "arrowleft") return { type: "move", step: -1 };
  if (key === "arrowright") return { type: "move", step: 1 };
  if (key === "delete" || key === "backspace") return { type: "toggleRemoved" };
  const trim = TRIM_KEYS[event.key];
  if (trim) return { type: "trim", ...trim };
  return ZOOM_KEYS[event.key] ?? null;
}

/** Keys typed into a form control, or handled by the player's own controls, are not ours. */
export function ownsKeys(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return target.closest("input, textarea, select, .player-frame") !== null;
}
