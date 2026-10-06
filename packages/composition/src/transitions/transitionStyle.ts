import { Easing, interpolate } from "remotion";

import type { TransitionIn } from "../types";

export interface TransitionStyle {
  opacity: number;
  scale: number;
  /** Horizontal offset as a fraction of the frame width (1 = fully off to the right). */
  translateX: number;
}

const NEUTRAL: TransitionStyle = { opacity: 1, scale: 1, translateX: 0 };

/**
 * How a clip looks `frame` frames after it starts, given its incoming transition.
 *
 * Transitions never overlap clips: `punch_in` zooms the whole clip, `fade` rises from black
 * and `slide` enters from the right over `durationFrames` at the start of the clip. The
 * timeline length stays the sum of clip frames, so the rebuilt audio stays aligned.
 */
export function transitionStyle(
  transition: TransitionIn,
  frame: number,
  punchInScale: number,
): TransitionStyle {
  const duration = transition.durationFrames;
  switch (transition.type) {
    case "punch_in":
      return { ...NEUTRAL, scale: punchInScale };
    case "fade":
      if (duration <= 0) return NEUTRAL;
      return {
        ...NEUTRAL,
        opacity: interpolate(frame, [0, duration], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        }),
      };
    case "slide":
      if (duration <= 0) return NEUTRAL;
      return {
        ...NEUTRAL,
        translateX: interpolate(frame, [0, duration], [1, 0], {
          easing: Easing.out(Easing.cubic),
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        }),
      };
    case "cut":
      return NEUTRAL;
  }
}
