import { EventEmitter } from "node:events";
import path from "node:path";
import { PassThrough } from "node:stream";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_PENDING_CHARS,
  ReadyLineReader,
  SidecarStartError,
  awaitReady,
  killPlan,
  parseReadyLine,
  sidecarCommand,
  spawnOptions,
  type SidecarProcess,
} from "../src/sidecar";

describe("parseReadyLine", () => {
  it("reads the port and token of the READY line", () => {
    expect(parseReadyLine('POWEREDITOR_READY {"port": 51234, "token": "abc"}')).toEqual({
      port: 51234,
      token: "abc",
    });
  });

  it("ignores other output and malformed READY lines", () => {
    expect(parseReadyLine("INFO: Started server process")).toBeNull();
    expect(parseReadyLine("POWEREDITOR_READY {not json")).toBeNull();
    expect(parseReadyLine('POWEREDITOR_READY {"port": 0, "token": "abc"}')).toBeNull();
    expect(parseReadyLine('POWEREDITOR_READY {"port": 51234, "token": null}')).toBeNull();
  });
});

describe("ReadyLineReader", () => {
  it("finds the READY line across chunk boundaries and CRLF endings", () => {
    const reader = new ReadyLineReader();

    expect(reader.push('loading models\r\nPOWEREDITOR_READY {"po')).toBeNull();
    expect(reader.push('rt": 8, "token": "t"}\r\nmore')).toEqual({ port: 8, token: "t" });
  });

  it("keeps memory bounded when the engine prints a huge line without an end", () => {
    const reader = new ReadyLineReader();

    expect(reader.push("x".repeat(4 * MAX_PENDING_CHARS))).toBeNull();
    expect(reader.pendingLength).toBeLessThanOrEqual(MAX_PENDING_CHARS);
    expect(reader.push('\nPOWEREDITOR_READY {"port": 9, "token": "t"}\n')).toEqual({
      port: 9,
      token: "t",
    });
  });
});

class FakeSidecar extends EventEmitter implements SidecarProcess {
  readonly stdout = new PassThrough();
  readonly pid = 4321;
  exitCode: number | null = null;

  exit(code: number) {
    this.exitCode = code;
    this.emit("exit", code);
  }
}

describe("awaitReady", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves with the READY line and stops watching for the start", async () => {
    const child = new FakeSidecar();
    const kill = vi.fn(async () => undefined);
    const ready = awaitReady(child, { timeoutMs: 1000, kill });

    child.stdout.write('starting\nPOWEREDITOR_READY {"port": 7, "token": "k"}\n');

    await expect(ready).resolves.toEqual({ port: 7, token: "k" });
    expect(child.listenerCount("exit")).toBe(0);
    expect(kill).not.toHaveBeenCalled();
  });

  it("kills the engine tree before reporting a timeout", async () => {
    vi.useFakeTimers();
    const child = new FakeSidecar();
    const order: string[] = [];
    const kill = vi.fn(async () => {
      order.push("kill");
    });
    const ready = awaitReady(child, { timeoutMs: 1000, kill }).catch((error: unknown) => {
      order.push("rejected");
      return error;
    });

    await vi.advanceTimersByTimeAsync(1000);

    const error = await ready;
    expect(order).toEqual(["kill", "rejected"]);
    expect(kill).toHaveBeenCalledWith(child);
    expect(error).toBeInstanceOf(SidecarStartError);
    expect((error as SidecarStartError).reason).toBe("timeout");
  });

  it("reports an engine that exits before READY with its exit code", async () => {
    const child = new FakeSidecar();
    const ready = awaitReady(child, { timeoutMs: 1000, kill: async () => undefined });

    child.exit(3);

    await expect(ready).rejects.toMatchObject({ reason: "exited", detail: "3" });
  });

  it("reports a spawn failure", async () => {
    const child = new FakeSidecar();
    const ready = awaitReady(child, { timeoutMs: 1000, kill: async () => undefined });

    child.emit("error", new Error("ENOENT"));

    await expect(ready).rejects.toMatchObject({ reason: "spawn", detail: "ENOENT" });
  });
});

describe("process tree", () => {
  it("kills the tree with taskkill on Windows", () => {
    expect(killPlan(4321, "win32")).toEqual({
      kind: "command",
      file: "taskkill",
      args: ["/PID", "4321", "/T", "/F"],
    });
  });

  it("signals the whole process group elsewhere, so the engine starts as a group leader", () => {
    expect(killPlan(4321, "linux")).toEqual({ kind: "group", pid: -4321, signal: "SIGTERM" });
    expect(spawnOptions("linux").detached).toBe(true);
    expect(spawnOptions("win32").detached).toBe(false);
  });
});

describe("sidecarCommand", () => {
  const args = ["serve", "--port", "0", "--parent-pid", "42"];

  it("starts the bundled sidecar from the app resources when packaged", () => {
    const command = sidecarCommand({
      packaged: true,
      resourcesPath: "C:/Apps/PowerEditor/resources",
      repoRoot: "C:/repo",
      parentPid: 42,
    });

    expect(command).toEqual({
      file: path.join("C:/Apps/PowerEditor/resources", "backend", "powereditor-sidecar.exe"),
      args,
      cwd: path.join("C:/Apps/PowerEditor/resources", "backend"),
    });
  });

  it("runs the backend from the repository through uv in development", () => {
    const command = sidecarCommand({
      packaged: false,
      resourcesPath: "unused",
      repoRoot: "C:/repo",
      parentPid: 42,
    });

    expect(command).toEqual({
      file: "uv",
      args: ["run", "powereditor", ...args],
      cwd: path.join("C:/repo", "backend"),
    });
  });
});
