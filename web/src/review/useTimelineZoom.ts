import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  clampZoom,
  followScrollLeft,
  maxZoom,
  wheelPixels,
  wheelZoomRatio,
  zoomedScrollLeft,
  zoomStep,
} from "./timelineModel";

/**
 * Zoom and horizontal scroll of the timeline. The lanes are `zoom` times as wide as the visible
 * part of the scroller, so every position stays a percentage of the lane. Ctrl/Cmd+wheel and
 * trackpad pinch zoom about the pointer, Shift+wheel scrolls; buttons and keys zoom about the
 * playhead when it is in view, else about the middle of the view. While the frame changes, the
 * view pages to keep the playhead visible.
 */
export function useTimelineZoom(durationInFrames: number, fps: number, frame: number) {
  // The scroller, and a lane in it: every lane has the same zoomed width.
  const scrollRef = useRef<HTMLDivElement>(null);
  const laneRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  // The visible width of a lane, which is its whole width at 1x.
  const [viewWidth, setViewWidth] = useState(0);
  const max = maxZoom(durationInFrames / fps, viewWidth);
  const shown = clampZoom(zoom, max);
  // The latest values for the event handlers: wheel events can come faster than renders, so a
  // zoom is recorded here at once, with the scroll it needs once the wider lanes are drawn.
  const latest = useRef({ zoom: shown, max, viewWidth, frame, durationInFrames });
  const pendingScroll = useRef<number | null>(null);

  useLayoutEffect(() => {
    latest.current = { zoom: shown, max, viewWidth, frame, durationInFrames };
  });

  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    if (scroller && pendingScroll.current !== null) scroller.scrollLeft = pendingScroll.current;
    pendingScroll.current = null;
  }, [shown]);

  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    const lane = laneRef.current;
    if (!scroller || !lane) return;
    const measure = () => setViewWidth(lane.getBoundingClientRect().width / latest.current.zoom);
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(scroller);
    return () => observer.disconnect();
  }, []);

  /** Zoom to `next`, keeping the point `viewX` pixels into the visible lane where it is. */
  const zoomAbout = useCallback((next: number, viewX?: number) => {
    const scroller = scrollRef.current;
    const current = latest.current;
    const to = clampZoom(next, current.max);
    if (!scroller || to === current.zoom) return;
    const scrollLeft = pendingScroll.current ?? scroller.scrollLeft;
    const playheadX =
      (current.frame / Math.max(current.durationInFrames, 1)) * current.viewWidth * current.zoom -
      scrollLeft;
    const inView = playheadX >= 0 && playheadX <= current.viewWidth;
    const anchor = viewX ?? (inView ? playheadX : current.viewWidth / 2);
    pendingScroll.current = zoomedScrollLeft(scrollLeft, scrollLeft + anchor, to / current.zoom);
    latest.current = { ...current, zoom: to };
    setZoom(to);
  }, []);

  const zoomBy = useCallback(
    (direction: -1 | 1) => zoomAbout(zoomStep(latest.current.zoom, direction, latest.current.max)),
    [zoomAbout],
  );
  const fit = useCallback(() => zoomAbout(1), [zoomAbout]);

  // React's onWheel is passive and cannot cancel the page's own zoom or scroll.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const onWheel = (event: WheelEvent) => {
      const { zoom: current, viewWidth: visible } = latest.current;
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        // The labels take the part of the scroller left of the lanes.
        const laneLeft = scroller.getBoundingClientRect().left + scroller.clientWidth - visible;
        const viewX = Math.min(Math.max(event.clientX - laneLeft, 0), visible);
        zoomAbout(current * wheelZoomRatio(event.deltaY, event.deltaMode), viewX);
      } else if (event.shiftKey && current > 1) {
        event.preventDefault();
        scroller.scrollLeft += wheelPixels(event.deltaX || event.deltaY, event.deltaMode);
      }
    };
    scroller.addEventListener("wheel", onWheel, { passive: false });
    return () => scroller.removeEventListener("wheel", onWheel);
  }, [zoomAbout]);

  // Only a new frame moves the view, so scrolling away while paused is left alone.
  useEffect(() => {
    const scroller = scrollRef.current;
    const current = latest.current;
    if (!scroller || current.zoom <= 1) return;
    const playheadX =
      (frame / Math.max(current.durationInFrames, 1)) * current.viewWidth * current.zoom;
    const target = followScrollLeft(scroller.scrollLeft, current.viewWidth, playheadX);
    if (target !== null) scroller.scrollLeft = target;
  }, [frame]);

  return { scrollRef, laneRef, zoom: shown, maxZoom: max, viewWidth, zoomBy, fit };
}
