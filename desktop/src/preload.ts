/**
 * Runs sandboxed before the web app, with context isolation: the page gets no Node access,
 * only this read-only description of the shell.
 */
import { contextBridge } from "electron";

contextBridge.exposeInMainWorld(
  "powerEditorDesktop",
  Object.freeze({ platform: process.platform }),
);
