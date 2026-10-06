import { useContext } from "react";
import { AbsoluteFill, Series } from "remotion";

import { speechIntervals, voiceGains } from "./audio/ducking";
import { Music } from "./audio/Music";
import { ClipVideo } from "./clips/ClipVideo";
import { edgeFadeFrames } from "./clips/edgeFade";
import { MediaResolverContext, mediaUrl, mezzanineResolver } from "./clips/media";
import { ColorGraded } from "./color/ColorGraded";
import { clipColorMatrix } from "./color/matrix";
import { Overlays } from "./overlays/Overlays";
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
  /**
   * Play the music track (Player preview only). Renders leave it off: they are muted and
   * the backend mixes the music with ffmpeg, so Remotion never needs to load it.
   */
  previewMusic?: boolean;
};

export const ProjectVideo: React.FC<ProjectVideoProps> = ({
  project,
  audioCrossfadeMs,
  punchInScale,
  mediaBaseUrl,
  previewMusic = false,
}) => {
  const resolve = useContext(MediaResolverContext) ?? mezzanineResolver(mediaBaseUrl);
  const clips = new Map<string, Clip>(project.clips.map((clip) => [clip.id, clip]));
  const sources = new Map<string, Source>(project.sources.map((source) => [source.id, source]));
  const fadeFrames = edgeFadeFrames(audioCrossfadeMs, project.fps);
  const gains = voiceGains(project);
  const music = project.audioTracks.find((track) => track.kind === "music" && track.sourcePath);
  const layout = timelineLayout(project);
  // Zero-length clips still count toward the layout but cannot become sequences.
  const placements = layout.clips.filter((placement) => placement.durationInFrames > 0);

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
                <ColorGraded
                  matrix={clipColorMatrix(
                    project.colorGrade,
                    source.colorCorrection,
                    clip.colorOverride,
                  )}
                >
                  <ClipVideo
                    src={resolve(source)}
                    clip={clip}
                    sourceStartFrame={placement.sourceStartFrame}
                    durationInFrames={placement.durationInFrames}
                    fadeFrames={fadeFrames}
                    gain={gains.get(source.id) ?? 1}
                  />
                </ColorGraded>
              </ClipTransition>
            </Series.Sequence>
          );
        })}
      </Series>
      {previewMusic && music?.sourcePath && (
        <Music
          src={mediaUrl(mediaBaseUrl, music.sourcePath)}
          track={music}
          speech={speechIntervals(project.subtitles.words, project.fps)}
        />
      )}
      <Overlays
        project={project}
        totalFrames={layout.durationInFrames}
        mediaBaseUrl={mediaBaseUrl}
      />
      <Subtitles project={project} />
    </AbsoluteFill>
  );
};
