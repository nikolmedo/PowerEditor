import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/api/endpoints";
import type { UpdateStatus } from "../src/api/types";
import { translate, type MessageKey, type Vars } from "../src/i18n";
import { About } from "../src/settings/About";
import { useAppStore } from "../src/store/app";
import type { DesktopUpdates, DesktopUpdateState } from "../src/updates/desktopBridge";
import { UpdateBanner } from "../src/updates/UpdateBanner";

vi.mock("../src/api/endpoints", () => ({ api: { updates: vi.fn(), health: vi.fn() } }));

const t = (key: MessageKey, vars?: Vars) => translate("en", key, vars);
const RELEASE_URL = "https://github.com/nikolmedo/PowerEditor/releases/tag/v0.2.0";

function status(overrides: Partial<UpdateStatus> = {}): UpdateStatus {
  return {
    current: "0.1.0",
    latest: "0.2.0",
    updateAvailable: true,
    releaseUrl: RELEASE_URL,
    installerUrl: null,
    sha256Url: null,
    notes: null,
    checkedAt: "2026-10-06T12:00:00Z",
    enabled: true,
    error: null,
    ...overrides,
  };
}

function fakeDesktop(
  final: DesktopUpdateState,
): DesktopUpdates & { emit: (s: DesktopUpdateState) => void; subscribed: () => boolean } {
  let listener: ((state: DesktopUpdateState) => void) | null = null;
  return {
    download: vi.fn(() => Promise.resolve(final)),
    installAndQuit: vi.fn(() => Promise.resolve(true)),
    onState: (next) => {
      listener = next;
      return () => (listener = null);
    },
    emit: (state) => listener?.(state),
    subscribed: () => listener !== null,
  };
}

beforeEach(() => {
  useAppStore.setState({ language: "en" });
  localStorage.clear();
  vi.mocked(api.updates).mockReset();
  vi.mocked(api.health).mockResolvedValue({ status: "ok", version: "0.1.0" });
});

afterEach(() => {
  delete window.powereditor;
  vi.restoreAllMocks();
});

describe("UpdateBanner", () => {
  it("announces a newer version with a link to what's new", async () => {
    vi.mocked(api.updates).mockResolvedValue(status());
    render(<UpdateBanner />);

    const banner = await screen.findByRole("region", { name: t("updates.label") });
    expect(within(banner).getByText(t("updates.available", { version: "0.2.0" }))).toBeTruthy();
    const link = within(banner).getByRole("link", { name: t("updates.whatsNew") });
    expect(link.getAttribute("href")).toBe(RELEASE_URL);
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it.each([
    ["no newer version", status({ updateAvailable: false, latest: "0.1.0" })],
    [
      "a failed check",
      status({ updateAvailable: false, latest: null, error: "update_check_failed" }),
    ],
    ["checks turned off", status({ updateAvailable: false, latest: null, enabled: false })],
  ])("stays hidden for %s", async (_name, answer) => {
    vi.mocked(api.updates).mockResolvedValue(answer);
    render(<UpdateBanner />);

    await vi.waitFor(() => expect(api.updates).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: t("updates.label") })).toBeNull();
  });

  it("stays dismissed for that version only", async () => {
    vi.mocked(api.updates).mockResolvedValue(status());
    const { unmount } = render(<UpdateBanner />);
    await userEvent.click(await screen.findByRole("button", { name: t("updates.dismiss") }));
    expect(screen.queryByRole("region", { name: t("updates.label") })).toBeNull();
    unmount();

    render(<UpdateBanner />);
    await vi.waitFor(() => expect(api.updates).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("region", { name: t("updates.label") })).toBeNull();

    vi.mocked(api.updates).mockResolvedValue(status({ latest: "0.3.0" }));
    render(<UpdateBanner />);
    expect(await screen.findByText(t("updates.available", { version: "0.3.0" }))).toBeTruthy();
  });

  it("opens the release page in the browser outside the desktop app", async () => {
    vi.mocked(api.updates).mockResolvedValue(status());
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<UpdateBanner />);

    await userEvent.click(await screen.findByRole("button", { name: t("updates.download") }));

    expect(open).toHaveBeenCalledWith(RELEASE_URL, "_blank", "noreferrer");
  });

  it("downloads through the desktop app, then installs", async () => {
    vi.mocked(api.updates).mockResolvedValue(status());
    const desktop = fakeDesktop({ status: "ready", version: "0.2.0" });
    window.powereditor = { updates: desktop };
    render(<UpdateBanner />);

    await userEvent.click(await screen.findByRole("button", { name: t("updates.download") }));
    expect(desktop.download).toHaveBeenCalledWith("0.2.0");
    await userEvent.click(await screen.findByRole("button", { name: t("updates.install") }));

    expect(desktop.installAndQuit).toHaveBeenCalled();
  });

  it("shows the progress the desktop app reports", async () => {
    vi.mocked(api.updates).mockResolvedValue(status());
    const desktop = fakeDesktop({
      status: "downloading",
      version: "0.2.0",
      received: 0,
      total: null,
    });
    window.powereditor = { updates: desktop };
    render(<UpdateBanner />);
    await screen.findByRole("button", { name: t("updates.download") });
    // The banner subscribes in an effect; emitting earlier would drop the event.
    await waitFor(() => expect(desktop.subscribed()).toBe(true));

    act(() => desktop.emit({ status: "downloading", version: "0.2.0", received: 25, total: 100 }));

    expect(await screen.findByText(t("updates.downloading", { percent: 25 }))).toBeTruthy();
  });

  it("shows the failure and a retry when the desktop download call itself fails", async () => {
    vi.mocked(api.updates).mockResolvedValue(status());
    const desktop = fakeDesktop({ status: "ready", version: "0.2.0" });
    vi.mocked(desktop.download).mockRejectedValueOnce(new Error("IPC channel closed"));
    window.powereditor = { updates: desktop };
    render(<UpdateBanner />);

    await userEvent.click(await screen.findByRole("button", { name: t("updates.download") }));

    expect(await screen.findByRole("alert")).toHaveProperty("textContent", t("updates.failed"));
    await userEvent.click(screen.getByRole("button", { name: t("updates.retry") }));
    expect(desktop.download).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("button", { name: t("updates.install") })).toBeTruthy();
  });

  it("offers a retry when the desktop download fails", async () => {
    vi.mocked(api.updates).mockResolvedValue(status());
    const desktop = fakeDesktop({ status: "failed", version: "0.2.0", error: "checksum_mismatch" });
    window.powereditor = { updates: desktop };
    render(<UpdateBanner />);

    await userEvent.click(await screen.findByRole("button", { name: t("updates.download") }));

    expect(await screen.findByText(t("updates.failed"))).toBeTruthy();
    expect(screen.getByRole("button", { name: t("updates.retry") })).toBeTruthy();
  });
});

describe("About updates", () => {
  it("shows the last check and checks again on request", async () => {
    vi.mocked(api.updates).mockResolvedValueOnce(
      status({ updateAvailable: false, latest: "0.1.0" }),
    );
    vi.mocked(api.updates).mockResolvedValueOnce(status({ checkedAt: "2026-10-06T13:00:00Z" }));
    render(<About />);

    expect(await screen.findByText(t("about.upToDate"))).toBeTruthy();
    expect(screen.getByText(/^Last checked /)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: t("about.checkNow") }));

    expect(await screen.findByText(t("updates.available", { version: "0.2.0" }))).toBeTruthy();
    expect(vi.mocked(api.updates).mock.calls).toEqual([[false], [true]]);
  });

  it("says when no release has been published yet", async () => {
    vi.mocked(api.updates).mockResolvedValue(
      status({ updateAvailable: false, latest: null, releaseUrl: null }),
    );
    render(<About />);

    expect(await screen.findByText(t("about.noRelease"))).toBeTruthy();
  });

  it("says when the check failed", async () => {
    vi.mocked(api.updates).mockResolvedValue(
      status({
        updateAvailable: false,
        latest: null,
        checkedAt: null,
        error: "update_check_failed",
      }),
    );
    render(<About />);

    expect(await screen.findByText(t("error.update_check_failed"))).toBeTruthy();
  });
});
