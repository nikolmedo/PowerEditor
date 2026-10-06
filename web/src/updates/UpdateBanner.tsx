import { useCallback, useEffect, useState } from "react";
import { api } from "../api/endpoints";
import type { UpdateStatus } from "../api/types";
import { useT, type Translate } from "../i18n";
import { useResource } from "../ui/useResource";
import { desktopUpdates, type DesktopUpdateState } from "./desktopBridge";
import { dismissVersion, dismissedVersion } from "./dismissal";

/** A discreet notice when a newer published release exists. It respects the
 * `checkForUpdates` setting (the engine answers `enabled: false`) and stays hidden for a
 * version the user dismissed. */
export function UpdateBanner() {
  const updates = useResource(useCallback(() => api.updates(), []));
  const [dismissed, setDismissed] = useState(dismissedVersion);
  const update = updates.data;
  if (!update?.enabled || !update.updateAvailable || !update.latest) return null;
  if (dismissed === update.latest) return null;
  const latest = update.latest;
  const dismiss = () => {
    dismissVersion(latest);
    setDismissed(latest);
  };
  return <UpdateNotice update={update} version={latest} onDismiss={dismiss} />;
}

function UpdateNotice({
  update,
  version,
  onDismiss,
}: {
  update: UpdateStatus;
  version: string;
  onDismiss: () => void;
}) {
  const t = useT();
  const desktop = desktopUpdates();
  const [download, setDownload] = useState<DesktopUpdateState>({ status: "idle" });
  useEffect(() => desktop?.onState(setDownload), [desktop]);

  const start = () => {
    if (!desktop) {
      if (update.releaseUrl) window.open(update.releaseUrl, "_blank", "noreferrer");
      return;
    }
    void desktop.download(version).then((state) => {
      if (state) setDownload(state);
    });
  };
  const install = () => void desktop?.installAndQuit();

  return (
    <section className="notice notice-ok update-banner" aria-label={t("updates.label")}>
      <span>{t("updates.available", { version })}</span>
      {update.releaseUrl && (
        <a href={update.releaseUrl} target="_blank" rel="noreferrer">
          {t("updates.whatsNew")}
        </a>
      )}
      <DownloadAction state={download} t={t} onStart={start} onInstall={install} />
      <button type="button" className="quiet" aria-label={t("updates.dismiss")} onClick={onDismiss}>
        ×
      </button>
    </section>
  );
}

function DownloadAction({
  state,
  t,
  onStart,
  onInstall,
}: {
  state: DesktopUpdateState;
  t: Translate;
  onStart: () => void;
  onInstall: () => void;
}) {
  switch (state.status) {
    case "downloading":
      return (
        <span role="status">
          {state.total
            ? t("updates.downloading", {
                percent: Math.floor((state.received / state.total) * 100),
              })
            : t("updates.downloadingUnknown")}
        </span>
      );
    case "verifying":
      return <span role="status">{t("updates.verifying")}</span>;
    case "ready":
      return (
        <button type="button" className="primary" onClick={onInstall}>
          {t("updates.install")}
        </button>
      );
    case "failed":
      return (
        <>
          <span role="alert">{t("updates.failed")}</span>
          <button type="button" onClick={onStart}>
            {t("updates.retry")}
          </button>
        </>
      );
    default:
      return (
        <button type="button" className="primary" onClick={onStart}>
          {t("updates.download")}
        </button>
      );
  }
}
