import type { CSSProperties } from "react";
import { interpolate, spring } from "remotion";

import { readableTextColor } from "../overlays/color";
import type { SubtitleStyle } from "../types";

/** What a word's look depends on at the current frame. */
export interface WordState {
  /** The last word of the line that has started. */
  isActive: boolean;
  /** Frames since the word started; negative before it starts. */
  framesSinceStart: number;
  fps: number;
  highlightColor: string;
  /** The line's one emphasized word (`editorial_emphasis`). */
  emphasized: boolean;
  /** The word carries an emoji (`emoji_pop`). */
  emoji: boolean;
}

/** Peak scale of the `bold_pop` word that just started. */
const POP_SCALE = 1.12;
/** `kinetic_slam` words land from this scale. */
const SLAM_FROM = 1.5;
const SLAM_FADE_FRAMES = 2;
/** `emoji_pop` emoji grow from this scale with one overshoot. */
const EMOJI_FROM = 0.4;
/** `pill_karaoke`: the pill grows from 85 % as its word starts. */
const PILL_FROM = 0.85;
const PILL_PADDING = "0 0.22em";

const round = (value: number) => Math.round(value * 1000) / 1000;
const scale = (value: number) => `scale(${round(value)})`;

type SpringConfig = NonNullable<Parameters<typeof spring>[0]["config"]>;

function settle(state: WordState, config: SpringConfig): number {
  return spring({ frame: Math.max(0, state.framesSinceStart), fps: state.fps, config });
}

/** Per-word style of each preset, on top of `lineStyle`. Pure, so it is tested per frame. */
export function wordStyle(preset: SubtitleStyle["preset"], state: WordState): CSSProperties {
  const highlight = state.isActive ? { color: state.highlightColor } : {};
  switch (preset) {
    case "karaoke_highlight":
      return highlight;
    case "clean":
    case "minimal":
      return {};
    case "bold_pop":
      if (!state.isActive) return {};
      return {
        ...highlight,
        transform: scale(POP_SCALE - (POP_SCALE - 1) * settle(state, { damping: 12 })),
      };
    case "pill_karaoke":
      return state.isActive
        ? {
            padding: PILL_PADDING,
            borderRadius: "0.3em",
            backgroundColor: state.highlightColor,
            color: readableTextColor(state.highlightColor),
            textShadow: "none",
            transform: scale(PILL_FROM + (1 - PILL_FROM) * settle(state, { damping: 200 })),
          }
        : { padding: PILL_PADDING, borderRadius: "0.3em", backgroundColor: "transparent" };
    case "kinetic_slam": {
      if (state.framesSinceStart < 0) return { opacity: 0 };
      const landed = settle(state, { damping: 14, stiffness: 200 });
      return {
        ...highlight,
        opacity: interpolate(state.framesSinceStart, [0, SLAM_FADE_FRAMES], [0, 1], {
          extrapolateRight: "clamp",
        }),
        transform: scale(SLAM_FROM - (SLAM_FROM - 1) * landed),
      };
    }
    case "emoji_pop": {
      if (!state.emoji) return {};
      if (state.framesSinceStart < 0) return { opacity: 0 };
      const popped = settle(state, { damping: 8, mass: 0.5 });
      return { transform: scale(EMOJI_FROM + (1 - EMOJI_FROM) * popped) };
    }
    case "editorial_emphasis":
      return state.emphasized ? { color: state.highlightColor, fontWeight: 800 } : {};
  }
}
