import {
  normalizeOverlayProps,
  OVERLAY_FIELDS,
  OVERLAY_TEMPLATES,
  overlayVariants,
  type Overlay,
  type OverlayField,
  type OverlayTemplateId,
  type Project,
} from "@powereditor/composition";
import { useCallback, useRef, type CSSProperties } from "react";
import type { OverlayAsset } from "../api/types";
import { uploadFraction, uploadOverlayAsset } from "../api/upload";
import { addOverlay, projectAccent, removeOverlay, setOverlayProps } from "../edit/overlays";
import { isMessageKey, useT, type MessageKey, type Translate } from "../i18n";
import { useProjectStore } from "../store/project";
import { ErrorNotice, NumberField, SelectField, Slider, TextField } from "../ui/primitives";
import { timecode } from "./Timeline";
import { useLatestUpload } from "./useLatestUpload";

const IMAGE_TYPES = "image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp";

/** Starter text of a new overlay, in the interface language. */
const STARTER_TEXT: Partial<Record<OverlayTemplateId, Record<string, MessageKey>>> = {
  title: { text: "graphics.default.title" },
  lower_third: { name: "graphics.default.name", role: "graphics.default.role" },
  cta: { text: "graphics.default.cta" },
};

/**
 * Shapes drawn by each thumbnail (see `.thumb` in styles.css), by template, or by
 * `template:variant` for a look that draws differently from its template's first look.
 */
const THUMB_MARKS: Record<OverlayTemplateId, number> & Record<string, number> = {
  title: 2,
  "title:headline_slam": 2,
  lower_third: 2,
  "lower_third:kicker_name": 2,
  "lower_third:mask_reveal": 2,
  "lower_third:soft_pill": 2,
  cta: 1,
  "cta:lockup": 2,
  "cta:close": 2,
  logo: 1,
  progress_bar: 2,
  image: 1,
  count_up: 2,
  progress_ring: 2,
};

/** One entry of the picker: a template in one of its looks (none for single-look ones). */
interface PickerEntry {
  templateId: OverlayTemplateId;
  variant: string | null;
}

/** Every template, each look of a template with several as its own entry. */
export const PICKER_ENTRIES: readonly PickerEntry[] = OVERLAY_TEMPLATES.flatMap(
  (templateId): PickerEntry[] => {
    const variants = overlayVariants(templateId);
    return variants.length === 0
      ? [{ templateId, variant: null }]
      : variants.map((variant) => ({ templateId, variant }));
  },
);

const label = (t: Translate, prefix: string, key: string) => {
  const full = `${prefix}.${key}`;
  return isMessageKey(full) ? t(full) : key;
};

const newOverlayId = () => `ov-${crypto.randomUUID().slice(0, 8)}`;

/** A schematic of the template on a frame of the project's shape, in the project's accent. */
function TemplateThumb({ entry, project }: { entry: PickerEntry; project: Project }) {
  const style = {
    "--thumb-accent": projectAccent(project),
    aspectRatio: project.preset === "reel_9x16" ? "9 / 16" : "16 / 9",
  } as CSSProperties;
  const marks =
    THUMB_MARKS[`${entry.templateId}:${entry.variant}`] ?? THUMB_MARKS[entry.templateId];
  return (
    <span
      className="thumb"
      data-template={entry.templateId}
      data-variant={entry.variant ?? undefined}
      style={style}
      aria-hidden="true"
    >
      {Array.from({ length: marks }, (_, index) => (
        <span key={index} className="thumb-mark" />
      ))}
    </span>
  );
}

function ImageField({
  projectId,
  overlay,
  project,
}: {
  projectId: string;
  overlay: Overlay;
  project: Project;
}) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const picker = useRef<HTMLInputElement>(null);
  const onStored = useCallback(
    (stored: OverlayAsset) => edit((p) => setOverlayProps(p, overlay.id, { src: stored.fileName })),
    [edit, overlay.id],
  );
  const { state, error, send } = useLatestUpload(projectId, uploadOverlayAsset, onStored);
  const current = typeof overlay.props.src === "string" ? overlay.props.src : "";
  // Images already used by the project's graphics, so a logo can be reused without uploading.
  const known = [
    ...new Set(
      project.overlays.flatMap(({ props }) =>
        typeof props.src === "string" && props.src ? [props.src] : [],
      ),
    ),
  ];
  return (
    <div className="panel-body">
      <SelectField
        label={t("graphics.field.src")}
        value={current}
        options={[
          { value: "", label: t("graphics.noImage") },
          ...known.map((name) => ({ value: name, label: name })),
        ]}
        onChange={(src) => edit((p) => setOverlayProps(p, overlay.id, { src }))}
      />
      <button type="button" onClick={() => picker.current?.click()}>
        {t("graphics.upload")}
      </button>
      <input
        ref={picker}
        type="file"
        accept={IMAGE_TYPES}
        hidden
        aria-label={t("graphics.upload")}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void send(file);
        }}
      />
      {state.phase === "uploading" && (
        <progress max={1} value={uploadFraction(state)} aria-label={t("load.uploading")} />
      )}
      <ErrorNotice error={error} />
    </div>
  );
}

function PropField({
  field,
  overlay,
  value,
}: {
  field: OverlayField;
  overlay: Overlay;
  value: unknown;
}) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const name = label(t, "graphics.field", field.key);
  // Typing and slider drags on one field merge into one undo step.
  const set = (next: unknown) =>
    edit(
      (p) => setOverlayProps(p, overlay.id, { [field.key]: next }),
      `overlay:${overlay.id}:${field.key}`,
    );
  switch (field.kind) {
    case "text":
      return <TextField label={name} value={String(value)} onChange={set} />;
    case "color":
      return (
        <label className="color-field">
          {name}
          <input type="color" value={String(value)} onChange={(event) => set(event.target.value)} />
        </label>
      );
    case "choice":
      return (
        <SelectField
          label={name}
          value={String(value)}
          options={field.options.map((option) => ({
            value: option,
            label: label(t, "graphics.option", option),
          }))}
          onChange={set}
        />
      );
    case "number":
      if (field.entry) {
        return (
          <NumberField
            label={name}
            value={Number(value)}
            min={field.min}
            max={field.max}
            integer={false}
            onChange={set}
          />
        );
      }
      return (
        <Slider
          label={name}
          value={Number(value)}
          min={field.min}
          max={field.max}
          step={field.step}
          format={(number) => (field.max <= 1 ? `${Math.round(number * 100)} %` : `${number} px`)}
          onChange={set}
        />
      );
    case "image":
      return null;
  }
}

function OverlayEditor({
  projectId,
  project,
  overlay,
  onSelect,
}: {
  projectId: string;
  project: Project;
  overlay: Overlay;
  onSelect: (id: string | null) => void;
}) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const props = normalizeOverlayProps(overlay.templateId, overlay.props, projectAccent(project));
  const values = props as unknown as Record<string, unknown>;
  return (
    <section className="panel-body" aria-label={t("graphics.properties")}>
      <h3>
        {t(`overlay.${overlay.templateId}`)} · {t("graphics.properties")}
      </h3>
      {overlay.autoGenerated && <p className="meta">{t("graphics.autoHint")}</p>}
      {OVERLAY_FIELDS[overlay.templateId].map((field) =>
        field.kind === "image" ? (
          <ImageField key={field.key} projectId={projectId} overlay={overlay} project={project} />
        ) : (
          <PropField key={field.key} field={field} overlay={overlay} value={values[field.key]} />
        ),
      )}
      <button
        type="button"
        className="quiet"
        onClick={() => {
          edit((p) => removeOverlay(p, overlay.id));
          onSelect(null);
        }}
      >
        {t("graphics.remove")}
      </button>
    </section>
  );
}

interface GraphicsPanelProps {
  projectId: string;
  project: Project;
  /** The playhead: new graphics start here. */
  frame: number;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

/** Overlay templates: add one at the playhead, pick one to edit its props, remove it. */
export function GraphicsPanel({
  projectId,
  project,
  frame,
  selectedId,
  onSelect,
}: GraphicsPanelProps) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const selected = project.overlays.find((overlay) => overlay.id === selectedId) ?? null;
  const ordered = [...project.overlays].sort((a, b) => a.startFrame - b.startFrame);

  const add = ({ templateId, variant }: PickerEntry) => {
    const id = newOverlayId();
    const props: Record<string, unknown> = Object.fromEntries(
      Object.entries(STARTER_TEXT[templateId] ?? {}).map(([key, message]) => [key, t(message)]),
    );
    if (variant) props.variant = variant;
    edit((p) => addOverlay(p, { id, templateId, atFrame: frame, props }));
    onSelect(id);
  };
  // A template's first look keeps the template's name; the others add the look's name.
  const entryName = ({ templateId, variant }: PickerEntry) =>
    variant && variant !== overlayVariants(templateId)[0]
      ? `${t(`overlay.${templateId}`)} · ${label(t, "graphics.option", variant)}`
      : t(`overlay.${templateId}`);

  return (
    <div className="panel-body">
      <h3>{t("graphics.templates")}</h3>
      <div className="template-grid">
        {PICKER_ENTRIES.map((entry) => (
          <button
            key={`${entry.templateId}:${entry.variant}`}
            type="button"
            className="template"
            aria-label={t("graphics.addTemplate", { template: entryName(entry) })}
            onClick={() => add(entry)}
          >
            <TemplateThumb entry={entry} project={project} />
            <span>{entryName(entry)}</span>
          </button>
        ))}
      </div>
      <h3>{t("graphics.list")}</h3>
      {ordered.length === 0 ? (
        <p className="meta">{t("graphics.empty")}</p>
      ) : (
        <ul className="overlay-list">
          {ordered.map((overlay) => (
            <li key={overlay.id}>
              <button
                type="button"
                className="quiet"
                aria-pressed={overlay.id === selectedId}
                onClick={() => onSelect(overlay.id)}
              >
                <span>{t(`overlay.${overlay.templateId}`)}</span>
                <span className="meta mono">
                  {t("graphics.span", {
                    start: timecode(overlay.startFrame, project.fps),
                    end: timecode(overlay.endFrame, project.fps),
                  })}
                </span>
                {overlay.autoGenerated && (
                  <span className="badge mono" title={t("graphics.autoHint")}>
                    {t("graphics.auto")}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="meta">{t("graphics.keys")}</p>
      {selected && (
        <OverlayEditor
          projectId={projectId}
          project={project}
          overlay={selected}
          onSelect={onSelect}
        />
      )}
    </div>
  );
}
