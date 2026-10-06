import { AbsoluteFill, OffthreadVideo } from "remotion";

import type { Clip } from "../types";
import { edgeFadeGain } from "./edgeFade";

interface ClipVideoProps {
  src: string;
  clip: Clip;
  /** First source frame to play, in timeline fps. */
  sourceStartFrame: number;
  /** Timeline length of the clip; the enclosing sequence ends playback there. */
  durationInFrames: number;
  fadeFrames: number;
}

/** One timeline clip: a trimmed, speed-adjusted slice of its source. */
export const ClipVideo: React.FC<ClipVideoProps> = ({
  src,
  clip,
  sourceStartFrame,
  durationInFrames,
  fadeFrames,
}) => (
  <AbsoluteFill>
    <OffthreadVideo
      src={src}
      trimBefore={sourceStartFrame}
      playbackRate={clip.speed}
      volume={(frame) => clip.volume * edgeFadeGain(frame, durationInFrames, fadeFrames)}
      style={{ width: "100%", height: "100%", objectFit: "cover" }}
    />
  </AbsoluteFill>
);
