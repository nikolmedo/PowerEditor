import type { AudioTrack, Project } from "@powereditor/composition";

/**
 * Pure audio edits (see `operations.ts` for the conventions): track volume and mute, ducking, the
 * music track and source loudness matching. Values are clamped to the backend's ranges.
 */

export const TRACK_VOLUME_RANGE = [0, 2] as const;
export const DUCKING_DB_RANGE = [0, 30] as const;
/** A new music track sits under the voice and ducks under speech. */
export const MUSIC_DEFAULTS = { volume: 0.3, duckingEnabled: true, duckingDb: 12 } as const;

const clamp = (value: number, [low, high]: readonly [number, number]) =>
  Math.min(high, Math.max(low, value));

function updateTrack(
  project: Project,
  trackId: string,
  change: (track: AudioTrack) => AudioTrack,
): Project {
  let changed = false;
  const audioTracks = project.audioTracks.map((track) => {
    if (track.id !== trackId) return track;
    const next = change(track);
    const same = (Object.keys(next) as (keyof AudioTrack)[]).every(
      (key) => next[key] === track[key],
    );
    if (same) return track;
    changed = true;
    return next;
  });
  return changed ? { ...project, audioTracks } : project;
}

export function setTrackVolume(project: Project, trackId: string, volume: number): Project {
  return updateTrack(project, trackId, (track) => ({
    ...track,
    volume: clamp(volume, TRACK_VOLUME_RANGE),
  }));
}

/** A muted track keeps its volume; unmuting brings it back at the same level. */
export function setTrackMuted(project: Project, trackId: string, muted: boolean): Project {
  return updateTrack(project, trackId, (track) =>
    (track.muted ?? false) === muted ? track : { ...track, muted },
  );
}

export function setDucking(
  project: Project,
  trackId: string,
  { enabled, db }: { enabled?: boolean; db?: number },
): Project {
  return updateTrack(project, trackId, (track) => ({
    ...track,
    ...(enabled === undefined ? {} : { duckingEnabled: enabled }),
    ...(db === undefined ? {} : { duckingDb: clamp(db, DUCKING_DB_RANGE) }),
  }));
}

export const musicTrack = (project: Project) =>
  project.audioTracks.find((track) => track.kind === "music");

/** Use `fileName` (a file in the project's media folder) as the music; a replacement keeps
 * the current track's volume and ducking. */
export function setMusic(project: Project, fileName: string): Project {
  const current = musicTrack(project);
  if (current) {
    return updateTrack(project, current.id, (track) => ({ ...track, sourcePath: fileName }));
  }
  const added: AudioTrack = { id: "music", kind: "music", sourcePath: fileName, ...MUSIC_DEFAULTS };
  return { ...project, audioTracks: [...project.audioTracks, added] };
}

export function removeMusic(project: Project): Project {
  const audioTracks = project.audioTracks.filter((track) => track.kind !== "music");
  return audioTracks.length === project.audioTracks.length ? project : { ...project, audioTracks };
}

export function setNormalizeSources(project: Project, normalizeSources: boolean): Project {
  return (project.normalizeSources ?? false) === normalizeSources
    ? project
    : { ...project, normalizeSources };
}
