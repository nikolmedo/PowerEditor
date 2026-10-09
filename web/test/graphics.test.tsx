import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { translate } from "../src/i18n";
import { GraphicsPanel } from "../src/review/GraphicsPanel";
import { Timeline } from "../src/review/Timeline";
import { buildTimeline } from "../src/review/timelineModel";
import { useProjectStore } from "../src/store/project";
import { PROJECT } from "./fixtures/reviewProject";

const t = (key: Parameters<typeof translate>[1], vars?: Record<string, string | number>) =>
  translate("es", key, vars);

// The fixture timeline is 105 frames; a 1050 px lane makes 10 px one frame.
const LANE_PX = 1050;

function renderTimeline(project = PROJECT) {
  const handlers = {
    onSelectOverlay: vi.fn(),
    onOverlaySpan: vi.fn(),
    onNudgeOverlay: vi.fn(),
    onDeleteOverlay: vi.fn(),
  };
  render(
    <Timeline
      model={buildTimeline(project, 0.8)}
      frame={0}
      selectedId={null}
      selectedOverlayId={null}
      onSeek={vi.fn()}
      onSelect={vi.fn()}
      onSwapNext={vi.fn()}
      onOpenTakes={vi.fn()}
      selectedTrackId={null}
      onSelectVoice={vi.fn()}
      onSelectMusic={vi.fn()}
      onToggleMute={vi.fn()}
      {...handlers}
    />,
  );
  const block = screen.getByRole("button", { name: /^Título,/ });
  return { handlers, block };
}

describe("Graphics track", () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: LANE_PX,
    } as DOMRect);
  });
  afterEach(() => vi.restoreAllMocks());

  it("moves an overlay by dragging it and commits once, on release", () => {
    const { handlers, block } = renderTimeline();

    fireEvent.pointerDown(block, { button: 0, clientX: 0 });
    fireEvent.pointerMove(block, { clientX: 60 });
    fireEvent.pointerMove(block, { clientX: 100 });
    expect(handlers.onOverlaySpan).not.toHaveBeenCalled();
    expect(block.style.left).toBe(`${(10 / 105) * 100}%`);
    fireEvent.pointerUp(block, { clientX: 100 });

    expect(handlers.onSelectOverlay).toHaveBeenCalledWith("o1");
    expect(handlers.onOverlaySpan).toHaveBeenCalledTimes(1);
    expect(handlers.onOverlaySpan).toHaveBeenCalledWith("o1", { startFrame: 10, endFrame: 40 });
  });

  it("drops a drag the browser cancels, without committing it", () => {
    const { handlers, block } = renderTimeline();
    const before = block.style.left;

    fireEvent.pointerDown(block, { button: 0, clientX: 0 });
    fireEvent.pointerMove(block, { clientX: 100 });
    fireEvent.pointerCancel(block, { clientX: 100 });

    expect(handlers.onOverlaySpan).not.toHaveBeenCalled();
    expect(block.style.left).toBe(before);
    expect(block.dataset.dragging).toBeUndefined();
  });

  it("ends a drag cleanly when the pointer capture is lost", () => {
    const { handlers, block } = renderTimeline();
    const before = block.style.left;

    fireEvent.pointerDown(block, { button: 0, clientX: 0 });
    fireEvent.pointerMove(block, { clientX: 100 });
    fireEvent.lostPointerCapture(block);
    fireEvent.pointerMove(block, { clientX: 300 });
    fireEvent.pointerUp(block, { clientX: 300 });

    expect(handlers.onOverlaySpan).not.toHaveBeenCalled();
    expect(block.style.left).toBe(before);
  });

  it("resizes an overlay by dragging its end edge", () => {
    const { handlers, block } = renderTimeline();
    const edge = block.querySelector('[data-edge="end"]') as HTMLElement;

    fireEvent.pointerDown(edge, { button: 0, clientX: 300 });
    fireEvent.pointerMove(edge, { clientX: 500 });
    fireEvent.pointerUp(edge, { clientX: 500 });

    expect(handlers.onOverlaySpan).toHaveBeenCalledWith("o1", { startFrame: 0, endFrame: 50 });
  });

  it("nudges by a frame, a second with Shift, and deletes with the keyboard", () => {
    const { handlers, block } = renderTimeline();

    fireEvent.keyDown(block, { key: "ArrowRight" });
    fireEvent.keyDown(block, { key: "ArrowLeft", shiftKey: true });
    fireEvent.keyDown(block, { key: "Delete" });
    fireEvent.keyDown(block, { key: "Enter" });

    expect(handlers.onNudgeOverlay.mock.calls).toEqual([
      ["o1", 1],
      ["o1", -30],
    ]);
    expect(handlers.onDeleteOverlay).toHaveBeenCalledWith("o1");
    expect(handlers.onSelectOverlay).toHaveBeenCalledWith("o1");
  });
});

describe("Graphics track with overlapping overlays", () => {
  // The fixture timeline is 105 frames: title, lower third and call to action follow each other
  // while the progress bar (60 s) and the logo span them.
  const overlays = [
    ["title", 0, 35],
    ["progress_bar", 0, 1800],
    ["lower_third", 35, 70],
    ["logo", 0, 105],
    ["cta", 70, 105],
  ] as const;
  const project = {
    ...PROJECT,
    overlays: overlays.map(([templateId, startFrame, endFrame]) => ({
      id: templateId,
      templateId,
      startFrame,
      endFrame,
      props: {},
      autoGenerated: false,
    })),
  };
  const labels = overlays.map(([templateId]) => t(`overlay.${templateId}`));
  // Document order is the order Tab walks the blocks.
  const blocks = () =>
    screen
      .getAllByRole("button", { name: new RegExp(`^(${labels.join("|")}),`) })
      .map((button) => button.getAttribute("aria-label")?.split(",")[0]);

  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: LANE_PX,
    } as DOMRect);
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows every overlay, in lane order then by start", () => {
    renderTimeline(project);
    expect(blocks()).toEqual([
      t("overlay.title"),
      t("overlay.lower_third"),
      t("overlay.cta"),
      t("overlay.progress_bar"),
      t("overlay.logo"),
    ]);
  });

  it("puts overlapping overlays on separate lanes", () => {
    renderTimeline(project);
    const lane = (name: string) =>
      screen
        .getByRole("button", { name: new RegExp(`^${name},`) })
        .style.getPropertyValue("--lane");
    expect([lane(t("overlay.title")), lane(t("overlay.cta"))]).toEqual(["0", "0"]);
    expect(lane(t("overlay.progress_bar"))).toBe("1");
    expect(lane(t("overlay.logo"))).toBe("2");
  });

  it("resizes an overlay that runs past the end from the edge drawn at the end", () => {
    const { handlers } = renderTimeline(project);
    const progress = screen.getByRole("button", {
      name: new RegExp(`^${t("overlay.progress_bar")},`),
    });
    const edge = progress.querySelector('[data-edge="end"]') as HTMLElement;

    fireEvent.pointerDown(progress, { button: 0, clientX: 200 });
    fireEvent.pointerUp(progress, { clientX: 200 });
    expect(handlers.onOverlaySpan).not.toHaveBeenCalled();

    fireEvent.pointerDown(edge, { button: 0, clientX: 1050 });
    fireEvent.pointerUp(edge, { clientX: 1000 });
    expect(handlers.onOverlaySpan).toHaveBeenCalledWith("progress_bar", {
      startFrame: 0,
      endFrame: 100,
    });
  });

  it("stops an overlay that runs past the end at the end of the timeline", () => {
    renderTimeline(project);
    const progress = screen.getByRole("button", {
      name: new RegExp(`^${t("overlay.progress_bar")},`),
    });
    expect(progress.style.left).toBe("0%");
    expect(progress.style.width).toBe("100%");
    expect(progress.dataset.continues).toBe("true");
    const logo = screen.getByRole("button", { name: new RegExp(`^${t("overlay.logo")},`) });
    expect(logo.style.width).toBe("100%");
    expect(logo.dataset.continues).toBeUndefined();
  });
});

describe("GraphicsPanel", () => {
  beforeEach(() => useProjectStore.getState().load("p1", PROJECT, "etag"));

  function Harness({ frame }: { frame: number }) {
    const project = useProjectStore((state) => state.project) ?? PROJECT;
    const [selected, setSelected] = useState<string | null>(null);
    return (
      <GraphicsPanel
        projectId="p1"
        project={project}
        frame={frame}
        selectedId={selected}
        onSelect={setSelected}
      />
    );
  }

  it("adds a call to action at the playhead with localized starter text, then edits it", async () => {
    render(<Harness frame={12} />);

    await userEvent.click(
      screen.getByRole("button", {
        name: t("graphics.addTemplate", { template: t("overlay.cta") }),
      }),
    );
    const added = useProjectStore.getState().project?.overlays.at(-1);
    expect(added).toMatchObject({
      templateId: "cta",
      startFrame: 12,
      endFrame: 102,
      props: { text: "¡Sígueme para más!", position: "bottom", color: "#ffcc00" },
      autoGenerated: false,
    });

    const text = screen.getByLabelText(t("graphics.field.text"));
    await userEvent.clear(text);
    await userEvent.type(text, "Comenta");
    expect(useProjectStore.getState().project?.overlays.at(-1)?.props.text).toBe("Comenta");

    await userEvent.click(screen.getByRole("button", { name: t("graphics.remove") }));
    expect(useProjectStore.getState().project?.overlays).toEqual(PROJECT.overlays);
  });

  it("offers each look of a template and adds the one picked, then switches its look", async () => {
    render(<Harness frame={0} />);
    const name = `${t("overlay.lower_third")} · ${t("graphics.option.kicker_name")}`;

    await userEvent.click(
      screen.getByRole("button", { name: t("graphics.addTemplate", { template: name }) }),
    );
    const added = () => useProjectStore.getState().project?.overlays.at(-1);
    expect(added()).toMatchObject({
      templateId: "lower_third",
      props: { variant: "kicker_name", name: "Tu nombre" },
    });

    await userEvent.selectOptions(
      screen.getByLabelText(t("graphics.field.variant")),
      t("graphics.option.mask_reveal"),
    );
    expect(added()?.props.variant).toBe("mask_reveal");
  });

  it("types the counter's number in a box instead of dragging a slider", async () => {
    render(<Harness frame={0} />);

    await userEvent.click(
      screen.getByRole("button", {
        name: t("graphics.addTemplate", { template: t("overlay.count_up") }),
      }),
    );
    const value = screen.getByLabelText(t("graphics.field.value"));
    await userEvent.clear(value);
    await userEvent.type(value, "2500");

    expect(useProjectStore.getState().project?.overlays.at(-1)?.props.value).toBe(2500);
  });

  it("marks automatic graphics in the list", () => {
    act(() => useProjectStore.getState().load("p1", PROJECT, "etag"));
    render(<Harness frame={0} />);
    expect(screen.getByTitle(t("graphics.autoHint")).textContent).toBe(t("graphics.auto"));
  });
});
