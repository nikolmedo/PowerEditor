import type { MessageKey } from "../i18n";

export interface ErrorAction {
  to: string;
  label: MessageKey;
}

const SETTINGS: ErrorAction = { to: "/settings", label: "action.settings" };
const SETUP: ErrorAction = { to: "/setup", label: "action.setup" };
const PROVIDERS: ErrorAction = { to: "/settings/providers", label: "action.providers" };

const ACTIONS: Record<string, ErrorAction> = {
  missing_openai_key: SETTINGS,
  openai_unauthorized: SETTINGS,
  missing_ffmpeg: SETUP,
  missing_ffprobe: SETUP,
  missing_node: SETUP,
  missing_node_x64: SETTINGS,
  provider_unauthorized: PROVIDERS,
  provider_unavailable: PROVIDERS,
  cli_not_found: PROVIDERS,
};

/** Where the user can fix a failed job, by its error code; null when nothing in the app helps. */
export function errorAction(code: string | null): ErrorAction | null {
  return (code && ACTIONS[code]) || null;
}
