import { videoMetadata, type Project } from "@powereditor/composition";
import { Player, type CallbackListener, type PlayerRef } from "@remotion/player";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "zustand";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { setRemoved, swapTake, trimClip } from "../edit/operations";
import { moveOverlay, removeOverlay, setOverlaySpan } from "../edit/overlays";
import { useT, type MessageKey } from "../i18n";
import { stepPath } from "../routes";
import { Link } from "../shell/AppShell";
import { useProjectStore } from "../store/project";
import { ErrorNotice, Status } from "../ui/primitives";
import { useResource } from "../ui/useResource";
import { AudioPanel } from "./AudioPanel";
import { ClipPanel } from "./ClipPanel";
import { ColorPanel } from "./ColorPanel";
import { editorCommand, ownsKeys } from "./editorKeys";
import { GraphicsPanel } from "./GraphicsPanel";
import { PreviewVideo, projectMediaBase } from "./PreviewVideo";
import { SubtitlesPanel } from "./SubtitlesPanel";
import { Timeline, type TimelineHandle } from "./Timeline";
import { buildTimeline, neighbourClip, type TimelineClip } from "./timelineModel";
import { TransitionsPanel } from "./TransitionsPanel";
import { useAutosave, type AutosaveState } from "./useAutosave";

/** Defaults of the user settings, used until (or if) the settings cannot be read. */
const PREVIEW_DEFAULTS = { audioCrossfadeMs: 15, punchInScale: 1.1, modelMinConfidence: 0.8 };
const PANELS = ["clip", "transitions", "subtitles", "audio", "color", "graphics"] as const;
type PanelName = (typeof PANELS)[number];

const SAVE_LABELS: Record<AutosaveState["status"], [MessageKey, boolean | null]> = {
  saved: ["save.saved", true],
  pending: ["save.pending", null],
  saving: ["save.saving", null],
  conflict: ["save.conflict", false],
  error: ["save.error", false],
};

function Toolbar({ save }: { save: AutosaveState }) {
  const t = useT();
  const { undo, redo } = useProjectStore();
  const canUndo = useStore(useProjectStore.temporal, (state) => state.pastStates.length > 0);
  const canRedo = useStore(useProjectStore.temporal, (state) => state.futureStates.length > 0);
  const [label, ok] = SAVE_LABELS[save.status];
  return (
    <div className="row toolbar">
      <button type="button" className="quiet" disabled={!canUndo} onClick={undo}>
        {t("edit.undo")}
      </button>
      <button type="button" className="quiet" disabled={!canRedo} onClick={redo}>
        {t("edit.redo")}
      </button>
      <span role="status">
        <Status ok={ok}>{t(label)}</Status>
      </span>
    </div>
  );
}

function SaveProblem({ save, onReload }: { save: AutosaveState; onReload: () => void }) {
  const t = useT();
  if (save.status === "conflict") {
    return (
      <div className="notice notice-warn" role="alert">
        <p>{t("save.conflictHint")}</p>
        <div className="row">
          <button type="button" onClick={onReload}>
            {t("save.reload")}
          </button>
          <button type="button" className="quiet" onClick={() => void save.keepMine()}>
            {t("save.keepMine")}
          </button>
        </div>
      </div>
    );
  }
  if (save.status !== "error") return null;
  return (
    <div className="row">
      <ErrorNotice error={save.error} />
      <button type="button" onClick={save.flush}>
        {t("save.retry")}
      </button>
    </div>
  );
}

function Editor({ projectId, project }: { projectId: string; project: Project }) {
  const t = useT();
  const settings = useResource(useCallback(() => api.settings(), []));
  const preview = settings.data?.settings ?? PREVIEW_DEFAULTS;
  const { edit, undo, redo } = useProjectStore();
  const playerRef = useRef<PlayerRef>(null);
  const timelineRef = useRef<TimelineHandle>(null);
  const [frame, setFrame] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedOverlayId, setSelectedOverlayId] = useState<string | null>(null);
  const [panel, setPanel] = useState<PanelName>("clip");

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
      previewMusic: true,
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

  const seek = useCallback((target: number) => {
    playerRef.current?.seekTo(target);
    setFrame(target);
  }, []);
  const select = useCallback(
    (clip: TimelineClip) => {
      setSelectedId(clip.clipId);
      seek(clip.startFrame);
    },
    [seek],
  );
  const selected = project.clips.find((clip) => clip.id === selectedId) ?? null;

  const swapNext = (clip: TimelineClip) => {
    const kept = project.clips.find((candidate) => candidate.id === clip.clipId);
    const next = kept?.alternativeTakeIds.at(-1);
    if (!next) return;
    edit((current) => swapTake(current, clip.clipId, next));
    setSelectedId(next);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || ownsKeys(event.target)) return;
      const command = editorCommand(event);
      if (!command) return;
      event.preventDefault();
      if (command.type === "undo") return undo();
      if (command.type === "redo") return redo();
      if (command.type === "move") {
        const target = neighbourClip(model, selectedId, command.step);
        if (target) select(target);
        return;
      }
      if (command.type === "zoom") return timelineRef.current?.zoom(command.direction);
      if (command.type === "zoomFit") return timelineRef.current?.fit();
      if (!selectedId) return;
      if (command.type === "toggleRemoved") {
        const removed = project.clips.find((clip) => clip.id === selectedId)?.removed ?? false;
        edit((current) => setRemoved(current, selectedId, !removed));
      } else {
        const { edge, deltaSec } = command;
        edit(
          (current) => trimClip(current, selectedId, edge, deltaSec),
          `trim:${selectedId}:${edge}`,
        );
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [edit, undo, redo, model, project, selectedId, select]);

  return (
    <div className="editor">
      <div className="player-frame">
        <Player
          ref={playerRef}
          component={PreviewVideo}
          inputProps={inputProps}
          durationInFrames={Math.max(1, metadata.durationInFrames)}
          fps={metadata.fps}
          compositionWidth={metadata.width}
          compositionHeight={metadata.height}
          style={{ width: "100%", height: "100%" }}
          controls
        />
      </div>
      <aside className="side-panel" aria-label={t(`panel.${panel}`)}>
        <div className="segmented" role="tablist" aria-label={t("panel.label")}>
          {PANELS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={panel === name}
              onClick={() => setPanel(name)}
            >
              {t(`panel.${name}`)}
            </button>
          ))}
        </div>
        {panel === "clip" && (
          <ClipPanel project={project} clip={selected} onSelect={setSelectedId} />
        )}
        {panel === "transitions" && <TransitionsPanel clip={selected} />}
        {panel === "subtitles" && <SubtitlesPanel project={project} />}
        {panel === "audio" && <AudioPanel projectId={projectId} project={project} />}
        {panel === "color" && <ColorPanel project={project} clip={selected} />}
        {panel === "graphics" && (
          <GraphicsPanel
            projectId={projectId}
            project={project}
            frame={frame}
            selectedId={selectedOverlayId}
            onSelect={setSelectedOverlayId}
          />
        )}
      </aside>
      <Timeline
        ref={timelineRef}
        model={model}
        frame={frame}
        selectedId={selectedId}
        onSeek={seek}
        onSelect={select}
        onSwapNext={swapNext}
        onOpenTakes={(clip) => {
          select(clip);
          setPanel("clip");
        }}
        selectedOverlayId={selectedOverlayId}
        onSelectOverlay={(id) => {
          setSelectedOverlayId(id);
          setPanel("graphics");
        }}
        onOverlaySpan={(id, span) =>
          edit((current) => setOverlaySpan(current, id, span.startFrame, span.endFrame))
        }
        onNudgeOverlay={(id, delta) =>
          edit((current) => moveOverlay(current, id, delta), `nudge:${id}`)
        }
        onDeleteOverlay={(id) => {
          edit((current) => removeOverlay(current, id));
          setSelectedOverlayId(null);
        }}
      />
      <p className="meta shortcuts">{t("edit.shortcuts")}</p>
    </div>
  );
}

export function ReviewStep({ projectId }: { projectId: string }) {
  const t = useT();
  const loadIntoStore = useProjectStore((state) => state.load);
  const project = useProjectStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  const loaded = useResource(useCallback(() => api.project(projectId), [projectId]));
  const save = useAutosave(projectId);

  useEffect(() => {
    if (loaded.data) loadIntoStore(projectId, loaded.data.project, loaded.data.etag);
  }, [loaded.data, loadIntoStore, projectId]);

  const notAnalyzed =
    loaded.error instanceof ApiError && loaded.error.code === "project_not_analyzed";
  return (
    <section className="screen wide">
      <div className="screen-head">
        <h1>{t("review.title")}</h1>
        {project && (
          <div className="row">
            <Toolbar save={save} />
            <Link to={stepPath("export", projectId) as string} className="button primary">
              {t("review.toExport")}
            </Link>
          </div>
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
      <SaveProblem save={save} onReload={() => void loaded.reload()} />
      {loaded.loading && !project && <p className="lede">{t("common.loading")}</p>}
      {project && <Editor projectId={projectId} project={project} />}
    </section>
  );
}
