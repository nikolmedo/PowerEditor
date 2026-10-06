import { describe, expect, it } from "vitest";
import { isAppUrl, isAllowedExternal, restoreBounds, type Rect } from "../src/policy";

const APP = "http://127.0.0.1:51234";

describe("isAppUrl", () => {
  it("accepts only the sidecar's own origin", () => {
    expect(isAppUrl(`${APP}/projects/a/review`, APP)).toBe(true);
    expect(isAppUrl("http://127.0.0.1:51235/", APP)).toBe(false);
    expect(isAppUrl("http://localhost:51234/", APP)).toBe(false);
    expect(isAppUrl("https://127.0.0.1:51234/", APP)).toBe(false);
    expect(isAppUrl("file:///C:/Windows/win.ini", APP)).toBe(false);
    expect(isAppUrl("not a url", APP)).toBe(false);
  });
});

describe("isAllowedExternal", () => {
  it("opens https links to the allowed sites only", () => {
    expect(isAllowedExternal("https://github.com/nikolmedo/PowerEditor#readme")).toBe(true);
    expect(isAllowedExternal("https://www.remotion.dev/license")).toBe(true);
    expect(isAllowedExternal("http://github.com/")).toBe(false);
    expect(isAllowedExternal("https://evil.example/")).toBe(false);
  });

  it("opens the author's site from the About section and the footer", () => {
    expect(isAllowedExternal("https://nolmedo.dev")).toBe(true);
    expect(isAllowedExternal("https://nolmedo.dev/")).toBe(true);
    expect(isAllowedExternal("http://nolmedo.dev/")).toBe(false);
    expect(isAllowedExternal("https://nolmedo.dev.evil.example/")).toBe(false);
    expect(isAllowedExternal("https://github.com.evil.example/")).toBe(false);
    expect(isAllowedExternal("https://evil.example/?u=github.com")).toBe(false);
    expect(isAllowedExternal("file:///C:/")).toBe(false);
    expect(isAllowedExternal("javascript:alert(1)")).toBe(false);
  });
});

describe("restoreBounds", () => {
  const primary: Rect = { x: 0, y: 0, width: 1920, height: 1040 };
  const fallback = { width: 1280, height: 800 };

  it("keeps saved bounds that are visible on a display", () => {
    const saved = { x: 100, y: 80, width: 1400, height: 900 };

    expect(restoreBounds(saved, [primary], fallback)).toEqual(saved);
  });

  it("drops the position of a window left on a display that is gone", () => {
    const saved = { x: 2500, y: 100, width: 1200, height: 800 };

    expect(restoreBounds(saved, [primary], fallback)).toEqual({ width: 1200, height: 800 });
  });

  it("shrinks a window larger than the display and ignores unreadable state", () => {
    const huge = { x: 0, y: 0, width: 4000, height: 3000 };

    expect(restoreBounds(huge, [primary], fallback)).toEqual({
      x: 0,
      y: 0,
      width: 1920,
      height: 1040,
    });
    expect(restoreBounds({ width: "wide" }, [primary], fallback)).toEqual(fallback);
    expect(restoreBounds(null, [primary], fallback)).toEqual(fallback);
  });
});
