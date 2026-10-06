import { useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { dragSpan, framesForPixels, type DragMode, type Span } from "../edit/overlays";
import { useT } from "../i18n";
import { visibleSpan, type TimelineOverlay } from "./timelineModel";

export interface OverlayBlockHandlers {
  onSelectOverlay: (id: string) => void;
  /** A finished drag: one edit, so one undo step. */
  onOverlaySpan: (id: string, span: Span) => void;
  onNudgeOverlay: (id: string, deltaFrames: number) => void;
  onDeleteOverlay: (id: string) => void;
}

interface OverlayBlockProps extends OverlayBlockHandlers {
  overlay: TimelineOverlay;
  totalFrames: number;
  fps: number;
  minFrames: number;
  selected: boolean;
  label: string;
  timecode: (frame: number) => string;
}

interface Drag {
  mode: DragMode;
  originX: number;
  laneWidth: number;
  pointerId: number;
}

/**
 * An overlay on its lane of the Graphics track, cut at the end of the timeline (with a
 * "continues" edge when it runs past it). Drag the body to move it, drag an edge to resize it; the
 * block follows the pointer locally and the project changes once, on release. Arrow keys nudge
 * it by a frame (Shift: a second), Enter or Space selects it and Delete removes it.
 */
export function OverlayBlock({
  overlay,
  totalFrames,
  fps,
  minFrames,
  selected,
  label,
  timecode,
  onSelectOverlay,
  onOverlaySpan,
  onNudgeOverlay,
  onDeleteOverlay,
}: OverlayBlockProps) {
  const t = useT();
  const drag = useRef<Drag | null>(null);
  const [preview, setPreview] = useState<Span | null>(null);
  const shown = preview ?? overlay;
  // Only the part inside the timeline is drawn; an overlay longer than the video is cut there.
  const drawn = visibleSpan(shown, totalFrames);
  const length = Math.max(totalFrames, 1);

  const begin = (mode: DragMode) => (event: PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    const lane = event.currentTarget.closest(".lane");
    drag.current = {
      mode,
      originX: event.clientX,
      laneWidth: lane?.getBoundingClientRect().width ?? 0,
      pointerId: event.pointerId,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    onSelectOverlay(overlay.id);
  };
  const framesMoved = (current: Drag, clientX: number) =>
    framesForPixels(clientX - current.originX, current.laneWidth, totalFrames);
  // A drag starts from the block as drawn, so an end cut at the timeline end moves from there.
  const spanAt = (current: Drag, clientX: number) =>
    dragSpan(
      visibleSpan(overlay, totalFrames),
      current.mode,
      framesMoved(current, clientX),
      totalFrames,
      minFrames,
    );
  const move = (event: PointerEvent<HTMLElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    setPreview(spanAt(current, event.clientX));
  };
  // The drop is computed from the release itself, not from the last rendered preview.
  const end = (event: PointerEvent<HTMLElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    drag.current = null;
    setPreview(null);
    // A click without movement selects only; it must not cut an overlay that runs past the end.
    if (framesMoved(current, event.clientX) === 0) return;
    const span = spanAt(current, event.clientX);
    if (span.startFrame !== overlay.startFrame || span.endFrame !== overlay.endFrame) {
      onOverlaySpan(overlay.id, span);
    }
  };
  // A cancelled gesture or a lost capture (the element re-rendered away, another window took
  // the pointer) abandons the drag: the block snaps back and the project stays unchanged.
  // After a normal release the browser also reports the lost capture; `end` already finished.
  const cancel = (event: PointerEvent<HTMLElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    drag.current = null;
    setPreview(null);
  };
  const keys = (event: KeyboardEvent<HTMLElement>) => {
    const step = event.shiftKey ? fps : 1;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      onNudgeOverlay(overlay.id, event.key === "ArrowLeft" ? -step : step);
    } else if (event.key === "Delete" || event.key === "Backspace") {
      onDeleteOverlay(overlay.id);
    } else if (event.key === "Enter" || event.key === " ") {
      onSelectOverlay(overlay.id);
    } else {
      return;
    }
    // The editor's own shortcuts (clip selection, removal) must not see this key.
    event.preventDefault();
    event.stopPropagation();
  };

  return (
    <div
      role="button"
      tabIndex={0}
      className="bar bar-graphic overlay-block"
      style={
        {
          left: `${(drawn.startFrame / length) * 100}%`,
          width: `${((drawn.endFrame - drawn.startFrame) / length) * 100}%`,
          "--lane": overlay.lane,
        } as CSSProperties
      }
      aria-pressed={selected}
      aria-label={t("graphics.block", {
        template: label,
        start: timecode(shown.startFrame),
        end: timecode(shown.endFrame),
      })}
      data-dragging={preview ? true : undefined}
      data-auto={overlay.autoGenerated || undefined}
      data-continues={drawn.continues || undefined}
      onPointerDown={begin("move")}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={keys}
      // Pointer capture sends an edge's moves here too, so one set of handlers serves all.
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={cancel}
      onLostPointerCapture={cancel}
    >
      <span
        className="overlay-edge"
        data-edge="start"
        aria-hidden="true"
        onPointerDown={begin("start")}
      />
      <span className="overlay-label">{label}</span>
      <span
        className="overlay-edge"
        data-edge="end"
        aria-hidden="true"
        onPointerDown={begin("end")}
      />
    </div>
  );
}
