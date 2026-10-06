import { useId, useState, type ReactNode } from "react";
import { errorMessage } from "../api/client";
import type { SecretStatus } from "../api/types";
import { useT } from "../i18n";

interface FieldProps {
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
  children: (id: string, describedBy: string | undefined) => ReactNode;
}

/** A labelled control with an optional hint and error, wired for screen readers. */
export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field" data-invalid={error ? true : undefined}>
      <label htmlFor={id}>{label}</label>
      {children(id, describedBy)}
      {hint && (
        <p id={hintId} className="field-hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string | undefined;
  error?: string | undefined;
  type?: "text" | "password" | "url";
  /** Decimal keyboard on a plain text input, so partial input like "-" is never discarded
   * and the backend's validation message can explain a bad value. */
  inputMode?: "decimal";
  autoComplete?: "new-password";
  placeholder?: string;
  mono?: boolean;
}

export function TextField({ label, value, onChange, hint, error, mono, ...input }: TextFieldProps) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id, describedBy) => (
        <input
          id={id}
          className={mono ? "mono" : undefined}
          value={value}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          onChange={(event) => onChange(event.target.value)}
          {...input}
        />
      )}
    </Field>
  );
}

interface SelectFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
  hint?: string | undefined;
  disabled?: boolean;
}

export function SelectField({ label, value, onChange, options, hint, disabled }: SelectFieldProps) {
  return (
    <Field label={label} hint={hint}>
      {(id, describedBy) => (
        <select
          id={id}
          value={value}
          disabled={disabled}
          aria-describedby={describedBy}
          onChange={(event) => onChange(event.target.value)}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

export function Status({ ok, children }: { ok: boolean | null; children: ReactNode }) {
  const tone = ok === null ? "neutral" : ok ? "ok" : "bad";
  return <span className={`status status-${tone}`}>{children}</span>;
}

export function ErrorNotice({ error }: { error: unknown }) {
  const t = useT();
  if (!error) return null;
  return (
    <p className="notice notice-bad" role="alert">
      {errorMessage(error, t)}
    </p>
  );
}

interface SecretFieldProps {
  label: string;
  status: SecretStatus | { set: boolean };
  onSave: (value: string) => Promise<void>;
  onClear?: (() => Promise<void>) | undefined;
}

/** A write-only secret: the value is sent once and only its "saved" state comes back. */
export function SecretField({ label, status, onSave, onClear }: SecretFieldProps) {
  const t = useT();
  const [value, setValue] = useState("");
  const [error, setError] = useState<unknown>(null);
  const run = async (action: () => Promise<void>) => {
    try {
      await action();
      setValue("");
      setError(null);
    } catch (caught) {
      setError(caught);
    }
  };
  return (
    <div className="secret">
      <TextField
        label={label}
        type="password"
        autoComplete="new-password"
        value={value}
        onChange={setValue}
        placeholder={t("secret.placeholder")}
        hint={status.set ? t("secret.set") : t("secret.notSet")}
      />
      <div className="row">
        <button type="button" disabled={!value.trim()} onClick={() => run(() => onSave(value))}>
          {t("secret.save")}
        </button>
        {onClear && status.set && (
          <button type="button" className="quiet" onClick={() => run(onClear)}>
            {t("settings.openaiKey.remove")}
          </button>
        )}
      </div>
      <ErrorNotice error={error} />
    </div>
  );
}
