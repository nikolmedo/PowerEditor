export type * from "./types";
export { COMPOSITION_ID } from "./compositionId";
export { ProjectVideo, type ProjectVideoProps } from "./ProjectVideo";
export { MediaResolverContext, mediaUrl, type MediaResolver } from "./clips/media";
export {
  clipFrames,
  roundHalfEven,
  timelineLayout,
  type ClipPlacement,
  type TimelineLayout,
} from "./timeline";
export { videoMetadata, type VideoMetadata } from "./metadata";
export {
  editSubtitleText,
  groupLines,
  remapWords,
  retimeWords,
  timelineWords,
  type SubtitleLine,
} from "./subtitles";
export {
  DEFAULT_DUCKING_DB,
  musicGain,
  sourceGainsDb,
  speechIntervals,
  voiceGains,
  type Interval,
} from "./audio/ducking";
export {
  clipColorMatrix,
  gradeMatrix,
  PRESET_VALUES,
  resolveGrade,
  type GradeValues,
} from "./color";
