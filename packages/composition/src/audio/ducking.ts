import type { AudioTrack, Project } from "../types";

/**
 * Music ducking and voice gains for the Player preview, mirroring the backend
 * (`render/ducking.py` and `render/audio_mix.py`); `test/fixtures/audio.json` pins both.
 *
 * Remotion applies volume once per video frame, so the preview follows the envelope in
 * frame steps. Exports are rendered muted and their audio is mixed by ffmpeg with
 * sample-accurate envelopes: the render is authoritative, the preview is close.
 */

export const ATTACK_S = 0.15;
export const RELEASE_S = 0.4;
export const FADE_IN_S = 1.0;
export const FADE_OUT_S = 2.0;
export const MAX_SOURCE_GAIN_DB = 12;
/** `AudioTrack.duckingDb` when a project does not set it (the backend default). */
export const DEFAULT_DUCKING_DB = 12;
/** EBU R128 absolute gate: sources at or below it count as silent. */
export const SILENT_LUFS = -70;

/** Timeline seconds `[start, end]` with speech. */
export type Interval = [number, number];

const clip01 = (value: number) => Math.min(1, Math.max(0, value));
const dbToGain = (db: number) => 10 ** (db / 20);

/** Words in timeline frames, merged into speech intervals across gaps shorter than a duck. */
export function speechIntervals(
  words: readonly { startFrame: number; endFrame: number }[],
  fps: number,
): Interval[] {
  const sorted = [...words].sort((a, b) => a.startFrame - b.startFrame || a.endFrame - b.endFrame);
  const merged: Interval[] = [];
  for (const word of sorted) {
    const start = word.startFrame / fps;
    const end = word.endFrame / fps;
    const last = merged.at(-1);
    if (last && start - last[1] < ATTACK_S + RELEASE_S) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  return merged;
}

/** 0 away from speech, 1 during it, with linear attack and release ramps. */
export function duckFraction(t: number, intervals: readonly Interval[]): number {
  let fraction = 0;
  for (const [start, end] of intervals) {
    fraction +=
      clip01((t - start + ATTACK_S) / ATTACK_S) * clip01((end + RELEASE_S - t) / RELEASE_S);
  }
  return fraction;
}

/** Linear fade-in and fade-out of the music, each at most half the timeline. */
export function fadeGain(t: number, duration: number): number {
  const fadeIn = Math.min(FADE_IN_S, duration / 2);
  const fadeOut = Math.min(FADE_OUT_S, duration / 2);
  const gainIn = fadeIn > 0 ? clip01(t / fadeIn) : 1;
  const gainOut = fadeOut > 0 ? clip01((duration - t) / fadeOut) : 1;
  return gainIn * gainOut;
}

export interface MusicLevel {
  volume: number;
  /** How far the music drops under speech; 0 disables ducking. */
  duckingDb: number;
  /** Timeline length in seconds. */
  duration: number;
}

export function musicGain(t: number, intervals: readonly Interval[], level: MusicLevel): number {
  const ducked = dbToGain(-level.duckingDb * duckFraction(t, intervals));
  return level.volume * fadeGain(t, level.duration) * ducked;
}

/** Gain in dB per source that brings it to the mean loudness of the audible sources. */
export function sourceGainsDb(loudness: Readonly<Record<string, number>>): Record<string, number> {
  const audible = Object.values(loudness).filter((lufs) => lufs > SILENT_LUFS);
  const reference = audible.reduce((sum, lufs) => sum + lufs, 0) / (audible.length || 1);
  return Object.fromEntries(
    Object.entries(loudness).map(([id, lufs]) => [
      id,
      audible.length === 0 || lufs <= SILENT_LUFS
        ? 0
        : Math.max(-MAX_SOURCE_GAIN_DB, Math.min(MAX_SOURCE_GAIN_DB, reference - lufs)),
    ]),
  );
}

/**
 * Linear voice gain per source id: the voice track's volume and the optional source match.
 * A muted voice track gives every source zero gain.
 */
export function voiceGains(project: Project): Map<string, number> {
  const voice = project.audioTracks.find((track) => track.kind === "voice");
  const volume = voice?.muted ? 0 : (voice?.volume ?? 1);
  const gains = project.normalizeSources
    ? sourceGainsDb(Object.fromEntries(project.sources.map((s) => [s.id, s.loudnessLufs])))
    : {};
  return new Map(project.sources.map((s) => [s.id, volume * dbToGain(gains[s.id] ?? 0)]));
}

/** The music track the preview plays: the first one with a file, unless it is muted. */
export function musicTrack(project: Project): AudioTrack | undefined {
  const track = project.audioTracks.find((t) => t.kind === "music" && t.sourcePath);
  return track?.muted ? undefined : track;
}
