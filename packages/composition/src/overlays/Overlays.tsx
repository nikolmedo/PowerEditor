import { Sequence, useCurrentFrame, useVideoConfig } from "remotion";

import type { Overlay, Project } from "../types";
import { CountUp, ProgressRing } from "./Counters";
import {
  Cta,
  ImageGraphic,
  Logo,
  LowerThird,
  ProgressBar,
  Title,
  type GraphicContext,
} from "./Graphics";
import { overlayInsets, overlayUnit } from "./layout";
import { overlayExit, overlayMotion } from "./motion";
import { overlaySpans } from "./spans";
import { normalizeOverlayProps } from "./templates";

interface GraphicProps {
  overlay: Overlay;
  project: Project;
  from: number;
  durationInFrames: number;
  totalFrames: number;
  mediaBaseUrl: string;
}

/** One overlay inside its sequence: frames here count from the overlay's start. */
function Graphic({
  overlay,
  project,
  from,
  durationInFrames,
  totalFrames,
  mediaBaseUrl,
}: GraphicProps) {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const accent = project.subtitles.style.highlightColor;
  const context: GraphicContext = {
    presence: overlayMotion(frame, durationInFrames, fps),
    exit: overlayExit(frame, durationInFrames, fps),
    frame,
    fps,
    insets: overlayInsets(project, width, height),
    unit: overlayUnit(width, height),
  };
  const raw = overlay.props;
  switch (overlay.templateId) {
    case "title":
      return <Title props={normalizeOverlayProps("title", raw, accent)} {...context} />;
    case "lower_third":
      return <LowerThird props={normalizeOverlayProps("lower_third", raw, accent)} {...context} />;
    case "cta":
      return <Cta props={normalizeOverlayProps("cta", raw, accent)} {...context} />;
    case "logo":
      return (
        <Logo
          props={normalizeOverlayProps("logo", raw, accent)}
          mediaBaseUrl={mediaBaseUrl}
          {...context}
        />
      );
    case "progress_bar":
      return (
        <ProgressBar
          props={normalizeOverlayProps("progress_bar", raw, accent)}
          from={from}
          totalFrames={totalFrames}
          {...context}
        />
      );
    case "image":
      return (
        <ImageGraphic
          props={normalizeOverlayProps("image", raw, accent)}
          mediaBaseUrl={mediaBaseUrl}
          {...context}
        />
      );
    case "count_up":
      return <CountUp props={normalizeOverlayProps("count_up", raw, accent)} {...context} />;
    case "progress_ring":
      return (
        <ProgressRing
          props={normalizeOverlayProps("progress_ring", raw, accent)}
          durationInFrames={durationInFrames}
          {...context}
        />
      );
  }
}

/**
 * The graphics layer, drawn over the video and under the subtitles. The Player and the render
 * both draw it from the same project; images load from `mediaBaseUrl` like the clips do.
 */
export const Overlays: React.FC<{
  project: Project;
  totalFrames: number;
  mediaBaseUrl: string;
}> = ({ project, totalFrames, mediaBaseUrl }) => (
  <>
    {overlaySpans(project.overlays, totalFrames).map(({ overlay, from, durationInFrames }) => (
      <Sequence
        key={overlay.id}
        name={`overlay ${overlay.templateId}`}
        from={from}
        durationInFrames={durationInFrames}
      >
        <Graphic
          overlay={overlay}
          project={project}
          from={from}
          durationInFrames={durationInFrames}
          totalFrames={totalFrames}
          mediaBaseUrl={mediaBaseUrl}
        />
      </Sequence>
    ))}
  </>
);
