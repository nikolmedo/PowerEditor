import { useEffect, useState } from "react";
import { desktopUpdates, type DesktopUpdateState } from "./desktopBridge";

export interface UpdateDownload {
  state: DesktopUpdateState;
  /** Download and verify the version in the desktop app; in a browser, open the release page. */
  start: () => void;
  /** Quit, install silently and start the new version (desktop app only). */
  install: () => void;
}

/** The download of release `version`, following the progress the desktop shell reports. The
 * shell sends its state to every listener, so a download started in one place shows in the
 * others. */
export function useUpdateDownload(version: string, releaseUrl: string | null): UpdateDownload {
  const desktop = desktopUpdates();
  const [state, setState] = useState<DesktopUpdateState>({ status: "idle" });
  useEffect(() => desktop?.onState(setState), [desktop]);

  const start = () => {
    if (!desktop) {
      if (releaseUrl) window.open(releaseUrl, "_blank", "noreferrer");
      return;
    }
    desktop.download(version).then(
      (final) => {
        if (final) setState(final);
      },
      // The shell went away mid-call (IPC closed): show the failure so Retry is offered.
      () => setState({ status: "failed", version, error: "download_failed" }),
    );
  };
  const install = () => void desktop?.installAndQuit();

  return { state, start, install };
}
