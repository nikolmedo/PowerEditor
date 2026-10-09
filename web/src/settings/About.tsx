import { useCallback, useId, useState } from "react";
import { api } from "../api/endpoints";
import type { UpdateStatus } from "../api/types";
import { useT, type Translate } from "../i18n";
import { useAppStore } from "../store/app";
import { AUTHOR_URL, LICENSE_URL, NOTICES_URL } from "../ui/projectLinks";
import { useResource } from "../ui/useResource";
import { DownloadAction } from "../updates/DownloadAction";
import { desktopUpdates } from "../updates/desktopBridge";

/** App name, engine version, update status, copyright and license. The version comes from
 * the engine, so it is left out while the engine cannot be reached. */
export function About() {
  const t = useT();
  const headingId = useId();
  const health = useResource(useCallback(() => api.health(), []));
  return (
    <section className="about" aria-labelledby={headingId}>
      <h2 id={headingId}>{t("about.title")}</h2>
      <p>
        <strong>{t("app.name")}</strong>
        {health.data && (
          <span className="meta"> {t("about.version", { version: health.data.version })}</span>
        )}
      </p>
      <UpdateCheck />
      <p>
        <a href={AUTHOR_URL} target="_blank" rel="noreferrer">
          {t("about.copyright")}
        </a>
      </p>
      <p className="meta">{t("about.license")}</p>
      <p className="row">
        <a href={LICENSE_URL} target="_blank" rel="noreferrer">
          {t("about.licenseLink")}
        </a>
        <a href={NOTICES_URL} target="_blank" rel="noreferrer">
          {t("about.noticesLink")}
        </a>
      </p>
    </section>
  );
}

function updateSummary(update: UpdateStatus, t: Translate): string {
  if (update.error) return t("error.update_check_failed");
  if (update.updateAvailable && update.latest)
    return t("updates.available", { version: update.latest });
  if (update.latest) return t("about.upToDate");
  if (update.checkedAt) return t("about.noRelease");
  return t("about.updatesOff");
}

/** The last answer of the update check, with "Check now" (which asks GitHub even when
 * automatic checks are off). In the desktop app a newer version can be downloaded and
 * installed from here; a browser only gets the link to the release. This check never asks
 * for a system notification: the user is already looking at the answer. */
function UpdateCheck() {
  const t = useT();
  const language = useAppStore((state) => state.language);
  const [checks, setChecks] = useState(0);
  const updates = useResource(useCallback(() => api.updates(checks > 0), [checks]));
  const update = updates.data;
  return (
    <div className="row" role="group" aria-label={t("about.updates")}>
      <span role="status">
        {updates.loading
          ? t("about.checking")
          : update
            ? updateSummary(update, t)
            : t("error.update_check_failed")}
      </span>
      {update?.updateAvailable && update.releaseUrl && (
        <a href={update.releaseUrl} target="_blank" rel="noreferrer">
          {t("updates.whatsNew")}
        </a>
      )}
      {update?.updateAvailable && update.latest && desktopUpdates() && (
        <DownloadAction
          key={update.latest}
          version={update.latest}
          releaseUrl={update.releaseUrl}
        />
      )}
      {update?.checkedAt && (
        <span className="meta">
          {t("about.lastCheck", { time: new Date(update.checkedAt).toLocaleString(language) })}
        </span>
      )}
      <button
        type="button"
        className="quiet"
        disabled={updates.loading}
        onClick={() => setChecks((count) => count + 1)}
      >
        {t("about.checkNow")}
      </button>
    </div>
  );
}
