import { roundHalfEven } from "../timeline";
import type { TimelineWord } from "../types";

/** A pause at least this long between two words starts a new line (backend: same value). */
export const LINE_PAUSE_SECONDS = 0.4;
/** A line stays this long after its last word unless the next line starts first. */
export const LINE_HOLD_SECONDS = 0.5;
const SENTENCE_END = /[.!?…]$/;

export interface SubtitleLine {
  words: TimelineWord[];
  text: string;
  startFrame: number;
  /** First frame the line is no longer on screen. */
  endFrame: number;
}

export interface LineOptions {
  maxWordsPerLine: number;
  fps: number;
  durationInFrames?: number;
}

function breaksBefore(
  line: readonly TimelineWord[],
  word: TimelineWord,
  limit: number,
  pause: number,
): boolean {
  const previous = line[line.length - 1];
  if (previous === undefined) return true;
  return (
    line.length >= limit ||
    word.clipId !== previous.clipId ||
    word.startFrame - previous.endFrame >= pause ||
    SENTENCE_END.test(previous.text)
  );
}

/**
 * Group timeline words into on-screen lines; mirrors the backend's `group_lines`. A line
 * ends at the word limit, at a cut between clips, at a pause and after sentence punctuation.
 */
export function groupLines(words: readonly TimelineWord[], options: LineOptions): SubtitleLine[] {
  const pause = roundHalfEven(LINE_PAUSE_SECONDS * options.fps);
  const hold = roundHalfEven(LINE_HOLD_SECONDS * options.fps);
  const groups: TimelineWord[][] = [];
  for (const word of words) {
    const current = groups[groups.length - 1];
    if (current && !breaksBefore(current, word, options.maxWordsPerLine, pause)) {
      current.push(word);
    } else {
      groups.push([word]);
    }
  }
  return groups.map((group, index) => {
    const first = group[0] as TimelineWord;
    const last = group[group.length - 1] as TimelineWord;
    let endFrame = last.endFrame + hold;
    const next = groups[index + 1]?.[0];
    if (next) endFrame = Math.min(endFrame, next.startFrame);
    if (options.durationInFrames !== undefined) {
      endFrame = Math.min(endFrame, options.durationInFrames);
    }
    return {
      words: group,
      text: group.map((word) => word.text).join(" "),
      startFrame: first.startFrame,
      endFrame: Math.max(endFrame, first.startFrame),
    };
  });
}

/** The line on screen at `frame`, if any. */
export function activeLine(
  lines: readonly SubtitleLine[],
  frame: number,
): SubtitleLine | undefined {
  return lines.find((line) => line.startFrame <= frame && frame < line.endFrame);
}

/** Index of the last word of `line` that has started by `frame`; -1 before the first. */
export function activeWordIndex(line: SubtitleLine, frame: number): number {
  let active = -1;
  line.words.forEach((word, index) => {
    if (word.startFrame <= frame) active = index;
  });
  return active;
}
