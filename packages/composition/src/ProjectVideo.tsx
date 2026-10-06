import { useContext } from "react";
import { AbsoluteFill, Series } from "remotion";

import { ClipVideo } from "./clips/ClipVideo";
import { edgeFadeFrames } from "./clips/edgeFade";
import { MediaResolverContext, mezzanineResolver } from "./clips/media";
import { Subtitles } from "./subtitles/Subtitles";
import { timelineLayout } from "./timeline";
import { ClipTransition } from "./transitions/ClipTransition";
import type { Clip, Project, Source } from "./types";

/** Input props of the `ProjectVideo` composition (must stay JSON-serializable). */
export type ProjectVideoProps = {
  project: Project;
  /**
   * Edge fade at both ends of every clip (UserSettings.audioCrossfadeMs), for Player preview
   * only. Remotion applies volume per video frame, so the preview can still click at cuts;
   * renders are muted and the backend rebuilds the voice sample-accurately with ffmpeg.
   */
  audioCrossfadeMs: number;
  /** Zoom of `punch_in` clips (UserSettings.punchInScale). */
  punchInScale: number;
  /** Where render-time media is served; each source loads `${mediaBaseUrl}/<mezzanine file name>`. */
  mediaBaseUrl: string;
};

export const ProjectVideo: React.FC<ProjectVideoProps> = ({
  project,
  audioCrossfadeMs,
  punchInScale,
  mediaBaseUrl,
}) => {
  const resolve = useContext(MediaResolverContext) ?? mezzanineResolver(mediaBaseUrl);
  const clips = new Map<string, Clip>(project.clips.map((clip) => [clip.id, clip]));
  const sources = new Map<string, Source>(project.sources.map((source) => [source.id, source]));
  const fadeFrames = edgeFadeFrames(audioCrossfadeMs, project.fps);
  // Zero-length clips still count toward the layout but cannot become sequences.
  const placements = timelineLayout(project).clips.filter(
    (placement) => placement.durationInFrames > 0,
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <Series>
        {placements.map((placement) => {
          const clip = clips.get(placement.clipId);
          const source = clip && sources.get(clip.sourceId);
          if (!clip || !source) {
            throw new Error(`clip ${placement.clipId} references a missing source`);
          }
          return (
            <Series.Sequence key={clip.id} durationInFrames={placement.durationInFrames}>
              <ClipTransition transition={clip.transitionIn} punchInScale={punchInScale}>
                <ClipVideo
                  src={resolve(source)}
                  clip={clip}
                  sourceStartFrame={placement.sourceStartFrame}
                  durationInFrames={placement.durationInFrames}
                  fadeFrames={fadeFrames}
                />
              </ClipTransition>
            </Series.Sequence>
          );
        })}
      </Series>
      <Subtitles project={project} />
    </AbsoluteFill>
  );
};
