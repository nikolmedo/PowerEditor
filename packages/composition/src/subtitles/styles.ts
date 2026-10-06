import type { CSSProperties } from "react";

import type { Project, SubtitleStyle } from "../types";

/** Margins as fractions of the frame, keeping text clear of platform UI. */
interface SafeArea {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

const SAFE_AREAS: Record<Project["preset"], SafeArea> = {
  // Reels, Shorts and TikTok overlay the caption and account at the bottom and the
  // action buttons on the right.
  reel_9x16: { top: 0.12, bottom: 0.24, left: 0.06, right: 0.16 },
  landscape_16x9: { top: 0.08, bottom: 0.1, left: 0.06, right: 0.06 },
};

const JUSTIFY: Record<SubtitleStyle["position"], CSSProperties["justifyContent"]> = {
  top: "flex-start",
  center: "center",
  bottom: "flex-end",
};

/** Container style that places the subtitle block inside the preset's safe area. */
export function safeAreaStyle(
  preset: Project["preset"],
  position: SubtitleStyle["position"],
  width: number,
  height: number,
): CSSProperties {
  const area = SAFE_AREAS[preset];
  return {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: JUSTIFY[position],
    paddingTop: Math.round(area.top * height),
    paddingBottom: Math.round(area.bottom * height),
    paddingLeft: Math.round(area.left * width),
    paddingRight: Math.round(area.right * width),
  };
}

const OUTLINE = "0 0 6px rgba(0,0,0,0.85), 0 3px 8px rgba(0,0,0,0.6)";

/** Text style of the whole line for each preset. */
export function lineStyle(style: SubtitleStyle, fontFamily: string): CSSProperties {
  const base: CSSProperties = {
    fontFamily,
    fontSize: style.fontSize,
    lineHeight: 1.2,
    textAlign: "center",
    color: "white",
  };
  switch (style.preset) {
    case "karaoke_highlight":
      return { ...base, fontWeight: 800, textShadow: OUTLINE };
    case "clean":
      return { ...base, fontWeight: 700, textShadow: OUTLINE };
    case "bold_pop":
      return { ...base, fontWeight: 800, textTransform: "uppercase", textShadow: OUTLINE };
    case "minimal":
      return {
        ...base,
        fontWeight: 400,
        fontSize: Math.round(style.fontSize * 0.8),
        backgroundColor: "rgba(0,0,0,0.55)",
        borderRadius: Math.round(style.fontSize * 0.2),
        padding: `${Math.round(style.fontSize * 0.15)}px ${Math.round(style.fontSize * 0.35)}px`,
      };
  }
}

/** Whether a preset colors the active word with `highlightColor`. */
export function highlightsActiveWord(preset: SubtitleStyle["preset"]): boolean {
  return preset === "karaoke_highlight" || preset === "bold_pop";
}
