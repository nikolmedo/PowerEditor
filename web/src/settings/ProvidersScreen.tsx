import { useCallback, useState, type FormEvent } from "react";
import { api } from "../api/endpoints";
import type {
  ModelInfo,
  Provider,
  ProviderDraft,
  ProviderKindInfo,
  ProviderTestResult,
  Transport,
} from "../api/types";
import { useT } from "../i18n";
import { ErrorNotice, Field, SecretField, SelectField, Status, TextField } from "../ui/primitives";
import { useResource } from "../ui/useResource";
import { draftFor, draftPayload, termsNoticeKey, toggleModel, validateDraft } from "./providerForm";

export const TERMS_URL = "https://github.com/nikolmedo/PowerEditor#subscriptions-and-terms-of-use";

function TermsNotice({ kind, transport }: { kind: string; transport: Transport }) {
  const t = useT();
  const key = termsNoticeKey(kind, transport);
  if (!key) return null;
  return (
    <aside className="notice notice-warn" aria-label={t("terms.title")}>
      <strong>{t("terms.title")}.</strong> {t(key)}{" "}
      <a href={TERMS_URL} target="_blank" rel="noreferrer">
        {t("terms.readMore")}
      </a>
    </aside>
  );
}

interface EditorProps {
  kinds: ProviderKindInfo[];
  provider: Provider | null;
  onDone: () => void;
}

/** Create a provider, or edit one (kind and transport are fixed once it exists). */
function ProviderEditor({ kinds, provider, onDone }: EditorProps) {
  const t = useT();
  const first = kinds[0];
  const [draft, setDraft] = useState<ProviderDraft | null>(() => {
    if (!provider) return first ? draftFor(first) : null;
    const { kind, transport, label, enabledModels, cliPath, baseUrl } = provider;
    return {
      kind,
      transport,
      label,
      enabledModels,
      cliPath,
      baseUrl,
      customBaseUrlConfirmed: provider.customBaseUrlConfirmed,
    };
  });
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [touched, setTouched] = useState(false);
  if (!draft) return null;

  const errors = touched ? validateDraft(draft) : {};
  const kind = kinds.find((candidate) => candidate.kind === draft.kind);
  const set = (changes: Partial<ProviderDraft>) => setDraft({ ...draft, ...changes });
  const changeKind = (value: string) => {
    const next = kinds.find((candidate) => candidate.kind === value);
    if (next) setDraft(draftFor(next));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (Object.keys(validateDraft(draft)).length > 0) return;
    try {
      const payload = draftPayload(draft);
      // Kind, transport and models are not edited here: models are toggled on the card.
      const { label, cliPath, baseUrl, customBaseUrlConfirmed } = payload;
      const saved = provider
        ? await api.updateProvider(provider.id, { label, cliPath, baseUrl, customBaseUrlConfirmed })
        : await api.createProvider(payload);
      if (apiKey.trim() && draft.transport === "api") await api.storeProviderKey(saved.id, apiKey);
      onDone();
    } catch (caught) {
      setError(caught);
    }
  };

  return (
    <form className="panel editor" onSubmit={submit} noValidate>
      <div className="grid-2">
        <SelectField
          label={t("providers.kind")}
          value={draft.kind}
          disabled={provider !== null}
          onChange={changeKind}
          options={kinds.map((option) => ({ value: option.kind, label: option.label }))}
        />
        <SelectField
          label={t("providers.transport")}
          value={draft.transport}
          disabled={provider !== null}
          onChange={(value) => set({ transport: value as Transport })}
          options={(kind?.transports ?? [draft.transport]).map((value) => ({
            value,
            label: t(`providers.transport.${value}`),
          }))}
        />
      </div>
      <TextField
        label={t("providers.label")}
        value={draft.label}
        onChange={(label) => set({ label })}
        error={errors.label && t(errors.label)}
      />
      <TermsNotice kind={draft.kind} transport={draft.transport} />
      {draft.transport === "api" ? (
        <>
          {!provider && (
            <TextField
              label={t("providers.apiKey")}
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={setApiKey}
              placeholder={t("secret.placeholder")}
            />
          )}
          <TextField
            label={t("providers.baseUrl")}
            type="url"
            mono
            value={draft.baseUrl ?? ""}
            onChange={(baseUrl) => set({ baseUrl })}
            hint={t("providers.baseUrl.hint")}
            error={errors.baseUrl && t(errors.baseUrl)}
          />
          {draft.baseUrl?.trim() && (
            <Field
              label={t("providers.confirmCustomUrl")}
              error={errors.customBaseUrlConfirmed && t(errors.customBaseUrlConfirmed)}
            >
              {(id, describedBy) => (
                <input
                  id={id}
                  type="checkbox"
                  aria-describedby={describedBy}
                  checked={draft.customBaseUrlConfirmed}
                  onChange={(event) => set({ customBaseUrlConfirmed: event.target.checked })}
                />
              )}
            </Field>
          )}
        </>
      ) : (
        <TextField
          label={t("providers.cliPath")}
          mono
          value={draft.cliPath ?? ""}
          onChange={(cliPath) => set({ cliPath })}
          hint={t("providers.cliPath.hint")}
        />
      )}
      <ErrorNotice error={error} />
      <div className="row">
        <button type="submit" className="primary">
          {provider ? t("common.save") : t("providers.create")}
        </button>
        <button type="button" className="quiet" onClick={onDone}>
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

function ModelPicker({ provider, onChange }: { provider: Provider; onChange: () => void }) {
  const t = useT();
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
      setError(null);
    } catch (caught) {
      setError(caught);
    }
  };
  const fetchModels = () => run(async () => setModels(await api.providerModels(provider.id)));
  const toggle = (id: string) =>
    run(async () => {
      await api.updateProvider(provider.id, {
        enabledModels: toggleModel(provider.enabledModels, id),
      });
      onChange();
    });
  const ids = [...new Set([...provider.enabledModels, ...(models ?? []).map((model) => model.id)])];

  return (
    <div className="models">
      <div className="row spread">
        <span className="subhead">
          {t("providers.modelsCount", { count: provider.enabledModels.length })}
        </span>
        <button type="button" className="quiet" onClick={fetchModels}>
          {t("providers.loadModels")}
        </button>
      </div>
      {models?.length === 0 && <p className="meta">{t("providers.noModels")}</p>}
      <ul className="model-list">
        {ids.map((id) => (
          <li key={id}>
            <label>
              <input
                type="checkbox"
                checked={provider.enabledModels.includes(id)}
                onChange={() => void toggle(id)}
              />
              <span className="mono">{id}</span>
            </label>
          </li>
        ))}
      </ul>
      <ErrorNotice error={error} />
    </div>
  );
}

function TestResult({ result }: { result: ProviderTestResult }) {
  const t = useT();
  return (
    <p className="row test-result" role="status">
      <Status ok={result.ok}>{result.detail}</Status>
      {result.version && (
        <span className="meta mono">{t("providers.version", { version: result.version })}</span>
      )}
      {result.authenticated !== null && (
        <span className="meta">
          {result.authenticated ? t("providers.signedIn") : t("providers.notSignedIn")}
        </span>
      )}
    </p>
  );
}

function ProviderCard(props: { provider: Provider; onEdit: () => void; onChange: () => void }) {
  const { provider, onEdit, onChange } = props;
  const t = useT();
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ProviderTestResult | null>(null);
  const [error, setError] = useState<unknown>(null);

  const test = async () => {
    setTesting(true);
    try {
      setResult(await api.testProvider(provider.id));
    } catch (caught) {
      setError(caught);
    } finally {
      setTesting(false);
    }
  };
  const remove = async () => {
    if (!window.confirm(t("providers.deleteConfirm", { label: provider.label }))) return;
    try {
      await api.deleteProvider(provider.id);
      onChange();
    } catch (caught) {
      setError(caught);
    }
  };

  return (
    <article className="panel provider" aria-label={provider.label}>
      <header className="row spread">
        <div>
          <h2>{provider.label}</h2>
          <p className="meta mono">
            {provider.kind} · {t(`providers.transport.${provider.transport}`)}
          </p>
        </div>
        <div className="row">
          <button type="button" onClick={test} disabled={testing}>
            {testing ? t("providers.testing") : t("providers.test")}
          </button>
          <button type="button" className="quiet" onClick={onEdit}>
            {t("common.edit")}
          </button>
          <button type="button" className="quiet danger" onClick={remove}>
            {t("common.delete")}
          </button>
        </div>
      </header>
      {result && <TestResult result={result} />}
      <ErrorNotice error={error} />
      <TermsNotice kind={provider.kind} transport={provider.transport} />
      {provider.transport === "api" && (
        <SecretField
          label={t("providers.apiKey")}
          status={{ set: provider.apiKeySet }}
          onSave={async (value) => {
            await api.storeProviderKey(provider.id, value);
            onChange();
          }}
        />
      )}
      <ModelPicker provider={provider} onChange={onChange} />
    </article>
  );
}

export function ProvidersScreen() {
  const t = useT();
  const kinds = useResource(useCallback(() => api.providerKinds(), []));
  const providers = useResource(useCallback(() => api.providers(), []));
  const [editing, setEditing] = useState<Provider | "new" | null>(null);
  const refresh = () => void providers.reload();
  const done = () => {
    setEditing(null);
    refresh();
  };

  return (
    <section className="screen">
      <div className="screen-head">
        <h1>{t("providers.title")}</h1>
        <button
          type="button"
          className="primary"
          onClick={() => setEditing("new")}
          disabled={!kinds.data}
        >
          {t("providers.add")}
        </button>
      </div>
      <p className="lede">{t("providers.intro")}</p>
      <ErrorNotice error={providers.error ?? kinds.error} />
      {editing && kinds.data && (
        <ProviderEditor
          key={editing === "new" ? "new" : editing.id}
          kinds={kinds.data}
          provider={editing === "new" ? null : editing}
          onDone={done}
        />
      )}
      {providers.data?.length === 0 && <p className="meta">{t("providers.empty")}</p>}
      {providers.data?.map((provider) => (
        <ProviderCard
          key={provider.id}
          provider={provider}
          onEdit={() => setEditing(provider)}
          onChange={refresh}
        />
      ))}
    </section>
  );
}
