import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  isAllowedReleaseAsset,
  parseSha256Sums,
  releaseAssets,
  UpdateDownloader,
  type ReleaseAssets,
  type UpdateState,
} from "../src/updater";

const DOWNLOAD = "https://github.com/nikolmedo/PowerEditor/releases/download";
const INSTALLER = new TextEncoder().encode("MZ fake installer bytes");
const sha256 = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

describe("isAllowedReleaseAsset", () => {
  it("accepts assets of a versioned PowerEditor release on github.com", () => {
    expect(isAllowedReleaseAsset(`${DOWNLOAD}/v1.2.3/PowerEditor-Setup-1.2.3-x64.exe`)).toBe(true);
    expect(isAllowedReleaseAsset(`${DOWNLOAD}/v1.2.3/SHA256SUMS.txt`)).toBe(true);
  });

  it.each([
    ["plain http", `http://github.com/nikolmedo/PowerEditor/releases/download/v1.2.3/a.exe`],
    [
      "another host",
      `https://github.com.evil.example/nikolmedo/PowerEditor/releases/download/v1.2.3/a.exe`,
    ],
    ["another repository", `https://github.com/someone/PowerEditor/releases/download/v1.2.3/a.exe`],
    ["a tag that is not a version", `${DOWNLOAD}/latest/a.exe`],
    ["a nested path", `${DOWNLOAD}/v1.2.3/../../a.exe`],
    ["credentials", `https://user@github.com/nikolmedo/PowerEditor/releases/download/v1.2.3/a.exe`],
    ["a port", `https://github.com:8443/nikolmedo/PowerEditor/releases/download/v1.2.3/a.exe`],
    ["a query", `${DOWNLOAD}/v1.2.3/a.exe?x=1`],
    ["not a URL", "PowerEditor-Setup.exe"],
  ])("refuses %s", (_name, url) => {
    expect(isAllowedReleaseAsset(url)).toBe(false);
  });
});

describe("releaseAssets", () => {
  it("names the installer electron-builder writes and the checksum file", () => {
    expect(releaseAssets("0.2.0")).toEqual({
      installerName: "PowerEditor-Setup-0.2.0-x64.exe",
      installerUrl: `${DOWNLOAD}/v0.2.0/PowerEditor-Setup-0.2.0-x64.exe`,
      checksumsUrl: `${DOWNLOAD}/v0.2.0/SHA256SUMS.txt`,
    });
  });

  it("refuses anything but a plain semver version", () => {
    for (const bad of ["0.2", "v0.2.0", "0.2.0/../x", "0.2.0-beta"]) {
      expect(releaseAssets(bad)).toBeNull();
    }
  });
});

describe("parseSha256Sums", () => {
  it("reads sha256sum lines in text and binary mode, lowercasing the hash", () => {
    const upper = "A".repeat(64);
    const text = `${"b".repeat(64)}  LICENSE\r\n${upper} *PowerEditor-Setup-0.2.0-x64.exe\n\njunk\n`;

    expect(parseSha256Sums(text)).toEqual(
      new Map([
        ["LICENSE", "b".repeat(64)],
        ["PowerEditor-Setup-0.2.0-x64.exe", "a".repeat(64)],
      ]),
    );
  });
});

type Answer = { status?: number; body: Uint8Array | string };

function fakeFetch(answers: Record<string, Answer>, requested: string[]): typeof fetch {
  return (input) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    requested.push(url);
    const answer = answers[url];
    if (!answer) return Promise.reject(new TypeError("fetch failed"));
    const length = typeof answer.body === "string" ? answer.body.length : answer.body.byteLength;
    return Promise.resolve(
      new Response(answer.body, {
        status: answer.status ?? 200,
        headers: { "content-length": String(length) },
      }),
    );
  };
}

describe("UpdateDownloader", () => {
  const assets = releaseAssets("0.2.0") ?? ({} as ReleaseAssets);
  let directory: string;
  let states: UpdateState[];
  let requested: string[];

  beforeEach(() => {
    directory = fs.mkdtempSync(path.join(os.tmpdir(), "pe-update-"));
    states = [];
    requested = [];
  });
  afterEach(() => fs.rmSync(directory, { recursive: true, force: true }));

  const downloader = (answers: Record<string, Answer>) =>
    new UpdateDownloader({
      fetch: fakeFetch(answers, requested),
      directory,
      onState: (state) => states.push(state),
    });

  const sums = (hash: string) => ({ body: `${hash}  ${assets.installerName}\n` });

  it("downloads, verifies and keeps the installer ready to run", async () => {
    const updates = downloader({
      [assets.checksumsUrl]: sums(sha256(INSTALLER)),
      [assets.installerUrl]: { body: INSTALLER },
    });

    const final = await updates.download("0.2.0");

    expect(final).toEqual({ status: "ready", version: "0.2.0" });
    // Progress is throttled by time, so only the order of distinct statuses is fixed.
    expect([...new Set(states.map((state) => state.status))]).toEqual([
      "downloading",
      "verifying",
      "ready",
    ]);
    expect(states.filter((state) => state.status === "downloading").at(-1)).toEqual({
      status: "downloading",
      version: "0.2.0",
      received: INSTALLER.byteLength,
      total: INSTALLER.byteLength,
    });
    const installer = updates.installerPath();
    expect(installer).toBe(path.join(directory, assets.installerName));
    expect(fs.readFileSync(installer ?? "")).toEqual(Buffer.from(INSTALLER));
    expect(requested).toEqual([assets.checksumsUrl, assets.installerUrl]);
  });

  it("deletes a download whose checksum does not match", async () => {
    const updates = downloader({
      [assets.checksumsUrl]: sums("0".repeat(64)),
      [assets.installerUrl]: { body: INSTALLER },
    });

    const final = await updates.download("0.2.0");

    expect(final).toEqual({ status: "failed", version: "0.2.0", error: "checksum_mismatch" });
    expect(updates.installerPath()).toBeNull();
    expect(fs.readdirSync(directory)).toEqual([]);
  });

  it("refuses a release whose checksum file does not list the installer", async () => {
    const updates = downloader({ [assets.checksumsUrl]: { body: `${"a".repeat(64)}  LICENSE\n` } });

    expect(await updates.download("0.2.0")).toEqual({
      status: "failed",
      version: "0.2.0",
      error: "checksum_missing",
    });
    expect(requested).toEqual([assets.checksumsUrl]);
  });

  it("reports a failed request and can try again", async () => {
    const updates = downloader({
      [assets.checksumsUrl]: sums(sha256(INSTALLER)),
      [assets.installerUrl]: { status: 404, body: "Not Found" },
    });

    expect(await updates.download("0.2.0")).toEqual({
      status: "failed",
      version: "0.2.0",
      error: "download_failed",
    });
    expect(updates.installerPath()).toBeNull();
  });

  it("refuses a version the renderer made up, without any request", async () => {
    const updates = downloader({});

    expect(await updates.download("../../evil")).toEqual({
      status: "failed",
      version: "../../evil",
      error: "invalid_version",
    });
    expect(requested).toEqual([]);
  });

  it("does not start a second download while one runs", async () => {
    const updates = downloader({
      [assets.checksumsUrl]: sums(sha256(INSTALLER)),
      [assets.installerUrl]: { body: INSTALLER },
    });

    const [first, second] = await Promise.all([
      updates.download("0.2.0"),
      updates.download("0.2.0"),
    ]);

    expect(first.status).toBe("ready");
    expect(second).toEqual({ status: "downloading", version: "0.2.0", received: 0, total: null });
    expect(requested).toHaveLength(2);
  });
});
