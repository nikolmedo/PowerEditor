/**
 * The local engine as a child process (contract: README "Desktop sidecar").
 *
 * The shell starts `powereditor-sidecar.exe serve --port 0 --parent-pid <pid>` and waits for
 * one stdout line `POWEREDITOR_READY {"port": N, "token": "..."}`. The token opens the API:
 * the window loads `/?token=<token>` once, which sets a session cookie.
 */
import { execFile, spawn, type ChildProcess, type SpawnOptions } from "node:child_process";
import type { EventEmitter } from "node:events";
import path from "node:path";
import type { Readable } from "node:stream";

export const READY_PREFIX = "POWEREDITOR_READY";
export const SIDECAR_EXE = "powereditor-sidecar.exe";

export interface Ready {
  port: number;
  token: string;
}

export function parseReadyLine(line: string): Ready | null {
  if (!line.startsWith(`${READY_PREFIX} `)) return null;
  try {
    const payload = JSON.parse(line.slice(READY_PREFIX.length + 1)) as Partial<Ready>;
    const { port, token } = payload;
    if (typeof port !== "number" || !Number.isInteger(port) || port <= 0) return null;
    if (typeof token !== "string" || token === "") return null;
    return { port, token };
  } catch {
    return null;
  }
}

/** The longest unfinished line kept; a READY line is far shorter, longer output is dropped. */
export const MAX_PENDING_CHARS = 64 * 1024;

/** Splits stdout chunks into lines and reports the first READY line. */
export class ReadyLineReader {
  private buffer = "";

  get pendingLength(): number {
    return this.buffer.length;
  }

  push(chunk: string): Ready | null {
    this.buffer += chunk;
    const lines = this.buffer.split(/\r?\n/);
    const rest = lines.pop() ?? "";
    this.buffer = rest.length > MAX_PENDING_CHARS ? "" : rest;
    for (const line of lines) {
      const ready = parseReadyLine(line);
      if (ready) return ready;
    }
    return null;
  }
}

/** What the start-up watch needs of the engine process (a `ChildProcess` in the app). */
export interface SidecarProcess extends EventEmitter {
  readonly stdout: Readable | null;
  readonly pid?: number | undefined;
  readonly exitCode: number | null;
  /** The signal that ended the process; set instead of `exitCode` on POSIX. */
  readonly signalCode?: NodeJS.Signals | null;
}

export type StartFailure = "timeout" | "exited" | "spawn";

/** Why the engine did not start; `detail` is the exit code, the seconds waited or the
 * spawn error message. */
export class SidecarStartError extends Error {
  constructor(
    readonly reason: StartFailure,
    readonly detail: string,
  ) {
    super(`sidecar start failed (${reason}): ${detail}`);
  }
}

export interface AwaitReadyOptions {
  timeoutMs: number;
  /** Stops the engine and what it started; awaited before a timeout is reported. */
  kill: (child: SidecarProcess) => Promise<void>;
  /** Every stdout chunk, for the log. */
  onOutput?: (chunk: string) => void;
}

/**
 * Resolve with the engine's READY line. Rejects with a `SidecarStartError` when the engine
 * fails to spawn, exits first, or stays silent past the timeout (after killing its tree, so a
 * hung engine does not outlive the error). Its listeners are removed once it settles.
 */
export function awaitReady(child: SidecarProcess, options: AwaitReadyOptions): Promise<Ready> {
  return new Promise((resolve, reject) => {
    const reader = new ReadyLineReader();
    let settled = false;
    const settle = (finish: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.stdout?.off("data", onData);
      child.off("exit", onExit);
      child.off("error", onError);
      finish();
    };
    const onData = (chunk: Buffer | string) => {
      const text = chunk.toString();
      options.onOutput?.(text);
      const ready = reader.push(text);
      if (ready) settle(() => resolve(ready));
    };
    const onExit = (code: number | null) =>
      settle(() => reject(new SidecarStartError("exited", String(code))));
    const onError = (error: Error) =>
      settle(() => reject(new SidecarStartError("spawn", error.message)));
    const timer = setTimeout(() => {
      settle(() => {
        const seconds = String(Math.round(options.timeoutMs / 1000));
        void options
          .kill(child)
          .catch(() => undefined)
          .then(() => reject(new SidecarStartError("timeout", seconds)));
      });
    }, options.timeoutMs);
    child.stdout?.on("data", onData);
    child.on("exit", onExit);
    child.on("error", onError);
  });
}

export interface CommandContext {
  packaged: boolean;
  /** `process.resourcesPath` of the packaged app. */
  resourcesPath: string;
  /** The repository, for development runs. */
  repoRoot: string;
  parentPid: number;
}

export interface Command {
  file: string;
  args: string[];
  cwd: string;
}

/** The bundled sidecar when packaged; `uv run powereditor` from the repository otherwise. */
export function sidecarCommand(context: CommandContext): Command {
  const serve = ["serve", "--port", "0", "--parent-pid", String(context.parentPid)];
  if (context.packaged) {
    const backend = path.join(context.resourcesPath, "backend");
    return { file: path.join(backend, SIDECAR_EXE), args: serve, cwd: backend };
  }
  return {
    file: "uv",
    args: ["run", "powereditor", ...serve],
    cwd: path.join(context.repoRoot, "backend"),
  };
}

/** Off Windows the engine leads its own process group, so one signal reaches its children. */
export function spawnOptions(platform: NodeJS.Platform): SpawnOptions & { detached: boolean } {
  return {
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
    detached: platform !== "win32",
  };
}

export function startSidecar(command: Command): ChildProcess {
  return spawn(command.file, command.args, {
    ...spawnOptions(process.platform),
    cwd: command.cwd,
  });
}

export type KillPlan =
  | { kind: "command"; file: string; args: string[] }
  | { kind: "group"; pid: number; signal: NodeJS.Signals };

/** How to stop a process and its children: `taskkill /T` on Windows, its group elsewhere. */
export function killPlan(pid: number, platform: NodeJS.Platform): KillPlan {
  if (platform === "win32") {
    return { kind: "command", file: "taskkill", args: ["/PID", String(pid), "/T", "/F"] };
  }
  return { kind: "group", pid: -pid, signal: "SIGTERM" };
}

/** True while the process runs. Once it has ended its pid (and process group) may belong to
 * another process, so nothing may be killed by that pid any more. */
export function isAlive(child: SidecarProcess): boolean {
  return child.pid !== undefined && child.exitCode === null && (child.signalCode ?? null) === null;
}

/** Kill the sidecar and everything it started (ffmpeg, the render Node and browser). */
export function killTree(child: SidecarProcess): Promise<void> {
  return new Promise((resolve) => {
    if (!isAlive(child) || child.pid === undefined) {
      resolve();
      return;
    }
    const plan = killPlan(child.pid, process.platform);
    if (plan.kind === "group") {
      try {
        process.kill(plan.pid, plan.signal);
      } catch {
        // The group is already gone.
      }
      resolve();
      return;
    }
    execFile(plan.file, plan.args, { windowsHide: true }, () => resolve());
  });
}
