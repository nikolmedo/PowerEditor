import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { translate } from "../src/i18n";
import { SubtitlesPanel } from "../src/review/SubtitlesPanel";
import { useProjectStore } from "../src/store/project";
import { PROJECT } from "./fixtures/reviewProject";

const t = (key: Parameters<typeof translate>[1]) => translate("es", key);

function Harness() {
  const project = useProjectStore((state) => state.project) ?? PROJECT;
  return <SubtitlesPanel project={project} />;
}

describe("SubtitlesPanel presets", () => {
  beforeEach(() => useProjectStore.getState().load("p1", PROJECT, "etag"));

  it("previews every preset and applies the one picked", async () => {
    render(<Harness />);
    const group = screen.getByRole("radiogroup", { name: t("edit.subtitlePreset") });
    const tiles = screen.getAllByRole("radio");
    expect(group).toBeTruthy();
    expect(tiles).toHaveLength(8);

    await userEvent.click(screen.getByRole("radio", { name: t("subtitlePreset.kinetic_slam") }));

    expect(useProjectStore.getState().project?.subtitles.style.preset).toBe("kinetic_slam");
    expect(
      screen
        .getByRole("radio", { name: t("subtitlePreset.kinetic_slam") })
        .getAttribute("aria-checked"),
    ).toBe("true");
  });
});
