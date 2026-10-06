import { describe, expect, it } from "vitest";
import { parseRoute, stepPath } from "../src/routes";

describe("routes", () => {
  it("reads a project's step from the path", () => {
    expect(parseRoute("/projects/p-1%20a/review")).toEqual({
      screen: "review",
      projectId: "p-1 a",
    });
    expect(parseRoute("/projects/p-1/export/")).toEqual({ screen: "export", projectId: "p-1" });
    expect(parseRoute("/load")).toEqual({ screen: "load", projectId: null });
    expect(parseRoute("/settings/providers")).toEqual({ screen: "providers" });
    expect(parseRoute("/welcome")).toEqual({ screen: "welcome" });
    expect(parseRoute("/projects/p-1/edit")).toEqual({ screen: "home" });
  });

  it("builds step paths and has no review or export without a project", () => {
    expect(stepPath("review", "p 1")).toBe("/projects/p%201/review");
    expect(stepPath("load", null)).toBe("/load");
    expect(stepPath("export", null)).toBeNull();
  });
});
