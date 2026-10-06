import { describe, expect, it } from "vitest";

import { remapWords } from "../src/subtitles/remap";
import { editSubtitleText, retimeWords } from "../src/subtitles/retime";
import type { Project } from "../src/types";
import fixture from "./fixtures/subtitles.json";

const base = fixture.project as Project;
const project: Project = {
  ...base,
  subtitles: {
    ...base.subtitles,
    words: remapWords(base.clips, base.subtitles.sourceWords ?? {}, base.fps),
  },
};

describe("retimeWords", () => {
  it("keeps each word's timing when the word count is unchanged", () => {
    const words = [
      { text: "ola", start: 1.0, end: 1.3 },
      { text: "mundo", start: 1.5, end: 2 },
    ];
    expect(retimeWords(words, "Hola mundo!")).toEqual([
      { text: "Hola", start: 1.0, end: 1.3 },
      { text: "mundo!", start: 1.5, end: 2 },
    ]);
  });

  it("spreads a different word count over the span by character length", () => {
    const edited = retimeWords([{ text: "porfavor", start: 2.0, end: 3.0 }], "por favor ya");
    expect(edited.map((word) => word.text)).toEqual(["por", "favor", "ya"]);
    const bounds = edited.map((word) => [word.start, word.end]).flat();
    [2.0, 2.3, 2.3, 2.8, 2.8, 3.0].forEach((value, index) =>
      expect(bounds[index]).toBeCloseTo(value, 9),
    );
  });

  it("rejects an empty edit or selection", () => {
    expect(() => retimeWords([{ text: "a", start: 0, end: 1 }], "   ")).toThrow();
    expect(() => retimeWords([], "hola")).toThrow();
  });
});

describe("editSubtitleText", () => {
  it("matches the backend's text edit for the shared fixture", () => {
    const { fromIndex, toIndex, text } = fixture.textEdit;
    const edited = editSubtitleText(project, fromIndex, toIndex, text);
    expect(edited.subtitles.sourceWords?.["s1"]?.slice(5, 9)).toEqual(
      fixture.textEdit.expectedSourceWords,
    );
    expect(edited.subtitles.words).toEqual(fixture.textEdit.expectedWords);
  });

  it("refuses a line that spans two sources", () => {
    expect(() => editSubtitleText(project, 5, 7, "Mezcla")).toThrow();
  });
});
