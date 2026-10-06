import { describe, expect, it } from "vitest";
import type { ProviderDraft } from "../src/api/types";
import {
  draftFor,
  draftPayload,
  termsNoticeKey,
  toggleModel,
  validateDraft,
} from "../src/settings/providerForm";

const base: ProviderDraft = {
  kind: "openai",
  transport: "api",
  label: "OpenAI",
  enabledModels: [],
  cliPath: null,
  baseUrl: null,
  customBaseUrlConfirmed: false,
};

describe("draftFor", () => {
  it("starts from the kind's label and first transport", () => {
    const draft = draftFor({ kind: "gemini", label: "Google Gemini", transports: ["local_cli"] });
    expect(draft).toMatchObject({ kind: "gemini", transport: "local_cli", label: "Google Gemini" });
  });
});

describe("draftPayload", () => {
  it("drops fields that do not apply to the transport and blanks to null", () => {
    const payload = draftPayload({ ...base, label: "  Work  ", cliPath: "codex", baseUrl: " " });
    expect(payload).toMatchObject({ label: "Work", cliPath: null, baseUrl: null });
    expect(payload.customBaseUrlConfirmed).toBe(false);
  });

  it("keeps the CLI path for local clients and never sends a base URL", () => {
    const payload = draftPayload({
      ...base,
      transport: "local_cli",
      cliPath: " C:/tools/codex.cmd ",
      baseUrl: "https://example.com",
      customBaseUrlConfirmed: true,
    });
    expect(payload).toMatchObject({ cliPath: "C:/tools/codex.cmd", baseUrl: null });
    expect(payload.customBaseUrlConfirmed).toBe(false);
  });
});

describe("validateDraft", () => {
  it("accepts a plain draft", () => {
    expect(validateDraft(base)).toEqual({});
  });

  it("requires a label and a well-formed base URL", () => {
    expect(validateDraft({ ...base, label: " ", baseUrl: "ftp://x" })).toEqual({
      label: "providers.error.label",
      baseUrl: "providers.error.baseUrl",
    });
  });

  it("requires an explicit confirmation for a custom base URL", () => {
    const custom = { ...base, baseUrl: "https://proxy.example/v1" };
    expect(validateDraft(custom)).toEqual({ customBaseUrlConfirmed: "providers.error.confirm" });
    expect(validateDraft({ ...custom, customBaseUrlConfirmed: true })).toEqual({});
  });
});

describe("termsNoticeKey", () => {
  it("warns about subscription terms for local clients only", () => {
    expect(termsNoticeKey("anthropic", "local_cli")).toBe("terms.claude");
    expect(termsNoticeKey("gemini", "local_cli")).toBe("terms.gemini");
    expect(termsNoticeKey("openai", "local_cli")).toBe("terms.codex");
    expect(termsNoticeKey("anthropic", "api")).toBeNull();
  });
});

describe("toggleModel", () => {
  it("adds and removes a model, keeping the list sorted", () => {
    expect(toggleModel(["b"], "a")).toEqual(["a", "b"]);
    expect(toggleModel(["a", "b"], "a")).toEqual(["b"]);
  });
});
