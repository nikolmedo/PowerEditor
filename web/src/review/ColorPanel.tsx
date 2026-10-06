import {
  resolveGrade,
  type Clip,
  type ColorPreset,
  type GradeValues,
  type Project,
} from "@powereditor/composition";
import { useState } from "react";
import {
  applyGradeToAll,
  clearClipColor,
  COLOR_PRESETS,
  GRADE_KEYS,
  GRADE_RANGES,
  resetColorCorrection,
  setClipColor,
  setClipColorPreset,
  setGrade,
  setGradePreset,
} from "../edit/color";
import { useT } from "../i18n";
import { useProjectStore } from "../store/project";
import { Slider } from "../ui/primitives";
import { fileLabel } from "./timelineModel";

type Scope = "all" | "clip";

const formatGrade = (key: keyof GradeValues, value: number) =>
  key === "temperature" ? `${value > 0 ? "+" : ""}${value.toFixed(2)}` : `${value.toFixed(2)}×`;
const formatGain = (gain: number) => gain.toFixed(2);

function SourceMatch({ project }: { project: Project }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  return (
    <section className="panel-body" aria-label={t("color.match")}>
      <h3>{t("color.match")}</h3>
      <p className="meta">{t("color.match.hint")}</p>
      <ul className="source-match">
        {project.sources.map((source) => {
          const gains = source.colorCorrection;
          return (
            <li key={source.id}>
              <span className="swatch" style={{ background: source.displayColor }} aria-hidden />
              <span className="mono">{fileLabel(source.originalPath)}</span>
              {gains ? (
                <>
                  <span className="meta mono">
                    R {formatGain(gains.redGain)} · G {formatGain(gains.greenGain)} · B{" "}
                    {formatGain(gains.blueGain)}
                  </span>
                  <button
                    type="button"
                    className="quiet"
                    onClick={() => edit((p) => resetColorCorrection(p, source.id))}
                  >
                    {t("color.reset")}
                  </button>
                </>
              ) : (
                <span className="meta">{t("color.unchanged")}</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The look of the video: one grade for every clip, overrides for single clips, and the
 * automatic match between sources. */
export function ColorPanel({ project, clip }: { project: Project; clip: Clip | null }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const [chosenScope, setScope] = useState<Scope>("all");
  const scope: Scope = clip ? chosenScope : "all";
  const grade =
    scope === "clip" && clip
      ? resolveGrade(project.colorGrade, clip.colorOverride)
      : project.colorGrade;
  const overridden = project.clips.filter((candidate) => candidate.colorOverride != null).length;

  const choosePreset = (preset: ColorPreset) =>
    edit((p) =>
      scope === "clip" && clip ? setClipColorPreset(p, clip.id, preset) : setGradePreset(p, preset),
    );
  const change = (key: keyof GradeValues, value: number) =>
    edit(
      (p) =>
        scope === "clip" && clip
          ? setClipColor(p, clip.id, { [key]: value })
          : setGrade(p, { [key]: value }),
      `color:${scope === "clip" && clip ? clip.id : "all"}:${key}`,
    );

  return (
    <div className="panel-body">
      <div className="segmented" role="tablist" aria-label={t("color.scope")}>
        {(["all", "clip"] as const).map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={scope === name}
            disabled={name === "clip" && !clip}
            onClick={() => setScope(name)}
          >
            {t(`color.scope.${name}`)}
          </button>
        ))}
      </div>
      {!clip && <p className="meta">{t("color.selectClip")}</p>}
      <div className="preset-row" role="group" aria-label={t("color.presets")}>
        {COLOR_PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            aria-pressed={grade.preset === preset}
            onClick={() => choosePreset(preset)}
          >
            {t(`color.preset.${preset}`)}
          </button>
        ))}
      </div>
      {GRADE_KEYS.map((key) => (
        <Slider
          key={key}
          label={t(`color.${key}`)}
          value={grade[key]}
          min={GRADE_RANGES[key][0]}
          max={GRADE_RANGES[key][1]}
          format={(value) => formatGrade(key, value)}
          onChange={(value) => change(key, value)}
        />
      ))}
      {scope === "clip" && clip?.colorOverride && (
        <button
          type="button"
          className="quiet"
          onClick={() => edit((p) => clearClipColor(p, clip.id))}
        >
          {t("color.useGlobal")}
        </button>
      )}
      {scope === "all" && (
        <>
          <button type="button" disabled={overridden === 0} onClick={() => edit(applyGradeToAll)}>
            {t("color.applyToAll")}
          </button>
          {overridden > 0 && (
            <p className="meta">{t("color.applyToAll.hint", { count: overridden })}</p>
          )}
        </>
      )}
      <SourceMatch project={project} />
    </div>
  );
}
