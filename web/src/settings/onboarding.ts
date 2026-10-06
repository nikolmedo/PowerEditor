import type { RuntimeStatus, SetupStatus } from "../api/types";

/** Install order: the render browser is installed by the downloaded Node. */
export const RUNTIME_ORDER: readonly string[] = ["ffmpeg", "node", "browser"];

/** Doctor checks a runtime download satisfies; the browser has no check of its own. */
const CHECKS_COVERED: Record<string, readonly string[]> = {
  ffmpeg: ["ffmpeg", "ffprobe"],
  node: ["node"],
};

const SKIP_KEY = "powereditor.onboardingSkipped";

function toolsFound(status: SetupStatus, runtime: string): boolean {
  const covered = CHECKS_COVERED[runtime] ?? [];
  if (covered.length === 0) return false;
  return covered.every(
    (name) => status.doctor.checks.find((check) => check.name === name)?.found ?? false,
  );
}

/** Runtimes still to download, in install order: supported here, not installed, and not
 * replaced by tools the user already has (FFmpeg or Node on PATH or set in settings). */
export function missingRuntimes(status: SetupStatus): RuntimeStatus[] {
  return status.runtimes
    .filter((runtime) => runtime.supported && !runtime.installed)
    .filter((runtime) => !toolsFound(status, runtime.name))
    .sort((a, b) => RUNTIME_ORDER.indexOf(a.name) - RUNTIME_ORDER.indexOf(b.name));
}

/** The guided setup opens by itself while a runtime is missing, unless the user skipped it. */
export function needsOnboarding(status: SetupStatus, skipped: boolean): boolean {
  return !skipped && missingRuntimes(status).length > 0;
}

export function onboardingSkipped(): boolean {
  try {
    return localStorage.getItem(SKIP_KEY) === "1";
  } catch {
    return false;
  }
}

export function skipOnboarding(): void {
  try {
    localStorage.setItem(SKIP_KEY, "1");
  } catch {
    // Without storage the guided setup simply opens again next time.
  }
}

export function formatMegabytes(bytes: number | null): string {
  return bytes === null ? "" : `${Math.round(bytes / 2 ** 20)} MB`;
}
