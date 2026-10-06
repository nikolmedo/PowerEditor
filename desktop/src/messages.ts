import en from "./i18n/en.json";
import es from "./i18n/es.json";

export type MessageKey = keyof typeof es;
export type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string;

const CATALOGS: Record<"es" | "en", Record<MessageKey, string>> = { es, en };

/** Messages of the shell itself (the web app has its own catalogs): Spanish for Spanish
 * locales, English otherwise. */
export function translator(locale: string): Translate {
  const catalog = CATALOGS[locale.toLowerCase().startsWith("es") ? "es" : "en"];
  return (key, vars = {}) =>
    catalog[key].replace(/\{(\w+)\}/g, (match, name: string) => String(vars[name] ?? match));
}
