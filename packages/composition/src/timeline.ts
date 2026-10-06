import type { Clip, Project } from "./types";

export interface ClipPlacement {
  clipId: string;
  startFrame: number;
  durationInFrames: number;
  sourceStartFrame: number;
}

export interface TimelineLayout {
  durationInFrames: number;
  clips: ClipPlacement[];
}

/** Round to the nearest integer, ties to even: the semantics of Python's `round()`. */
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff < 0.5) return floor;
  if (diff > 0.5) return floor + 1;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** Timeline length of a clip in frames; mirrors the backend's `clip_frames`. */
export function clipFrames(clip: Clip, fps: number): number {
  return roundHalfEven(((clip.outSec - clip.inSec) / clip.speed) * fps);
}

/** Back-to-back placement of every kept clip, in timeline frames. */
export function timelineLayout(project: Project): TimelineLayout {
  const clips: ClipPlacement[] = [];
  let offset = 0;
  for (const clip of project.clips) {
    if (clip.removed) continue;
    const durationInFrames = clipFrames(clip, project.fps);
    clips.push({
      clipId: clip.id,
      startFrame: offset,
      durationInFrames,
      sourceStartFrame: roundHalfEven(clip.inSec * project.fps),
    });
    offset += durationInFrames;
  }
  return { durationInFrames: offset, clips };
}
