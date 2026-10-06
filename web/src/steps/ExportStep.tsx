import { useCallback, useState, type FormEvent } from "react";
import { api } from "../api/endpoints";
import type { ExportFile, JobKind, SubtitleFormat } from "../api/types";
import { useT } from "../i18n";
import { JobStages } from "../jobs/JobStages";
import { isRunning, useJob } from "../jobs/useJob";
import { stepPath } from "../routes";
import { Link } from "../shell/AppShell";
import { ErrorNotice, SelectField, TextField } from "../ui/primitives";
import { useResource } from "../ui/useResource";

/** Mirrors the backend's `EXPORT_NAME_PATTERN`: a plain file name without extension. */
const EXPORT_NAME = /^[A-Za-z0-9][A-Za-z0-9._ -]*$/;

export function validExportName(name: string): boolean {
  return name.length <= 100 && EXPORT_NAME.test(name);
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.ceil(bytes / 1024)} KB`;
}

function ExportRow({ projectId, file }: { projectId: string; file: ExportFile }) {
  const t = useT();
  const [error, setError] = useState<unknown>(null);
  const reveal = async () => {
    try {
      await api.revealExport(projectId, file.name);
      setError(null);
    } catch (caught) {
      setError(caught);
    }
  };
  return (
    <li className="export-row">
      <span className="mono">{file.name}</span>
      <span className="meta mono">{formatSize(file.sizeBytes)}</span>
      <span className="meta">{new Date(file.modifiedAt).toLocaleString()}</span>
      <div className="row">
        <a className="button" href={file.url} target="_blank" rel="noreferrer">
          {t("export.open")}
        </a>
        <a className="button quiet" href={file.url} download={file.name}>
          {t("export.download")}
        </a>
        <button type="button" className="quiet" onClick={reveal}>
          {t("export.reveal")}
        </button>
      </div>
      <ErrorNotice error={error} />
    </li>
  );
}

interface StartedJob {
  id: string;
  kind: JobKind;
}

export function ExportStep({ projectId }: { projectId: string }) {
  const t = useT();
  const project = useResource(
    useCallback(
      () => api.projects().then((items) => items.find((item) => item.id === projectId) ?? null),
      [projectId],
    ),
  );
  const exports = useResource(useCallback(() => api.exports(projectId), [projectId]));
  const [name, setName] = useState("final");
  const [format, setFormat] = useState<SubtitleFormat>("srt");
  const [started, setStarted] = useState<StartedJob | null>(null);
  const [startError, setStartError] = useState<unknown>(null);

  const item = project.data;
  const resumed: StartedJob | null =
    item?.activeJobId && item.activeJobKind
      ? { id: item.activeJobId, kind: item.activeJobKind }
      : null;
  const job = started ?? resumed;
  const progress = useJob(job?.id ?? null, () => void exports.reload());
  const busy = isRunning(progress);
  const nameOk = validExportName(name);

  const start = async (action: () => Promise<{ id: string }>, kind: JobKind) => {
    try {
      setStarted({ id: (await action()).id, kind });
      setStartError(null);
    } catch (caught) {
      setStartError(caught);
    }
  };
  const render = (event: FormEvent) => {
    event.preventDefault();
    if (nameOk) void start(() => api.render(projectId, name), "render");
  };

  if (item && item.status !== "analyzed") {
    return (
      <section className="screen">
        <h1>{t("export.title")}</h1>
        <div className="notice notice-warn">
          <p>{t("review.notAnalyzed")}</p>
          <Link to={stepPath("load", projectId) as string} className="button">
            {t("review.toLoad")}
          </Link>
        </div>
      </section>
    );
  }

  const result = progress?.status === "succeeded" ? progress.result : null;
  const resultFile = typeof result?.file === "string" ? result.file : null;
  const produced = exports.data?.find((file) => file.name === resultFile) ?? null;

  return (
    <section className="screen">
      <h1>{t("export.title")}</h1>
      <p className="lede">{t("export.intro")}</p>
      <ErrorNotice error={project.error} />
      <form className="panel" onSubmit={render} noValidate>
        <TextField
          label={t("export.name")}
          value={name}
          onChange={setName}
          mono
          hint={t("export.name.hint")}
          error={nameOk ? undefined : t("export.name.invalid")}
        />
        <button type="submit" className="primary" disabled={busy || !nameOk}>
          {t("export.render")}
        </button>
      </form>
      <div className="panel">
        <h2>{t("export.subtitles")}</h2>
        <div className="row">
          <SelectField
            label={t("export.format")}
            value={format}
            onChange={(value) => setFormat(value as SubtitleFormat)}
            options={[
              { value: "srt", label: "SRT" },
              { value: "ass", label: "ASS" },
            ]}
          />
          <button
            type="button"
            disabled={busy || !nameOk}
            onClick={() =>
              void start(() => api.exportSubtitles(projectId, format, name), "export_subtitles")
            }
          >
            {t("export.subtitlesStart")}
          </button>
        </div>
      </div>
      <ErrorNotice error={startError} />
      {progress && job && <JobStages progress={progress} kind={job.kind} />}
      {produced && (
        <div className="panel result" role="status">
          <h2>{t("export.done")}</h2>
          <ExportRow projectId={projectId} file={produced} />
          {typeof result?.wallSeconds === "number" && (
            <p className="meta">
              {t("export.timing", {
                video: Number(result.videoSeconds ?? 0).toFixed(1),
                wall: result.wallSeconds.toFixed(0),
              })}
            </p>
          )}
        </div>
      )}
      <h2>{t("export.previous")}</h2>
      <ErrorNotice error={exports.error} />
      {exports.data?.length === 0 && <p className="meta">{t("export.none")}</p>}
      <ul className="exports">
        {exports.data?.map((file) => (
          <ExportRow key={file.name} projectId={projectId} file={file} />
        ))}
      </ul>
    </section>
  );
}
