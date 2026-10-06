import type { CSSProperties } from "react";

import { SUBTITLE_FONT_FAMILY } from "../subtitles/font";
import type { Insets } from "./layout";
import type { VerticalPosition } from "./templates";

/** What every template receives besides its own props. */
export interface GraphicContext {
  /** 0 hidden … 1 settled, from `overlayMotion`. */
  presence: number;
  /** The shared exit alone (1 until the last 0.3 s), for looks with their own entrance. */
  exit: number;
  /** Frame inside the overlay's own span. */
  frame: number;
  fps: number;
  insets: Insets;
  /** Size unit: 1 at 1080 p. */
  unit: number;
}

const JUSTIFY: Record<VerticalPosition, CSSProperties["justifyContent"]> = {
  top: "flex-start",
  center: "center",
  bottom: "flex-end",
};

export const SHADOW = "0 2px 12px rgba(0,0,0,0.55)";

/** A full-frame column inside the insets, its content pushed to `position`. */
export function area(insets: Insets, position: VerticalPosition): CSSProperties {
  return {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: JUSTIFY[position],
    padding: `${insets.top}px ${insets.right}px ${insets.bottom}px ${insets.left}px`,
    fontFamily: SUBTITLE_FONT_FAMILY,
  };
}
