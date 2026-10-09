import type { Project } from "@powereditor/composition";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { setTrackMuted } from "../src/edit/audio";
import { setClipVolume } from "../src/edit/operations";
import { translate } from "../src/i18n";
import { Timeline } from "../src/review/Timeline";
import { buildTimeline } from "../src/review/timelineModel";
import { PROJECT } from "./fixtures/reviewProject";

const t = (key: Parameters<typeof translate>[1], vars?: Record<string, string | number>) =>
  translate("es", key, vars);

function renderTimeline(
  project: Project = PROJECT,
  selectedTrackId: "voice" | "music" | null = null,
) {
  const handlers = {
    onSeek: vi.fn(),
    onSelect: vi.fn(),
    onSelectVoice: vi.fn(),
    onSelectMusic: vi.fn(),
    onToggleMute: vi.fn(),
  };
  const { container } = render(
    <Timeline
      model={buildTimeline(project, 0.8)}
      frame={0}
      selectedId={null}
      selectedOverlayId={null}
      selectedTrackId={selectedTrackId}
      onSwapNext={vi.fn()}
      onOpenTakes={vi.fn()}
      onSelectOverlay={vi.fn()}
      onOverlaySpan={vi.fn()}
      onNudgeOverlay={vi.fn()}
      onDeleteOverlay={vi.fn()}
      {...handlers}
    />,
  );
  const voiceTrack = container.querySelector<HTMLElement>('.track[data-track="voice"]');
  const musicTrack = container.querySelector<HTMLElement>('.track[data-track="music"]');
  return { handlers, voiceTrack, musicTrack };
}

const voiceSegments = () => screen.getAllByRole("button", { name: /^Voz del clip en/ });

describe("Voice lane", () => {
  it("draws one voice segment under each kept clip, in the same place", () => {
    renderTimeline();
    const clips = screen.getAllByRole("button", { name: /^Clip en/ });
    const segments = voiceSegments();
    expect(segments).toHaveLength(3);
    expect(segments.map((segment) => [segment.style.left, segment.style.width])).toEqual(
      clips.map((clip) => [clip.style.left, clip.style.width]),
    );
  });

  it("selects the clip and the voice track when a segment is clicked, without seeking", async () => {
    const user = userEvent.setup();
    const { handlers } = renderTimeline();
    await user.click(voiceSegments()[1] as HTMLElement);
    expect(handlers.onSelectVoice).toHaveBeenCalledWith(expect.objectContaining({ clipId: "k2" }));
    expect(handlers.onSelect).not.toHaveBeenCalled();
    expect(handlers.onSeek).not.toHaveBeenCalled();
  });

  it("selects the music track from its bar", async () => {
    const user = userEvent.setup();
    const { handlers } = renderTimeline();
    await user.click(screen.getByRole("button", { name: /song\.mp3/ }));
    expect(handlers.onSelectMusic).toHaveBeenCalledWith("m1");
    expect(handlers.onSeek).not.toHaveBeenCalled();
  });

  it("mutes and unmutes the tracks from the lane labels", async () => {
    const user = userEvent.setup();
    const muted = setTrackMuted(PROJECT, "m1", true);
    const { handlers } = renderTimeline(muted);

    const voice = screen.getByRole("button", { name: t("track.muteVoice") });
    expect(voice.getAttribute("aria-pressed")).toBe("false");
    await user.click(voice);
    expect(handlers.onToggleMute).toHaveBeenCalledWith("voice", true);

    const music = screen.getByRole("button", { name: t("track.unmuteMusic") });
    expect(music.getAttribute("aria-pressed")).toBe("true");
    await user.click(music);
    expect(handlers.onToggleMute).toHaveBeenCalledWith("m1", false);
  });

  it("marks a muted voice, a silent segment and the selected track", () => {
    const project = setClipVolume(setTrackMuted(PROJECT, "voice", true), "k2", 0);
    const { voiceTrack, musicTrack } = renderTimeline(project, "voice");
    expect(voiceTrack?.hasAttribute("data-muted")).toBe(true);
    expect(voiceTrack?.hasAttribute("data-selected")).toBe(true);
    expect(musicTrack?.hasAttribute("data-selected")).toBe(false);
    expect(voiceSegments().map((segment) => segment.hasAttribute("data-silent"))).toEqual([
      false,
      true,
      false,
    ]);
  });
});
