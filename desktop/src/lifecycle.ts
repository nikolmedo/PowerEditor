/**
 * Ordering rules for leaving the app: restarting it, and handing over to the update installer.
 * Electron and process calls are injected so the order can be tested.
 */
import type { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";

export interface RestartSteps {
  /** Stop the engine this instance started, if it still runs. */
  stopEngine: () => Promise<void>;
  releaseLock: () => void;
  relaunch: () => void;
  quit: () => void;
}

/**
 * Restart the app. Everything this instance owns is stopped before the new instance exists,
 * so nothing it kills can belong to the new one, and the single-instance lock is released
 * before the relaunch, so the new instance is not turned away as a second instance.
 */
export async function restartApp(steps: RestartSteps): Promise<void> {
  try {
    await steps.stopEngine();
  } catch {
    // The engine is gone or cannot be stopped; the restart must still happen.
  }
  steps.releaseLock();
  steps.relaunch();
  steps.quit();
}

/** True when `file` resolves to a path inside `directory` (symbolic links followed); false
 * when either does not exist. */
export function isInsideDirectory(file: string, directory: string): boolean {
  let realFile: string;
  let realDirectory: string;
  try {
    realFile = fs.realpathSync.native(file);
    realDirectory = fs.realpathSync.native(directory);
  } catch {
    return false;
  }
  const relative = path.relative(realDirectory, realFile);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

/** What `launchInstaller` needs of the spawned installer (a `ChildProcess` in the app). */
export interface InstallerProcess extends EventEmitter {
  unref(): void;
}

export type InstallerLaunch =
  | { started: true }
  | { started: false; reason: "outside_update_dir" | "spawn_failed"; detail: string };

/**
 * Start the verified installer, detached. The path is checked again right before the spawn
 * (it must still be a file inside the update folder), and the result is known only once the
 * process has spawned or failed, so the caller quits only for an installer that runs.
 */
export function launchInstaller(
  installer: string,
  directory: string,
  spawnInstaller: (file: string) => InstallerProcess,
): Promise<InstallerLaunch> {
  if (!isInsideDirectory(installer, directory)) {
    return Promise.resolve({ started: false, reason: "outside_update_dir", detail: installer });
  }
  const child = spawnInstaller(fs.realpathSync.native(installer));
  return new Promise((resolve) => {
    child.once("spawn", () => {
      child.unref();
      resolve({ started: true });
    });
    child.once("error", (error: Error) => {
      resolve({ started: false, reason: "spawn_failed", detail: error.message });
    });
  });
}
