import type { Project, SourceWord } from "../types";
import { remapWords } from "./remap";

/**
 * Replace the words' texts with `text`, keeping their timing; mirrors the backend's
 * `retime_words`. With the same number of words each one keeps its own timing; otherwise the
 * span from the first start to the last end is split in proportion to each new word's length.
 */
export function retimeWords(words: readonly SourceWord[], text: string): SourceWord[] {
  const tokens = text.split(/\s+/).filter(Boolean);
  const first = words[0];
  const last = words[words.length - 1];
  if (first === undefined || last === undefined || tokens.length === 0) {
    throw new Error("an edit needs at least one word before and after");
  }
  if (tokens.length === words.length) {
    return words.map((word, index) => ({ ...word, text: tokens[index] as string }));
  }
  const spanStart = first.start;
  const spanEnd = last.end;
  const total = tokens.reduce((sum, token) => sum + token.length, 0);
  let consumed = 0;
  return tokens.map((token) => {
    const start = spanStart + ((spanEnd - spanStart) * consumed) / total;
    consumed += token.length;
    const end = spanStart + ((spanEnd - spanStart) * consumed) / total;
    return { text: token, start, end };
  });
}

/**
 * Replace the text of `subtitles.words[fromIndex:toIndex]` and rebuild the timeline words;
 * mirrors the backend's `edit_subtitle_text`. The edit lands in the source words, so it
 * survives every later clip edit. Throws when the range is not consecutive words of one source.
 */
export function editSubtitleText(
  project: Project,
  fromIndex: number,
  toIndex: number,
  text: string,
): Project {
  const line = project.subtitles.words.slice(fromIndex, toIndex);
  if (line.length === 0) throw new Error("the word range is empty");
  const sourceOf = new Map(project.clips.map((clip) => [clip.id, clip.sourceId]));
  const sources = new Set(line.map((word) => sourceOf.get(word.clipId)));
  const indexes = line.map((word) => word.wordIndex);
  const [sourceId] = sources;
  if (sources.size !== 1 || sourceId === undefined || indexes.some((index) => index == null)) {
    throw new Error("an edited line must come from one source");
  }
  const known = indexes as number[];
  const first = Math.min(...known);
  const last = Math.max(...known);
  const sorted = [...known].sort((a, b) => a - b);
  if (sorted.some((index, position) => index !== first + position)) {
    throw new Error("an edited line must be consecutive words");
  }
  const sourceWords = project.subtitles.sourceWords ?? {};
  const stored = sourceWords[sourceId] ?? [];
  if (last >= stored.length) throw new Error("the line does not match the stored source words");
  const replaced = [
    ...stored.slice(0, first),
    ...retimeWords(stored.slice(first, last + 1), text),
    ...stored.slice(last + 1),
  ];
  const nextSourceWords = { ...sourceWords, [sourceId]: replaced };
  return {
    ...project,
    subtitles: {
      ...project.subtitles,
      sourceWords: nextSourceWords,
      words: remapWords(project.clips, nextSourceWords, project.fps),
    },
  };
}
