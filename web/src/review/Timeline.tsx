import type { CSSProperties, MouseEvent, ReactNode } from "react";
import { useT, type MessageKey } from "../i18n";
import { frameAtRatio, type TimelineClip, type TimelineModel } from "./timelineModel";

interface TimelineProps {
  model: TimelineModel;
  frame: number;
  selectedId: string | null;
  onSeek: (frame: number) => void;
  onSelect: (clip: TimelineClip) => void;
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

function Track({
  label,
  onSeek,
  total,
  children,
}: {
  label: MessageKey;
  onSeek: (frame: number) => void;
  total: number;
  children: ReactNode;
}) {
  const t = useT();
  const seek = (event: MouseEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    onSeek(frameAtRatio((event.clientX - box.left) / Math.max(box.width, 1), total));
  };
  return (
    <div className="track">
      <span className="track-label">{t(label)}</span>
      {/* Clicking the lane seeks; every clip is also a button, so this is mouse-only sugar. */}
      <div className="lane" onClick={seek} role="presentation">
        {children}
      </div>
    </div>
  );
}

/** Read-only timeline: kept clips in their source color, removed clips as dimmed marks at
 * their cut, subtitle lines, graphics and music, with a playhead synced to the player. */
export function Timeline({ model, frame, selectedId, onSeek, onSelect }: TimelineProps) {
  const t = useT();
  const total = model.durationInFrames;
  const playhead = { left: `${(frame / Math.max(total, 1)) * 100}%` };

  return (
    <div className="timeline" aria-label={t("review.timeline")}>
      <div className="timeline-ruler mono">
        <span>{timecode(frame, model.fps)}</span>
        <span>{timecode(total, model.fps)}</span>
      </div>
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
                onSelect(clip);
              }}
            >
              {clip.takes > 0 && (
                <span className="takes mono">{t("review.takes", { count: clip.takes })}</span>
              )}
            </button>
          ))}
          {model.removed.map((clip) => (
            <span
              key={clip.clipId}
              className="removed-mark"
              style={
                {
                  left: `${(clip.startFrame / Math.max(total, 1)) * 100}%`,
                  "--clip": clip.color,
                } as CSSProperties
              }
              title={t("review.removed")}
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
        <Track label="track.graphics" onSeek={onSeek} total={total}>
          {model.graphics.map((overlay) => (
            <span
              key={overlay.id}
              className="bar bar-graphic"
              style={span(overlay.startFrame, overlay.endFrame, total)}
            >
              {t(`overlay.${overlay.templateId}`)}
            </span>
          ))}
        </Track>
        <Track label="track.music" onSeek={onSeek} total={total}>
          {model.music.map((track) => (
            <span key={track.id} className="bar bar-music" style={span(0, total, total)}>
              {track.label}
            </span>
          ))}
        </Track>
        <div className="playhead-layer" aria-hidden="true">
          <span className="playhead" style={playhead} />
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
