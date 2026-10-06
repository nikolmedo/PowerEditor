import { useCallback, useReducer, useRef, useState, type DragEvent, type FormEvent } from "react";
import { api } from "../api/endpoints";
import type { ProjectOptions, ProjectPreset } from "../api/types";
import { uploadFraction, uploadProject, uploadReducer } from "../api/upload";
import { useT } from "../i18n";
import { JobFailure, JobStages } from "../jobs/JobStages";
import { isRunning, useJob } from "../jobs/useJob";
import { stepPath } from "../routes";
import { Link } from "../shell/AppShell";
import { useAppStore } from "../store/app";
import { ErrorNotice, Field, SelectField, TextField } from "../ui/primitives";
import { useResource } from "../ui/useResource";

const LANGUAGES = ["", "es", "en", "pt", "fr", "de", "it"] as const;
type SourceMode = "upload" | "paths";

export function parsePaths(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/^"(.*)"$/, "$1"))
    .filter(Boolean);
}

function formatSize(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Warns before processing when the transcriber is not ready yet. */
function SetupWarning() {
  const t = useT();
  const setup = useResource(useCallback(() => api.setup(), []));
  const status = setup.data;
  if (!status || status.transcriberReady) return null;
  const local = status.transcriber === "local";
  return (
    <div className="notice notice-warn">
      <p>{local ? t("load.modelMissing", { model: status.whisperModel }) : t("load.keyMissing")}</p>
      <Link to={local ? "/setup" : "/settings"} className="button">
        {local ? t("action.setup") : t("action.settings")}
      </Link>
    </div>
  );
}

function NewProjectForm() {
  const t = useT();
  const navigate = useAppStore((state) => state.navigate);
  const [mode, setMode] = useState<SourceMode>("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [pathsText, setPathsText] = useState("");
  const [name, setName] = useState("");
  const [preset, setPreset] = useState<ProjectPreset>("reel_9x16");
  const [language, setLanguage] = useState("");
  const [script, setScript] = useState("");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [upload, dispatch] = useReducer(uploadReducer, { phase: "idle" });
  const picker = useRef<HTMLInputElement>(null);

  const paths = parsePaths(pathsText);
  const ready = mode === "upload" ? files.length > 0 : paths.length > 0;

  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    setFiles([...files, ...Array.from(event.dataTransfer.files)]);
  };

  const create = async (options: ProjectOptions): Promise<string> => {
    if (mode === "paths") return (await api.createProject(paths, options)).id;
    dispatch({ type: "start", total: files.reduce((sum, file) => sum + file.size, 0) });
    const sent = uploadProject(files, options, (loaded, total) =>
      dispatch({ type: "progress", loaded, total }),
    );
    const { id } = await sent.done;
    dispatch({ type: "done" });
    return id;
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const options: ProjectOptions = { preset };
    if (name.trim()) options.name = name.trim();
    if (language) options.language = language;
    if (script.trim()) options.script = script.trim();
    let id: string;
    try {
      id = await create(options);
    } catch (caught) {
      setError(caught);
      setBusy(false);
      return;
    }
    // A failure to start shows up on the project's page, which offers to process again.
    await api.analyze(id).catch(() => undefined);
    navigate(stepPath("load", id) as string);
  };

  return (
    <form className="load" onSubmit={submit} noValidate>
      <div className="segmented" role="tablist" aria-label={t("load.source")}>
        {(["upload", "paths"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            onClick={() => setMode(value)}
          >
            {t(`load.mode.${value}`)}
          </button>
        ))}
      </div>
      {mode === "upload" ? (
        <div
          className="dropzone"
          data-active={dragging || undefined}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
        >
          <p>{t("load.drop")}</p>
          <button type="button" onClick={() => picker.current?.click()}>
            {t("load.pick")}
          </button>
          <input
            ref={picker}
            type="file"
            accept="video/*"
            multiple
            hidden
            aria-label={t("load.pick")}
            onChange={(event) => setFiles([...files, ...Array.from(event.target.files ?? [])])}
          />
          {files.length > 0 && (
            <ul className="file-list">
              {files.map((file, index) => (
                <li key={`${file.name}-${index}`} className="row spread">
                  <span className="mono">{file.name}</span>
                  <span className="meta mono">{formatSize(file.size)}</span>
                  <button
                    type="button"
                    className="quiet"
                    onClick={() => setFiles(files.filter((_, other) => other !== index))}
                  >
                    {t("load.remove")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <Field label={t("load.paths")} hint={t("load.paths.hint")}>
          {(id, describedBy) => (
            <textarea
              id={id}
              className="mono"
              rows={4}
              aria-describedby={describedBy}
              value={pathsText}
              onChange={(event) => setPathsText(event.target.value)}
            />
          )}
        </Field>
      )}
      <fieldset>
        <legend>{t("load.options")}</legend>
        <div className="field">
          <span className="field-label">{t("load.preset")}</span>
          <div className="choices" role="radiogroup" aria-label={t("load.preset")}>
            {(["reel_9x16", "landscape_16x9"] as const).map((value) => (
              <label key={value} className="choice">
                <input
                  type="radio"
                  name="preset"
                  checked={preset === value}
                  onChange={() => setPreset(value)}
                />
                <span className={`aspect aspect-${value}`} aria-hidden="true" />
                {t(`preset.${value}`)}
              </label>
            ))}
          </div>
        </div>
        <SelectField
          label={t("load.language")}
          value={language}
          onChange={setLanguage}
          options={LANGUAGES.map((code) => ({
            value: code,
            label: code ? code.toUpperCase() : t("load.language.default"),
          }))}
        />
        <TextField label={t("load.name")} value={name} onChange={setName} />
        <Field label={t("load.script")} hint={t("load.script.hint")}>
          {(id, describedBy) => (
            <textarea
              id={id}
              rows={4}
              aria-describedby={describedBy}
              value={script}
              onChange={(event) => setScript(event.target.value)}
            />
          )}
        </Field>
      </fieldset>
      {upload.phase === "uploading" && (
        <div className="row">
          <progress max={1} value={uploadFraction(upload)} aria-label={t("load.uploading")} />
          <span className="meta mono">
            {t("load.uploadProgress", { percent: Math.round(uploadFraction(upload) * 100) })}
          </span>
        </div>
      )}
      <ErrorNotice error={error} />
      <div className="row">
        <button type="submit" className="primary" disabled={!ready || busy}>
          {busy ? t("load.starting") : t("load.process")}
        </button>
      </div>
    </form>
  );
}

/** An existing project: its analysis progress, failure or result. */
function ProcessPanel({ projectId }: { projectId: string }) {
  const t = useT();
  const project = useResource(
    useCallback(
      () => api.projects().then((items) => items.find((item) => item.id === projectId) ?? null),
      [projectId],
    ),
  );
  const [startedId, setStartedId] = useState<string | null>(null);
  const [startError, setStartError] = useState<unknown>(null);
  const item = project.data;
  const activeId = startedId ?? (item?.activeJobKind === "analyze" ? item.activeJobId : null);
  const progress = useJob(activeId, () => void project.reload());
  const running = isRunning(progress);

  const start = async () => {
    try {
      setStartedId((await api.analyze(projectId)).id);
      setStartError(null);
    } catch (caught) {
      setStartError(caught);
    }
  };

  if (project.loading && !item) return <p className="lede">{t("common.loading")}</p>;
  if (!item) return <ErrorNotice error={project.error ?? new Error("not found")} />;
  const analyzed = item.status === "analyzed";
  const failure = progress ? null : item.lastError;

  return (
    <>
      <p className="lede">{t("load.projectIntro", { name: item.name })}</p>
      {!running && !analyzed && <SetupWarning />}
      {progress && <JobStages progress={progress} kind="analyze" />}
      {failure && <JobFailure {...failure} />}
      <ErrorNotice error={startError} />
      <div className="row">
        {analyzed && !running && (
          <Link to={stepPath("review", projectId) as string} className="button primary">
            {t("load.review")}
          </Link>
        )}
        {!running && (
          <button type="button" className={analyzed ? "quiet" : "primary"} onClick={start}>
            {analyzed ? t("load.reprocess") : t("load.process")}
          </button>
        )}
      </div>
    </>
  );
}

export function LoadStep({ projectId }: { projectId: string | null }) {
  const t = useT();
  return (
    <section className="screen">
      <h1>{t("load.title")}</h1>
      {projectId ? (
        <ProcessPanel projectId={projectId} />
      ) : (
        <>
          <p className="lede">{t("load.intro")}</p>
          <SetupWarning />
          <NewProjectForm />
        </>
      )}
    </section>
  );
}
