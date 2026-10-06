import { clipFrames, type Clip, type Project } from "@powereditor/composition";
import {
  setClipSpeed,
  setClipVolume,
  setRemoved,
  swapTake,
  takesOf,
  trimClip,
  TRIM_STEP_SECONDS,
  type Edge,
} from "../edit/operations";
import { useT } from "../i18n";
import { useProjectStore } from "../store/project";
import { Slider } from "../ui/primitives";
import { fileLabel } from "./timelineModel";

function TrimRow({ clip, edge }: { clip: Clip; edge: Edge }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const trim = (deltaSec: number) =>
    edit((project) => trimClip(project, clip.id, edge, deltaSec), `trim:${clip.id}:${edge}`);
  const seconds = edge === "start" ? clip.inSec : clip.outSec;
  return (
    <div className="trim-row">
      <span>{t(edge === "start" ? "review.in" : "review.out")}</span>
      <span className="mono">{seconds.toFixed(2)} s</span>
      <button
        type="button"
        aria-label={t(`edit.trim.${edge}.earlier`)}
        onClick={() => trim(-TRIM_STEP_SECONDS)}
      >
        −0.1
      </button>
      <button
        type="button"
        aria-label={t(`edit.trim.${edge}.later`)}
        onClick={() => trim(TRIM_STEP_SECONDS)}
      >
        +0.1
      </button>
    </div>
  );
}

function Takes({ project, clip, onSelect }: ClipPanelProps & { clip: Clip }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const takes = takesOf(project, clip.id);
  const kept = takes.find((take) => take.kept);
  if (takes.length < 2 || !kept) return null;
  const use = (alternativeId: string) => {
    edit((current) => swapTake(current, kept.clip.id, alternativeId));
    onSelect(alternativeId);
  };
  return (
    <section aria-label={t("edit.takes")}>
      <h3>{t("edit.takes")}</h3>
      <ol className="takes-list">
        {takes.map((take, index) => (
          <li key={take.clip.id} data-kept={take.kept || undefined}>
            <span className="meta mono">
              {index + 1} · {(take.clip.outSec - take.clip.inSec).toFixed(1)} s
            </span>
            <span className="take-text">{take.text || t("edit.noWords")}</span>
            {take.kept ? (
              <span className="meta">{t("edit.takeInUse")}</span>
            ) : (
              <button type="button" onClick={() => use(take.clip.id)}>
                {t("edit.useTake")}
              </button>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

interface ClipPanelProps {
  project: Project;
  clip: Clip | null;
  onSelect: (clipId: string) => void;
}

/** The selected clip: trim, speed, volume, remove/restore and its takes. */
export function ClipPanel({ project, clip, onSelect }: ClipPanelProps) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  if (!clip) return <p className="meta">{t("review.selectHint")}</p>;
  const source = project.sources.find((candidate) => candidate.id === clip.sourceId);
  const seconds = clipFrames(clip, project.fps) / project.fps;
  const confidence = clip.decisionConfidence;
  return (
    <div className="panel-body">
      <h2 className="row">
        <span className="swatch" style={{ background: source?.displayColor }} aria-hidden="true" />
        <span className="mono">{source ? fileLabel(source.originalPath) : clip.sourceId}</span>
      </h2>
      <dl className="details">
        <div>
          <dt>{t("edit.length")}</dt>
          <dd className="mono">{clip.removed ? t("review.removed") : `${seconds.toFixed(2)} s`}</dd>
        </div>
        <div>
          <dt>{t("review.confidence")}</dt>
          <dd className="mono">{confidence == null ? "—" : `${Math.round(confidence * 100)} %`}</dd>
        </div>
      </dl>
      <TrimRow clip={clip} edge="start" />
      <TrimRow clip={clip} edge="end" />
      <Slider
        label={t("review.speed")}
        value={clip.speed}
        min={0.5}
        max={2}
        format={(speed) => `${speed.toFixed(2)}×`}
        onChange={(speed) => edit((p) => setClipSpeed(p, clip.id, speed), `speed:${clip.id}`)}
      />
      <Slider
        label={t("edit.volume")}
        value={clip.volume}
        min={0}
        max={2}
        format={(volume) => `${Math.round(volume * 100)} %`}
        onChange={(volume) => edit((p) => setClipVolume(p, clip.id, volume), `volume:${clip.id}`)}
      />
      <button type="button" onClick={() => edit((p) => setRemoved(p, clip.id, !clip.removed))}>
        {clip.removed ? t("edit.restore") : t("edit.remove")}
      </button>
      <Takes project={project} clip={clip} onSelect={onSelect} />
    </div>
  );
}
