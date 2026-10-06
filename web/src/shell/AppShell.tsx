import type { MouseEvent, ReactNode } from "react";
import { api } from "../api/endpoints";
import { LANGUAGES, useT, type Language, type MessageKey } from "../i18n";
import { STEPS, stepPath, type Step } from "../routes";
import { useAppStore } from "../store/app";
import { AUTHOR_URL } from "../ui/projectLinks";

const NAV: readonly { path: string; key: MessageKey; nested?: boolean }[] = [
  { path: "/", key: "nav.projects" },
  { path: "/setup", key: "nav.setup" },
  { path: "/settings", key: "nav.general", nested: true },
  { path: "/settings/providers", key: "nav.providers", nested: true },
  { path: "/settings/features", key: "nav.features", nested: true },
];

/** A same-app link: updates the URL without reloading the page. */
export function Link({
  to,
  children,
  className,
}: {
  to: string;
  children: ReactNode;
  className?: string;
}) {
  const { path, navigate } = useAppStore();
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(to);
  };
  return (
    <a
      href={to}
      className={className}
      aria-current={path === to ? "page" : undefined}
      onClick={follow}
    >
      {children}
    </a>
  );
}

function Preferences() {
  const t = useT();
  const { theme, setTheme, language, setLanguage } = useAppStore();
  const changeLanguage = (next: Language) => {
    setLanguage(next);
    void api.updateSettings({ uiLanguage: next }).catch(() => undefined);
  };
  return (
    <div className="preferences">
      <select
        aria-label={t("language.label")}
        value={language}
        onChange={(event) => changeLanguage(event.target.value as Language)}
      >
        {LANGUAGES.map((code) => (
          <option key={code} value={code}>
            {code.toUpperCase()}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="quiet"
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      >
        {theme === "dark" ? t("theme.light") : t("theme.dark")}
      </button>
    </div>
  );
}

interface ShellProps {
  step: Step | null;
  projectId: string | null;
  children: ReactNode;
}

export function AppShell({ step, projectId, children }: ShellProps) {
  const t = useT();
  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">{t("app.name")}</span>
        <ol className="steps" aria-label={t("steps.label")}>
          {STEPS.map((name, index) => {
            const to = stepPath(name, projectId);
            const label = (
              <>
                <span className="step-index mono">{String(index + 1).padStart(2, "0")}</span>
                {t(`steps.${name}`)}
              </>
            );
            return (
              <li key={name}>
                {to ? (
                  <Link to={to} className="step">
                    {label}
                  </Link>
                ) : (
                  <span className="step" aria-disabled="true" title={t("steps.needsProject")}>
                    {label}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
        <Preferences />
      </header>
      <nav className="sidebar" aria-label={t("nav.main")}>
        {NAV.map((item, index) => (
          <div key={item.path}>
            {item.nested && !NAV[index - 1]?.nested && (
              <p className="sidebar-group">{t("nav.settings")}</p>
            )}
            <Link to={item.path} className="sidebar-link">
              {t(item.key)}
            </Link>
          </div>
        ))}
      </nav>
      <main className="content" data-step={step ?? undefined}>
        {children}
      </main>
      <footer className="app-footer">
        <a href={AUTHOR_URL} target="_blank" rel="noreferrer">
          {t("about.copyright")}
        </a>
      </footer>
    </div>
  );
}
