/** The desktop shell's updater, exposed by its preload script (`desktop/src/preload.ts`) as
 * `window.powereditor.updates`. Missing in a plain browser. */

export type DesktopUpdateState =
  | { status: "idle" }
  | { status: "downloading"; version: string; received: number; total: number | null }
  | { status: "verifying"; version: string }
  | { status: "ready"; version: string }
  | { status: "failed"; version: string; error: string };

export interface DesktopUpdates {
  /** Download and verify the installer of `version`; resolves with the final state, or
   * null when the shell refused the call. */
  download: (version: string) => Promise<DesktopUpdateState | null>;
  /** Quit and install the verified update silently; the new version starts on its own.
   * False when none is ready. */
  installAndQuit: () => Promise<boolean>;
  /** Announce `version` with a system notification; the shell shows it once per version and
   * run, and resolves false when it showed nothing. */
  notifyAvailable: (version: string) => Promise<boolean>;
  /** Follow the download; returns a function that stops listening. */
  onState: (listener: (state: DesktopUpdateState) => void) => () => void;
}

declare global {
  interface Window {
    powereditor?: { updates?: DesktopUpdates };
  }
}

export function desktopUpdates(): DesktopUpdates | null {
  return window.powereditor?.updates ?? null;
}
