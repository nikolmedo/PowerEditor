import { SAFE_AREAS } from "../subtitles/styles";
import type { Project } from "../types";

/** Pixel margins that keep graphics clear of platform UI and of the subtitles. */
export interface Insets {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** Room a subtitle block takes: two lines at 1.2 line height plus half a line of gap. */
const SUBTITLE_BAND_LINES = 2.9;

/**
 * The preset's safe area in pixels, grown by the subtitle band on the side the subtitles sit,
 * so a bottom graphic (a lower third, a call to action) stays above bottom subtitles and a
 * top one stays under top subtitles. Centered subtitles reserve nothing: graphics go to the
 * top or bottom anyway, and the subtitles are drawn above every graphic.
 */
export function overlayInsets(project: Project, width: number, height: number): Insets {
  const area = SAFE_AREAS[project.preset];
  const { position, fontSize } = project.subtitles.style;
  const band = Math.round(fontSize * SUBTITLE_BAND_LINES);
  return {
    top: Math.round(area.top * height) + (position === "top" ? band : 0),
    bottom: Math.round(area.bottom * height) + (position === "bottom" ? band : 0),
    left: Math.round(area.left * width),
    right: Math.round(area.right * width),
  };
}

/** Size unit of the templates: 1 at 1080 p (the short side), so both presets match. */
export function overlayUnit(width: number, height: number): number {
  return Math.min(width, height) / 1080;
}
