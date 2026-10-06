/** Near-black text on a light `background` (a `#rrggbb` color), white on a dark one. */
export function readableTextColor(background: string): string {
  const channels = [1, 3, 5].map((at) => parseInt(background.slice(at, at + 2), 16) / 255);
  const [r = 0, g = 0, b = 0] = channels.map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  // WCAG relative luminance; 0.179 is where black and white text have equal contrast.
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.179 ? "#111111" : "#FFFFFF";
}
