import { useAppStore } from "../store/app";
import en from "./en.json";
import es from "./es.json";

export type Language = "es" | "en";
export type MessageKey = keyof typeof es;
export type Vars = Record<string, string | number>;
export type Translate = (key: MessageKey, vars?: Vars) => string;

export const LANGUAGES: readonly Language[] = ["es", "en"];
const CATALOGS: Record<Language, Record<MessageKey, string>> = { es, en };

export function isMessageKey(key: string): key is MessageKey {
  return key in es;
}

export function translate(language: Language, key: MessageKey, vars?: Vars): string {
  const text = CATALOGS[language][key];
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => String(vars[name] ?? match));
}

export function useT(): Translate {
  const language = useAppStore((state) => state.language);
  return (key, vars) => translate(language, key, vars);
}
