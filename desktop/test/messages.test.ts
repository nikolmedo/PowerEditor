import { describe, expect, it } from "vitest";
import en from "../src/i18n/en.json";
import es from "../src/i18n/es.json";
import { translator } from "../src/messages";

describe("translator", () => {
  it("has the same keys in both catalogs", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
  });

  it("picks Spanish for Spanish locales and English otherwise, with variables", () => {
    expect(translator("es-AR")("error.timeout", { seconds: 90 })).toBe(
      "El motor de edición no arrancó en 90 segundos.",
    );
    expect(translator("de-DE")("error.exited", { code: 3 })).toBe(
      "The editing engine stopped unexpectedly (exit code 3).",
    );
  });
});
