/**
 * The local engine as a child process (contract: README "Desktop sidecar").
 *
 * The shell starts `powereditor-sidecar.exe serve --port 0 --parent-pid <pid>` and waits for
 * one stdout line `POWEREDITOR_READY {"port": N, "token": "..."}`. The token opens the API:
 * the window loads `/?token=<token>` once, which sets a session cookie.
 */
import { execFile, spawn, type ChildProcess } from "node:child_process";
import path from "node:path";

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

/** Splits stdout chunks into lines and reports the first READY line. */
export class ReadyLineReader {
  private buffer = "";

  push(chunk: string): Ready | null {
    this.buffer += chunk;
    const lines = this.buffer.split(/\r?\n/);
    this.buffer = lines.pop() ?? "";
    for (const line of lines) {
      const ready = parseReadyLine(line);
      if (ready) return ready;
    }
    return null;
  }
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

export function startSidecar(command: Command): ChildProcess {
  return spawn(command.file, command.args, {
    cwd: command.cwd,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
}

/** Kill the sidecar and everything it started (ffmpeg, the render Node and browser). */
export function killTree(child: ChildProcess): Promise<void> {
  return new Promise((resolve) => {
    if (child.pid === undefined || child.exitCode !== null) {
      resolve();
      return;
    }
    if (process.platform !== "win32") {
      child.kill("SIGTERM");
      resolve();
      return;
    }
    execFile("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true }, () =>
      resolve(),
    );
  });
}
