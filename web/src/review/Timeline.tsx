import {
  memo,
  useImperativeHandle,
  useMemo,
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
  type Ref,
} from "react";
import { useT, type MessageKey } from "../i18n";
import { minOverlayFrames } from "../edit/overlays";
import { OverlayBlock, type OverlayBlockHandlers } from "./OverlayBlock";
import {
  frameAtRatio,
  rulerInterval,
  rulerTicks,
  type TimelineClip,
  type TimelineModel,
  type VoiceSegment,
} from "./timelineModel";
import { useTimelineZoom } from "./useTimelineZoom";

/** What the review step's keys can do to the timeline. */
export interface TimelineHandle {
  zoom: (direction: -1 | 1) => void;
  fit: () => void;
}

interface TimelineProps extends OverlayBlockHandlers {
  model: TimelineModel;
  frame: number;
  selectedId: string | null;
  selectedOverlayId: string | null;
  onSeek: (frame: number) => void;
  onSelect: (clip: TimelineClip) => void;
  /** Alt-click: keep the clip's next take. */
  onSwapNext: (clip: TimelineClip) => void;
  /** The "N takes" badge: show the clip's takes. */
  onOpenTakes: (clip: TimelineClip) => void;
  /** The audio track the user picked on the timeline, shown in the Audio tab. */
  selectedTrackId: "voice" | "music" | null;
  /** A voice segment: select its clip and the voice track. */
  onSelectVoice: (segment: VoiceSegment) => void;
  /** The music bar: select the music track. */
  onSelectMusic: (trackId: string) => void;
  onToggleMute: (trackId: string, muted: boolean) => void;
  ref?: Ref<TimelineHandle>;
}

export function timecode(frame: number, fps: number): string {
  const seconds = frame / fps;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(1).padStart(4, "0")}`;
}

/** Position and width of a frame range as percentages of the timeline. */
function span(start: number, end: number, total: number): CSSProperties {
  const length = Math.max(total, 1);
  return { left: `${(start / length) * 100}%`, width: `${((end - start) / length) * 100}%` };
}

/** Seeks to the frame under a click on a lane or the ruler. */
function seekAt(event: MouseEvent<HTMLElement>, total: number, onSeek: (frame: number) => void) {
  const box = event.currentTarget.getBoundingClientRect();
  onSeek(frameAtRatio((event.clientX - box.left) / Math.max(box.width, 1), total));
}

/** Time labels along the top of the lanes. Memoized: the timeline redraws on every frame. */
const Ruler = memo(function Ruler({
  total,
  fps,
  pxPerSecond,
  onSeek,
  laneRef,
}: {
  total: number;
  fps: number;
  pxPerSecond: number;
  onSeek: (frame: number) => void;
  laneRef: Ref<HTMLDivElement>;
}) {
  const ticks = useMemo(
    () => rulerTicks(total, fps, rulerInterval(pxPerSecond)),
    [total, fps, pxPerSecond],
  );
  return (
    <div className="timeline-ruler mono" aria-hidden="true">
      <span className="ruler-corner" />
      <div ref={laneRef} className="ruler-lane" onClick={(event) => seekAt(event, total, onSeek)}>
        {ticks.map((tick) => (
          <span
            key={tick.frame}
            className="ruler-tick"
            style={{ left: `${(tick.frame / Math.max(total, 1)) * 100}%` }}
          >
            {tick.label}
          </span>
        ))}
      </div>
    </div>
  );
});

/** A speaker, crossed out while muted. */
function SpeakerIcon({ muted }: { muted: boolean }) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M2 6h3l4-3v10l-4-3H2z" fill="currentColor" />
      {muted ? (
        <path d="M11 6l4 4m0-4l-4 4" stroke="currentColor" strokeWidth="1.5" />
      ) : (
        <path d="M11 5.5a3.5 3.5 0 0 1 0 5" stroke="currentColor" strokeWidth="1.5" fill="none" />
      )}
    </svg>
  );
}

function MuteButton({
  muted,
  label,
  onToggle,
}: {
  muted: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className="track-mute"
      aria-pressed={muted}
      aria-label={label}
      title={label}
      onClick={onToggle}
    >
      <SpeakerIcon muted={muted} />
    </button>
  );
}

function Track({
  label,
  onSeek,
  total,
  lanes,
  track,
  selected,
  muted,
  control,
  children,
}: {
  label: MessageKey;
  onSeek: (frame: number) => void;
  total: number;
  /** Stacked rows for overlapping items; a track without it has a single row. */
  lanes?: number;
  /** An audio track the user can select and mute. */
  track?: "voice" | "music";
  selected?: boolean;
  muted?: boolean | undefined;
  /** A control next to the label (the mute button). */
  control?: ReactNode;
  children: ReactNode;
}) {
  const t = useT();
  return (
    <div
      className="track"
      data-lanes={lanes}
      data-track={track}
      data-selected={selected || undefined}
      data-muted={muted || undefined}
      style={lanes ? ({ "--lanes": lanes } as CSSProperties) : undefined}
    >
      <div className="track-label">
        <span>{t(label)}</span>
        {control}
      </div>
      {/* Clicking the lane seeks; every clip is also a button, so this is mouse-only sugar. */}
      <div className="lane" onClick={(event) => seekAt(event, total, onSeek)} role="presentation">
        {children}
      </div>
    </div>
  );
}

/** The edit timeline: kept clips in their source color, removed clips as dimmed marks at their
 * cut (selectable, to restore them), the clips' own audio on the Voice track (derived from the
 * kept clips, so it follows takes and trims), subtitle lines, graphics and music, with a playhead
 * synced to the player. It zooms and scrolls horizontally (`useTimelineZoom`). */
export function Timeline({
  model,
  frame,
  selectedId,
  onSeek,
  onSelect,
  onSwapNext,
  onOpenTakes,
  selectedTrackId,
  onSelectVoice,
  onSelectMusic,
  onToggleMute,
  selectedOverlayId,
  ref,
  ...overlayHandlers
}: TimelineProps) {
  const t = useT();
  const total = model.durationInFrames;
  const playhead = { left: `${(frame / Math.max(total, 1)) * 100}%` };
  const { scrollRef, laneRef, zoom, maxZoom, viewWidth, zoomBy, fit } = useTimelineZoom(
    total,
    model.fps,
    frame,
  );
  useImperativeHandle(ref, () => ({ zoom: zoomBy, fit }), [zoomBy, fit]);
  const pxPerSecond = (viewWidth * zoom * model.fps) / Math.max(total, 1);
  const voiceTrack = model.voiceTrack;
  const music = model.music[0];

  return (
    <div className="timeline" aria-label={t("review.timeline")}>
      <div className="timeline-header">
        <span className="timeline-time mono">
          <span>{timecode(frame, model.fps)}</span> / {timecode(total, model.fps)}
        </span>
        <div className="timeline-zoom" role="group" aria-label={t("review.zoom")}>
          <button
            type="button"
            aria-label={t("review.zoomOut")}
            disabled={zoom <= 1}
            onClick={() => zoomBy(-1)}
          >
            −
          </button>
          <span className="mono" aria-live="polite">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            aria-label={t("review.zoomIn")}
            disabled={zoom >= maxZoom}
            onClick={() => zoomBy(1)}
          >
            +
          </button>
          <button type="button" aria-label={t("review.zoomFit")} disabled={zoom <= 1} onClick={fit}>
            {t("review.fit")}
          </button>
        </div>
      </div>
      <div className="timeline-scroll" ref={scrollRef}>
        <div
          className="timeline-content"
          data-zoom={zoom}
          style={{ "--zoom": zoom } as CSSProperties}
        >
          <Ruler
            total={total}
            fps={model.fps}
            pxPerSecond={pxPerSecond}
            onSeek={onSeek}
            laneRef={laneRef}
          />
          <div className="tracks">
            <Track label="track.video" onSeek={onSeek} total={total}>
              {model.video.map((clip) => (
                <button
                  key={clip.clipId}
                  type="button"
                  className="clip"
                  style={
                    {
                      ...span(clip.startFrame, clip.startFrame + clip.durationInFrames, total),
                      "--clip": clip.color,
                    } as CSSProperties
                  }
                  data-low-confidence={clip.lowConfidence || undefined}
                  aria-pressed={clip.clipId === selectedId}
                  aria-label={t("review.clipAt", { time: timecode(clip.startFrame, model.fps) })}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (event.altKey && clip.takes > 0) onSwapNext(clip);
                    else onSelect(clip);
                  }}
                >
                  {clip.takes > 0 && (
                    // Mouse shortcut to the takes list; the clip panel lists the takes for keyboards.
                    <span
                      className="takes mono"
                      role="presentation"
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenTakes(clip);
                      }}
                    >
                      {t("review.takes", { count: clip.takes })}
                    </span>
                  )}
                </button>
              ))}
              {model.removed.map((clip) => (
                <button
                  key={clip.clipId}
                  type="button"
                  className="removed-mark"
                  style={
                    {
                      left: `${(clip.startFrame / Math.max(total, 1)) * 100}%`,
                      "--clip": clip.color,
                    } as CSSProperties
                  }
                  title={t("review.removed")}
                  aria-pressed={clip.clipId === selectedId}
                  aria-label={t("edit.removedAt", { time: timecode(clip.startFrame, model.fps) })}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(clip);
                  }}
                />
              ))}
            </Track>
            <Track
              label="track.voice"
              onSeek={onSeek}
              total={total}
              track="voice"
              selected={selectedTrackId === "voice"}
              muted={voiceTrack?.muted}
              control={
                voiceTrack && (
                  <MuteButton
                    muted={voiceTrack.muted}
                    label={t(voiceTrack.muted ? "track.unmuteVoice" : "track.muteVoice")}
                    onToggle={() => onToggleMute(voiceTrack.id, !voiceTrack.muted)}
                  />
                )
              }
            >
              {model.voice.map((segment) => (
                <button
                  key={segment.clipId}
                  type="button"
                  className="voice-segment"
                  style={
                    {
                      ...span(
                        segment.startFrame,
                        segment.startFrame + segment.durationInFrames,
                        total,
                      ),
                      "--clip": segment.color,
                    } as CSSProperties
                  }
                  data-silent={segment.volume === 0 || undefined}
                  aria-pressed={selectedTrackId === "voice" && segment.clipId === selectedId}
                  aria-label={t("review.voiceAt", {
                    time: timecode(segment.startFrame, model.fps),
                  })}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelectVoice(segment);
                  }}
                />
              ))}
            </Track>
            <Track label="track.subtitles" onSeek={onSeek} total={total}>
              {model.subtitles.map((line) => (
                <span
                  key={line.startFrame}
                  className="bar bar-text"
                  style={span(line.startFrame, line.endFrame, total)}
                  title={line.text}
                >
                  {line.text}
                </span>
              ))}
            </Track>
            <Track label="track.graphics" onSeek={onSeek} total={total} lanes={model.graphicsLanes}>
              {model.graphics.map((overlay) => (
                <OverlayBlock
                  key={overlay.id}
                  overlay={overlay}
                  totalFrames={total}
                  fps={model.fps}
                  minFrames={minOverlayFrames(model.fps)}
                  selected={overlay.id === selectedOverlayId}
                  label={t(`overlay.${overlay.templateId}`)}
                  timecode={(frame) => timecode(frame, model.fps)}
                  {...overlayHandlers}
                />
              ))}
            </Track>
            <Track
              label="track.music"
              onSeek={onSeek}
              total={total}
              track="music"
              selected={selectedTrackId === "music"}
              muted={music?.muted}
              control={
                music && (
                  <MuteButton
                    muted={music.muted}
                    label={t(music.muted ? "track.unmuteMusic" : "track.muteMusic")}
                    onToggle={() => onToggleMute(music.id, !music.muted)}
                  />
                )
              }
            >
              {model.music.map((track) => (
                <button
                  key={track.id}
                  type="button"
                  className="bar bar-music"
                  style={span(0, total, total)}
                  aria-pressed={selectedTrackId === "music"}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelectMusic(track.id);
                  }}
                >
                  {track.label}
                </button>
              ))}
            </Track>
            <div className="playhead-layer" aria-hidden="true">
              <span className="playhead" style={playhead} />
            </div>
          </div>
        </div>
      </div>
      <ul className="legend" aria-label={t("review.legend")}>
        {model.legend.map((entry) => (
          <li key={entry.sourceId}>
            <span className="swatch" style={{ background: entry.color }} aria-hidden="true" />
            <span className="mono">{entry.label}</span>
            <span className="meta mono">{entry.seconds.toFixed(1)} s</span>
          </li>
        ))}
        <li className="legend-key">
          <span className="swatch swatch-low" aria-hidden="true" />
          {t("review.lowConfidence")}
        </li>
      </ul>
    </div>
  );
}
