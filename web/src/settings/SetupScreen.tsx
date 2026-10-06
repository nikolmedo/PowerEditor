import { useCallback, useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { watchJob } from "../api/jobs";
import type { DependencyCheck, JobEvent } from "../api/types";
import { isMessageKey, useT } from "../i18n";
import { Link } from "../shell/AppShell";
import { ErrorNotice, Status } from "../ui/primitives";
import { useResource } from "../ui/useResource";

function CheckRow({ check }: { check: DependencyCheck }) {
  const t = useT();
  const hintKey = `setup.hint.${check.name}`;
  const label = check.found
    ? t("setup.found")
    : check.required
      ? t("setup.missing")
      : t("setup.optional");
  return (
    <li className="check">
      <span className="mono check-name">{check.name}</span>
      <Status ok={check.found ? true : check.required ? false : null}>{label}</Status>
      <span className="mono meta">{check.version ?? ""}</span>
      {!check.found && isMessageKey(hintKey) && <p className="check-hint">{t(hintKey)}</p>}
    </li>
  );
}

function useJobProgress(jobId: string | null, onDone: () => void): JobEvent | null {
  const [event, setEvent] = useState<JobEvent | null>(null);
  useEffect(() => {
    if (!jobId) return;
    return watchJob(jobId, (next) => {
      setEvent(next);
      if (next.status === "succeeded") onDone();
    });
  }, [jobId, onDone]);
  return event;
}

export function SetupScreen() {
  const t = useT();
  const setup = useResource(useCallback(() => api.setup(), []));
  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<unknown>(null);
  const { reload } = setup;
  const activeJob = jobId ?? setup.data?.whisperDownloadJobId ?? null;
  const progress = useJobProgress(
    activeJob,
    useCallback(() => void reload(), [reload]),
  );
  const downloading = progress !== null && ["queued", "running"].includes(progress.status);

  const download = async () => {
    try {
      setJobId((await api.downloadWhisperModel()).id);
      setStartError(null);
    } catch (caught) {
      setStartError(caught);
    }
  };

  const status = setup.data;
  return (
    <section className="screen">
      <h1>{t("setup.title")}</h1>
      <p className="lede">{t("setup.intro")}</p>
      <ErrorNotice error={setup.error} />
      {status && (
        <>
          <p className={`notice ${status.ready ? "notice-ok" : "notice-warn"}`}>
            {status.ready ? t("setup.ready") : t("setup.notReady")}
          </p>
          <h2>{t("setup.tools")}</h2>
          <ul className="checks">
            {status.doctor.checks.map((check) => (
              <CheckRow key={check.name} check={check} />
            ))}
          </ul>
          <h2>{t("setup.transcription")}</h2>
          <div className="panel">
            <div className="row spread">
              <span>{t("setup.whisperModel", { model: status.whisperModel })}</span>
              <Status ok={status.whisperModelDownloaded}>
                {status.whisperModelDownloaded ? t("setup.downloaded") : t("setup.notDownloaded")}
              </Status>
            </div>
            {!status.whisperModelDownloaded && (
              <button type="button" className="primary" disabled={downloading} onClick={download}>
                {downloading
                  ? t("setup.downloading", { percent: Math.round(progress.fraction * 100) })
                  : t("setup.download")}
              </button>
            )}
            {downloading && (
              <progress max={1} value={progress.fraction} aria-label={t("setup.download")} />
            )}
            {progress?.error && <p className="notice notice-bad">{progress.error.message}</p>}
            <ErrorNotice error={startError} />
          </div>
          <div className="panel">
            <p>{status.openaiKeySet ? t("setup.openaiKeySet") : t("setup.openaiInstead")}</p>
            <Link to="/settings" className="button">
              {t("setup.configureOpenAi")}
            </Link>
          </div>
        </>
      )}
    </section>
  );
}
