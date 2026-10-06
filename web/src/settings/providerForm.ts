import type { ProviderDraft, ProviderKindInfo, Transport } from "../api/types";
import type { MessageKey } from "../i18n";

export type DraftErrors = Partial<Record<keyof ProviderDraft, MessageKey>>;

const TERMS_BY_KIND: Record<string, MessageKey> = {
  anthropic: "terms.claude",
  gemini: "terms.gemini",
  openai: "terms.codex",
};

export function draftFor(kind: ProviderKindInfo): ProviderDraft {
  return {
    kind: kind.kind,
    transport: kind.transports[0] ?? "api",
    label: kind.label,
    enabledModels: [],
    cliPath: null,
    baseUrl: null,
    customBaseUrlConfirmed: false,
  };
}

function blankToNull(value: string | null): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed === "" ? null : trimmed;
}

/** The body the API expects: only the fields that apply to the transport. */
export function draftPayload(draft: ProviderDraft): ProviderDraft {
  const isApi = draft.transport === "api";
  const baseUrl = isApi ? blankToNull(draft.baseUrl) : null;
  return {
    ...draft,
    label: draft.label.trim(),
    cliPath: isApi ? null : blankToNull(draft.cliPath),
    baseUrl,
    customBaseUrlConfirmed: baseUrl !== null && draft.customBaseUrlConfirmed,
  };
}

/** Client-side checks; the backend still decides which hosts are official. */
export function validateDraft(draft: ProviderDraft): DraftErrors {
  const payload = draftPayload(draft);
  const errors: DraftErrors = {};
  if (!payload.label) errors.label = "providers.error.label";
  if (payload.baseUrl !== null && !/^https?:\/\/\S+$/.test(payload.baseUrl)) {
    errors.baseUrl = "providers.error.baseUrl";
  } else if (payload.baseUrl !== null && !payload.customBaseUrlConfirmed) {
    errors.customBaseUrlConfirmed = "providers.error.confirm";
  }
  return errors;
}

/** Local subscription clients carry their vendor's terms; API keys do not need a notice. */
export function termsNoticeKey(kind: string, transport: Transport): MessageKey | null {
  return transport === "local_cli" ? (TERMS_BY_KIND[kind] ?? null) : null;
}

export function toggleModel(enabled: readonly string[], model: string): string[] {
  const next = enabled.includes(model) ? enabled.filter((id) => id !== model) : [...enabled, model];
  return next.sort();
}
