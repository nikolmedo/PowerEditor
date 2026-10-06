/**
 * Download a PowerEditor installer from a GitHub release and verify it before it may run.
 *
 * The renderer only names a version; the URLs are built here and must point at this
 * repository's release downloads on github.com (GitHub then redirects to its asset storage).
 * The installer is trusted only when its SHA-256 matches the release's `SHA256SUMS.txt`
 * (written by `scripts/checksums.py`).
 */
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const RELEASES_PATH = "/nikolmedo/PowerEditor/releases/download/";
const SEMVER = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const ASSET_PATH = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\/[\w.-]+$/;
const PROGRESS_INTERVAL_MS = 250;

export type UpdateFailure =
  "invalid_version" | "download_failed" | "checksum_missing" | "checksum_mismatch";

/** What the shell tells the web app about an update download (IPC `updates:state`). */
export type UpdateState =
  | { status: "idle" }
  | { status: "downloading"; version: string; received: number; total: number | null }
  | { status: "verifying"; version: string }
  | { status: "ready"; version: string }
  | { status: "failed"; version: string; error: UpdateFailure };

export interface ReleaseAssets {
  installerName: string;
  installerUrl: string;
  checksumsUrl: string;
}

export function isAllowedReleaseAsset(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return (
    parsed.protocol === "https:" &&
    parsed.host === "github.com" &&
    parsed.username === "" &&
    parsed.password === "" &&
    parsed.search === "" &&
    parsed.hash === "" &&
    parsed.pathname.startsWith(RELEASES_PATH) &&
    ASSET_PATH.test(parsed.pathname.slice(RELEASES_PATH.length))
  );
}

/** The installer electron-builder names `PowerEditor-Setup-<version>-x64.exe`, and the
 * checksum file, of release `v<version>`; null unless `version` is plain semver. */
export function releaseAssets(version: string): ReleaseAssets | null {
  if (!SEMVER.test(version)) return null;
  const base = `https://github.com${RELEASES_PATH}v${version}/`;
  const installerName = `PowerEditor-Setup-${version}-x64.exe`;
  return {
    installerName,
    installerUrl: base + installerName,
    checksumsUrl: `${base}SHA256SUMS.txt`,
  };
}

/** File name → lowercase SHA-256 from `sha256sum` output (`<hex>  <name>` or `<hex> *<name>`). */
export function parseSha256Sums(text: string): Map<string, string> {
  const sums = new Map<string, string>();
  for (const line of text.split(/\r?\n/)) {
    const match = /^([0-9a-fA-F]{64}) [ *](.+)$/.exec(line.trim());
    if (match?.[1] && match[2]) sums.set(match[2], match[1].toLowerCase());
  }
  return sums;
}

export interface DownloaderOptions {
  fetch: typeof fetch;
  /** Where the installer is saved (a temporary folder). */
  directory: string;
  onState: (state: UpdateState) => void;
}

class DownloadError extends Error {
  constructor(readonly reason: UpdateFailure) {
    super(reason);
  }
}

export class UpdateDownloader {
  private state: UpdateState = { status: "idle" };
  private installer: string | null = null;

  constructor(private readonly options: DownloaderOptions) {}

  /** The verified installer, once the state is `ready`. */
  installerPath(): string | null {
    return this.state.status === "ready" ? this.installer : null;
  }

  /** Download and verify release `version`. A call while a download runs changes nothing
   * and resolves with the current state. */
  async download(version: string): Promise<UpdateState> {
    if (this.state.status === "downloading" || this.state.status === "verifying") {
      return this.state;
    }
    const assets = releaseAssets(version);
    if (!assets) return this.set({ status: "failed", version, error: "invalid_version" });
    this.installer = null;
    this.set({ status: "downloading", version, received: 0, total: null });
    try {
      const sums = parseSha256Sums(await (await this.get(assets.checksumsUrl)).text());
      const expected = sums.get(assets.installerName);
      if (!expected) throw new DownloadError("checksum_missing");
      const target = path.join(this.options.directory, assets.installerName);
      const actual = await this.save(version, await this.get(assets.installerUrl), target);
      this.set({ status: "verifying", version });
      if (actual !== expected) {
        await fs.promises.rm(`${target}.part`, { force: true });
        throw new DownloadError("checksum_mismatch");
      }
      await fs.promises.rename(`${target}.part`, target);
      this.installer = target;
      return this.set({ status: "ready", version });
    } catch (error) {
      const reason = error instanceof DownloadError ? error.reason : "download_failed";
      return this.set({ status: "failed", version, error: reason });
    }
  }

  private set(state: UpdateState): UpdateState {
    this.state = state;
    this.options.onState(state);
    return state;
  }

  private async get(url: string): Promise<Response> {
    if (!isAllowedReleaseAsset(url)) throw new DownloadError("download_failed");
    const response = await this.options.fetch(url, { redirect: "follow" });
    if (!response.ok) throw new DownloadError("download_failed");
    return response;
  }

  /** Stream the body to `<target>.part`, reporting progress; resolves with its SHA-256. */
  private async save(version: string, response: Response, target: string): Promise<string> {
    const body = response.body;
    if (!body) throw new DownloadError("download_failed");
    const total = Number(response.headers.get("content-length")) || null;
    const hash = createHash("sha256");
    await fs.promises.mkdir(path.dirname(target), { recursive: true });
    const file = await fs.promises.open(`${target}.part`, "w");
    let received = 0;
    let reported = Date.now();
    try {
      const reader = body.getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        hash.update(value);
        await file.write(value);
        received += value.byteLength;
        if (Date.now() - reported >= PROGRESS_INTERVAL_MS) {
          reported = Date.now();
          this.set({ status: "downloading", version, received, total });
        }
      }
    } catch (error) {
      await file.close();
      await fs.promises.rm(`${target}.part`, { force: true });
      throw error;
    }
    await file.close();
    this.set({ status: "downloading", version, received, total });
    return hash.digest("hex");
  }
}
