import { useEffect, type ReactNode } from "react";
import { api } from "./api/endpoints";
import { LANGUAGES, type Language } from "./i18n";
import { FeaturesScreen } from "./settings/FeaturesScreen";
import { ProvidersScreen } from "./settings/ProvidersScreen";
import { SettingsScreen } from "./settings/SettingsScreen";
import { SetupScreen } from "./settings/SetupScreen";
import { AppShell, type Step } from "./shell/AppShell";
import { ProjectsHome } from "./shell/ProjectsHome";
import { StepPlaceholder } from "./shell/StepPlaceholder";
import { useAppStore } from "./store/app";

const STEP_PATHS: Record<string, Step> = {
  "/load": "load",
  "/review": "review",
  "/export": "export",
};

function screenFor(path: string): ReactNode {
  const step = STEP_PATHS[path];
  if (step) return <StepPlaceholder step={step} />;
  switch (path) {
    case "/setup":
      return <SetupScreen />;
    case "/settings":
      return <SettingsScreen />;
    case "/settings/providers":
      return <ProvidersScreen />;
    case "/settings/features":
      return <FeaturesScreen />;
    default:
      return <ProjectsHome />;
  }
}

export function App() {
  const { path, theme, language, setLanguage, syncPath } = useAppStore();

  useEffect(() => {
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, [syncPath]);

  useEffect(() => {
    api
      .settings()
      .then(({ settings }) => {
        const saved = settings.uiLanguage as Language;
        if (LANGUAGES.includes(saved)) setLanguage(saved);
      })
      .catch(() => undefined); // Screens report an unreachable server themselves.
  }, [setLanguage]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.lang = language;
  }, [theme, language]);

  return <AppShell step={STEP_PATHS[path] ?? null}>{screenFor(path)}</AppShell>;
}
