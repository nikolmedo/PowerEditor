import type { Clip, Project } from "@powereditor/composition";
import { describe, expect, it } from "vitest";
import fixture from "../../packages/composition/test/fixtures/subtitles.json";
import {
  applyTransitionPreset,
  editSubtitles,
  setClipSpeed,
  setClipVolume,
  setRemoved,
  setSubtitleStyle,
  setTransition,
  swapTake,
  takesOf,
  trimClip,
} from "../src/edit/operations";
import { PROJECT } from "./fixtures/reviewProject";

const SUBTITLED = fixture.project as Project;

const clip = (project: Project, id: string): Clip => {
  const found = project.clips.find((candidate) => candidate.id === id);
  if (!found) throw new Error(`no clip ${id}`);
  return found;
};
const words = (project: Project) =>
  project.subtitles.words.map((word) => [word.text, word.startFrame, word.endFrame, word.clipId]);

describe("swapTake", () => {
  const swapped = swapTake(PROJECT, "k1", "r1");

  it("keeps the alternative in the old take's place and moves the take list to it", () => {
    expect(swapped.clips.map((c) => [c.id, c.removed])).toEqual([
      ["r1", false],
      ["k1", true],
      ["k2", false],
      ["r2", true],
      ["k3", false],
    ]);
    expect(clip(swapped, "r1").alternativeTakeIds).toEqual(["k1"]);
    expect(clip(swapped, "k1").alternativeTakeIds).toEqual([]);
  });

  it("carries the incoming transition to the newly kept take", () => {
    const faded = setTransition(PROJECT, "k1", "fade", 9);
    const result = swapTake(faded, "k1", "r1");
    expect(clip(result, "r1").transitionIn).toEqual({ type: "fade", durationFrames: 9 });
    expect(clip(result, "k1").transitionIn).toEqual({ type: "cut", durationFrames: 0 });
  });

  it("ignores a clip that is not one of the take's alternatives", () => {
    expect(swapTake(PROJECT, "k1", "k2")).toBe(PROJECT);
  });
});

describe("trimClip", () => {
  it("moves an edge by the step and clamps it to the start of the file", () => {
    expect(clip(trimClip(PROJECT, "k2", "start", 0.1), "k2").inSec).toBe(0.1);
    expect(trimClip(PROJECT, "k2", "start", -0.1)).toBe(PROJECT);
  });

  it("rounds away float noise from repeated steps", () => {
    let project = PROJECT;
    for (let step = 0; step < 3; step += 1) project = trimClip(project, "k3", "start", 0.1);
    expect(clip(project, "k3").inSec).toBe(5.3);
  });

  it("keeps a minimum length and never extends past the known end of the file", () => {
    const short = trimClip(PROJECT, "k3", "end", -5);
    expect(clip(short, "k3").outSec).toBe(5.1);
    // Source "a" is known up to 6 s (k3's out point): the end cannot grow past it.
    expect(trimClip(PROJECT, "k3", "end", 0.1)).toBe(PROJECT);
    expect(clip(trimClip(PROJECT, "k1", "end", 0.1), "k1").outSec).toBe(2.1);
  });
});

describe("setRemoved", () => {
  it("removes and restores a clip", () => {
    const removed = setRemoved(PROJECT, "k2", true);
    expect(clip(removed, "k2").removed).toBe(true);
    expect(clip(setRemoved(removed, "k2", false), "k2").removed).toBe(false);
    expect(setRemoved(PROJECT, "k2", false)).toBe(PROJECT);
  });
});

describe("clip speed and volume", () => {
  it("clamps to the ranges the backend accepts", () => {
    expect(clip(setClipSpeed(PROJECT, "k2", 3), "k2").speed).toBe(2);
    expect(clip(setClipSpeed(PROJECT, "k2", 0.1), "k2").speed).toBe(0.5);
    expect(clip(setClipVolume(PROJECT, "k2", -1), "k2").volume).toBe(0);
    expect(clip(setClipVolume(PROJECT, "k2", 1.5), "k2").volume).toBe(1.5);
  });
});

describe("transitions", () => {
  it("makes cut and punch-in instant and caps a timed transition at the clip length", () => {
    expect(clip(setTransition(PROJECT, "k2", "punch_in", 12), "k2").transitionIn).toEqual({
      type: "punch_in",
      durationFrames: 0,
    });
    // k3 lasts 15 frames (1 s at 2x).
    expect(clip(setTransition(PROJECT, "k3", "slide", 40), "k3").transitionIn).toEqual({
      type: "slide",
      durationFrames: 15,
    });
  });

  it("applies a preset to every kept clip but the first, with the default duration", () => {
    const faded = applyTransitionPreset(PROJECT, "fade");
    expect(
      faded.clips.map((c) => [c.id, c.transitionIn.type, c.transitionIn.durationFrames]),
    ).toEqual([
      ["k1", "cut", 0],
      ["r1", "cut", 0],
      ["k2", "fade", 9],
      ["r2", "cut", 0],
      ["k3", "fade", 9],
    ]);
  });
});

describe("subtitles stay in sync with clip edits (backend fixture numbers)", () => {
  it("follows a speed change", () => {
    const edited = setClipSpeed(SUBTITLED, "c1", 1.5);
    expect(words(edited).slice(0, 4)).toEqual([
      ["Hola", 2, 8, "c1"],
      ["a", 9, 11, "c1"],
      ["todos.", 12, 23, "c1"],
      ["Ahora", 23, 29, "c3"],
    ]);
    expect(words(edited).at(-1)).toEqual(["aquí", 88, 97, "c4"]);
  });

  it("uses the words of the newly chosen take after a swap", () => {
    const edited = swapTake(SUBTITLED, "c3", "c2");
    expect(edited.subtitles.words.filter((w) => w.clipId === "c2").map((w) => w.text)).toEqual([
      "corta",
      "uh",
    ]);
    expect(edited.subtitles.words.some((w) => w.clipId === "c3")).toBe(false);
    expect(words(edited)[5]).toEqual(["Nuevo", 64, 76, "c4"]);
  });

  it("keeps a text edit through a later speed change", () => {
    const rebuilt = setClipSpeed(SUBTITLED, "c3", 1.5);
    const edited = editSubtitles(rebuilt, 3, 6, "Ahora esto vuela");
    const later = setClipSpeed(edited, "c3", 1);
    expect(later.subtitles.words.slice(3, 6).map((w) => w.text)).toEqual([
      "Ahora",
      "esto",
      "vuela",
    ]);
  });
});

describe("setSubtitleStyle", () => {
  it("keeps sizes and word limits positive whole numbers", () => {
    const styled = setSubtitleStyle(PROJECT, {
      fontSize: 0,
      maxWordsPerLine: 2.6,
      position: "top",
    });
    expect(styled.subtitles.style).toMatchObject({
      fontSize: 1,
      maxWordsPerLine: 3,
      position: "top",
    });
  });
});

describe("takesOf", () => {
  it("lists the kept take first, then its alternatives with their words", () => {
    const takes = takesOf(SUBTITLED, "c3");
    expect(takes.map((take) => [take.clip.id, take.kept, take.text])).toEqual([
      ["c3", true, "Ahora Esto va"],
      ["c2", false, "corta uh"],
    ]);
    expect(takesOf(SUBTITLED, "c2").map((take) => take.clip.id)).toEqual(["c3", "c2"]);
  });
});
