import type { MouseEvent, ReactNode } from "react";
import { api } from "../api/endpoints";
import { LANGUAGES, useT, type Language, type MessageKey } from "../i18n";
import { useAppStore } from "../store/app";

export type Step = "load" | "review" | "export";
const STEPS: readonly Step[] = ["load", "review", "export"];

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

export function AppShell({ step, children }: { step: Step | null; children: ReactNode }) {
  const t = useT();
  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">{t("app.name")}</span>
        <ol className="steps" aria-label={t("steps.label")}>
          {STEPS.map((name, index) => (
            <li key={name}>
              <Link to={`/${name}`} className="step">
                <span className="step-index mono">{String(index + 1).padStart(2, "0")}</span>
                {t(`steps.${name}`)}
              </Link>
            </li>
          ))}
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
    </div>
  );
}
