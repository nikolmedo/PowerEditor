import type { Overlay } from "../types";

/**
 * Overlay templates: the typed props of each `templateId`, their defaults and a field table.
 * `project.json` stores props as free-form JSON, so the composition never trusts them:
 * `normalizeOverlayProps` keeps valid values and falls back to the defaults for the rest.
 * The editor builds its forms from `OVERLAY_FIELDS`, the same table the renderer validates with.
 */

export type OverlayTemplateId = Overlay["templateId"];
export type VerticalPosition = "top" | "center" | "bottom";
export type Corner = "top_left" | "top_right" | "bottom_left" | "bottom_right";

export interface TitleProps {
  text: string;
  subtitle: string;
  position: VerticalPosition;
  color: string;
}

export interface LowerThirdProps {
  name: string;
  role: string;
  side: "left" | "right";
  color: string;
}

export interface CtaProps {
  text: string;
  position: VerticalPosition;
  color: string;
}

export interface LogoProps {
  /** File name in the project's media folder. */
  src: string;
  corner: Corner;
  /** Width as a share of the frame width. */
  size: number;
  opacity: number;
}

export interface ProgressBarProps {
  position: "top" | "bottom";
  color: string;
  /** Bar height in pixels at 1080 p. */
  thickness: number;
}

export interface ImageProps {
  /** File name in the project's media folder. */
  src: string;
  position: VerticalPosition;
  /** Width as a share of the safe area's width. */
  size: number;
}

export interface OverlayPropsMap {
  title: TitleProps;
  lower_third: LowerThirdProps;
  cta: CtaProps;
  logo: LogoProps;
  progress_bar: ProgressBarProps;
  image: ImageProps;
}

export type OverlayField =
  | { key: string; kind: "text"; maxLength: number }
  | { key: string; kind: "color" }
  | { key: string; kind: "choice"; options: readonly string[] }
  | { key: string; kind: "number"; min: number; max: number; step: number }
  | { key: string; kind: "image" };

const VERTICAL = ["top", "center", "bottom"] as const;
const text = (key: string, maxLength = 80): OverlayField => ({ key, kind: "text", maxLength });
const color: OverlayField = { key: "color", kind: "color" };
const choice = (key: string, options: readonly string[]): OverlayField => ({
  key,
  kind: "choice",
  options,
});
const number = (key: string, min: number, max: number, step: number): OverlayField => ({
  key,
  kind: "number",
  min,
  max,
  step,
});
const image: OverlayField = { key: "src", kind: "image" };

/** The editable props of each template, in form order. */
export const OVERLAY_FIELDS: Record<OverlayTemplateId, readonly OverlayField[]> = {
  title: [text("text"), text("subtitle", 120), choice("position", VERTICAL), color],
  lower_third: [text("name", 60), text("role", 80), choice("side", ["left", "right"]), color],
  cta: [text("text", 60), choice("position", VERTICAL), color],
  logo: [
    image,
    choice("corner", ["top_left", "top_right", "bottom_left", "bottom_right"]),
    number("size", 0.05, 0.4, 0.01),
    number("opacity", 0.2, 1, 0.05),
  ],
  progress_bar: [choice("position", ["top", "bottom"]), color, number("thickness", 4, 40, 1)],
  image: [image, choice("position", VERTICAL), number("size", 0.2, 1, 0.05)],
};

export const OVERLAY_TEMPLATES = Object.keys(OVERLAY_FIELDS) as OverlayTemplateId[];

/** Defaults of each template; `accent` is the project's accent color. */
export function defaultOverlayProps<K extends OverlayTemplateId>(
  templateId: K,
  accent: string,
): OverlayPropsMap[K] {
  const defaults: { [T in OverlayTemplateId]: OverlayPropsMap[T] } = {
    title: { text: "", subtitle: "", position: "center", color: accent },
    lower_third: { name: "", role: "", side: "left", color: accent },
    cta: { text: "", position: "bottom", color: accent },
    logo: { src: "", corner: "top_right", size: 0.14, opacity: 0.9 },
    progress_bar: { position: "top", color: accent, thickness: 10 },
    image: { src: "", position: "center", size: 0.6 },
  };
  return defaults[templateId];
}

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;
/** Images are served flat from the media folder, so only a plain file name is kept. */
const FILE_NAME = /^[^\\/]*[^\\/.][^\\/]*$/;

function normalizeValue(field: OverlayField, value: unknown): unknown {
  switch (field.kind) {
    case "text":
      return typeof value === "string" ? value.trim().slice(0, field.maxLength) : undefined;
    case "color":
      return typeof value === "string" && HEX_COLOR.test(value) ? value : undefined;
    case "choice":
      return typeof value === "string" && field.options.includes(value) ? value : undefined;
    case "number":
      return typeof value === "number" && Number.isFinite(value)
        ? Math.min(field.max, Math.max(field.min, value))
        : undefined;
    case "image": {
      if (typeof value !== "string") return undefined;
      const name = value.split(/[\\/]/).pop() ?? "";
      return FILE_NAME.test(name) ? name : undefined;
    }
  }
}

/** `raw` props with every invalid or missing value replaced by its default; unknown keys go. */
export function normalizeOverlayProps<K extends OverlayTemplateId>(
  templateId: K,
  raw: Record<string, unknown>,
  accent: string,
): OverlayPropsMap[K] {
  const props: Record<string, unknown> = { ...(defaultOverlayProps(templateId, accent) as object) };
  for (const field of OVERLAY_FIELDS[templateId]) {
    const value = normalizeValue(field, raw[field.key]);
    if (value !== undefined) props[field.key] = value;
  }
  return props as unknown as OverlayPropsMap[K];
}
