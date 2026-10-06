import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import type { SettingsResponse, UserSettings } from "../api/types";
import { isMessageKey, useT } from "../i18n";
import { ErrorNotice, SecretField, SelectField, TextField } from "../ui/primitives";
import { useResource } from "../ui/useResource";
import { About } from "./About";

type Form = Record<string, string>;

const TEXT_FIELDS = ["language", "whisperModel", "ffmpegPath", "ffprobePath", "nodePath"] as const;
const NUMBER_FIELDS = [
  "silencePaddingMs",
  "audioCrossfadeMs",
  "targetLufs",
  "punchInScale",
  "modelMinConfidence",
  "renderMaxConcurrency",
] as const;
const BOOLEAN_FIELDS = ["autoCta"] as const;
const WEIGHT_PREFIX = "takeWeights.";

function toForm(settings: UserSettings): Form {
  const form: Form = { transcriber: settings.transcriber, whisperDevice: settings.whisperDevice };
  for (const name of TEXT_FIELDS) form[name] = settings[name] ?? "";
  for (const name of NUMBER_FIELDS) form[name] = String(settings[name]);
  for (const name of BOOLEAN_FIELDS) form[name] = String(settings[name]);
  for (const [name, weight] of Object.entries(settings.takeWeights)) {
    form[WEIGHT_PREFIX + name] = String(weight);
  }
  return form;
}

/** The PATCH body: only changed fields, blanks as null, numbers as numbers. A value that is
 * not a number is sent as typed so the backend's validation message reaches the field. */
export function settingsChanges(before: Form, after: Form): Record<string, unknown> {
  const changes: Record<string, unknown> = {};
  const weights: Record<string, unknown> = {};
  const asNumber = (value: string) =>
    value.trim() !== "" && Number.isFinite(Number(value)) ? Number(value) : value;
  for (const [name, value] of Object.entries(after)) {
    if (before[name] === value) continue;
    if (name.startsWith(WEIGHT_PREFIX)) weights[name.slice(WEIGHT_PREFIX.length)] = asNumber(value);
    else if ((NUMBER_FIELDS as readonly string[]).includes(name)) changes[name] = asNumber(value);
    else if ((BOOLEAN_FIELDS as readonly string[]).includes(name)) changes[name] = value === "true";
    else
      changes[name] =
        (TEXT_FIELDS as readonly string[]).includes(name) && !value.trim() ? null : value;
  }
  if (Object.keys(weights).length > 0) changes.takeWeights = weights;
  return changes;
}

export function SettingsScreen() {
  const t = useT();
  const resource = useResource(useCallback(() => api.settings(), []));
  const [saved, setSaved] = useState<Form>({});
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");

  const apply = useCallback((response: SettingsResponse) => {
    setSaved(toForm(response.settings));
    setForm(toForm(response.settings));
  }, []);
  // Only the first load fills the form; a later reload (after a key change) keeps edits.
  const loaded = form !== null;
  useEffect(() => {
    if (resource.data && !loaded) apply(resource.data);
  }, [resource.data, loaded, apply]);

  const data = resource.data;
  if (!data || !form)
    return (
      <section className="screen">
        <ErrorNotice error={resource.error} />
      </section>
    );

  const fieldErrors = error instanceof ApiError ? error.fieldErrors : {};
  const label = (key: string) => (isMessageKey(key) ? t(key) : key);
  const bind = (name: string, labelKey: string) => ({
    label: label(labelKey),
    value: form[name] ?? "",
    onChange: (value: string) => setForm({ ...form, [name]: value }),
    error: fieldErrors[name],
  });
  const select = (name: string, values: readonly string[], prefix: string) => ({
    ...bind(name, prefix),
    options: values.map((value) => ({ value, label: label(`${prefix}.${value}`) })),
  });

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setStatus("saving");
    try {
      const response = await api.updateSettings(settingsChanges(saved, form));
      resource.setData(response);
      apply(response);
      setError(null);
      setStatus("saved");
    } catch (caught) {
      setError(caught);
      setStatus("idle");
    }
  };
  const updateKey = async (action: Promise<unknown>) => {
    await action;
    await resource.reload();
  };

  return (
    <section className="screen">
      <h1>{t("settings.title")}</h1>
      <form onSubmit={save} noValidate>
        <fieldset>
          <legend>{t("settings.section.transcription")}</legend>
          <SelectField {...select("transcriber", ["local", "openai"], "settings.transcriber")} />
          <TextField
            {...bind("language", "settings.language")}
            hint={t("settings.language.hint")}
          />
          <TextField
            {...bind("whisperModel", "settings.whisperModel")}
            hint={t("settings.whisperModel.hint", { model: data.resolvedWhisperModel })}
          />
          <SelectField
            {...select("whisperDevice", ["auto", "cuda", "cpu"], "settings.whisperDevice")}
          />
        </fieldset>
        <fieldset>
          <legend>{t("settings.section.audio")}</legend>
          <TextField
            inputMode="decimal"
            {...bind("silencePaddingMs", "settings.silencePaddingMs")}
          />
          <TextField
            inputMode="decimal"
            {...bind("audioCrossfadeMs", "settings.audioCrossfadeMs")}
          />
          <TextField inputMode="decimal" {...bind("targetLufs", "settings.targetLufs")} />
          <TextField inputMode="decimal" {...bind("punchInScale", "settings.punchInScale")} />
          <TextField
            inputMode="decimal"
            {...bind("renderMaxConcurrency", "settings.renderMaxConcurrency")}
            hint={t("settings.renderMaxConcurrency.hint")}
          />
        </fieldset>
        <fieldset>
          <legend>{t("settings.section.takes")}</legend>
          <TextField
            inputMode="decimal"
            {...bind("modelMinConfidence", "settings.modelMinConfidence")}
            hint={t("settings.modelMinConfidence.hint")}
          />
          <label className="toggle">
            <input
              type="checkbox"
              checked={form.autoCta === "true"}
              onChange={(event) => setForm({ ...form, autoCta: String(event.target.checked) })}
            />
            {t("settings.autoCta")}
          </label>
          <p className="meta">{t("settings.autoCta.hint")}</p>
          <p className="subhead">{t("settings.takeWeights")}</p>
          <div className="grid-weights">
            {Object.keys(data.settings.takeWeights).map((name) => (
              <TextField
                key={name}
                inputMode="decimal"
                {...bind(WEIGHT_PREFIX + name, `weight.${name}`)}
              />
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("settings.section.tools")}</legend>
          {(["ffmpegPath", "ffprobePath", "nodePath"] as const).map((name) => (
            <TextField
              key={name}
              mono
              {...bind(name, `settings.${name}`)}
              hint={t("settings.pathHint")}
            />
          ))}
        </fieldset>
        <div className="row sticky-actions">
          <button type="submit" className="primary" disabled={status === "saving"}>
            {status === "saving" ? t("common.saving") : t("common.save")}
          </button>
          {status === "saved" && <span role="status">{t("common.saved")}</span>}
        </div>
        <ErrorNotice error={error} />
      </form>
      <fieldset>
        <legend>{t("settings.openaiKey")}</legend>
        <SecretField
          label={t("settings.openaiKey")}
          status={data.secrets.openaiApiKey}
          onSave={(value) => updateKey(api.storeOpenAiKey(value))}
          onClear={() => updateKey(api.clearOpenAiKey())}
        />
      </fieldset>
      <About />
    </section>
  );
}
