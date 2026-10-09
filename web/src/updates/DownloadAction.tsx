import { useT } from "../i18n";
import { useUpdateDownload } from "./useUpdateDownload";

/** Download, progress, check, then "Restart and update", with a retry after a failure. Give it
 * `key={version}` so a newer version starts from a fresh download. */
export function DownloadAction({
  version,
  releaseUrl,
}: {
  version: string;
  releaseUrl: string | null;
}) {
  const t = useT();
  const { state, start, install } = useUpdateDownload(version, releaseUrl);
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
        <button type="button" className="primary" onClick={install}>
          {t("updates.install")}
        </button>
      );
    case "failed":
      return (
        <>
          <span role="alert">{t("updates.failed")}</span>
          <button type="button" onClick={start}>
            {t("updates.retry")}
          </button>
        </>
      );
    default:
      return (
        <button type="button" className="primary" onClick={start}>
          {t("updates.download")}
        </button>
      );
  }
}
