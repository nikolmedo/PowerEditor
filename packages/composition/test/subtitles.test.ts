import { describe, expect, it } from "vitest";

import { activeLine, activeWordIndex, groupLines } from "../src/subtitles/lines";
import { remapWords, timelineWords } from "../src/subtitles/remap";
import type { Project } from "../src/types";
import fixture from "./fixtures/subtitles.json";

const project = fixture.project as Project;
const sourceWords = project.subtitles.sourceWords ?? {};

describe("remapWords", () => {
  it("matches the words the backend computes for the shared fixture", () => {
    expect(remapWords(project.clips, sourceWords, project.fps)).toEqual(fixture.expectedWords);
  });

  it("follows a speed change of an earlier clip", () => {
    const clips = project.clips.map((clip) => (clip.id === "c1" ? { ...clip, speed: 1.5 } : clip));
    const words = remapWords(clips, sourceWords, project.fps);
    expect(words.slice(0, 4).map((w) => [w.text, w.startFrame, w.endFrame])).toEqual([
      ["Hola", 2, 8],
      ["a", 9, 11],
      ["todos.", 12, 23],
      ["Ahora", 23, 29],
    ]);
  });

  it("uses the words of the newly chosen take after a take switch", () => {
    const clips = project.clips.map((clip) =>
      clip.id === "c2" || clip.id === "c3" ? { ...clip, removed: !clip.removed } : clip,
    );
    const words = remapWords(clips, sourceWords, project.fps);
    expect(words.filter((w) => w.clipId === "c2").map((w) => w.text)).toEqual(["corta", "uh"]);
    expect(words.some((w) => w.clipId === "c3")).toBe(false);
  });
});

describe("timelineWords", () => {
  it("remaps stored source words instead of trusting saved timeline words", () => {
    const stale = { ...project, subtitles: { ...project.subtitles, words: [] } };
    expect(timelineWords(stale)).toEqual(fixture.expectedWords);
  });

  it("falls back to the saved timeline words of a project without source words", () => {
    const saved = fixture.expectedWords.slice(0, 2);
    const legacy = { ...project, subtitles: { style: project.subtitles.style, words: saved } };
    expect(timelineWords(legacy)).toEqual(saved);
  });
});

describe("groupLines", () => {
  it("matches the lines the backend computes for the shared fixture", () => {
    const lines = groupLines(fixture.expectedWords, {
      maxWordsPerLine: 3,
      fps: 30,
      durationInFrames: 114,
    });
    expect(lines.map(({ text, startFrame, endFrame }) => ({ text, startFrame, endFrame }))).toEqual(
      fixture.expectedLines,
    );
  });

  it("breaks lines at the word limit and holds the last one", () => {
    const lines = groupLines(fixture.expectedWords, { maxWordsPerLine: 2, fps: 30 });
    expect(lines.map((line) => line.text)).toEqual([
      "Hola a",
      "todos.",
      "Ahora Esto",
      "va",
      "Nuevo tema",
      "aquí",
    ]);
    expect(lines.at(-1)?.endFrame).toBe(123);
  });
});

describe("active line and word", () => {
  const lines = groupLines(fixture.expectedWords, {
    maxWordsPerLine: 3,
    fps: 30,
    durationInFrames: 114,
  });

  it("shows a line from its first word until it ends", () => {
    expect(
      [2, 3, 33, 34, 96, 98, 99].map((frame) => activeLine(lines, frame)?.text ?? null),
    ).toEqual([null, "Hola a todos.", "Hola a todos.", "Ahora Esto va", null, null, "aquí"]);
  });

  it("keeps the last started word active through the gaps between words", () => {
    const [first] = lines;
    if (first === undefined) throw new Error("fixture has no lines");
    expect([3, 12, 13, 14, 30].map((frame) => activeWordIndex(first, frame))).toEqual([
      0, 0, 0, 1, 2,
    ]);
  });
});
