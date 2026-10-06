import { AbsoluteFill } from "remotion";

import { area, SHADOW, type GraphicContext } from "./base";
import { readableTextColor } from "./color";
import type { CtaProps, LowerThirdProps, TitleProps } from "./templates";
import { revealProgress, slamOpacity, slamScale, VARIANT_TIMING } from "./variantMotion";

/*
 * The variant looks of `title`, `lower_third` and `cta` (the default looks live in
 * `Graphics.tsx`). Designs follow the HyperFrames registry blocks; the code is our own.
 * Entrances come from `variantMotion.ts`, exits from the shared `exit`.
 */

/** `headline_slam`: the line lands from 1.8x with one overshoot, then its accent bar wipes. */
export const HeadlineSlam: React.FC<{ props: TitleProps } & GraphicContext> = ({
  props,
  exit,
  frame,
  fps,
  insets,
  unit,
}) => {
  const bar = revealProgress(frame, fps, 0.15, 0.3);
  const subtitle = revealProgress(frame, fps, 0.3, 0.3);
  return (
    <AbsoluteFill style={area(insets, props.position)}>
      <div style={{ opacity: exit, textAlign: "center", color: "white", textShadow: SHADOW }}>
        <div
          style={{
            fontSize: 124 * unit,
            fontWeight: 800,
            lineHeight: 0.95,
            letterSpacing: "-0.02em",
            textTransform: "uppercase",
            opacity: slamOpacity(frame),
            transform: `scale(${slamScale(frame, fps)})`,
          }}
        >
          {props.text}
        </div>
        <div
          style={{
            height: 14 * unit,
            width: "70%",
            margin: `${20 * unit}px auto`,
            background: props.color,
            transform: `scaleX(${bar})`,
          }}
        />
        {props.subtitle && (
          <div
            style={{
              fontSize: 44 * unit,
              fontWeight: 700,
              opacity: subtitle,
              transform: `translateY(${(1 - subtitle) * 16 * unit}px)`,
            }}
          >
            {props.subtitle}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};

export type LowerThirdLook = React.FC<
  { props: LowerThirdProps; fromLeft: boolean } & GraphicContext
>;

/** `kicker_name`: the role as a small spaced kicker in the accent rises, the name follows. */
const KickerName: LowerThirdLook = ({ props, fromLeft, exit, frame, fps, unit }) => {
  const { kickerSeconds, nameDelay, nameSeconds } = VARIANT_TIMING.kickerName;
  const kicker = revealProgress(frame, fps, 0, kickerSeconds);
  const name = revealProgress(frame, fps, nameDelay, nameSeconds);
  return (
    <div style={{ opacity: exit, textAlign: fromLeft ? "left" : "right", textShadow: SHADOW }}>
      {props.role && (
        <div
          style={{
            fontSize: 30 * unit,
            fontWeight: 800,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: props.color,
            opacity: kicker,
            transform: `translateY(${(1 - kicker) * 18 * unit}px)`,
          }}
        >
          {props.role}
        </div>
      )}
      {props.name && (
        <div
          style={{
            fontSize: 68 * unit,
            fontWeight: 800,
            lineHeight: 1.05,
            color: "white",
            opacity: name,
            transform: `translateY(${(1 - name) * 24 * unit}px)`,
          }}
        >
          {props.name}
        </div>
      )}
    </div>
  );
};

/** `mask_reveal`: an accent block wipes across, then the name and the role are unmasked. */
const MaskReveal: LowerThirdLook = ({ props, fromLeft, exit, frame, fps, unit }) => {
  const { barSeconds, textDelay, textSeconds } = VARIANT_TIMING.maskReveal;
  const bar = revealProgress(frame, fps, 0, barSeconds);
  const name = revealProgress(frame, fps, textDelay, textSeconds);
  const role = revealProgress(frame, fps, textDelay + 0.1, textSeconds);
  // Clip from the far side, so the reveal travels away from the frame edge.
  const mask = (shown: number) =>
    fromLeft ? `inset(0 ${(1 - shown) * 100}% 0 0)` : `inset(0 0 0 ${(1 - shown) * 100}%)`;
  return (
    <div
      style={{
        opacity: exit,
        display: "flex",
        flexDirection: "column",
        alignItems: fromLeft ? "flex-start" : "flex-end",
      }}
    >
      <div
        style={{
          clipPath: mask(bar),
          background: props.color,
          color: readableTextColor(props.color),
          padding: `${12 * unit}px ${26 * unit}px`,
        }}
      >
        <div style={{ fontSize: 56 * unit, fontWeight: 800, clipPath: mask(name) }}>
          {props.name || props.role}
        </div>
      </div>
      {props.name && props.role && (
        <div
          style={{
            clipPath: mask(role),
            background: "rgba(10,10,10,0.78)",
            color: "white",
            padding: `${10 * unit}px ${26 * unit}px`,
            fontSize: 32 * unit,
          }}
        >
          {props.role}
        </div>
      )}
    </div>
  );
};

/** `soft_pill`: a light rounded card with an accent dot that settles in. */
const SoftPill: LowerThirdLook = ({ props, fromLeft, presence, unit }) => (
  <div
    style={{
      display: "flex",
      flexDirection: fromLeft ? "row" : "row-reverse",
      alignItems: "center",
      gap: 20 * unit,
      padding: `${16 * unit}px ${34 * unit}px`,
      borderRadius: 48 * unit,
      background: "rgba(250,250,250,0.94)",
      color: "#111111",
      boxShadow: "0 6px 24px rgba(0,0,0,0.35)",
      opacity: presence,
      transform: `scale(${0.92 + 0.08 * presence})`,
      transformOrigin: fromLeft ? "left center" : "right center",
    }}
  >
    <div
      style={{
        width: 22 * unit,
        height: 22 * unit,
        borderRadius: "50%",
        background: props.color,
        flex: "none",
      }}
    />
    <div style={{ textAlign: fromLeft ? "left" : "right" }}>
      {props.name && <div style={{ fontSize: 46 * unit, fontWeight: 800 }}>{props.name}</div>}
      {props.role && <div style={{ fontSize: 30 * unit, opacity: 0.7 }}>{props.role}</div>}
    </div>
  </div>
);

/** The lower-third looks other than the default `clean_bar`. */
export const LOWER_THIRD_LOOKS: Partial<Record<LowerThirdProps["variant"], LowerThirdLook>> = {
  kicker_name: KickerName,
  mask_reveal: MaskReveal,
  soft_pill: SoftPill,
};

/** `lockup`: the text locked to an accent tile whose arrow slides in last. */
export const CtaLockup: React.FC<{ props: CtaProps } & GraphicContext> = ({
  props,
  presence,
  frame,
  fps,
  insets,
  unit,
}) => {
  const { arrowDelay, arrowSeconds } = VARIANT_TIMING.lockup;
  const arrow = revealProgress(frame, fps, arrowDelay, arrowSeconds);
  const tile = 96 * unit;
  const ink = readableTextColor(props.color);
  return (
    <AbsoluteFill style={area(insets, props.position)}>
      <div
        style={{
          display: "flex",
          alignItems: "stretch",
          opacity: presence,
          transform: `translateY(${(1 - presence) * 30 * unit}px)`,
          boxShadow: SHADOW,
        }}
      >
        <div
          style={{
            padding: `0 ${36 * unit}px`,
            display: "flex",
            alignItems: "center",
            background: "rgba(10,10,10,0.82)",
            color: "white",
            fontSize: 52 * unit,
            fontWeight: 800,
          }}
        >
          {props.text}
        </div>
        <div
          style={{
            width: tile,
            minHeight: tile,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: props.color,
            overflow: "hidden",
          }}
        >
          {/* A chevron drawn with two borders: no glyph the bundled font might lack. */}
          <div
            style={{
              width: 26 * unit,
              height: 26 * unit,
              borderTop: `${8 * unit}px solid ${ink}`,
              borderRight: `${8 * unit}px solid ${ink}`,
              transform: `translateX(${(arrow - 1) * tile}px) rotate(45deg)`,
            }}
          />
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** `close`: an end card. The frame dims and one centered line rises over an accent rule. */
export const CtaClose: React.FC<{ props: CtaProps } & GraphicContext> = ({
  props,
  exit,
  frame,
  fps,
  insets,
  unit,
}) => {
  const { scrimOpacity, riseSeconds } = VARIANT_TIMING.close;
  const rise = revealProgress(frame, fps, 0, riseSeconds);
  const rule = revealProgress(frame, fps, riseSeconds / 2, riseSeconds);
  return (
    <AbsoluteFill style={{ opacity: exit }}>
      <AbsoluteFill style={{ background: "black", opacity: scrimOpacity * rise }} />
      <AbsoluteFill style={area(insets, "center")}>
        <div
          style={{
            opacity: rise,
            transform: `translateY(${(1 - rise) * 50 * unit}px)`,
            color: "white",
            fontSize: 84 * unit,
            fontWeight: 800,
            lineHeight: 1.1,
            textAlign: "center",
          }}
        >
          {props.text}
        </div>
        <div
          style={{
            height: 10 * unit,
            width: 180 * unit,
            marginTop: 28 * unit,
            background: props.color,
            transform: `scaleX(${rule})`,
          }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
