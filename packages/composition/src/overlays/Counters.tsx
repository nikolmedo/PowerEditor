import { AbsoluteFill, useVideoConfig } from "remotion";

import { SUBTITLE_FONT_FAMILY } from "../subtitles/font";
import { area, SHADOW, type GraphicContext } from "./base";
import {
  countDecimals,
  countUpValue,
  formatCount,
  ringDashOffset,
  ringProgress,
} from "./countMath";
import type { CountUpProps, ProgressRingProps } from "./templates";

/** A number that counts up from zero, with a prefix, a suffix and an optional label. */
export const CountUp: React.FC<{ props: CountUpProps } & GraphicContext> = ({
  props,
  presence,
  frame,
  fps,
  insets,
  unit,
}) => {
  const shown = formatCount(countUpValue(frame, fps, props.value), countDecimals(props.value));
  return (
    <AbsoluteFill style={area(insets, props.position)}>
      <div
        style={{
          opacity: presence,
          transform: `translateY(${(1 - presence) * 30 * unit}px)`,
          textAlign: "center",
          color: "white",
          textShadow: SHADOW,
        }}
      >
        <div
          style={{
            fontSize: 150 * unit,
            fontWeight: 800,
            lineHeight: 1,
            letterSpacing: "-0.03em",
            // Equal-width digits, so the number does not wobble while it counts.
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {props.prefix}
          <span style={{ color: props.color }}>{shown}</span>
          {props.suffix}
        </div>
        {props.label && (
          <div style={{ marginTop: 12 * unit, fontSize: 40 * unit, fontWeight: 700 }}>
            {props.label}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};

/** A ring in a corner that fills over the overlay's span, with an optional label inside. */
export const ProgressRing: React.FC<
  { props: ProgressRingProps; durationInFrames: number } & GraphicContext
> = ({ props, durationInFrames, presence, frame, insets, unit }) => {
  const { width } = useVideoConfig();
  const [vertical, horizontal] = props.corner.split("_") as ["top" | "bottom", "left" | "right"];
  const diameter = props.size * width;
  const stroke = Math.max(2, 10 * unit);
  const radius = (diameter - stroke) / 2;
  const progress = ringProgress(frame, durationInFrames);
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          [vertical]: insets[vertical],
          [horizontal]: insets[horizontal],
          width: diameter,
          height: diameter,
          opacity: presence,
          transform: `scale(${0.85 + 0.15 * presence})`,
        }}
      >
        <svg width={diameter} height={diameter} style={{ position: "absolute", inset: 0 }}>
          <circle
            cx={diameter / 2}
            cy={diameter / 2}
            r={radius}
            fill="rgba(10,10,10,0.55)"
            stroke="rgba(255,255,255,0.25)"
            strokeWidth={stroke}
          />
          <circle
            cx={diameter / 2}
            cy={diameter / 2}
            r={radius}
            fill="none"
            stroke={props.color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={2 * Math.PI * radius}
            strokeDashoffset={ringDashOffset(progress, radius)}
            // Start at twelve o'clock and run clockwise.
            transform={`rotate(-90 ${diameter / 2} ${diameter / 2})`}
          />
        </svg>
        {props.label && (
          <AbsoluteFill
            style={{
              alignItems: "center",
              justifyContent: "center",
              color: "white",
              fontFamily: SUBTITLE_FONT_FAMILY,
              fontWeight: 800,
              fontSize: diameter * 0.2,
              textAlign: "center",
            }}
          >
            {props.label}
          </AbsoluteFill>
        )}
      </div>
    </AbsoluteFill>
  );
};
