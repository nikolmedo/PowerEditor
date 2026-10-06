import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/endpoints";
import { FEATURE_IDS, type FeatureModels } from "../api/types";
import { useT } from "../i18n";
import { ErrorNotice } from "../ui/primitives";
import { useResource } from "../ui/useResource";
import { decodeRef, encodeRef, HEURISTIC, modelOptions } from "./featureOptions";

export function FeaturesScreen() {
  const t = useT();
  const providers = useResource(useCallback(() => api.providers(), []));
  const assigned = useResource(useCallback(() => api.featureModels(), []));
  const [features, setFeatures] = useState<FeatureModels | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  // Bumped on every edit, so a save that answers after a newer edit cannot undo it.
  const revision = useRef(0);

  useEffect(() => {
    if (assigned.data) setFeatures(assigned.data.features);
  }, [assigned.data]);

  const save = async () => {
    if (!features) return;
    const savedRevision = revision.current;
    try {
      const response = await api.saveFeatureModels(features);
      if (savedRevision !== revision.current) return;
      setFeatures(response.features);
      setError(null);
      setSaved(true);
    } catch (caught) {
      setError(caught);
    }
  };

  const hasModels = providers.data?.some((provider) => provider.enabledModels.length > 0);
  return (
    <section className="screen">
      <h1>{t("features.title")}</h1>
      <p className="lede">{t("features.intro")}</p>
      <ErrorNotice error={providers.error ?? assigned.error} />
      {providers.data && !hasModels && (
        <p className="notice notice-warn">{t("features.noModels")}</p>
      )}
      {features && providers.data && (
        <table className="features">
          <thead>
            <tr>
              <th scope="col">{t("features.feature")}</th>
              <th scope="col">{t("features.model")}</th>
            </tr>
          </thead>
          <tbody>
            {FEATURE_IDS.map((feature) => {
              const current = features[feature] ?? null;
              const label = t(`feature.${feature}`);
              return (
                <tr key={feature}>
                  <th scope="row">{label}</th>
                  <td>
                    <select
                      aria-label={label}
                      value={current ? encodeRef(current) : HEURISTIC}
                      onChange={(event) => {
                        revision.current += 1;
                        setFeatures({ ...features, [feature]: decodeRef(event.target.value) });
                        setSaved(false);
                      }}
                    >
                      <option value={HEURISTIC}>{t("features.heuristic")}</option>
                      {modelOptions(providers.data ?? [], current).map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.stale
                            ? t("features.stale", { label: option.label })
                            : option.label}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="row">
        <button type="button" className="primary" onClick={save} disabled={!features}>
          {t("common.save")}
        </button>
        {saved && <span role="status">{t("common.saved")}</span>}
      </div>
      <ErrorNotice error={error} />
    </section>
  );
}
