import path from "node:path";
import { describe, expect, it } from "vitest";
import { ReadyLineReader, parseReadyLine, sidecarCommand } from "../src/sidecar";

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
