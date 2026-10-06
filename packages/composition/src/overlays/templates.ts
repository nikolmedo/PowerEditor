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

/**
 * Looks of a template, stored as `props.variant`. The first one is the default, so projects
 * saved before variants existed keep their look.
 */
export const OVERLAY_VARIANTS = {
  title: ["classic", "headline_slam"],
  lower_third: ["clean_bar", "kicker_name", "mask_reveal", "soft_pill"],
  cta: ["pill", "lockup", "close"],
} as const;

export type TitleVariant = (typeof OVERLAY_VARIANTS.title)[number];
export type LowerThirdVariant = (typeof OVERLAY_VARIANTS.lower_third)[number];
export type CtaVariant = (typeof OVERLAY_VARIANTS.cta)[number];

/** The looks of `templateId`, or none when the template has a single look. */
export function overlayVariants(templateId: OverlayTemplateId): readonly string[] {
  return templateId in OVERLAY_VARIANTS
    ? OVERLAY_VARIANTS[templateId as keyof typeof OVERLAY_VARIANTS]
    : [];
}

export interface TitleProps {
  variant: TitleVariant;
  text: string;
  subtitle: string;
  position: VerticalPosition;
  color: string;
}

export interface LowerThirdProps {
  variant: LowerThirdVariant;
  name: string;
  /** The second line; `kicker_name` shows it above the name as a small kicker. */
  role: string;
  side: "left" | "right";
  color: string;
}

export interface CtaProps {
  variant: CtaVariant;
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

export interface CountUpProps {
  /** The number the counter lands on; its decimals (up to two) are kept while counting. */
  value: number;
  prefix: string;
  suffix: string;
  /** A short line under the number. */
  label: string;
  position: VerticalPosition;
  color: string;
}

export interface ProgressRingProps {
  /** Text in the ring's center. */
  label: string;
  corner: Corner;
  color: string;
  /** Diameter as a share of the frame width. */
  size: number;
}

export interface OverlayPropsMap {
  title: TitleProps;
  lower_third: LowerThirdProps;
  cta: CtaProps;
  logo: LogoProps;
  progress_bar: ProgressBarProps;
  image: ImageProps;
  count_up: CountUpProps;
  progress_ring: ProgressRingProps;
}

export type OverlayField =
  | { key: string; kind: "text"; maxLength: number }
  | { key: string; kind: "color" }
  | { key: string; kind: "choice"; options: readonly string[] }
  | {
      key: string;
      kind: "number";
      min: number;
      max: number;
      step: number;
      /** Typed in a number box instead of a slider (a wide range such as a count). */
      entry?: true;
    }
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
const CORNERS = ["top_left", "top_right", "bottom_left", "bottom_right"] as const;
const image: OverlayField = { key: "src", kind: "image" };
const variant = (templateId: keyof typeof OVERLAY_VARIANTS): OverlayField =>
  choice("variant", OVERLAY_VARIANTS[templateId]);

/** The editable props of each template, in form order. */
export const OVERLAY_FIELDS: Record<OverlayTemplateId, readonly OverlayField[]> = {
  title: [
    variant("title"),
    text("text"),
    text("subtitle", 120),
    choice("position", VERTICAL),
    color,
  ],
  lower_third: [
    variant("lower_third"),
    text("name", 60),
    text("role", 80),
    choice("side", ["left", "right"]),
    color,
  ],
  cta: [variant("cta"), text("text", 60), choice("position", VERTICAL), color],
  logo: [
    image,
    choice("corner", CORNERS),
    number("size", 0.05, 0.4, 0.01),
    number("opacity", 0.2, 1, 0.05),
  ],
  progress_bar: [choice("position", ["top", "bottom"]), color, number("thickness", 4, 40, 1)],
  image: [image, choice("position", VERTICAL), number("size", 0.2, 1, 0.05)],
  count_up: [
    { key: "value", kind: "number", min: 0, max: 999_999_999, step: 1, entry: true },
    text("prefix", 12),
    text("suffix", 12),
    text("label", 60),
    choice("position", VERTICAL),
    color,
  ],
  progress_ring: [
    text("label", 24),
    choice("corner", CORNERS),
    color,
    number("size", 0.08, 0.3, 0.01),
  ],
};

export const OVERLAY_TEMPLATES = Object.keys(OVERLAY_FIELDS) as OverlayTemplateId[];

/** Defaults of each template; `accent` is the project's accent color. */
export function defaultOverlayProps<K extends OverlayTemplateId>(
  templateId: K,
  accent: string,
): OverlayPropsMap[K] {
  const defaults: { [T in OverlayTemplateId]: OverlayPropsMap[T] } = {
    title: { variant: "classic", text: "", subtitle: "", position: "center", color: accent },
    lower_third: { variant: "clean_bar", name: "", role: "", side: "left", color: accent },
    cta: { variant: "pill", text: "", position: "bottom", color: accent },
    logo: { src: "", corner: "top_right", size: 0.14, opacity: 0.9 },
    progress_bar: { position: "top", color: accent, thickness: 10 },
    image: { src: "", position: "center", size: 0.6 },
    count_up: { value: 100, prefix: "", suffix: "", label: "", position: "center", color: accent },
    progress_ring: { label: "", corner: "top_right", color: accent, size: 0.14 },
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

/** `raw` props with every invalid or missing value replaced by its default; unknown keys go.
 * Props that are not an object at all (a hand-edited `null`) count as empty. */
export function normalizeOverlayProps<K extends OverlayTemplateId>(
  templateId: K,
  raw: Readonly<Record<string, unknown>> | null | undefined,
  accent: string,
): OverlayPropsMap[K] {
  const source: Readonly<Record<string, unknown>> =
    typeof raw === "object" && raw !== null && !Array.isArray(raw) ? raw : {};
  const props: Record<string, unknown> = { ...(defaultOverlayProps(templateId, accent) as object) };
  for (const field of OVERLAY_FIELDS[templateId]) {
    const value = normalizeValue(field, source[field.key]);
    if (value !== undefined) props[field.key] = value;
  }
  return props as unknown as OverlayPropsMap[K];
}
