import { describe, expect, it } from "vitest";

import {
  duckFraction,
  musicGain,
  sourceGainsDb,
  speechIntervals,
  voiceGains,
  type Interval,
} from "../src/audio/ducking";
import type { Project } from "../src/types";
import fixture from "./fixtures/audio.json";
import projectFixture from "./fixtures/project.json";

const intervals = fixture.speechIntervals as Interval[];
const duration = fixture.durationInFrames / fixture.fps;

describe("speechIntervals", () => {
  it("merges words closer than a release and an attack, like the backend", () => {
    expect(speechIntervals(fixture.words, fixture.fps)).toEqual(intervals);
    expect(speechIntervals([], 30)).toEqual([]);
  });
});

describe("duckFraction", () => {
  it.each(fixture.duckFraction)("at %f s is %f", (t, expected) => {
    expect(duckFraction(t, intervals)).toBeCloseTo(expected, 9);
  });
});

describe("musicGain", () => {
  it.each(fixture.musicGain)("at %f s is %f", (t, expected) => {
    const gain = musicGain(t, intervals, { ...fixture.music, duration });
    expect(gain).toBeCloseTo(expected, 8);
  });

  it("only fades when ducking is off", () => {
    expect(musicGain(1.5, intervals, { volume: 0.5, duckingDb: 0, duration })).toBe(0.5);
  });
});

describe("sourceGainsDb", () => {
  it("brings audible sources to their mean loudness and leaves silence alone", () => {
    expect(sourceGainsDb(fixture.sourceLoudness)).toEqual(fixture.sourceGainDb);
  });

  it("caps the gain", () => {
    expect(sourceGainsDb({ quiet: -40, loud: -10 })).toEqual({ quiet: 12, loud: -12 });
  });
});

describe("voiceGains", () => {
  const base = projectFixture.project as Project;
  const [template] = base.sources;
  if (!template) throw new Error("the fixture has no source");
  const project: Project = {
    ...base,
    sources: [
      { ...template, id: "a", loudnessLufs: -20 },
      { ...template, id: "b", loudnessLufs: -14 },
    ],
    audioTracks: [{ id: "voice", kind: "voice", volume: 0.5, duckingEnabled: false }],
  };

  it("applies the voice track volume, and the source match only when asked", () => {
    expect(voiceGains(project)).toEqual(
      new Map([
        ["a", 0.5],
        ["b", 0.5],
      ]),
    );
    const normalized = voiceGains({ ...project, normalizeSources: true });
    expect(normalized.get("a")).toBeCloseTo(0.5 * 10 ** (3 / 20), 9);
    expect(normalized.get("b")).toBeCloseTo(0.5 * 10 ** (-3 / 20), 9);
  });
});
