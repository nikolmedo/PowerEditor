import { describe, expect, it } from "vitest";
import { editorCommand, ownsKeys } from "../src/review/editorKeys";

const press = (
  key: string,
  modifiers: Partial<Record<"ctrl" | "meta" | "shift" | "alt", boolean>> = {},
) =>
  editorCommand({
    key,
    ctrlKey: modifiers.ctrl ?? false,
    metaKey: modifiers.meta ?? false,
    shiftKey: modifiers.shift ?? false,
    altKey: modifiers.alt ?? false,
  });

describe("editorCommand", () => {
  it("maps undo and both redo shortcuts", () => {
    expect(press("z", { ctrl: true })).toEqual({ type: "undo" });
    expect(press("Z", { ctrl: true, shift: true })).toEqual({ type: "redo" });
    expect(press("y", { ctrl: true })).toEqual({ type: "redo" });
    expect(press("z", { meta: true })).toEqual({ type: "undo" });
    expect(press("s", { ctrl: true })).toBeNull();
  });

  it("maps selection, removal and trims", () => {
    expect(press("ArrowLeft")).toEqual({ type: "move", step: -1 });
    expect(press("ArrowRight")).toEqual({ type: "move", step: 1 });
    expect(press("Delete")).toEqual({ type: "toggleRemoved" });
    expect(press("[")).toEqual({ type: "trim", edge: "start", deltaSec: 0.1 });
    expect(press("{", { shift: true })).toEqual({ type: "trim", edge: "start", deltaSec: -0.1 });
    expect(press("]")).toEqual({ type: "trim", edge: "end", deltaSec: -0.1 });
    expect(press("}", { shift: true })).toEqual({ type: "trim", edge: "end", deltaSec: 0.1 });
    expect(press("ArrowLeft", { alt: true })).toBeNull();
    expect(press("a")).toBeNull();
  });
});

describe("ownsKeys", () => {
  it("leaves keys typed into form controls and the player to them", () => {
    document.body.innerHTML =
      '<input id="text"><div class="player-frame"><button id="play"></button></div><button id="clip"></button>';
    const byId = (id: string) => document.getElementById(id);
    expect([ownsKeys(byId("text")), ownsKeys(byId("play")), ownsKeys(byId("clip"))]).toEqual([
      true,
      true,
      false,
    ]);
  });
});
