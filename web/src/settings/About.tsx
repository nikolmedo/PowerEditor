import { useCallback, useId } from "react";
import { api } from "../api/endpoints";
import { useT } from "../i18n";
import { AUTHOR_URL, LICENSE_URL, NOTICES_URL } from "../ui/projectLinks";
import { useResource } from "../ui/useResource";

/** App name, engine version, copyright and license. The version comes from the engine, so
 * it is left out while the engine cannot be reached. */
export function About() {
  const t = useT();
  const headingId = useId();
  const health = useResource(useCallback(() => api.health(), []));
  return (
    <section className="about" aria-labelledby={headingId}>
      <h2 id={headingId}>{t("about.title")}</h2>
      <p>
        <strong>{t("app.name")}</strong>
        {health.data && (
          <span className="meta"> {t("about.version", { version: health.data.version })}</span>
        )}
      </p>
      <p>
        <a href={AUTHOR_URL} target="_blank" rel="noreferrer">
          {t("about.copyright")}
        </a>
      </p>
      <p className="meta">{t("about.license")}</p>
      <p className="row">
        <a href={LICENSE_URL} target="_blank" rel="noreferrer">
          {t("about.licenseLink")}
        </a>
        <a href={NOTICES_URL} target="_blank" rel="noreferrer">
          {t("about.noticesLink")}
        </a>
      </p>
    </section>
  );
}
