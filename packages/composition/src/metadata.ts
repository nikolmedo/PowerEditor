import { timelineLayout } from "./timeline";
import type { Project } from "./types";

export interface VideoMetadata {
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
}

const DIMENSIONS: Record<Project["preset"], { width: number; height: number }> = {
  reel_9x16: { width: 1080, height: 1920 },
  landscape_16x9: { width: 1920, height: 1080 },
};

export function videoMetadata(project: Project): VideoMetadata {
  const { durationInFrames } = timelineLayout(project);
  return {
    // Remotion rejects zero-length compositions; an empty edit renders one frame.
    durationInFrames: Math.max(1, durationInFrames),
    fps: project.fps,
    ...DIMENSIONS[project.preset],
  };
}
