import type { Project } from "@powereditor/composition";
import { describe, expect, it } from "vitest";
import {
  MUSIC_DEFAULTS,
  removeMusic,
  setDucking,
  setMusic,
  setNormalizeSources,
  setTrackMuted,
  setTrackVolume,
} from "../src/edit/audio";
import {
  applyGradeToAll,
  clearClipColor,
  resetColorCorrection,
  setClipColor,
  setClipColorPreset,
  setGrade,
  setGradePreset,
} from "../src/edit/color";
import { PROJECT } from "./fixtures/reviewProject";

const track = (project: Project, id: string) =>
  project.audioTracks.find((candidate) => candidate.id === id);
const clip = (project: Project, id: string) =>
  project.clips.find((candidate) => candidate.id === id);
const WITHOUT_MUSIC: Project = { ...PROJECT, audioTracks: [PROJECT.audioTracks[0]] } as Project;
const CORRECTED: Project = {
  ...PROJECT,
  sources: PROJECT.sources.map((source, index) =>
    index === 0
      ? { ...source, colorCorrection: { redGain: 1.1, greenGain: 1, blueGain: 0.9 } }
      : source,
  ),
};

describe("audio edits", () => {
  it("clamps track volume and leaves the project untouched when nothing changes", () => {
    expect(track(setTrackVolume(PROJECT, "voice", 3), "voice")?.volume).toBe(2);
    expect(track(setTrackVolume(PROJECT, "m1", -1), "m1")?.volume).toBe(0);
    expect(setTrackVolume(PROJECT, "voice", 1)).toBe(PROJECT);
  });

  it("switches ducking and clamps its depth", () => {
    const off = setDucking(PROJECT, "m1", { enabled: false });
    expect(track(off, "m1")?.duckingEnabled).toBe(false);
    expect(track(setDucking(PROJECT, "m1", { db: 50 }), "m1")?.duckingDb).toBe(30);
    expect(setDucking(PROJECT, "m1", { enabled: true })).toBe(PROJECT);
  });

  it("adds a music track with defaults, and a replacement keeps the track's settings", () => {
    const added = setMusic(WITHOUT_MUSIC, "music-0a1b2c3d.mp3");
    expect(added.audioTracks.at(-1)).toEqual({
      id: "music",
      kind: "music",
      sourcePath: "music-0a1b2c3d.mp3",
      ...MUSIC_DEFAULTS,
    });

    const replaced = setMusic(PROJECT, "music-ffff0000.wav");
    expect(track(replaced, "m1")).toEqual({
      ...track(PROJECT, "m1"),
      sourcePath: "music-ffff0000.wav",
    });
    expect(replaced.audioTracks).toHaveLength(2);
  });

  it("removes the music track and nothing else", () => {
    expect(removeMusic(PROJECT).audioTracks.map((t) => t.id)).toEqual(["voice"]);
    expect(removeMusic(WITHOUT_MUSIC)).toBe(WITHOUT_MUSIC);
  });

  it("mutes and unmutes a track, and leaves the project untouched when nothing changes", () => {
    const muted = setTrackMuted(PROJECT, "voice", true);
    expect(track(muted, "voice")?.muted).toBe(true);
    expect(track(muted, "m1")).toBe(track(PROJECT, "m1"));
    expect(track(setTrackMuted(muted, "voice", false), "voice")?.muted).toBe(false);
    expect(setTrackMuted(PROJECT, "voice", false)).toBe(PROJECT);
    expect(setTrackMuted(muted, "voice", true)).toBe(muted);
    expect(setTrackMuted(PROJECT, "missing", true)).toBe(PROJECT);
  });

  it("turns source loudness matching on and off", () => {
    expect(setNormalizeSources(PROJECT, true).normalizeSources).toBe(true);
    expect(setNormalizeSources(PROJECT, false)).toBe(PROJECT);
  });
});

describe("color edits", () => {
  it("sets a preset's values on the global grade", () => {
    expect(setGradePreset(PROJECT, "warm").colorGrade).toEqual({
      preset: "warm",
      brightness: 1,
      contrast: 1,
      saturation: 1.1,
      temperature: 0.35,
    });
  });

  it("clamps slider values and keeps the preset label", () => {
    const grade = setGrade(setGradePreset(PROJECT, "cool"), { temperature: -4, brightness: 1.25 });
    expect(grade.colorGrade).toMatchObject({ preset: "cool", temperature: -1, brightness: 1.25 });
  });

  it("overrides one clip only and merges further changes into its override", () => {
    const once = setClipColor(PROJECT, "k2", { saturation: 0.5 });
    const twice = setClipColor(once, "k2", { contrast: 1.2 });
    expect(clip(twice, "k2")?.colorOverride).toEqual({ saturation: 0.5, contrast: 1.2 });
    expect(clip(twice, "k1")?.colorOverride).toBeUndefined();
    expect(clip(setClipColorPreset(PROJECT, "k1", "bw"), "k1")?.colorOverride).toEqual({
      preset: "bw",
      brightness: 1,
      contrast: 1.1,
      saturation: 0,
      temperature: 0,
    });
  });

  it("applies the global grade to every clip by clearing their overrides", () => {
    const overridden = setClipColor(PROJECT, "k2", { saturation: 0.5 });
    const cleared = applyGradeToAll(overridden);
    expect(cleared.clips.every((c) => c.colorOverride == null)).toBe(true);
    expect(applyGradeToAll(PROJECT)).toBe(PROJECT);
  });

  it("lets one clip follow the global grade again", () => {
    const overridden = setClipColor(PROJECT, "k2", { saturation: 0.5 });
    expect(clip(clearClipColor(overridden, "k2"), "k2")?.colorOverride).toBeNull();
    expect(clearClipColor(PROJECT, "k2")).toBe(PROJECT);
  });

  it("resets the automatic match of one source", () => {
    const reset = resetColorCorrection(CORRECTED, "a");
    expect(reset.sources[0]?.colorCorrection).toBeNull();
    expect(resetColorCorrection(reset, "a")).toBe(reset);
  });
});
