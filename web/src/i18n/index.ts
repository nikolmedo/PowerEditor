import { useAppStore } from "../store/app";
import en from "./en.json";
import es from "./es.json";

export type Language = "es" | "en";
export type Vars = Record<string, string | number>;

/** Spanish and English both use the singular for exactly one and the plural otherwise. */
export type PluralCategory = "one" | "other";

type CatalogKey = keyof typeof es;
/** A message with plural forms is stored as `key.one` and `key.other` and asked for by `key`. */
type PluralKey<K> = K extends `${infer Base}.${PluralCategory}` ? Base : never;
export type MessageKey = Exclude<CatalogKey, `${string}.${PluralCategory}`> | PluralKey<CatalogKey>;
export type Translate = (key: MessageKey, vars?: Vars) => string;

export const LANGUAGES: readonly Language[] = ["es", "en"];
const CATALOGS: Record<Language, Record<CatalogKey, string>> = { es, en };

const inCatalog = (key: string): key is CatalogKey => key in es;

export function pluralCategory(count: number): PluralCategory {
  return count === 1 ? "one" : "other";
}

export function isMessageKey(key: string): key is MessageKey {
  if (/\.(one|other)$/.test(key)) return false;
  return inCatalog(key) || inCatalog(`${key}.other`);
}

/** The message for `key`; a plural message picks its form from `vars.count`. */
export function translate(language: Language, key: MessageKey, vars?: Vars): string {
  const catalog = CATALOGS[language];
  const count = typeof vars?.count === "number" ? vars.count : NaN;
  const plural = `${key}.${pluralCategory(count)}`;
  const text = inCatalog(key) ? catalog[key] : inCatalog(plural) ? catalog[plural] : key;
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => String(vars[name] ?? match));
}

export function useT(): Translate {
  const language = useAppStore((state) => state.language);
  return (key, vars) => translate(language, key, vars);
}
