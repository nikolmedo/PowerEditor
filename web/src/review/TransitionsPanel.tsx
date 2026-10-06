import type { Clip, TransitionType } from "@powereditor/composition";
import { useState } from "react";
import { applyTransitionPreset, setTransition, TRANSITION_TYPES } from "../edit/operations";
import { useT } from "../i18n";
import { useProjectStore } from "../store/project";
import { Field, SelectField } from "../ui/primitives";

const INSTANT: readonly TransitionType[] = ["cut", "punch_in"];

/** The incoming transition of the selected cut, and one type for every cut at once. */
export function TransitionsPanel({ clip }: { clip: Clip | null }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const [preset, setPreset] = useState<TransitionType>("fade");
  const options = TRANSITION_TYPES.map((type) => ({ value: type, label: t(`transition.${type}`) }));
  const current = clip?.transitionIn;

  return (
    <div className="panel-body">
      {clip && current ? (
        <>
          <h3>{t("edit.thisCut")}</h3>
          <SelectField
            label={t("review.transition")}
            value={current.type}
            options={options}
            onChange={(type) => edit((p) => setTransition(p, clip.id, type as TransitionType))}
          />
          <Field label={t("edit.durationFrames")} hint={t("edit.durationFrames.hint")}>
            {(id, describedBy) => (
              <input
                id={id}
                type="number"
                min={0}
                className="mono"
                aria-describedby={describedBy}
                disabled={INSTANT.includes(current.type)}
                value={current.durationFrames}
                onChange={(event) =>
                  edit(
                    (p) => setTransition(p, clip.id, current.type, Number(event.target.value)),
                    `transition:${clip.id}`,
                  )
                }
              />
            )}
          </Field>
        </>
      ) : (
        <p className="meta">{t("edit.selectCut")}</p>
      )}
      <h3>{t("edit.allCuts")}</h3>
      <SelectField
        label={t("edit.preset")}
        value={preset}
        options={options}
        onChange={(type) => setPreset(type as TransitionType)}
      />
      <button type="button" onClick={() => edit((p) => applyTransitionPreset(p, preset))}>
        {t("edit.applyToAll")}
      </button>
    </div>
  );
}
