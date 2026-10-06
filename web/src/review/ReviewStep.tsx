import { videoMetadata, type Clip, type Project } from "@powereditor/composition";
import { Player, type CallbackListener, type PlayerRef } from "@remotion/player";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { useT } from "../i18n";
import { stepPath } from "../routes";
import { Link } from "../shell/AppShell";
import { useProjectStore } from "../store/project";
import { ErrorNotice } from "../ui/primitives";
import { useResource } from "../ui/useResource";
import { PreviewVideo, projectMediaBase } from "./PreviewVideo";
import { Timeline } from "./Timeline";
import { buildTimeline, fileLabel, type TimelineClip } from "./timelineModel";

/** Defaults of the user settings, used until (or if) the settings cannot be read. */
const PREVIEW_DEFAULTS = { audioCrossfadeMs: 15, punchInScale: 1.1, modelMinConfidence: 0.8 };

function ClipPanel({ project, clip }: { project: Project; clip: Clip | null }) {
  const t = useT();
  if (!clip) {
    return (
      <aside className="side-panel">
        <h2>{t("review.clip")}</h2>
        <p className="meta">{t("review.selectHint")}</p>
      </aside>
    );
  }
  const source = project.sources.find((candidate) => candidate.id === clip.sourceId);
  const rows: [string, string][] = [
    [t("review.source"), source ? fileLabel(source.originalPath) : clip.sourceId],
    [t("review.in"), `${clip.inSec.toFixed(2)} s`],
    [t("review.out"), `${clip.outSec.toFixed(2)} s`],
    [t("review.speed"), `${clip.speed}×`],
    [t("review.transition"), t(`transition.${clip.transitionIn.type}`)],
    [
      t("review.confidence"),
      clip.decisionConfidence == null ? "—" : `${Math.round(clip.decisionConfidence * 100)} %`,
    ],
    [t("review.takeCount"), String(clip.alternativeTakeIds.length + 1)],
  ];
  return (
    <aside className="side-panel" aria-label={t("review.clip")}>
      <h2 className="row">
        <span className="swatch" style={{ background: source?.displayColor }} aria-hidden="true" />
        {t("review.clip")}
      </h2>
      <dl className="details">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className="mono">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="meta">{t("review.readOnly")}</p>
    </aside>
  );
}

function Editor({ projectId, project }: { projectId: string; project: Project }) {
  const settings = useResource(useCallback(() => api.settings(), []));
  const preview = settings.data?.settings ?? PREVIEW_DEFAULTS;
  const playerRef = useRef<PlayerRef>(null);
  const [frame, setFrame] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const metadata = videoMetadata(project);
  const model = useMemo(
    () => buildTimeline(project, preview.modelMinConfidence),
    [project, preview.modelMinConfidence],
  );
  const inputProps = useMemo(
    () => ({
      project,
      audioCrossfadeMs: preview.audioCrossfadeMs,
      punchInScale: preview.punchInScale,
      mediaBaseUrl: projectMediaBase(projectId),
    }),
    [project, projectId, preview.audioCrossfadeMs, preview.punchInScale],
  );

  useEffect(() => {
    const player = playerRef.current;
    if (!player) return;
    const update: CallbackListener<"frameupdate"> = (event) => setFrame(event.detail.frame);
    player.addEventListener("frameupdate", update);
    return () => player.removeEventListener("frameupdate", update);
  }, []);

  const seek = (target: number) => {
    playerRef.current?.seekTo(target);
    setFrame(target);
  };
  const select = (clip: TimelineClip) => {
    setSelectedId(clip.clipId);
    seek(clip.startFrame);
  };
  const selected = project.clips.find((clip) => clip.id === selectedId) ?? null;

  return (
    <div className="editor">
      <div className="player-frame">
        <Player
          ref={playerRef}
          component={PreviewVideo}
          inputProps={inputProps}
          durationInFrames={metadata.durationInFrames}
          fps={metadata.fps}
          compositionWidth={metadata.width}
          compositionHeight={metadata.height}
          style={{ width: "100%", height: "100%" }}
          controls
        />
      </div>
      <ClipPanel project={project} clip={selected} />
      <Timeline
        model={model}
        frame={frame}
        selectedId={selectedId}
        onSeek={seek}
        onSelect={select}
      />
    </div>
  );
}

export function ReviewStep({ projectId }: { projectId: string }) {
  const t = useT();
  const loadIntoStore = useProjectStore((state) => state.load);
  const loaded = useResource(useCallback(() => api.project(projectId), [projectId]));

  useEffect(() => {
    if (loaded.data) loadIntoStore(loaded.data.project, loaded.data.etag);
  }, [loaded.data, loadIntoStore]);

  const notAnalyzed =
    loaded.error instanceof ApiError && loaded.error.code === "project_not_analyzed";
  return (
    <section className="screen wide">
      <div className="screen-head">
        <h1>{t("review.title")}</h1>
        {loaded.data && (
          <Link to={stepPath("export", projectId) as string} className="button primary">
            {t("review.toExport")}
          </Link>
        )}
      </div>
      {notAnalyzed ? (
        <div className="notice notice-warn">
          <p>{t("review.notAnalyzed")}</p>
          <Link to={stepPath("load", projectId) as string} className="button">
            {t("review.toLoad")}
          </Link>
        </div>
      ) : (
        <ErrorNotice error={loaded.error} />
      )}
      {loaded.loading && !loaded.data && <p className="lede">{t("common.loading")}</p>}
      {loaded.data && <Editor projectId={projectId} project={loaded.data.project} />}
    </section>
  );
}
