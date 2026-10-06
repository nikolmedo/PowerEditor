import { useMemo } from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

import type { Project } from "../types";
import { emphasizedWordIndex, hasEmoji } from "./emphasis";
import { loadSubtitleFont, SUBTITLE_FONT_FAMILY } from "./font";
import { activeLine, activeWordIndex, groupLines } from "./lines";
import { timelineWords } from "./remap";
import { lineStyle, safeAreaStyle } from "./styles";
import { wordStyle } from "./wordStyle";

loadSubtitleFont();

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
  const emphasized =
    style.preset === "editorial_emphasis"
      ? emphasizedWordIndex(line.words.map((word) => word.text))
      : -1;

  return (
    <AbsoluteFill style={safeAreaStyle(project.preset, style.position, width, height)}>
      <div style={lineStyle(style, SUBTITLE_FONT_FAMILY)}>
        {line.words.map((word, index) => (
          <span
            key={`${word.clipId}-${word.startFrame}-${index}`}
            style={{
              display: "inline-block",
              margin: "0 0.2em",
              ...wordStyle(style.preset, {
                isActive: index === active,
                framesSinceStart: frame - word.startFrame,
                fps,
                highlightColor: style.highlightColor,
                emphasized: index === emphasized,
                emoji: style.preset === "emoji_pop" && hasEmoji(word.text),
              }),
            }}
          >
            {word.text}
          </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};
