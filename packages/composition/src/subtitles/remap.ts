import { clipFrames, roundHalfEven } from "../timeline";
import type { Clip, Project, SourceWord, TimelineWord } from "../types";

function overlap(word: SourceWord, clip: Clip): number {
  return Math.min(word.end, clip.outSec) - Math.max(word.start, clip.inSec);
}

/** The clip of the word's source that holds most of it (the first one on a tie). */
function owner(word: SourceWord, clips: readonly Clip[]): Clip | undefined {
  let best: Clip | undefined;
  let bestOverlap = 0;
  for (const clip of clips) {
    const amount = overlap(word, clip);
    if (amount > bestOverlap) {
      best = clip;
      bestOverlap = amount;
    }
  }
  return best;
}

/**
 * Source-time words → timeline frames; mirrors the backend's `remap_words`.
 *
 * Every clip of the word's source competes, removed ones included, so words of a take that
 * was not chosen are dropped. Words are clamped to their clip and rounded like clip frames.
 */
export function remapWords(
  clips: readonly Clip[],
  wordsBySource: Readonly<Record<string, readonly SourceWord[]>>,
  fps: number,
): TimelineWord[] {
  const owners = new Map<string, string>();
  for (const [sourceId, words] of Object.entries(wordsBySource)) {
    const candidates = clips.filter((clip) => clip.sourceId === sourceId);
    words.forEach((word, index) => {
      const found = owner(word, candidates);
      if (found && !found.removed) owners.set(`${sourceId}:${index}`, found.id);
    });
  }
  const timeline: TimelineWord[] = [];
  let offset = 0;
  for (const clip of clips) {
    if (clip.removed) continue;
    const length = clipFrames(clip, fps);
    (wordsBySource[clip.sourceId] ?? []).forEach((word, index) => {
      if (owners.get(`${clip.sourceId}:${index}`) !== clip.id) return;
      const start = (Math.max(word.start, clip.inSec) - clip.inSec) / clip.speed;
      const end = (Math.min(word.end, clip.outSec) - clip.inSec) / clip.speed;
      const startFrame = offset + Math.min(roundHalfEven(start * fps), length);
      const endFrame = offset + Math.min(roundHalfEven(end * fps), length);
      timeline.push({
        text: word.text,
        startFrame,
        endFrame: Math.max(endFrame, startFrame),
        clipId: clip.id,
        wordIndex: index,
      });
    });
    offset += length;
  }
  return timeline;
}

/**
 * The words to show: remapped live from the stored source words, so the Player stays in
 * sync while clips are edited; projects without source words use their saved words.
 */
export function timelineWords(project: Project): TimelineWord[] {
  const sourceWords = project.subtitles.sourceWords ?? {};
  if (Object.keys(sourceWords).length === 0) return project.subtitles.words;
  return remapWords(project.clips, sourceWords, project.fps);
}
