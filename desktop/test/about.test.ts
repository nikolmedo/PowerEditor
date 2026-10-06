import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { aboutPanelOptions, applicationMenuTemplate, COPYRIGHT } from "../src/about";

describe("aboutPanelOptions", () => {
  it("names the app, its version, the copyright and the website", () => {
    expect(aboutPanelOptions("0.1.0")).toEqual({
      applicationName: "PowerEditor",
      applicationVersion: "0.1.0",
      copyright: "Copyright 2026 Nicolás Olmedo (https://nolmedo.dev)",
      credits: "https://github.com/nikolmedo/PowerEditor",
      website: "https://github.com/nikolmedo/PowerEditor",
    });
    expect(aboutPanelOptions("2.3.4").applicationVersion).toBe("2.3.4");
  });

  it("uses the same notice as the installer metadata", () => {
    const file = path.join(__dirname, "..", "package.json");
    const manifest = JSON.parse(fs.readFileSync(file, "utf-8")) as {
      build: { copyright: string };
    };

    expect(manifest.build.copyright).toBe(COPYRIGHT);
  });
});

describe("applicationMenuTemplate", () => {
  it("keeps the standard menus and adds About under Help", () => {
    const template = applicationMenuTemplate("Help");

    expect(template.map((item) => item.role ?? item.label)).toEqual([
      "fileMenu",
      "editMenu",
      "viewMenu",
      "windowMenu",
      "Help",
    ]);
    expect(template[4]?.submenu).toEqual([{ role: "about" }]);
  });
});
