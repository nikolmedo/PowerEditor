import { describe, expect, it } from "vitest";
import { setRemoved, trimClip } from "../src/edit/operations";
import { createProjectStore } from "../src/store/project";
import { PROJECT } from "./fixtures/reviewProject";

function setup() {
  let now = 0;
  const store = createProjectStore({ now: () => now, historyLimit: 3 });
  store.getState().load("p1", PROJECT, '"e1"');
  return { store, tick: (ms: number) => (now += ms) };
}
const inOf = (store: ReturnType<typeof setup>["store"], id: string) =>
  store.getState().project?.clips.find((clip) => clip.id === id)?.inSec;

describe("project store history", () => {
  it("starts a loaded project with nothing to undo", () => {
    const { store } = setup();
    expect(store.temporal.getState().pastStates).toHaveLength(0);
    store.getState().undo();
    expect(store.getState().project).toBe(PROJECT);
  });

  it("undoes and redoes an edit", () => {
    const { store } = setup();
    store.getState().edit((p) => setRemoved(p, "k2", true));
    store.getState().undo();
    expect(store.getState().project).toBe(PROJECT);
    store.getState().redo();
    expect(store.getState().project?.clips[2]?.removed).toBe(true);
  });

  it("groups a burst of trims of one edge into a single step", () => {
    const { store, tick } = setup();
    for (let step = 0; step < 3; step += 1) {
      store.getState().edit((p) => trimClip(p, "k2", "start", 0.1), "trim:k2:start");
      tick(200);
    }
    expect(inOf(store, "k2")).toBe(0.3);
    store.getState().undo();
    expect(inOf(store, "k2")).toBe(0);
  });

  it("starts a new step after a pause or on another edge", () => {
    const { store, tick } = setup();
    store.getState().edit((p) => trimClip(p, "k2", "start", 0.1), "trim:k2:start");
    tick(2000);
    store.getState().edit((p) => trimClip(p, "k2", "start", 0.1), "trim:k2:start");
    store.getState().edit((p) => trimClip(p, "k2", "end", 0.1), "trim:k2:end");
    store.getState().undo();
    store.getState().undo();
    expect(inOf(store, "k2")).toBe(0.1);
  });

  it("records no step for an edit that changes nothing or for a new ETag", () => {
    const { store } = setup();
    store.getState().edit((p) => trimClip(p, "k2", "start", -0.1));
    store.getState().setEtag('"e2"');
    expect(store.temporal.getState().pastStates).toHaveLength(0);
  });

  it("keeps at most the configured number of steps", () => {
    const { store } = setup();
    for (const id of ["k1", "k2", "k3", "r1"])
      store.getState().edit((p) => setRemoved(p, id, true));
    expect(store.temporal.getState().pastStates).toHaveLength(3);
  });
});
