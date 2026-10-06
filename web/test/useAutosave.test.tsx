import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import { api } from "../src/api/endpoints";
import { useAutosave } from "../src/review/useAutosave";

describe("useAutosave", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reports a failed reload of the latest revision instead of throwing from keep mine", async () => {
    const offline = new ApiError(0, "network", "The local server is not reachable.");
    vi.spyOn(api, "project").mockRejectedValue(offline);
    const { result } = renderHook(() => useAutosave("p1"));

    await act(async () => {
      await expect(result.current.keepMine()).resolves.toBeUndefined();
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe(offline);
  });
});
