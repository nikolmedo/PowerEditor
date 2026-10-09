/**
 * Runs sandboxed before the web app, with context isolation: the page gets no Node access,
 * only a read-only description of the shell and the updater calls below. A sandboxed
 * preload cannot load local modules, so it imports types only.
 */
import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import type { UpdateState } from "./updater";

contextBridge.exposeInMainWorld(
  "powerEditorDesktop",
  Object.freeze({ platform: process.platform }),
);

contextBridge.exposeInMainWorld(
  "powereditor",
  Object.freeze({
    updates: Object.freeze({
      /** Download and verify the installer of release `version`; resolves with the final
       * state (null when the shell refused the call). */
      download: (version: string): Promise<UpdateState | null> =>
        ipcRenderer.invoke("updates:download", version),
      /** Quit and install the verified installer silently; the new version starts on its
       * own. False when there is none ready. */
      installAndQuit: (): Promise<boolean> => ipcRenderer.invoke("updates:installAndQuit"),
      /** Announce that `version` is available with a system notification, once per version
       * and run; false when nothing was shown. */
      notifyAvailable: (version: string): Promise<boolean> =>
        ipcRenderer.invoke("updates:notify", version),
      /** Follow download progress; returns a function that stops listening. */
      onState: (listener: (state: UpdateState) => void): (() => void) => {
        const forward = (_event: IpcRendererEvent, state: UpdateState) => listener(state);
        ipcRenderer.on("updates:state", forward);
        return () => ipcRenderer.removeListener("updates:state", forward);
      },
    }),
  }),
);
