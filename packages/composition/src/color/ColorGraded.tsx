import { useId, type ReactNode } from "react";
import { AbsoluteFill } from "remotion";

import type { Matrix } from "./matrix";

/** Its children seen through one color matrix; no filter at all when `matrix` is null. */
export const ColorGraded: React.FC<{ matrix: Matrix | null; children: ReactNode }> = ({
  matrix,
  children,
}) => {
  const id = `grade-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  if (!matrix) return <>{children}</>;
  return (
    <AbsoluteFill style={{ filter: `url(#${id})` }}>
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
        {/* sRGB: the matrix works on the encoded values the color stats were measured on. */}
        <filter id={id} colorInterpolationFilters="sRGB">
          <feColorMatrix type="matrix" values={matrix.join(" ")} />
        </filter>
      </svg>
      {children}
    </AbsoluteFill>
  );
};
