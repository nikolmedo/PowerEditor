import {
  groupLines,
  timelineLayout,
  timelineWords,
  type Clip,
  type Overlay,
  type Project,
} from "@powereditor/composition";

/** A clip as the timeline draws it. Removed clips have no length on the timeline; they sit at
 * the cut where they were dropped (the start of the next kept clip). */
export interface TimelineClip {
  clipId: string;
  sourceId: string;
  startFrame: number;
  durationInFrames: number;
  color: string;
  /** Takes recorded for this phrase (the clip plus its alternatives); 0 without alternatives. */
  takes: number;
  lowConfidence: boolean;
  removed: boolean;
}

export interface LegendEntry {
  sourceId: string;
  color: string;
  label: string;
  /** Seconds of the final video taken from this file. */
  seconds: number;
}

export interface TimelineModel {
  fps: number;
  durationInFrames: number;
  video: TimelineClip[];
  removed: TimelineClip[];
  subtitles: { startFrame: number; endFrame: number; text: string }[];
  graphics: {
    id: string;
    startFrame: number;
    endFrame: number;
    templateId: Overlay["templateId"];
  }[];
  music: { id: string; label: string }[];
  legend: LegendEntry[];
}

export function fileLabel(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

/** Everything the read-only timeline shows; positions come from the composition's
 * `timelineLayout`, the same layout the Player and the render use. */
export function buildTimeline(project: Project, minConfidence: number): TimelineModel {
  const layout = timelineLayout(project);
  const placements = new Map(layout.clips.map((placement) => [placement.clipId, placement]));
  const colors = new Map(project.sources.map((source) => [source.id, source.displayColor]));
  const view = (clip: Clip, startFrame: number, durationInFrames: number): TimelineClip => ({
    clipId: clip.id,
    sourceId: clip.sourceId,
    startFrame,
    durationInFrames,
    color: colors.get(clip.sourceId) ?? "#808080",
    takes: clip.alternativeTakeIds.length > 0 ? clip.alternativeTakeIds.length + 1 : 0,
    lowConfidence: clip.decisionConfidence != null && clip.decisionConfidence < minConfidence,
    removed: clip.removed,
  });

  const video: TimelineClip[] = [];
  const removed: TimelineClip[] = [];
  const pending: Clip[] = [];
  for (const clip of project.clips) {
    const placement = placements.get(clip.id);
    if (!placement) {
      pending.push(clip);
      continue;
    }
    removed.push(...pending.splice(0).map((gone) => view(gone, placement.startFrame, 0)));
    video.push(view(clip, placement.startFrame, placement.durationInFrames));
  }
  removed.push(...pending.map((gone) => view(gone, layout.durationInFrames, 0)));

  const legend = project.sources.map((source) => {
    const frames = video
      .filter((clip) => clip.sourceId === source.id)
      .reduce((sum, clip) => sum + clip.durationInFrames, 0);
    return {
      sourceId: source.id,
      color: source.displayColor,
      label: fileLabel(source.originalPath),
      seconds: frames / project.fps,
    };
  });

  const lines = groupLines(timelineWords(project), {
    maxWordsPerLine: project.subtitles.style.maxWordsPerLine,
    fps: project.fps,
    durationInFrames: layout.durationInFrames,
  });

  return {
    fps: project.fps,
    durationInFrames: layout.durationInFrames,
    video,
    removed,
    subtitles: lines.map(({ startFrame, endFrame, text }) => ({ startFrame, endFrame, text })),
    graphics: project.overlays.map(({ id, startFrame, endFrame, templateId }) => ({
      id,
      startFrame,
      endFrame,
      templateId,
    })),
    music: project.audioTracks
      .filter((track) => track.kind !== "voice")
      .map((track) => ({ id: track.id, label: fileLabel(track.sourcePath ?? track.id) })),
    legend,
  };
}

/** The frame under a horizontal position given as a 0–1 share of the timeline width. */
export function frameAtRatio(ratio: number, durationInFrames: number): number {
  const last = Math.max(0, durationInFrames - 1);
  return Math.min(last, Math.max(0, Math.floor(ratio * durationInFrames)));
}

export function clipAt(model: TimelineModel, frame: number): TimelineClip | undefined {
  return model.video.find(
    (clip) => clip.startFrame <= frame && frame < clip.startFrame + clip.durationInFrames,
  );
}

/** The kept clip `step` places from the selection. A removed clip sits at the cut before the
 * kept clip that starts at its frame; with nothing selected the walk starts at either end. */
export function neighbourClip(
  model: TimelineModel,
  selectedId: string | null,
  step: -1 | 1,
): TimelineClip | undefined {
  const kept = model.video;
  const at = kept.findIndex((clip) => clip.clipId === selectedId);
  if (at >= 0) return kept[at + step];
  const removed = model.removed.find((clip) => clip.clipId === selectedId);
  if (!removed) return step > 0 ? kept[0] : kept.at(-1);
  const after = kept.findIndex((clip) => clip.startFrame >= removed.startFrame);
  if (step > 0) return after < 0 ? undefined : kept[after];
  return kept[(after < 0 ? kept.length : after) - 1];
}
