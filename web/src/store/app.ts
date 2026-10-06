import { create } from "zustand";
import type { Language } from "../i18n";

export type Theme = "dark" | "light";
const THEME_KEY = "powereditor.theme";

function storedTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

interface AppState {
  language: Language;
  theme: Theme;
  path: string;
  setLanguage: (language: Language) => void;
  setTheme: (theme: Theme) => void;
  navigate: (path: string) => void;
  syncPath: () => void;
}

/** UI-wide state. The language is persisted by the backend (`uiLanguage`); the theme is a
 * per-browser preference. */
export const useAppStore = create<AppState>((set) => ({
  language: "es",
  theme: storedTheme(),
  path: window.location.pathname,
  setLanguage: (language) => set({ language }),
  setTheme: (theme) => {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Storage can be unavailable; the theme still applies for this session.
    }
    set({ theme });
  },
  navigate: (path) => {
    window.history.pushState(null, "", path);
    set({ path });
  },
  syncPath: () => set({ path: window.location.pathname }),
}));
