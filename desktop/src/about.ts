/** The shell's About panel and menu. Pure data, so it can be tested without Electron. */
import type { AboutPanelOptionsOptions, MenuItemConstructorOptions } from "electron";

export const APP_NAME = "PowerEditor";
export const COPYRIGHT = "Copyright 2026 Nicolás Olmedo (https://nolmedo.dev)";
const HOMEPAGE = "https://github.com/nikolmedo/PowerEditor";

/** Options for `app.setAboutPanelOptions`. Windows shows `credits` but not `website`, so the
 * homepage goes in both. */
export function aboutPanelOptions(version: string): AboutPanelOptionsOptions {
  return {
    applicationName: APP_NAME,
    applicationVersion: version,
    copyright: COPYRIGHT,
    credits: HOMEPAGE,
    website: HOMEPAGE,
  };
}

/** Electron's default menus, with a Help menu that opens the About panel. */
export function applicationMenuTemplate(helpLabel: string): MenuItemConstructorOptions[] {
  return [
    { role: "fileMenu" },
    { role: "editMenu" },
    { role: "viewMenu" },
    { role: "windowMenu" },
    { label: helpLabel, submenu: [{ role: "about" }] },
  ];
}
