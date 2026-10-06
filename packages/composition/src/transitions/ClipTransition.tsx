import type { ReactNode } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

import type { TransitionIn } from "../types";
import { transitionStyle } from "./transitionStyle";

interface ClipTransitionProps {
  transition: TransitionIn;
  punchInScale: number;
  children: ReactNode;
}

/** Applies a clip's incoming transition; the frame is local to the clip's sequence. */
export const ClipTransition: React.FC<ClipTransitionProps> = ({
  transition,
  punchInScale,
  children,
}) => {
  const frame = useCurrentFrame();
  const { opacity, scale, translateX } = transitionStyle(transition, frame, punchInScale);
  return (
    <AbsoluteFill
      style={{ opacity, transform: `translateX(${translateX * 100}%) scale(${scale})` }}
    >
      {children}
    </AbsoluteFill>
  );
};
