import {
  PRESET_VALUES,
  type Clip,
  type ColorGrade,
  type ColorGradeOverride,
  type ColorPreset,
  type GradeValues,
  type Project,
} from "@powereditor/composition";

/**
 * Pure color edits (see `operations.ts` for the conventions). The global grade applies to every
 * clip; a clip's `colorOverride` replaces the values it sets; a source's `colorCorrection` is
 * the automatic match computed when the draft was built.
 */

export const GRADE_RANGES: Record<keyof GradeValues, readonly [number, number]> = {
  brightness: [0, 2],
  contrast: [0, 2],
  saturation: [0, 2],
  temperature: [-1, 1],
};
export const GRADE_KEYS = Object.keys(GRADE_RANGES) as (keyof GradeValues)[];
export const COLOR_PRESETS = Object.keys(PRESET_VALUES) as ColorPreset[];

type GradeChanges = Partial<GradeValues>;

function clamped(changes: GradeChanges): GradeChanges {
  return Object.fromEntries(
    Object.entries(changes).map(([key, value]) => {
      const [low, high] = GRADE_RANGES[key as keyof GradeValues];
      return [key, Math.min(high, Math.max(low, value))];
    }),
  );
}

const sameValues = <T extends object>(a: T, b: T) =>
  (Object.keys({ ...a, ...b }) as (keyof T)[]).every((key) => a[key] === b[key]);

function withGrade(project: Project, colorGrade: ColorGrade): Project {
  return sameValues(colorGrade, project.colorGrade) ? project : { ...project, colorGrade };
}

export function setGradePreset(project: Project, preset: ColorPreset): Project {
  return withGrade(project, { preset, ...PRESET_VALUES[preset] });
}

/** Slider changes keep the preset label: it names where the values started. */
export function setGrade(project: Project, changes: GradeChanges): Project {
  return withGrade(project, { ...project.colorGrade, ...clamped(changes) });
}

function updateClipColor(
  project: Project,
  clipId: string,
  change: (override: ColorGradeOverride) => ColorGradeOverride | null,
): Project {
  let changed = false;
  const clips = project.clips.map((clip): Clip => {
    if (clip.id !== clipId) return clip;
    const colorOverride = change(clip.colorOverride ?? {});
    if (colorOverride && clip.colorOverride && sameValues(colorOverride, clip.colorOverride)) {
      return clip;
    }
    changed = true;
    return { ...clip, colorOverride };
  });
  return changed ? { ...project, clips } : project;
}

export function setClipColor(project: Project, clipId: string, changes: GradeChanges): Project {
  return updateClipColor(project, clipId, (override) => ({ ...override, ...clamped(changes) }));
}

export function setClipColorPreset(project: Project, clipId: string, preset: ColorPreset): Project {
  return updateClipColor(project, clipId, () => ({ preset, ...PRESET_VALUES[preset] }));
}

/** The clip follows the global grade again. */
export function clearClipColor(project: Project, clipId: string): Project {
  const target = project.clips.find((clip) => clip.id === clipId);
  if (target?.colorOverride == null) return project;
  return {
    ...project,
    clips: project.clips.map((clip) =>
      clip.id === clipId ? { ...clip, colorOverride: null } : clip,
    ),
  };
}

/** Every clip follows the global grade again. */
export function applyGradeToAll(project: Project): Project {
  if (project.clips.every((clip) => clip.colorOverride == null)) return project;
  return { ...project, clips: project.clips.map((clip) => ({ ...clip, colorOverride: null })) };
}

export function resetColorCorrection(project: Project, sourceId: string): Project {
  const target = project.sources.find((source) => source.id === sourceId);
  if (!target?.colorCorrection) return project;
  return {
    ...project,
    sources: project.sources.map((source) =>
      source.id === sourceId ? { ...source, colorCorrection: null } : source,
    ),
  };
}
