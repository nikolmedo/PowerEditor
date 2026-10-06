import type { ModelRef, Provider } from "../api/types";

/** Select value for "no model": the feature uses the built-in heuristic. */
export const HEURISTIC = "";

export interface ModelOption {
  value: string;
  label: string;
  /** The current assignment, but the model is no longer enabled on its provider. */
  stale: boolean;
}

// Provider ids never contain "/", model ids may (for example "models/gemini-2.5-pro").
export function encodeRef(ref: ModelRef): string {
  return `${ref.providerId}/${ref.model}`;
}

export function decodeRef(value: string): ModelRef | null {
  const slash = value.indexOf("/");
  if (value === HEURISTIC || slash < 0) return null;
  return { providerId: value.slice(0, slash), model: value.slice(slash + 1) };
}

export function modelOptions(
  providers: readonly Provider[],
  current: ModelRef | null,
): ModelOption[] {
  const labelOf = (ref: ModelRef) => {
    const provider = providers.find((candidate) => candidate.id === ref.providerId);
    return `${provider?.label ?? ref.providerId} · ${ref.model}`;
  };
  const options = providers.flatMap((provider) =>
    provider.enabledModels.map((model) => {
      const ref = { providerId: provider.id, model };
      return { value: encodeRef(ref), label: labelOf(ref), stale: false };
    }),
  );
  if (current && !options.some((option) => option.value === encodeRef(current))) {
    options.push({ value: encodeRef(current), label: labelOf(current), stale: true });
  }
  return options;
}
