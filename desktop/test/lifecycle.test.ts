import { EventEmitter } from "node:events";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  isInsideDirectory,
  launchInstaller,
  restartApp,
  type InstallerProcess,
} from "../src/lifecycle";

describe("restartApp", () => {
  it("stops the old engine and releases the single-instance lock before relaunching", async () => {
    const calls: string[] = [];
    let finishStop: () => void = () => undefined;
    const steps = {
      stopEngine: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            calls.push("stopEngine");
            finishStop = () => {
              calls.push("engineStopped");
              resolve();
            };
          }),
      ),
      releaseLock: vi.fn(() => calls.push("releaseLock")),
      relaunch: vi.fn(() => calls.push("relaunch")),
      quit: vi.fn(() => calls.push("quit")),
    };

    const restarted = restartApp(steps);
    await Promise.resolve();
    expect(calls).toEqual(["stopEngine"]);
    finishStop();
    await restarted;

    expect(calls).toEqual(["stopEngine", "engineStopped", "releaseLock", "relaunch", "quit"]);
  });

  it("still relaunches when stopping the engine fails", async () => {
    const calls: string[] = [];
    await restartApp({
      stopEngine: () => Promise.reject(new Error("taskkill failed")),
      releaseLock: () => calls.push("releaseLock"),
      relaunch: () => calls.push("relaunch"),
      quit: () => calls.push("quit"),
    });

    expect(calls).toEqual(["releaseLock", "relaunch", "quit"]);
  });
});

class FakeInstaller extends EventEmitter implements InstallerProcess {
  unref = vi.fn();
}

describe("launchInstaller", () => {
  let directory: string;
  let installer: string;

  beforeEach(() => {
    directory = fs.mkdtempSync(path.join(os.tmpdir(), "pe-install-"));
    installer = path.join(directory, "PowerEditor-Setup-0.2.0-x64.exe");
    fs.writeFileSync(installer, "MZ");
  });
  afterEach(() => fs.rmSync(directory, { recursive: true, force: true }));

  it("resolves as started only once the process has spawned", async () => {
    const child = new FakeInstaller();
    const spawnInstaller = vi.fn(() => child);
    let settled = false;
    const launched = launchInstaller(installer, directory, spawnInstaller).then((result) => {
      settled = true;
      return result;
    });

    await Promise.resolve();
    expect(settled).toBe(false);
    child.emit("spawn");

    expect(await launched).toEqual({ started: true });
    expect(spawnInstaller).toHaveBeenCalledWith(fs.realpathSync.native(installer));
    expect(child.unref).toHaveBeenCalled();
  });

  it("reports a process that fails to start", async () => {
    const child = new FakeInstaller();
    const launched = launchInstaller(installer, directory, () => child);

    child.emit("error", new Error("spawn EACCES"));

    expect(await launched).toEqual({
      started: false,
      reason: "spawn_failed",
      detail: "spawn EACCES",
    });
    expect(child.unref).not.toHaveBeenCalled();
  });

  it("refuses an installer outside the update folder without spawning", async () => {
    const outside = fs.mkdtempSync(path.join(os.tmpdir(), "pe-outside-"));
    const stray = path.join(outside, "setup.exe");
    fs.writeFileSync(stray, "MZ");
    const spawnInstaller = vi.fn(() => new FakeInstaller());
    try {
      expect(await launchInstaller(stray, directory, spawnInstaller)).toEqual({
        started: false,
        reason: "outside_update_dir",
        detail: stray,
      });
      expect(spawnInstaller).not.toHaveBeenCalled();
    } finally {
      fs.rmSync(outside, { recursive: true, force: true });
    }
  });

  it("refuses an installer that is gone", async () => {
    fs.rmSync(installer);
    const spawnInstaller = vi.fn(() => new FakeInstaller());

    expect((await launchInstaller(installer, directory, spawnInstaller)).started).toBe(false);
    expect(spawnInstaller).not.toHaveBeenCalled();
  });
});

describe("isInsideDirectory", () => {
  it("accepts a file inside the folder and refuses the folder itself or a path out of it", () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), "pe-inside-"));
    const file = path.join(directory, "a.exe");
    fs.writeFileSync(file, "");
    try {
      expect(isInsideDirectory(file, directory)).toBe(true);
      expect(isInsideDirectory(directory, directory)).toBe(false);
      expect(
        isInsideDirectory(path.join(directory, "..", path.basename(directory)), directory),
      ).toBe(false);
      expect(isInsideDirectory(os.tmpdir(), directory)).toBe(false);
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });
});
