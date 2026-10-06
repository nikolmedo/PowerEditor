import inter400 from "@fontsource/inter/files/inter-latin-400-normal.woff2";
import inter700 from "@fontsource/inter/files/inter-latin-700-normal.woff2";
import inter800 from "@fontsource/inter/files/inter-latin-800-normal.woff2";
import { loadFont } from "@remotion/fonts";

/** Inter (SIL Open Font License), bundled from `@fontsource/inter`: no network at render. */
export const SUBTITLE_FONT_FAMILY = "Inter";

const FILES: Record<string, string> = { "400": inter400, "700": inter700, "800": inter800 };

let loaded = false;

/** Register the subtitle font once; `loadFont` holds the render until it is ready. */
export function loadSubtitleFont(): void {
  if (loaded) return;
  loaded = true;
  for (const [weight, url] of Object.entries(FILES)) {
    void loadFont({ family: SUBTITLE_FONT_FAMILY, url, weight });
  }
}
