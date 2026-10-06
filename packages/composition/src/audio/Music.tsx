import { Audio, useVideoConfig } from "remotion";

import type { AudioTrack } from "../types";
import { DEFAULT_DUCKING_DB, musicGain, type Interval } from "./ducking";

interface MusicProps {
  src: string;
  track: AudioTrack;
  speech: readonly Interval[];
}

/**
 * Preview of a music track: looped over the timeline with the same fades and ducking the
 * render applies. Volume changes per video frame here; the exported mix is built by ffmpeg.
 */
export const Music: React.FC<MusicProps> = ({ src, track, speech }) => {
  const { fps, durationInFrames } = useVideoConfig();
  const level = {
    volume: track.volume,
    duckingDb: track.duckingEnabled ? (track.duckingDb ?? DEFAULT_DUCKING_DB) : 0,
    duration: durationInFrames / fps,
  };
  return (
    <Audio
      src={src}
      loop
      loopVolumeCurveBehavior="extend"
      volume={(frame) => musicGain(frame / fps, speech, level)}
    />
  );
};
