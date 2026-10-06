import { describe, expect, it } from "vitest";

import { area } from "../src/overlays/base";
import { overlayInsets } from "../src/overlays/layout";
import { overlayExit, overlayMotion } from "../src/overlays/motion";
import { overlayVariants, normalizeOverlayProps } from "../src/overlays/templates";
import {
  revealProgress,
  slamOpacity,
  slamScale,
  VARIANT_TIMING,
} from "../src/overlays/variantMotion";
import type { Project } from "../src/types";
import fixture from "./fixtures/project.json";

const FPS = 30;
const ACCENT = "#FFD400";

describe("overlay variants", () => {
  it("lists the looks of each template with the original look first", () => {
    expect(overlayVariants("lower_third")).toEqual([
      "clean_bar",
      "kicker_name",
      "mask_reveal",
      "soft_pill",
    ]);
    expect(overlayVariants("cta")).toEqual(["pill", "lockup", "close"]);
    expect(overlayVariants("title")).toEqual(["classic", "headline_slam"]);
    expect(overlayVariants("logo")).toEqual([]);
  });

  it("keeps a known variant and falls back to the default for unknown or missing ones", () => {
    expect(normalizeOverlayProps("cta", { variant: "lockup" }, ACCENT).variant).toBe("lockup");
    expect(normalizeOverlayProps("cta", { variant: "neon" }, ACCENT).variant).toBe("pill");
    expect(normalizeOverlayProps("lower_third", {}, ACCENT).variant).toBe("clean_bar");
    // A variant of another template is not a look of this one.
    expect(normalizeOverlayProps("title", { variant: "soft_pill" }, ACCENT).variant).toBe(
      "classic",
    );
  });
});

describe("variant motion", () => {
  it("eases a reveal out over its window, after its delay", () => {
    const { barSeconds } = VARIANT_TIMING.maskReveal;
    expect(revealProgress(0, FPS, 0, barSeconds)).toBe(0);
    // 0.2 s into 0.35 s with an ease-out cubic: 1 - (1 - 4/7)^3.
    expect(revealProgress(6, FPS, 0, barSeconds)).toBeCloseTo(1 - (3 / 7) ** 3, 5);
    expect(revealProgress(11, FPS, 0, barSeconds)).toBe(1);
    expect(revealProgress(4, FPS, 0.15, 0.4)).toBe(0);
    expect(revealProgress(10, FPS, 0.15, 0.4)).toBeCloseTo(
      1 - (1 - (10 / 30 - 0.15) / 0.4) ** 3,
      5,
    );
  });

  it("slams a headline in from 1.8x, overshoots below 1 and settles", () => {
    expect(slamScale(0, FPS)).toBe(1.8);
    const frames = Array.from({ length: 30 }, (_, frame) => slamScale(frame, FPS));
    expect(Math.min(...frames)).toBeLessThan(0.97);
    expect(slamScale(30, FPS)).toBeCloseTo(1, 2);
    expect(slamOpacity(0)).toBe(0);
    expect(slamOpacity(1)).toBe(0.5);
    expect(slamOpacity(2)).toBe(1);
  });

  it("splits the shared motion into entrance and exit, so variants reuse the exit", () => {
    expect(overlayExit(45, 90, FPS)).toBe(1);
    expect(overlayExit(85, 90, FPS)).toBeCloseTo(overlayMotion(85, 90, FPS), 6);
    expect(overlayExit(90, 90, FPS)).toBe(0);
    expect(overlayExit(1, 90, FPS)).toBe(1);
  });
});

describe("variant layout", () => {
  const project = fixture.project as Project;

  it("lays every look out inside the preset's safe area and clear of bottom subtitles", () => {
    const reel = { ...project, preset: "reel_9x16" as const };
    const landscape = { ...project, preset: "landscape_16x9" as const };
    const bottom = (base: Project): Project => ({
      ...base,
      subtitles: {
        ...base.subtitles,
        style: { ...base.subtitles.style, position: "bottom", fontSize: 60 },
      },
    });
    expect(area(overlayInsets(bottom(reel), 1080, 1920), "bottom")).toMatchObject({
      justifyContent: "flex-end",
      padding: "230px 173px 635px 65px",
    });
    expect(area(overlayInsets(bottom(landscape), 1920, 1080), "center")).toMatchObject({
      justifyContent: "center",
      padding: "86px 115px 282px 115px",
    });
  });
});
