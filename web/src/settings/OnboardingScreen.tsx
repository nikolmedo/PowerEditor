import { useCallback, useState } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { watchJob } from "../api/jobs";
import type { JobEvent, SetupStatus } from "../api/types";
import { useT, type MessageKey } from "../i18n";
import { Link } from "../shell/AppShell";
import { useAppStore } from "../store/app";
import { ErrorNotice, SecretField, Status } from "../ui/primitives";
import { useResource } from "../ui/useResource";
import { formatMegabytes, missingRuntimes, RUNTIME_ORDER, skipOnboarding } from "./onboarding";

type StepId = "runtimes" | "transcription" | "providers";
const STEPS: readonly StepId[] = ["runtimes", "transcription", "providers"];

/** Resolve with the job's terminal event, reporting its progress on the way. */
function followJob(jobId: string, onFraction: (fraction: number) => void): Promise<JobEvent> {
  return new Promise((resolve) => {
    const stop = watchJob(jobId, (event) => {
      onFraction(event.fraction);
      if (
        event.status === "succeeded" ||
        event.status === "failed" ||
        event.status === "cancelled"
      ) {
        resolve(event);
        queueMicrotask(() => stop());
      }
    });
  });
}

function useJobRunner() {
  const [label, setLabel] = useState<string | null>(null);
  const [fraction, setFraction] = useState(0);
  const [error, setError] = useState<unknown>(null);
  /** Run the jobs one after the other; false when one failed. */
  const run = async (jobs: { label: string; start: () => Promise<{ id: string }> }[]) => {
    setError(null);
    try {
      for (const job of jobs) {
        setLabel(job.label);
        setFraction(0);
        const end = await followJob((await job.start()).id, setFraction);
        if (end.status !== "succeeded") {
          setError(new ApiError(0, end.error?.code ?? null, end.error?.message ?? end.status));
          return false;
        }
      }
      return true;
    } catch (caught) {
      setError(caught);
      return false;
    } finally {
      setLabel(null);
    }
  };
  return { label, fraction, error, run };
}

interface StepProps {
  status: SetupStatus;
  reload: () => Promise<void>;
  next: () => void;
}

function RuntimesStep({ status, reload, next }: StepProps) {
  const t = useT();
  const runner = useJobRunner();
  const missing = missingRuntimes(status);
  const total = missing.reduce((sum, runtime) => sum + (runtime.downloadBytes ?? 0), 0);
  const runtimes = [...status.runtimes].sort(
    (a, b) => RUNTIME_ORDER.indexOf(a.name) - RUNTIME_ORDER.indexOf(b.name),
  );
  const nameOf = (name: string) => t(`onboarding.runtime.${name}` as MessageKey);

  const installAll = async () => {
    await runner.run(
      missing.map((runtime) => ({
        label: nameOf(runtime.name),
        start: () => api.installRuntime(runtime.name),
      })),
    );
    await reload();
  };
  return (
    <>
      <h2>{t("onboarding.runtimes.title")}</h2>
      <p className="lede">{t("onboarding.runtimes.intro")}</p>
      <ul className="checks">
        {runtimes.map((runtime) => {
          const pending = missing.includes(runtime);
          const label = runtime.installed
            ? t("onboarding.runtimes.installed")
            : !runtime.supported
              ? t("onboarding.runtimes.unsupported")
              : pending
                ? t("onboarding.runtimes.pending")
                : t("onboarding.runtimes.found");
          return (
            <li key={runtime.name} className="check">
              <span className="check-name">{nameOf(runtime.name)}</span>
              <Status ok={pending ? null : true}>{label}</Status>
              <span className="mono meta">
                {pending ? formatMegabytes(runtime.downloadBytes) : ""}
              </span>
            </li>
          );
        })}
      </ul>
      {runner.label && (
        <div className="onboarding-progress">
          <span>
            {t("onboarding.runtimes.installing", {
              name: runner.label,
              percent: Math.round(runner.fraction * 100),
            })}
          </span>
          <progress max={1} value={runner.fraction} aria-label={runner.label} />
        </div>
      )}
      <ErrorNotice error={runner.error} />
      {missing.length === 0 ? (
        <>
          <p className="notice notice-ok">{t("onboarding.runtimes.done")}</p>
          <div className="row">
            <button type="button" className="primary" onClick={next}>
              {t("onboarding.next")}
            </button>
          </div>
        </>
      ) : (
        <div className="row">
          <button type="button" className="primary" disabled={!!runner.label} onClick={installAll}>
            {t("onboarding.runtimes.installAll")}
          </button>
          {total > 0 && <span className="mono meta">{formatMegabytes(total)}</span>}
          <button type="button" className="quiet" disabled={!!runner.label} onClick={next}>
            {t("onboarding.skipStep")}
          </button>
        </div>
      )}
      {missing.length > 0 && <p className="meta">{t("onboarding.runtimes.skipHint")}</p>}
    </>
  );
}

function TranscriptionStep({ status, reload, next }: StepProps) {
  const t = useT();
  const runner = useJobRunner();
  const downloadModel = async () => {
    await runner.run([{ label: status.whisperModel, start: () => api.downloadWhisperModel() }]);
    await reload();
  };
  const useOpenAi = async (value: string) => {
    await api.storeOpenAiKey(value);
    await api.updateSettings({ transcriber: "openai" });
    await reload();
  };

  return (
    <>
      <h2>{t("onboarding.transcription.title")}</h2>
      <p className="lede">{t("onboarding.transcription.intro")}</p>
      {status.transcriberReady && (
        <p className="notice notice-ok">{t("onboarding.transcription.ready")}</p>
      )}
      <div className="onboarding-choices">
        <div className="panel">
          <h3>{t("onboarding.transcription.local")}</h3>
          <p>{t("onboarding.transcription.localHint", { model: status.whisperModel })}</p>
          {status.whisperModelDownloaded ? (
            <Status ok>{t("setup.downloaded")}</Status>
          ) : (
            <button type="button" disabled={!!runner.label} onClick={downloadModel}>
              {runner.label
                ? t("setup.downloading", { percent: Math.round(runner.fraction * 100) })
                : t("setup.download")}
            </button>
          )}
          <ErrorNotice error={runner.error} />
        </div>
        <div className="panel">
          <h3>{t("onboarding.transcription.cloud")}</h3>
          <p>{t("onboarding.transcription.cloudHint")}</p>
          <SecretField
            label={t("settings.openaiKey")}
            status={{ set: status.openaiKeySet }}
            onSave={useOpenAi}
          />
        </div>
      </div>
      <div className="row">
        <button
          type="button"
          className={status.transcriberReady ? "primary" : "quiet"}
          onClick={next}
        >
          {status.transcriberReady ? t("onboarding.next") : t("onboarding.skipStep")}
        </button>
      </div>
    </>
  );
}

function ProvidersStep({ finish }: { finish: () => void }) {
  const t = useT();
  return (
    <>
      <h2>{t("onboarding.providers.title")}</h2>
      <p className="lede">{t("onboarding.providers.intro")}</p>
      <div className="row">
        <Link to="/settings/providers" className="button">
          {t("onboarding.providers.open")}
        </Link>
        <button type="button" className="primary" onClick={finish}>
          {t("onboarding.finish")}
        </button>
      </div>
    </>
  );
}

/** First-run guide: download the runtimes, pick a transcriber, optionally add AI models. */
export function OnboardingScreen() {
  const t = useT();
  const navigate = useAppStore((state) => state.navigate);
  const setup = useResource(useCallback(() => api.setup(), []));
  const [step, setStep] = useState<StepId>("runtimes");
  const status = setup.data;
  const advance = (from: StepId) => setStep(STEPS[STEPS.indexOf(from) + 1] ?? from);
  const leave = () => {
    skipOnboarding();
    navigate("/");
  };

  return (
    <section className="screen onboarding">
      <div className="row spread">
        <h1>{t("onboarding.title")}</h1>
        <button type="button" className="quiet" onClick={leave}>
          {t("onboarding.skipAll")}
        </button>
      </div>
      <p className="lede">{t("onboarding.intro")}</p>
      <ol className="onboarding-steps">
        {STEPS.map((id, index) => (
          <li key={id}>
            <button
              type="button"
              className="onboarding-step"
              aria-current={id === step ? "step" : undefined}
              onClick={() => setStep(id)}
            >
              <span className="step-index mono">{String(index + 1).padStart(2, "0")}</span>
              {t(`onboarding.step.${id}`)}
              {id === "providers" && <span className="meta">{t("onboarding.optional")}</span>}
            </button>
          </li>
        ))}
      </ol>
      <ErrorNotice error={setup.error} />
      {status && (
        <div className="onboarding-body">
          {step === "runtimes" && (
            <RuntimesStep status={status} reload={setup.reload} next={() => advance("runtimes")} />
          )}
          {step === "transcription" && (
            <TranscriptionStep
              status={status}
              reload={setup.reload}
              next={() => advance("transcription")}
            />
          )}
          {step === "providers" && <ProvidersStep finish={() => navigate("/")} />}
        </div>
      )}
    </section>
  );
}
