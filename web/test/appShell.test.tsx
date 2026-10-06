import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { translate, type MessageKey } from "../src/i18n";
import { AppShell } from "../src/shell/AppShell";
import { useAppStore } from "../src/store/app";

vi.mock("../src/api/endpoints", () => ({
  api: {
    updateSettings: vi.fn(),
    updates: vi.fn(() => Promise.resolve({ updateAvailable: false, enabled: true })),
  },
}));

const t = (key: MessageKey) => translate("es", key);

beforeEach(() => {
  useAppStore.setState({ language: "es" });
});

describe("AppShell", () => {
  it("shows a footer with the copyright linking to the author's site in a new tab", () => {
    render(
      <AppShell step={null} projectId={null}>
        <p>content</p>
      </AppShell>,
    );

    const footer = screen.getByRole("contentinfo");
    const link = within(footer).getByRole("link", { name: t("about.copyright") });
    expect(link.getAttribute("href")).toBe("https://nolmedo.dev");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noreferrer");
  });
});
