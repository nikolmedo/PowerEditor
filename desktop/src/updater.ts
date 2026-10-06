/**
 * Download a PowerEditor installer from a GitHub release and verify it before it may run.
 *
 * The renderer only names a version; the URLs are built here and must point at this
 * repository's release downloads on github.com. GitHub redirects those to its asset storage;
 * every redirect is checked by `isAllowedRedirect` before it is followed, because the
 * checksum file comes through the same channel as the installer: a redirect to any other
 * host would let that host choose both the bytes and the hash they are checked against.
 * The installer is trusted only when its SHA-256 matches the release's `SHA256SUMS.txt`
 * (written by `scripts/checksums.py`).
 */
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const RELEASES_PATH = "/nikolmedo/PowerEditor/releases/download/";
const SEMVER = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const ASSET_PATH = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\/[\w.-]+$/;
/** Where github.com sends release downloads (signed, short-lived URLs). */
const ASSET_STORAGE_HOSTS: ReadonlySet<string> = new Set([
  "objects.githubusercontent.com",
  "release-assets.githubusercontent.com",
]);
const PROGRESS_INTERVAL_MS = 250;

export interface DownloadTimeouts {
  /** The whole download, checksum file included. */
  totalMs: number;
  /** The longest wait for a response or the next chunk of data. */
  idleMs: number;
}

export const DEFAULT_TIMEOUTS: DownloadTimeouts = { totalMs: 15 * 60_000, idleMs: 60_000 };

export type UpdateFailure =
  "invalid_version" | "download_failed" | "timed_out" | "checksum_missing" | "checksum_mismatch";

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

/** A URL a release download may be redirected to: GitHub's asset storage, or another
 * release asset of this repository, over https on the default port and without credentials. */
export function isAllowedRedirect(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (isAllowedReleaseAsset(url)) return true;
  return (
    parsed.protocol === "https:" &&
    ASSET_STORAGE_HOSTS.has(parsed.host) &&
    parsed.username === "" &&
    parsed.password === ""
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

export interface ReleaseRequestOptions {
  /** Aborts the request and its body. */
  signal: AbortSignal;
  /** Asked before each redirect is followed; a refused redirect fails the request. */
  allowRedirect: (url: string) => boolean;
}

/** A GET that only follows the redirects `allowRedirect` accepts. */
export type ReleaseRequest = (url: string, options: ReleaseRequestOptions) => Promise<Response>;

export interface DownloaderOptions {
  request: ReleaseRequest;
  /** Where the installer is saved (a temporary folder). */
  directory: string;
  onState: (state: UpdateState) => void;
  timeouts?: Partial<DownloadTimeouts>;
}

class DownloadError extends Error {
  constructor(readonly reason: UpdateFailure) {
    super(reason);
  }
}

/** Aborts a download when it runs past its overall limit or waits too long for data. */
class Deadline {
  private readonly controller = new AbortController();
  private readonly aborted: Promise<never>;
  private readonly totalTimer: ReturnType<typeof setTimeout>;
  private idleTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly timeouts: DownloadTimeouts) {
    this.aborted = new Promise<never>((_resolve, reject) => {
      this.controller.signal.addEventListener(
        "abort",
        () => reject(new DownloadError("timed_out")),
        { once: true },
      );
    });
    this.aborted.catch(() => undefined); // only awaited through `guard`
    this.totalTimer = setTimeout(() => this.controller.abort(), timeouts.totalMs);
    this.touch();
  }

  get signal(): AbortSignal {
    return this.controller.signal;
  }

  get expired(): boolean {
    return this.controller.signal.aborted;
  }

  /** Data arrived: restart the idle wait. */
  touch(): void {
    clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => this.controller.abort(), this.timeouts.idleMs);
  }

  /** `work`, or a `timed_out` rejection once the deadline passes, whichever comes first. */
  guard<T>(work: Promise<T>): Promise<T> {
    return Promise.race([work, this.aborted]);
  }

  dispose(): void {
    clearTimeout(this.totalTimer);
    clearTimeout(this.idleTimer);
  }
}

export class UpdateDownloader {
  private state: UpdateState = { status: "idle" };
  private installer: string | null = null;
  private running: Promise<UpdateState> | null = null;
  private readonly timeouts: DownloadTimeouts;

  constructor(private readonly options: DownloaderOptions) {
    this.timeouts = { ...DEFAULT_TIMEOUTS, ...options.timeouts };
  }

  /** The verified installer, once the state is `ready`. */
  installerPath(): string | null {
    return this.state.status === "ready" ? this.installer : null;
  }

  /** Download and verify release `version`; always resolves with `ready` or `failed`. A call
   * while a download runs starts nothing and resolves with that download's result. */
  download(version: string): Promise<UpdateState> {
    this.running ??= this.run(version).finally(() => {
      this.running = null;
    });
    return this.running;
  }

  private async run(version: string): Promise<UpdateState> {
    const assets = releaseAssets(version);
    if (!assets) return this.set({ status: "failed", version, error: "invalid_version" });
    this.installer = null;
    const target = path.join(this.options.directory, assets.installerName);
    const partial = `${target}.part`;
    const deadline = new Deadline(this.timeouts);
    this.set({ status: "downloading", version, received: 0, total: null });
    try {
      const checksums = await this.get(assets.checksumsUrl, deadline);
      const sums = parseSha256Sums(await deadline.guard(checksums.text()));
      const expected = sums.get(assets.installerName);
      if (!expected) throw new DownloadError("checksum_missing");
      const installer = await this.get(assets.installerUrl, deadline);
      const actual = await this.save(version, installer, partial, deadline);
      this.set({ status: "verifying", version });
      if (actual !== expected) throw new DownloadError("checksum_mismatch");
      await fs.promises.rename(partial, target);
      this.installer = target;
      return this.set({ status: "ready", version });
    } catch (error) {
      await fs.promises.rm(partial, { force: true }).catch(() => undefined);
      return this.set({ status: "failed", version, error: failureReason(error, deadline) });
    } finally {
      deadline.dispose();
    }
  }

  private set(state: UpdateState): UpdateState {
    this.state = state;
    this.options.onState(state);
    return state;
  }

  private async get(url: string, deadline: Deadline): Promise<Response> {
    if (!isAllowedReleaseAsset(url)) throw new DownloadError("download_failed");
    const response = await deadline.guard(
      this.options.request(url, { signal: deadline.signal, allowRedirect: isAllowedRedirect }),
    );
    deadline.touch();
    if (!response.ok) throw new DownloadError("download_failed");
    return response;
  }

  /** Stream the body to `partial`, reporting progress; resolves with its SHA-256. */
  private async save(
    version: string,
    response: Response,
    partial: string,
    deadline: Deadline,
  ): Promise<string> {
    const body = response.body;
    if (!body) throw new DownloadError("download_failed");
    const total = Number(response.headers.get("content-length")) || null;
    const hash = createHash("sha256");
    await fs.promises.mkdir(path.dirname(partial), { recursive: true });
    const file = await fs.promises.open(partial, "w");
    const reader = body.getReader();
    let received = 0;
    let reported = Date.now();
    try {
      for (;;) {
        const { done, value } = await deadline.guard(reader.read());
        if (done) break;
        deadline.touch();
        hash.update(value);
        await file.write(value);
        received += value.byteLength;
        if (Date.now() - reported >= PROGRESS_INTERVAL_MS) {
          reported = Date.now();
          this.set({ status: "downloading", version, received, total });
        }
      }
    } catch (error) {
      reader.cancel().catch(() => undefined);
      throw error;
    } finally {
      await file.close();
    }
    this.set({ status: "downloading", version, received, total });
    return hash.digest("hex");
  }
}

function failureReason(error: unknown, deadline: Deadline): UpdateFailure {
  if (deadline.expired) return "timed_out";
  return error instanceof DownloadError ? error.reason : "download_failed";
}
