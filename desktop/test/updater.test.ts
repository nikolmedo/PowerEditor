import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  isAllowedRedirect,
  isReleaseVersion,
  UpdateAnnouncements,
  isAllowedReleaseAsset,
  parseSha256Sums,
  releaseAssets,
  UpdateDownloader,
  type ReleaseAssets,
  type ReleaseRequest,
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

describe("isAllowedRedirect", () => {
  it("accepts GitHub's release asset storage and release URLs over https", () => {
    expect(
      isAllowedRedirect(
        "https://objects.githubusercontent.com/github-production-release-asset/1?X-Amz=s",
      ),
    ).toBe(true);
    expect(
      isAllowedRedirect("https://release-assets.githubusercontent.com/github/1?sp=r&sig=x"),
    ).toBe(true);
    expect(isAllowedRedirect(`${DOWNLOAD}/v1.2.3/SHA256SUMS.txt`)).toBe(true);
  });

  it.each([
    ["plain http", "http://objects.githubusercontent.com/github-production-release-asset/1"],
    ["another host", "https://evil.example/PowerEditor-Setup-1.2.3-x64.exe"],
    ["a look-alike host", "https://objects.githubusercontent.com.evil.example/a"],
    ["a sibling host", "https://raw.githubusercontent.com/nikolmedo/PowerEditor/main/a.exe"],
    ["credentials", "https://user:pw@objects.githubusercontent.com/a"],
    ["a port", "https://objects.githubusercontent.com:8443/a"],
    ["not a URL", "objects.githubusercontent.com/a"],
  ])("refuses %s", (_name, url) => {
    expect(isAllowedRedirect(url)).toBe(false);
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

type Answer =
  | { status?: number; body: Uint8Array | string | ReadableStream<Uint8Array> }
  | { redirect: string };

/** A release request that follows `redirect` answers only while `allowRedirect` agrees, like
 * the shell's `net.request` adapter. */
function fakeRequest(answers: Record<string, Answer>, requested: string[]): ReleaseRequest {
  return (url, { allowRedirect }) => {
    let current = url;
    for (;;) {
      requested.push(current);
      const answer = answers[current];
      if (!answer) return Promise.reject(new TypeError("fetch failed"));
      if ("redirect" in answer) {
        if (!allowRedirect(answer.redirect)) {
          return Promise.reject(new Error("Redirect was cancelled"));
        }
        current = answer.redirect;
        continue;
      }
      const headers: Record<string, string> = {};
      if (typeof answer.body === "string") headers["content-length"] = String(answer.body.length);
      else if (answer.body instanceof Uint8Array) {
        headers["content-length"] = String(answer.body.byteLength);
      }
      return Promise.resolve(new Response(answer.body, { status: answer.status ?? 200, headers }));
    }
  };
}

/** A body that never sends anything, like a stalled connection. */
const silentBody = () =>
  new ReadableStream<Uint8Array>({ pull: () => new Promise<void>(() => undefined) });

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
  afterEach(() => {
    vi.useRealTimers();
    fs.rmSync(directory, { recursive: true, force: true });
  });

  const downloader = (
    answers: Record<string, Answer>,
    timeouts?: { totalMs?: number; idleMs?: number },
  ) =>
    new UpdateDownloader({
      request: fakeRequest(answers, requested),
      directory,
      onState: (state) => states.push(state),
      ...(timeouts ? { timeouts } : {}),
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

  it("does not start a second download while one runs; both callers get its result", async () => {
    const updates = downloader({
      [assets.checksumsUrl]: sums(sha256(INSTALLER)),
      [assets.installerUrl]: { body: INSTALLER },
    });

    const [first, second] = await Promise.all([
      updates.download("0.2.0"),
      updates.download("0.2.0"),
    ]);

    expect(first).toEqual({ status: "ready", version: "0.2.0" });
    expect(second).toEqual({ status: "ready", version: "0.2.0" });
    expect(requested).toHaveLength(2);
  });

  it("follows GitHub's redirect to its asset storage", async () => {
    const storage = "https://release-assets.githubusercontent.com/github/1?sig=abc";
    const updates = downloader({
      [assets.checksumsUrl]: sums(sha256(INSTALLER)),
      [assets.installerUrl]: { redirect: storage },
      [storage]: { body: INSTALLER },
    });

    expect(await updates.download("0.2.0")).toEqual({ status: "ready", version: "0.2.0" });
    expect(requested).toEqual([assets.checksumsUrl, assets.installerUrl, storage]);
  });

  it.each([
    ["the installer", assets.installerUrl],
    ["the checksum file", assets.checksumsUrl],
  ])("refuses a redirect of %s to another host", async (_name, redirected) => {
    const evil = "https://evil.example/payload";
    const answers: Record<string, Answer> = {
      [assets.checksumsUrl]: sums(sha256(INSTALLER)),
      [assets.installerUrl]: { body: INSTALLER },
      [evil]: { body: INSTALLER },
    };
    answers[redirected] = { redirect: evil };
    const updates = downloader(answers);

    expect(await updates.download("0.2.0")).toEqual({
      status: "failed",
      version: "0.2.0",
      error: "download_failed",
    });
    expect(requested).not.toContain(evil);
    expect(updates.installerPath()).toBeNull();
  });

  it("gives up on a download that stops sending data and removes the partial file", async () => {
    vi.useFakeTimers();
    const updates = downloader(
      {
        [assets.checksumsUrl]: sums(sha256(INSTALLER)),
        [assets.installerUrl]: { body: silentBody() },
      },
      { idleMs: 1000, totalMs: 60_000 },
    );

    const result = updates.download("0.2.0");
    await vi.advanceTimersByTimeAsync(1500);

    const failed = { status: "failed", version: "0.2.0", error: "timed_out" };
    expect(await result).toEqual(failed);
    expect(states.at(-1)).toEqual(failed);
    expect(fs.readdirSync(directory)).toEqual([]);
  });

  it("gives up on a download that takes longer than the overall limit", async () => {
    // Real timers: the chunks are written to disk, which fake time does not wait for.
    let chunks = 0;
    const trickle = new ReadableStream<Uint8Array>({
      pull: async (controller) => {
        await new Promise((resolve) => setTimeout(resolve, 20));
        chunks += 1;
        controller.enqueue(new Uint8Array([chunks % 256]));
      },
    });
    const updates = downloader(
      {
        [assets.checksumsUrl]: sums(sha256(INSTALLER)),
        [assets.installerUrl]: { body: trickle },
      },
      { idleMs: 200, totalMs: 500 },
    );

    expect(await updates.download("0.2.0")).toEqual({
      status: "failed",
      version: "0.2.0",
      error: "timed_out",
    });
    // Data kept coming, so it was the overall limit and not the idle wait that stopped it.
    expect(chunks).toBeGreaterThan(5);
    expect(fs.readdirSync(directory)).toEqual([]);
  });

  it("can download again after a timeout", async () => {
    vi.useFakeTimers();
    const answers: Record<string, Answer> = {
      [assets.checksumsUrl]: sums(sha256(INSTALLER)),
      [assets.installerUrl]: { body: silentBody() },
    };
    const updates = downloader(answers, { idleMs: 1000, totalMs: 60_000 });
    const first = updates.download("0.2.0");
    await vi.advanceTimersByTimeAsync(1500);
    expect((await first).status).toBe("failed");

    answers[assets.installerUrl] = { body: INSTALLER };
    vi.useRealTimers();

    expect(await updates.download("0.2.0")).toEqual({ status: "ready", version: "0.2.0" });
  });
});

describe("isReleaseVersion", () => {
  it("accepts plain semantic versions only", () => {
    expect(isReleaseVersion("0.2.0")).toBe(true);
    expect(isReleaseVersion("10.20.30")).toBe(true);
    for (const value of ["v0.2.0", "0.2", "0.2.0-beta", "01.2.3", "", 2, null, undefined]) {
      expect(isReleaseVersion(value)).toBe(false);
    }
  });
});

describe("UpdateAnnouncements", () => {
  it("announces each version once per run", () => {
    const announcements = new UpdateAnnouncements();

    expect(announcements.claim("0.2.0")).toBe(true);
    expect(announcements.claim("0.2.0")).toBe(false);
    expect(announcements.claim("0.3.0")).toBe(true);
  });

  it("never announces something that is not a release version", () => {
    const announcements = new UpdateAnnouncements();

    expect(announcements.claim("../0.2.0")).toBe(false);
    expect(announcements.claim({ version: "0.2.0" })).toBe(false);
    expect(announcements.claim("0.2.0")).toBe(true);
  });
});
