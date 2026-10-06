import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

interface Manifest {
  build: { extraResources: { from: string; to: string }[] };
}

const desktop = path.join(__dirname, "..");
const manifest = JSON.parse(
  fs.readFileSync(path.join(desktop, "package.json"), "utf-8"),
) as Manifest;

describe("installer resources", () => {
  it("ship the GPL text for Remotion's compositor next to the third-party notices", () => {
    const shipped = manifest.build.extraResources.map((resource) => resource.to);
    const gpl = manifest.build.extraResources.find((resource) => resource.to.includes("GPL"));

    expect(shipped).toEqual(
      expect.arrayContaining(["THIRD_PARTY_NOTICES.md", "licenses/GPL-2.0.txt"]),
    );
    expect(gpl).toBeDefined();
    const text = fs.readFileSync(path.join(desktop, gpl?.from ?? ""), "utf-8");
    expect(text).toContain("GNU GENERAL PUBLIC LICENSE");
    expect(text).toContain("Version 2, June 1991");
  });
});
