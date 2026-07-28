import { describe, expect, it } from "vitest";
import { resolveProfile } from "./profile";

describe("resolveProfile", () => {
  it("resolves the isolated demo path", () => {
    expect(resolveProfile("/demo/map/buildings")).toEqual({
      profile: "DEMO",
      badge: "체험 데이터",
      basePath: "/demo/",
      apiBase: "/demo/api/v1",
    });
  });

  it("defaults unknown and live paths to LIVE", () => {
    expect(resolveProfile("/live/").profile).toBe("LIVE");
    expect(resolveProfile("/").apiBase).toBe("/live/api/v1");
  });
});
