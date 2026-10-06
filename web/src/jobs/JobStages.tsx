import { useState } from "react";
import { ApiError, errorMessage } from "../api/client";
import { api } from "../api/endpoints";
import type { JobKind } from "../api/types";
import { isMessageKey, useT } from "../i18n";
import { Link } from "../shell/AppShell";
import { errorAction } from "../steps/errorActions";
import { ErrorNotice } from "../ui/primitives";
import { stageRows, type JobProgress } from "./jobProgress";

const percent = (fraction: number) => `${Math.round(fraction * 100)} %`;

/** A failed job's message with a link to the screen that can fix it. */
export function JobFailure({ code, message }: { code: string; message: string }) {
  const t = useT();
  const action = errorAction(code);
  return (
    <div className="notice notice-bad" role="alert">
      <p>{errorMessage(new ApiError(0, code, message), t)}</p>
      {action && (
        <Link to={action.to} className="button">
          {t(action.label)}
        </Link>
      )}
    </div>
  );
}

/** Live stage list of a job with its fractions and a cancel button while it runs. */
export function JobStages({ progress, kind }: { progress: JobProgress; kind: JobKind }) {
  const t = useT();
  const [cancelError, setCancelError] = useState<unknown>(null);
  const running = progress.status === "queued" || progress.status === "running";
  const cancel = async () => {
    try {
      await api.cancelJob(progress.jobId);
    } catch (caught) {
      setCancelError(caught);
    }
  };

  return (
    <div className="panel job" aria-live="polite">
      <ol className="stages">
        {stageRows(progress, kind).map((row) => {
          const key = `stage.${row.stage}`;
          return (
            <li key={row.stage} className="stage" data-state={row.state}>
              <span className="stage-dot" aria-hidden="true" />
              <span>{isMessageKey(key) ? t(key) : row.stage}</span>
              <span className="mono meta">
                {row.state === "active" ? percent(row.fraction) : t(`stageState.${row.state}`)}
              </span>
              {row.state === "active" && (
                <progress max={1} value={row.fraction} aria-label={t("job.progress")} />
              )}
            </li>
          );
        })}
      </ol>
      {running && (
        <button type="button" className="quiet danger" onClick={cancel}>
          {t("job.cancel")}
        </button>
      )}
      {progress.status === "cancelled" && <p className="notice">{t("job.cancelled")}</p>}
      {progress.error && <JobFailure {...progress.error} />}
      <ErrorNotice error={cancelError} />
    </div>
  );
}
