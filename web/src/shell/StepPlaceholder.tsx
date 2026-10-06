import { useT } from "../i18n";
import type { Step } from "./AppShell";

/** Steps 1–3 are built in Phase 6b-2; until then each shows where it will live. */
export function StepPlaceholder({ step }: { step: Step }) {
  const t = useT();
  return (
    <section className="screen">
      <h1>{t(`steps.${step}`)}</h1>
      <p className="lede">{t("steps.soon")}</p>
    </section>
  );
}
