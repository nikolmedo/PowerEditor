import {
  groupLines,
  timelineWords,
  type Project,
  type SubtitleStyle,
} from "@powereditor/composition";
import { useState, type KeyboardEvent } from "react";
import { editSubtitles, setSubtitleStyle } from "../edit/operations";
import { useT } from "../i18n";
import { useProjectStore } from "../store/project";
import { Field, NumberField, SelectField } from "../ui/primitives";

const PRESETS: readonly SubtitleStyle["preset"][] = [
  "karaoke_highlight",
  "clean",
  "bold_pop",
  "minimal",
];
const POSITIONS: readonly SubtitleStyle["position"][] = ["bottom", "center", "top"];

interface LineRange {
  fromIndex: number;
  toIndex: number;
  text: string;
  startFrame: number;
}

/** Subtitle lines with the range of timeline words each one covers. */
export function lineRanges(project: Project): LineRange[] {
  const lines = groupLines(timelineWords(project), {
    maxWordsPerLine: project.subtitles.style.maxWordsPerLine,
    fps: project.fps,
  });
  let fromIndex = 0;
  return lines.map((line) => {
    const range = {
      fromIndex,
      toIndex: fromIndex + line.words.length,
      text: line.text,
      startFrame: line.startFrame,
    };
    fromIndex = range.toIndex;
    return range;
  });
}

function LineEditor({ line, editable }: { line: LineRange; editable: boolean }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const [draft, setDraft] = useState(line.text);
  const [invalid, setInvalid] = useState(false);
  const commit = () => {
    if (draft.trim() === line.text) {
      setDraft(line.text);
      return;
    }
    try {
      edit((p) => editSubtitles(p, line.fromIndex, line.toIndex, draft));
      setInvalid(false);
    } catch {
      setInvalid(true);
    }
  };
  const keys = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") commit();
    if (event.key === "Escape") setDraft(line.text);
  };
  return (
    <li>
      <input
        aria-label={t("edit.lineText")}
        aria-invalid={invalid || undefined}
        title={invalid ? t("edit.lineInvalid") : undefined}
        value={draft}
        disabled={!editable}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={keys}
      />
    </li>
  );
}

/** Subtitle style and the text of each line. */
export function SubtitlesPanel({ project }: { project: Project }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const style = project.subtitles.style;
  const restyle = (changes: Partial<SubtitleStyle>, group?: string) =>
    edit((p) => setSubtitleStyle(p, changes), group);
  const editable = Object.keys(project.subtitles.sourceWords ?? {}).length > 0;
  const number = (key: "fontSize" | "maxWordsPerLine", min: number, max: number) => (
    <NumberField
      label={t(`edit.${key}`)}
      value={style[key]}
      min={min}
      max={max}
      onChange={(value) => restyle({ [key]: value }, `style:${key}`)}
    />
  );

  return (
    <div className="panel-body">
      <SelectField
        label={t("edit.subtitlePreset")}
        value={style.preset}
        options={PRESETS.map((value) => ({ value, label: t(`subtitlePreset.${value}`) }))}
        onChange={(value) => restyle({ preset: value as SubtitleStyle["preset"] })}
      />
      <div className="grid-2">
        {number("fontSize", 16, 160)}
        {number("maxWordsPerLine", 1, 12)}
      </div>
      <SelectField
        label={t("edit.position")}
        value={style.position}
        options={POSITIONS.map((value) => ({ value, label: t(`position.${value}`) }))}
        onChange={(value) => restyle({ position: value as SubtitleStyle["position"] })}
      />
      <Field label={t("edit.highlightColor")}>
        {(id) => (
          <input
            id={id}
            type="color"
            value={style.highlightColor}
            onChange={(event) => restyle({ highlightColor: event.target.value }, "style:color")}
          />
        )}
      </Field>
      <h3>{t("edit.lines")}</h3>
      {!editable && <p className="meta">{t("edit.linesReadOnly")}</p>}
      <ol className="line-list">
        {lineRanges(project).map((line) => (
          <LineEditor
            key={`${line.startFrame}:${line.fromIndex}:${line.text}`}
            line={line}
            editable={editable}
          />
        ))}
      </ol>
    </div>
  );
}
