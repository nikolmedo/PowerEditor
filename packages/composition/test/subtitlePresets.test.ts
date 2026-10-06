import { describe, expect, it } from "vitest";

import { emphasizedWordIndex, hasEmoji } from "../src/subtitles/emphasis";
import { highlightsActiveWord, lineStyle, SUBTITLE_PRESETS } from "../src/subtitles/styles";
import { wordStyle, type WordState } from "../src/subtitles/wordStyle";
import type { SubtitleStyle } from "../src/types";

const FPS = 30;
const HIGHLIGHT = "#FFD400";

const state = (overrides: Partial<WordState> = {}): WordState => ({
  isActive: false,
  framesSinceStart: 10,
  fps: FPS,
  highlightColor: HIGHLIGHT,
  emphasized: false,
  emoji: false,
  ...overrides,
});

describe("editorial emphasis", () => {
  it("picks the longest content word of a line, skipping stopwords of both languages", () => {
    expect(emphasizedWordIndex(["Hoy", "vamos", "a", "construir", "algo"])).toBe(3);
    expect(emphasizedWordIndex(["This", "changes", "everything", "about", "editing."])).toBe(2);
    // "también" and "porque" are stopwords, so the shorter content word wins.
    expect(emphasizedWordIndex(["también", "porque", "video"])).toBe(2);
  });

  it("breaks ties by the first word and ignores punctuation around words", () => {
    expect(emphasizedWordIndex(["¡Graba", "ahora", "mismo!"])).toBe(0);
    expect(emphasizedWordIndex(["“quiero”", "editar", "videos"])).toBe(0);
  });

  it("emphasizes nothing on short lines or lines of only stopwords and short words", () => {
    expect(emphasizedWordIndex(["Muchas", "gracias"])).toBe(-1);
    expect(emphasizedWordIndex(["and", "then", "the", "end"])).toBe(-1);
    expect(emphasizedWordIndex([])).toBe(-1);
  });
});

describe("hasEmoji", () => {
  it("finds pictographic emoji but not text symbols", () => {
    expect(hasEmoji("listo🔥")).toBe(true);
    expect(hasEmoji("❤️")).toBe(true);
    expect(hasEmoji("👍🏽")).toBe(true);
    expect(hasEmoji("©2026")).toBe(false);
    expect(hasEmoji("hola")).toBe(false);
    expect(hasEmoji("#1")).toBe(false);
  });
});

describe("subtitle presets", () => {
  it("lists every preset once, the original four first", () => {
    expect(SUBTITLE_PRESETS).toEqual([
      "karaoke_highlight",
      "clean",
      "bold_pop",
      "minimal",
      "pill_karaoke",
      "kinetic_slam",
      "emoji_pop",
      "editorial_emphasis",
    ]);
  });

  it("colors the active word only for the karaoke-like presets", () => {
    expect(SUBTITLE_PRESETS.filter(highlightsActiveWord)).toEqual([
      "karaoke_highlight",
      "bold_pop",
      "pill_karaoke",
      "kinetic_slam",
    ]);
  });

  it("gives each preset a line style", () => {
    const style = (preset: SubtitleStyle["preset"]): SubtitleStyle => ({
      preset,
      fontSize: 60,
      position: "bottom",
      highlightColor: HIGHLIGHT,
      maxWordsPerLine: 4,
    });
    expect(lineStyle(style("kinetic_slam"), "Inter")).toMatchObject({
      fontWeight: 800,
      textTransform: "uppercase",
      fontSize: 66,
    });
    expect(lineStyle(style("editorial_emphasis"), "Inter").fontWeight).toBe(400);
  });
});

describe("word styles", () => {
  it("puts the active word of pill karaoke on a pill that grows in", () => {
    const start = wordStyle("pill_karaoke", state({ isActive: true, framesSinceStart: 0 }));
    expect(start.backgroundColor).toBe(HIGHLIGHT);
    expect(start.color).toBe("#111111");
    expect(start.transform).toBe("scale(0.85)");
    const settled = wordStyle("pill_karaoke", state({ isActive: true, framesSinceStart: 45 }));
    expect(settled.transform).toBe("scale(1)");
    const idle = wordStyle("pill_karaoke", state());
    expect(idle.backgroundColor).toBe("transparent");
    // Every word keeps the pill's padding, so the line never shifts as the pill moves.
    expect(idle.padding).toBe(start.padding);
  });

  it("hides kinetic words until they start, then slams them in from 1.5x", () => {
    expect(wordStyle("kinetic_slam", state({ framesSinceStart: -1 })).opacity).toBe(0);
    const landing = wordStyle("kinetic_slam", state({ isActive: true, framesSinceStart: 0 }));
    expect(landing).toMatchObject({ opacity: 0, transform: "scale(1.5)", color: HIGHLIGHT });
    expect(wordStyle("kinetic_slam", state({ framesSinceStart: 2 })).opacity).toBe(1);
    const settled = wordStyle("kinetic_slam", state({ framesSinceStart: 30 }));
    expect(settled.transform).toMatch(/^scale\(1(\.00\d*)?\)$/);
  });

  it("pops only words that carry an emoji", () => {
    expect(wordStyle("emoji_pop", state({ framesSinceStart: 0 }))).toEqual({});
    const before = wordStyle("emoji_pop", state({ emoji: true, framesSinceStart: -3 }));
    expect(before.opacity).toBe(0);
    const popping = wordStyle("emoji_pop", state({ emoji: true, framesSinceStart: 0 }));
    expect(popping.transform).toBe("scale(0.4)");
    const sizes = Array.from({ length: 20 }, (_, frame) =>
      Number(
        /scale\(([\d.]+)\)/.exec(
          String(wordStyle("emoji_pop", state({ emoji: true, framesSinceStart: frame })).transform),
        )?.[1],
      ),
    );
    expect(Math.max(...sizes)).toBeGreaterThan(1.05);
  });

  it("marks the one emphasized word of an editorial line", () => {
    expect(wordStyle("editorial_emphasis", state({ emphasized: true }))).toMatchObject({
      color: HIGHLIGHT,
      fontWeight: 800,
    });
    expect(wordStyle("editorial_emphasis", state({ isActive: true }))).toEqual({});
  });

  it("keeps the original presets as they were", () => {
    expect(wordStyle("karaoke_highlight", state({ isActive: true }))).toEqual({
      color: HIGHLIGHT,
    });
    expect(wordStyle("clean", state({ isActive: true }))).toEqual({});
    expect(wordStyle("bold_pop", state({ isActive: true, framesSinceStart: 0 }))).toEqual({
      color: HIGHLIGHT,
      transform: "scale(1.12)",
    });
  });
});
