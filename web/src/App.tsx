import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { api } from "./api/endpoints";
import { LANGUAGES, useT, type Language } from "./i18n";
import { parseRoute, type Route } from "./routes";
import { FeaturesScreen } from "./settings/FeaturesScreen";
import { ProvidersScreen } from "./settings/ProvidersScreen";
import { SettingsScreen } from "./settings/SettingsScreen";
import { SetupScreen } from "./settings/SetupScreen";
import { AppShell } from "./shell/AppShell";
import { ProjectsHome } from "./shell/ProjectsHome";
import { ExportStep } from "./steps/ExportStep";
import { LoadStep } from "./steps/LoadStep";
import { useAppStore } from "./store/app";

// The player and the composition are the heaviest part of the bundle: load them on demand.
const ReviewStep = lazy(() =>
  import("./review/ReviewStep").then((module) => ({ default: module.ReviewStep })),
);

function Loading() {
  const t = useT();
  return <p className="lede">{t("common.loading")}</p>;
}

function screenFor(route: Route): ReactNode {
  switch (route.screen) {
    case "load":
      return <LoadStep key={route.projectId ?? "new"} projectId={route.projectId} />;
    case "review":
      return (
        <Suspense fallback={<Loading />}>
          <ReviewStep key={route.projectId} projectId={route.projectId} />
        </Suspense>
      );
    case "export":
      return <ExportStep key={route.projectId} projectId={route.projectId} />;
    case "setup":
      return <SetupScreen />;
    case "settings":
      return <SettingsScreen />;
    case "providers":
      return <ProvidersScreen />;
    case "features":
      return <FeaturesScreen />;
    case "home":
      return <ProjectsHome />;
  }
}

export function App() {
  const { path, theme, language, setLanguage, syncPath } = useAppStore();
  const route = parseRoute(path);

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

  const step = "projectId" in route ? route.screen : null;
  const projectId = "projectId" in route ? route.projectId : null;
  return (
    <AppShell step={step} projectId={projectId}>
      {screenFor(route)}
    </AppShell>
  );
}
