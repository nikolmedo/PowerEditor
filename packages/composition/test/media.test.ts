import { describe, expect, it } from "vitest";

import { mediaUrl } from "../src/clips/media";
import { videoMetadata } from "../src/metadata";
import type { Project } from "../src/types";
import fixture from "./fixtures/project.json";

const project = fixture.project as Project;

describe("mediaUrl", () => {
  it("serves a Windows media file by its encoded file name under the base URL", () => {
    expect(
      mediaUrl(
        "http://127.0.0.1:9000/",
        String.raw`C:\data\projects\p\media\my clip.mezzanine.mp4`,
      ),
    ).toBe("http://127.0.0.1:9000/my%20clip.mezzanine.mp4");
  });

  it("accepts POSIX paths and a base URL without a trailing slash", () => {
    expect(mediaUrl("http://localhost:1/media", "/srv/p/media/s1.proxy.mp4")).toBe(
      "http://localhost:1/media/s1.proxy.mp4",
    );
  });
});

describe("videoMetadata", () => {
  it("derives a vertical 1080x1920 frame and the kept duration for reels", () => {
    expect(videoMetadata(project)).toEqual({
      durationInFrames: 160,
      fps: 30,
      width: 1080,
      height: 1920,
    });
  });

  it("derives a 1920x1080 frame for landscape and never a zero-length video", () => {
    const empty: Project = { ...project, preset: "landscape_16x9", fps: 25, clips: [] };
    expect(videoMetadata(empty)).toEqual({
      durationInFrames: 1,
      fps: 25,
      width: 1920,
      height: 1080,
    });
  });
});
