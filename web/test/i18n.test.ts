import { describe, expect, it } from "vitest";
import en from "../src/i18n/en.json";
import es from "../src/i18n/es.json";
import { translate } from "../src/i18n";

describe("i18n", () => {
  it("has the same keys in Spanish and English", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
  });

  it("has no empty strings", () => {
    const empty = [...Object.entries(es), ...Object.entries(en)].filter(([, text]) => !text.trim());
    expect(empty).toEqual([]);
  });

  it("translates per language and fills placeholders", () => {
    expect(translate("es", "steps.load")).toBe("Cargar");
    expect(translate("en", "steps.load")).toBe("Load");
    expect(translate("en", "providers.modelsCount", { count: 3 })).toBe("3 models enabled");
  });
});
