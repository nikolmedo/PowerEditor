import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, errorMessage, request } from "../src/api/client";
import { translate } from "../src/i18n";

const t = (key: Parameters<typeof translate>[1], vars?: Record<string, string | number>) =>
  translate("en", key, vars);

function respond(status: number, body: unknown): void {
  const response = new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
}

async function failure(): Promise<ApiError> {
  try {
    await request("GET", "/api/anything");
  } catch (error) {
    if (error instanceof ApiError) return error;
  }
  throw new Error("expected an ApiError");
}

afterEach(() => vi.unstubAllGlobals());

describe("request", () => {
  it("returns the parsed JSON body", async () => {
    respond(200, { status: "ok" });
    await expect(request("GET", "/api/health")).resolves.toEqual({ status: "ok" });
  });

  it("returns undefined for 204", async () => {
    respond(204, undefined);
    await expect(request("DELETE", "/api/providers/x")).resolves.toBeUndefined();
  });

  it("sends JSON bodies", async () => {
    respond(200, {});
    await request("PATCH", "/api/settings", { language: "en" });
    const [path, init] = vi.mocked(fetch).mock.calls[0] ?? [];
    expect(path).toBe("/api/settings");
    expect(init?.body).toBe('{"language":"en"}');
  });
});

describe("error mapping", () => {
  it("reads coded errors and translates known codes", async () => {
    respond(409, { detail: { code: "job_active", message: "busy" } });
    const error = await failure();
    expect(error.code).toBe("job_active");
    expect(errorMessage(error, t)).toBe(t("error.job_active"));
  });

  it("falls back to the server message for unknown codes", async () => {
    respond(409, { detail: { code: "brand_new", message: "Something specific" } });
    expect(errorMessage(await failure(), t)).toBe("Something specific");
  });

  it("maps validation lists to fields by their location", async () => {
    respond(422, {
      detail: [
        { loc: ["targetLufs"], msg: "Input should be a valid number", type: "float_parsing" },
        { loc: ["body", "label"], msg: "String should have at least 1 character", type: "x" },
      ],
    });
    const error = await failure();
    expect(error.fieldErrors).toEqual({
      targetLufs: "Input should be a valid number",
      label: "String should have at least 1 character",
    });
    expect(errorMessage(error, t)).toBe(t("error.validation"));
  });

  it("keeps plain string details as the message", async () => {
    respond(422, { detail: "Plain http is only allowed for localhost; use https." });
    const error = await failure();
    expect(error.code).toBeNull();
    expect(errorMessage(error, t)).toBe("Plain http is only allowed for localhost; use https.");
  });

  it("reports unreachable servers", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect(errorMessage(await failure(), t)).toBe(t("error.network"));
  });
});
