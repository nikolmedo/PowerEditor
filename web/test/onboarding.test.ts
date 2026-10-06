import { beforeEach, describe, expect, it } from "vitest";
import type { DependencyCheck, RuntimeStatus, SetupStatus } from "../src/api/types";
import {
  formatMegabytes,
  missingRuntimes,
  needsOnboarding,
  onboardingSkipped,
  skipOnboarding,
} from "../src/settings/onboarding";

const check = (name: string, found: boolean): DependencyCheck => ({
  name,
  required: true,
  found,
  version: null,
  detail: null,
});

const runtime = (name: string, installed: boolean, supported = true): RuntimeStatus => ({
  name,
  version: name === "browser" ? null : "1.0",
  supported,
  installed,
  path: installed ? `C:/bin/${name}` : null,
  downloadBytes: name === "browser" ? null : 50_000_000,
});

function setup(checks: DependencyCheck[], runtimes: RuntimeStatus[]): SetupStatus {
  return {
    doctor: { system: "Windows", machine: "AMD64", checks, ok: false },
    transcriber: "local",
    whisperModel: "small",
    whisperModelDownloaded: false,
    openaiKeySet: false,
    transcriberReady: false,
    ready: false,
    whisperDownloadJobId: null,
    runtimes,
  };
}

describe("missingRuntimes", () => {
  it("lists every runtime of a fresh install in install order", () => {
    const status = setup(
      [check("ffmpeg", false), check("ffprobe", false), check("node", false)],
      [runtime("browser", false), runtime("node", false), runtime("ffmpeg", false)],
    );

    expect(missingRuntimes(status).map((r) => r.name)).toEqual(["ffmpeg", "node", "browser"]);
  });

  it("skips runtimes whose tools are already found or installed", () => {
    const status = setup(
      [check("ffmpeg", true), check("ffprobe", true), check("node", false)],
      [runtime("ffmpeg", false), runtime("node", true), runtime("browser", false)],
    );

    expect(missingRuntimes(status).map((r) => r.name)).toEqual(["browser"]);
  });

  it("needs ffmpeg when ffprobe alone is missing", () => {
    const status = setup(
      [check("ffmpeg", true), check("ffprobe", false), check("node", true)],
      [runtime("ffmpeg", false), runtime("node", false), runtime("browser", true)],
    );

    expect(missingRuntimes(status).map((r) => r.name)).toEqual(["ffmpeg"]);
  });

  it("ignores runtimes this platform cannot download", () => {
    const status = setup([check("ffmpeg", false)], [runtime("ffmpeg", false, false)]);

    expect(missingRuntimes(status)).toEqual([]);
  });
});

describe("needsOnboarding", () => {
  const fresh = setup([check("ffmpeg", false)], [runtime("ffmpeg", false)]);
  const done = setup([check("ffmpeg", false)], [runtime("ffmpeg", true)]);

  it("is due while a runtime is missing and the user did not skip it", () => {
    expect(needsOnboarding(fresh, false)).toBe(true);
    expect(needsOnboarding(fresh, true)).toBe(false);
    expect(needsOnboarding(done, false)).toBe(false);
  });
});

describe("skipOnboarding", () => {
  beforeEach(() => localStorage.clear());

  it("is remembered by the browser", () => {
    expect(onboardingSkipped()).toBe(false);
    skipOnboarding();
    expect(onboardingSkipped()).toBe(true);
  });
});

describe("formatMegabytes", () => {
  it("rounds to whole megabytes and hides unknown sizes", () => {
    expect(formatMegabytes(50_000_000)).toBe("48 MB");
    expect(formatMegabytes(null)).toBe("");
  });
});
