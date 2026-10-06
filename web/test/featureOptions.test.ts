import { describe, expect, it } from "vitest";
import type { Provider } from "../src/api/types";
import { decodeRef, encodeRef, HEURISTIC, modelOptions } from "../src/settings/featureOptions";

function provider(id: string, label: string, enabledModels: string[]): Provider {
  return {
    id,
    kind: "openai",
    transport: "api",
    label,
    enabledModels,
    cliPath: null,
    baseUrl: null,
    customBaseUrlConfirmed: false,
    apiKeySet: true,
  };
}

describe("model refs", () => {
  it("round-trips model ids that contain slashes", () => {
    const ref = { providerId: "gemini-api", model: "models/gemini-2.5-pro" };
    expect(decodeRef(encodeRef(ref))).toEqual(ref);
  });

  it("decodes the heuristic choice as no model", () => {
    expect(decodeRef(HEURISTIC)).toBeNull();
  });
});

describe("modelOptions", () => {
  const providers = [provider("openai-api", "OpenAI", ["gpt-a", "gpt-b"]), provider("x", "X", [])];

  it("lists every enabled model of every provider", () => {
    expect(modelOptions(providers, null)).toEqual([
      { value: "openai-api/gpt-a", label: "OpenAI · gpt-a", stale: false },
      { value: "openai-api/gpt-b", label: "OpenAI · gpt-b", stale: false },
    ]);
  });

  it("keeps a current choice that is no longer enabled, marked stale", () => {
    const options = modelOptions(providers, { providerId: "openai-api", model: "gpt-old" });
    expect(options.at(-1)).toEqual({
      value: "openai-api/gpt-old",
      label: "OpenAI · gpt-old",
      stale: true,
    });
    expect(options).toHaveLength(3);
  });
});
