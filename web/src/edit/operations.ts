import {
  clipFrames,
  editSubtitleText,
  remapWords,
  roundHalfEven,
  type Clip,
  type Project,
  type SubtitleStyle,
  type TransitionType,
} from "@powereditor/composition";

/**
 * Pure edits of a loaded project: each takes a `Project` and returns the edited one, or the
 * same object when nothing changed (so undo history and autosave skip no-ops). Clip edits
 * also recompute `subtitles.words` with the shared `remapWords`, so a saved project never
 * carries stale subtitle timing. Values are clamped to the ranges the backend validates.
 */

export const TRIM_STEP_SECONDS = 0.1;
export const MIN_CLIP_SECONDS = 0.1;
export const SPEED_RANGE = [0.5, 2] as const;
export const VOLUME_RANGE = [0, 2] as const;
/** Length of a fade or slide when none is given; the draft builder uses the same value. */
export const TRANSITION_SECONDS = 0.3;
export const TRANSITION_TYPES: readonly TransitionType[] = ["cut", "punch_in", "fade", "slide"];

export type Edge = "start" | "end";

const clamp = (value: number, [low, high]: readonly [number, number]) =>
  Math.min(high, Math.max(low, value));
/** Millisecond precision: repeated 0.1 s steps would otherwise drift (0.30000000000000004). */
const toMs = (seconds: number) => Math.round(seconds * 1000) / 1000;

/** Recompute the timeline words from the stored source words (legacy projects keep theirs). */
export function withWords(project: Project): Project {
  const sourceWords = project.subtitles.sourceWords ?? {};
  if (Object.keys(sourceWords).length === 0) return project;
  const words = remapWords(project.clips, sourceWords, project.fps);
  return { ...project, subtitles: { ...project.subtitles, words } };
}

function sameClip(a: Clip, b: Clip): boolean {
  return (
    a.inSec === b.inSec &&
    a.outSec === b.outSec &&
    a.speed === b.speed &&
    a.volume === b.volume &&
    a.removed === b.removed &&
    a.transitionIn.type === b.transitionIn.type &&
    a.transitionIn.durationFrames === b.transitionIn.durationFrames
  );
}

/** Apply `change` to the clips it returns a different value for, then resync the words. */
function updateClips(project: Project, change: (clip: Clip) => Clip): Project {
  let changed = false;
  const clips = project.clips.map((clip) => {
    const next = change(clip);
    if (next === clip || sameClip(next, clip)) return clip;
    changed = true;
    return next;
  });
  return changed ? withWords({ ...project, clips }) : project;
}

const updateClip = (project: Project, clipId: string, change: (clip: Clip) => Clip) =>
  updateClips(project, (clip) => (clip.id === clipId ? change(clip) : clip));

/** Where the source file is known to end: the furthest clip or word taken from it. The project
 * does not store file lengths, so trimming never extends a clip past material it has seen. */
function knownSourceEnd(project: Project, sourceId: string): number {
  const clipEnds = project.clips.filter((c) => c.sourceId === sourceId).map((c) => c.outSec);
  const wordEnds = (project.subtitles.sourceWords?.[sourceId] ?? []).map((word) => word.end);
  return Math.max(0, ...clipEnds, ...wordEnds);
}

/** Move one edge of a clip by `deltaSec` of source time (positive = later), keeping at least
 * `MIN_CLIP_SECONDS` of length and staying inside the known part of the file. */
export function trimClip(project: Project, clipId: string, edge: Edge, deltaSec: number): Project {
  /** The moved edge, or the current one when clamping would push it the other way. */
  const move = (current: number, bounds: readonly [number, number]) => {
    const next = clamp(toMs(current + deltaSec), bounds);
    return Math.sign(next - current) === Math.sign(deltaSec) ? next : current;
  };
  return updateClip(project, clipId, (clip) =>
    edge === "start"
      ? { ...clip, inSec: move(clip.inSec, [0, toMs(clip.outSec - MIN_CLIP_SECONDS)]) }
      : {
          ...clip,
          outSec: move(clip.outSec, [
            toMs(clip.inSec + MIN_CLIP_SECONDS),
            knownSourceEnd(project, clip.sourceId),
          ]),
        },
  );
}

export function setRemoved(project: Project, clipId: string, removed: boolean): Project {
  return updateClip(project, clipId, (clip) => ({ ...clip, removed }));
}

export function setClipSpeed(project: Project, clipId: string, speed: number): Project {
  return updateClip(project, clipId, (clip) => ({ ...clip, speed: clamp(speed, SPEED_RANGE) }));
}

export function setClipVolume(project: Project, clipId: string, volume: number): Project {
  return updateClip(project, clipId, (clip) => ({ ...clip, volume: clamp(volume, VOLUME_RANGE) }));
}

/** The clip whose alternatives include `clipId`, or the clip itself when it owns the take. */
function takeOwner(project: Project, clipId: string): Clip | undefined {
  return (
    project.clips.find((clip) => clip.alternativeTakeIds.includes(clipId)) ??
    project.clips.find((clip) => clip.id === clipId)
  );
}

/**
 * Keep `alternativeId` instead of the take `keptId`. The alternative moves into the kept take's
 * place on the timeline and inherits its incoming transition and its list of alternatives.
 */
export function swapTake(project: Project, keptId: string, alternativeId: string): Project {
  const kept = project.clips.find((clip) => clip.id === keptId);
  const alternative = project.clips.find((clip) => clip.id === alternativeId);
  if (!kept || !alternative || !kept.alternativeTakeIds.includes(alternativeId)) return project;
  const newKept: Clip = {
    ...alternative,
    removed: kept.removed,
    transitionIn: kept.transitionIn,
    alternativeTakeIds: [keptId, ...kept.alternativeTakeIds.filter((id) => id !== alternativeId)],
  };
  const newAlternative: Clip = {
    ...kept,
    removed: true,
    transitionIn: alternative.transitionIn,
    alternativeTakeIds: [],
  };
  const clips = project.clips.map((clip) => {
    if (clip.id === keptId) return newKept;
    if (clip.id === alternativeId) return newAlternative;
    return clip;
  });
  return withWords({ ...project, clips });
}

export interface Take {
  clip: Clip;
  kept: boolean;
  /** The take's transcribed words, for telling takes apart. */
  text: string;
}

/** The take group of `clipId`: the kept take first, then its alternatives. */
export function takesOf(project: Project, clipId: string): Take[] {
  const owner = takeOwner(project, clipId);
  if (!owner) return [];
  const byId = new Map(project.clips.map((clip) => [clip.id, clip]));
  const members = [owner, ...owner.alternativeTakeIds.map((id) => byId.get(id))];
  return members
    .filter((clip): clip is Clip => clip !== undefined)
    .map((clip) => {
      const sourceWords = project.subtitles.sourceWords?.[clip.sourceId] ?? [];
      const text = sourceWords
        .filter((word) => {
          const middle = (word.start + word.end) / 2;
          return middle >= clip.inSec && middle < clip.outSec;
        })
        .map((word) => word.text)
        .join(" ");
      return { clip, kept: clip.id === owner.id, text };
    });
}

/** Instant transitions (cut, punch-in) have no length; a fade or slide fits inside its clip. */
function transition(
  type: TransitionType,
  durationFrames: number | undefined,
  clip: Clip,
  fps: number,
) {
  if (type === "cut" || type === "punch_in") return { type, durationFrames: 0 };
  const wanted = durationFrames ?? roundHalfEven(fps * TRANSITION_SECONDS);
  return { type, durationFrames: Math.max(0, Math.min(Math.round(wanted), clipFrames(clip, fps))) };
}

export function setTransition(
  project: Project,
  clipId: string,
  type: TransitionType,
  durationFrames?: number,
): Project {
  return updateClip(project, clipId, (clip) => ({
    ...clip,
    transitionIn: transition(type, durationFrames, clip, project.fps),
  }));
}

/** One transition type for every cut: all kept clips but the first, at the default length. */
export function applyTransitionPreset(project: Project, type: TransitionType): Project {
  const first = project.clips.find((clip) => !clip.removed);
  return updateClips(project, (clip) =>
    clip.removed || clip === first
      ? clip
      : { ...clip, transitionIn: transition(type, undefined, clip, project.fps) },
  );
}

/** Replace the text of `timeline words[fromIndex:toIndex]`; see `editSubtitleText`. */
export function editSubtitles(
  project: Project,
  fromIndex: number,
  toIndex: number,
  text: string,
): Project {
  return editSubtitleText(withWords(project), fromIndex, toIndex, text);
}

export function setSubtitleStyle(project: Project, changes: Partial<SubtitleStyle>): Project {
  const style = { ...project.subtitles.style, ...changes };
  style.fontSize = Math.max(1, Math.round(style.fontSize));
  style.maxWordsPerLine = Math.max(1, Math.round(style.maxWordsPerLine));
  return { ...project, subtitles: { ...project.subtitles, style } };
}
