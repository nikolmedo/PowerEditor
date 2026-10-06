import { describe, expect, it } from "vitest";
import en from "../src/i18n/en.json";
import es from "../src/i18n/es.json";
import { isMessageKey, pluralCategory, translate } from "../src/i18n";

describe("i18n", () => {
  it("has the same keys in Spanish and English", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
  });

  it("has no empty strings", () => {
    const empty = [...Object.entries(es), ...Object.entries(en)].filter(([, text]) => !text.trim());
    expect(empty).toEqual([]);
  });

  it("gives every plural message both its one and other form", () => {
    const keys = Object.keys(es);
    const plurals = keys.filter((key) => /\.(one|other)$/.test(key));
    const bases = new Set(plurals.map((key) => key.replace(/\.(one|other)$/, "")));
    expect(bases.size).toBeGreaterThan(0);
    for (const base of bases) {
      expect(keys).toContain(`${base}.one`);
      expect(keys).toContain(`${base}.other`);
      expect(keys).not.toContain(base);
    }
  });

  it("translates per language and fills placeholders", () => {
    expect(translate("es", "steps.load")).toBe("Cargar");
    expect(translate("en", "steps.load")).toBe("Load");
    expect(translate("en", "review.clipAt", { time: "0:01.0" })).toContain("0:01.0");
  });

  it("picks the singular only for a count of exactly one", () => {
    expect(pluralCategory(1)).toBe("one");
    expect(pluralCategory(0)).toBe("other");
    expect(pluralCategory(2)).toBe("other");
    expect(pluralCategory(1.5)).toBe("other");
  });

  it("pluralizes count messages in both languages", () => {
    expect(translate("en", "providers.modelsCount", { count: 1 })).toBe("1 model enabled");
    expect(translate("en", "providers.modelsCount", { count: 3 })).toBe("3 models enabled");
    expect(translate("en", "providers.modelsCount", { count: 0 })).toBe("0 models enabled");
    expect(translate("es", "providers.modelsCount", { count: 1 })).toBe("1 modelo habilitado");
    expect(translate("es", "providers.modelsCount", { count: 2 })).toBe("2 modelos habilitados");
    expect(translate("en", "review.takes", { count: 1 })).toBe("1 take");
    expect(translate("es", "review.takes", { count: 3 })).toBe("3 tomas");
    expect(translate("en", "color.applyToAll.hint", { count: 1 })).toBe(
      "1 clip has a look of its own; applying removes it.",
    );
    expect(translate("es", "color.applyToAll.hint", { count: 1 })).toBe(
      "1 clip tiene un look propio; aplicar lo quita.",
    );
  });

  it("recognizes plural messages by their base key", () => {
    expect(isMessageKey("providers.modelsCount")).toBe(true);
    expect(isMessageKey("providers.modelsCount.one")).toBe(false);
    expect(isMessageKey("no.such.key")).toBe(false);
  });
});
