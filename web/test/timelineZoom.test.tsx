import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act, createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { translate } from "../src/i18n";
import { Timeline, type TimelineHandle } from "../src/review/Timeline";
import { buildTimeline } from "../src/review/timelineModel";
import { PROJECT } from "./fixtures/reviewProject";

const t = (key: Parameters<typeof translate>[1]) => translate("es", key);

// jsdom measures nothing, so the lanes have no width and the zoom gets its full range.
function renderTimeline() {
  const ref = createRef<TimelineHandle>();
  const { container } = render(
    <Timeline
      ref={ref}
      model={buildTimeline(PROJECT, 0.8)}
      frame={0}
      selectedId={null}
      selectedOverlayId={null}
      onSeek={vi.fn()}
      onSelect={vi.fn()}
      onSwapNext={vi.fn()}
      onOpenTakes={vi.fn()}
      onSelectOverlay={vi.fn()}
      onOverlaySpan={vi.fn()}
      onNudgeOverlay={vi.fn()}
      onDeleteOverlay={vi.fn()}
    />,
  );
  const content = container.querySelector<HTMLElement>(".timeline-content");
  const zoom = () => Number(content?.dataset.zoom);
  return { ref, zoom };
}

describe("timeline zoom", () => {
  it("zooms in and out with the buttons and fits the whole video again", async () => {
    const user = userEvent.setup();
    const { zoom } = renderTimeline();
    const zoomIn = screen.getByRole("button", { name: t("review.zoomIn") });
    const zoomOut = screen.getByRole("button", { name: t("review.zoomOut") });
    const fit = screen.getByRole("button", { name: t("review.zoomFit") });
    expect(zoom()).toBe(1);
    expect([zoomOut, fit].map((button) => button.hasAttribute("disabled"))).toEqual([true, true]);

    await user.click(zoomIn);
    await user.click(zoomIn);
    expect(zoom()).toBe(2.25);
    expect(screen.getByText("225%")).toBeTruthy();

    await user.click(zoomOut);
    expect(zoom()).toBe(1.5);

    await user.click(fit);
    expect(zoom()).toBe(1);
    expect(fit.hasAttribute("disabled")).toBe(true);
  });

  it("zooms through the handle the review step's keys use", () => {
    const { ref, zoom } = renderTimeline();
    act(() => ref.current?.zoom(1));
    expect(zoom()).toBe(1.5);
    act(() => ref.current?.fit());
    expect(zoom()).toBe(1);
  });
});
