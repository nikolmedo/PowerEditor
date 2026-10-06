import { useMemo } from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";

import type { Project } from "../types";
import { loadSubtitleFont, SUBTITLE_FONT_FAMILY } from "./font";
import { activeLine, activeWordIndex, groupLines } from "./lines";
import { timelineWords } from "./remap";
import { highlightsActiveWord, lineStyle, safeAreaStyle } from "./styles";

loadSubtitleFont();

/** Peak scale of the `bold_pop` word that just started. */
const POP_SCALE = 1.12;

export const Subtitles: React.FC<{ project: Project }> = ({ project }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const { style } = project.subtitles;
  const lines = useMemo(
    () =>
      groupLines(timelineWords(project), {
        maxWordsPerLine: style.maxWordsPerLine,
        fps,
        durationInFrames,
      }),
    [project, style.maxWordsPerLine, fps, durationInFrames],
  );
  const line = activeLine(lines, frame);
  if (!line) return null;
  const active = activeWordIndex(line, frame);
  const highlight = highlightsActiveWord(style.preset);

  return (
    <AbsoluteFill style={safeAreaStyle(project.preset, style.position, width, height)}>
      <div style={lineStyle(style, SUBTITLE_FONT_FAMILY)}>
        {line.words.map((word, index) => {
          const isActive = index === active;
          const pop =
            style.preset === "bold_pop" && isActive
              ? spring({ frame: frame - word.startFrame, fps, config: { damping: 12 } })
              : 1;
          return (
            <span
              key={`${word.clipId}-${word.startFrame}-${index}`}
              style={{
                display: "inline-block",
                margin: "0 0.2em",
                color: highlight && isActive ? style.highlightColor : undefined,
                transform: `scale(${POP_SCALE - (POP_SCALE - 1) * pop})`,
              }}
            >
              {word.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
