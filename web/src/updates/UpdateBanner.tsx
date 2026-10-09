import { useCallback, useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { useT } from "../i18n";
import { useResource } from "../ui/useResource";
import { DownloadAction } from "./DownloadAction";
import { desktopUpdates } from "./desktopBridge";
import { dismissVersion, dismissedVersion } from "./dismissal";

/** How often an open app asks again; the engine answers from its cache in between. */
const RECHECK_MS = 6 * 60 * 60 * 1000;

/** A discreet notice when a newer published release exists. It respects the
 * `checkForUpdates` setting (the engine answers `enabled: false`) and stays hidden for a
 * version the user dismissed. In the desktop app a version found this way is also announced
 * with a system notification, which the shell shows once per version. */
export function UpdateBanner() {
  const t = useT();
  const updates = useResource(useCallback(() => api.updates(), []));
  const [dismissed, setDismissed] = useState(dismissedVersion);
  const update = updates.data;
  const shown =
    update?.enabled && update.updateAvailable && update.latest && update.latest !== dismissed
      ? update.latest
      : null;

  const { reload } = updates;
  useEffect(() => {
    const timer = setInterval(() => void reload(), RECHECK_MS);
    return () => clearInterval(timer);
  }, [reload]);

  useEffect(() => {
    const desktop = desktopUpdates();
    // Best effort: the banner still tells the user when the shell shows nothing.
    if (shown && desktop) desktop.notifyAvailable(shown).catch(() => undefined);
  }, [shown]);

  if (!shown) return null;
  const dismiss = () => {
    dismissVersion(shown);
    setDismissed(shown);
  };
  const releaseUrl = update?.releaseUrl ?? null;
  return (
    <section className="notice notice-ok update-banner" aria-label={t("updates.label")}>
      <span>{t("updates.available", { version: shown })}</span>
      {releaseUrl && (
        <a href={releaseUrl} target="_blank" rel="noreferrer">
          {t("updates.whatsNew")}
        </a>
      )}
      <DownloadAction key={shown} version={shown} releaseUrl={releaseUrl} />
      <button type="button" className="quiet" aria-label={t("updates.dismiss")} onClick={dismiss}>
        ×
      </button>
    </section>
  );
}
