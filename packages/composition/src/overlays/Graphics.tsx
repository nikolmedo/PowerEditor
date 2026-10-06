import { useState, type CSSProperties } from "react";
import { AbsoluteFill, Img, useCurrentFrame, useVideoConfig } from "remotion";

import { mediaUrl } from "../clips/media";
import { area, SHADOW, type GraphicContext } from "./base";
import { readableTextColor } from "./color";
import { CtaClose, CtaLockup, HeadlineSlam, LOWER_THIRD_LOOKS } from "./Looks";
import type {
  CtaProps,
  ImageProps,
  LogoProps,
  LowerThirdProps,
  ProgressBarProps,
  TitleProps,
} from "./templates";

export type { GraphicContext } from "./base";

export const Title: React.FC<{ props: TitleProps } & GraphicContext> = (context) => {
  const { props, presence, insets, unit } = context;
  if (!props.text) return null;
  if (props.variant === "headline_slam") return <HeadlineSlam {...context} />;
  return (
    <AbsoluteFill style={area(insets, props.position)}>
      <div
        style={{
          opacity: presence,
          transform: `translateY(${(1 - presence) * 40 * unit}px)`,
          textAlign: "center",
          color: "white",
          textShadow: SHADOW,
        }}
      >
        <div style={{ fontSize: 96 * unit, fontWeight: 800, lineHeight: 1.05 }}>{props.text}</div>
        <div
          style={{
            height: 8 * unit,
            width: 140 * unit,
            margin: `${24 * unit}px auto`,
            background: props.color,
            transform: `scaleX(${presence})`,
          }}
        />
        {props.subtitle && (
          <div style={{ fontSize: 44 * unit, fontWeight: 400, opacity: 0.9 }}>{props.subtitle}</div>
        )}
      </div>
    </AbsoluteFill>
  );
};

export const LowerThird: React.FC<{ props: LowerThirdProps } & GraphicContext> = (context) => {
  const { props, presence, insets, unit } = context;
  if (!props.name && !props.role) return null;
  const fromLeft = props.side === "left";
  const Look = LOWER_THIRD_LOOKS[props.variant];
  return (
    <AbsoluteFill
      style={{
        ...area(insets, "bottom"),
        alignItems: fromLeft ? "flex-start" : "flex-end",
      }}
    >
      {Look ? (
        <Look {...context} fromLeft={fromLeft} />
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: fromLeft ? "row" : "row-reverse",
            opacity: presence,
            transform: `translateX(${(1 - presence) * (fromLeft ? -60 : 60) * unit}px)`,
          }}
        >
          <div
            style={{
              width: 10 * unit,
              background: props.color,
              transform: `scaleY(${presence})`,
            }}
          />
          <div
            style={{
              padding: `${18 * unit}px ${28 * unit}px`,
              background: "rgba(10,10,10,0.72)",
              color: "white",
              textAlign: fromLeft ? "left" : "right",
            }}
          >
            {props.name && (
              <div style={{ fontSize: 52 * unit, fontWeight: 700, lineHeight: 1.15 }}>
                {props.name}
              </div>
            )}
            {props.role && (
              <div style={{ fontSize: 34 * unit, fontWeight: 400, opacity: 0.85 }}>
                {props.role}
              </div>
            )}
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
};

export const Cta: React.FC<{ props: CtaProps } & GraphicContext> = (context) => {
  const { props, presence, insets, unit } = context;
  if (!props.text) return null;
  if (props.variant === "lockup") return <CtaLockup {...context} />;
  if (props.variant === "close") return <CtaClose {...context} />;
  return (
    <AbsoluteFill style={area(insets, props.position)}>
      <div
        style={{
          opacity: presence,
          transform: `scale(${0.85 + 0.15 * presence})`,
          padding: `${22 * unit}px ${48 * unit}px`,
          borderRadius: 999,
          background: props.color,
          color: readableTextColor(props.color),
          fontSize: 56 * unit,
          fontWeight: 800,
          boxShadow: SHADOW,
          textAlign: "center",
        }}
      >
        {props.text}
      </div>
    </AbsoluteFill>
  );
};

/** An image from the project's media folder; a file that fails to load shows nothing, so a
 * missing asset never breaks the preview (renders check the files before they start). */
function MediaImage({
  src,
  mediaBaseUrl,
  style,
}: {
  src: string;
  mediaBaseUrl: string;
  style: CSSProperties;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return null;
  return <Img src={mediaUrl(mediaBaseUrl, src)} style={style} onError={() => setFailed(true)} />;
}

export const Logo: React.FC<{ props: LogoProps; mediaBaseUrl: string } & GraphicContext> = ({
  props,
  mediaBaseUrl,
  presence,
  insets,
}) => {
  const { width } = useVideoConfig();
  const [vertical, horizontal] = props.corner.split("_") as ["top" | "bottom", "left" | "right"];
  return (
    <AbsoluteFill>
      <MediaImage
        src={props.src}
        mediaBaseUrl={mediaBaseUrl}
        style={{
          position: "absolute",
          [vertical]: insets[vertical],
          [horizontal]: insets[horizontal],
          width: props.size * width,
          opacity: props.opacity * presence,
        }}
      />
    </AbsoluteFill>
  );
};

export const ImageGraphic: React.FC<
  { props: ImageProps; mediaBaseUrl: string } & GraphicContext
> = ({ props, mediaBaseUrl, presence, insets }) => {
  const { width } = useVideoConfig();
  return (
    <AbsoluteFill style={area(insets, props.position)}>
      <MediaImage
        src={props.src}
        mediaBaseUrl={mediaBaseUrl}
        style={{
          width: props.size * (width - insets.left - insets.right),
          objectFit: "contain",
          opacity: presence,
          transform: `scale(${0.96 + 0.04 * presence})`,
        }}
      />
    </AbsoluteFill>
  );
};

/** A bar across the frame edge that fills with the progress of the whole video. */
export const ProgressBar: React.FC<
  { props: ProgressBarProps; from: number; totalFrames: number } & GraphicContext
> = ({ props, from, totalFrames, presence, unit }) => {
  const frame = useCurrentFrame();
  const progress = Math.min(1, (from + frame + 1) / Math.max(1, totalFrames));
  const height = Math.max(1, Math.round(props.thickness * unit));
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          [props.position]: 0,
          height,
          background: "rgba(255,255,255,0.25)",
          opacity: presence,
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${progress * 100}%`,
            background: props.color,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
