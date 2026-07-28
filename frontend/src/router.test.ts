import { describe, expect, it } from "vitest";
import { resolveProfile } from "./profile";
import { internalPath, profileHref, safeReturnTo } from "./router";

const demo = resolveProfile("/demo/");

describe("profile-aware navigation safety", () => {
  it("treats the profile root as H-01D home", () => {
    expect(internalPath("/demo/", demo)).toBe("/home");
    expect(profileHref(demo, "/login?returnTo=%2Fmap")).toBe("/demo/login?returnTo=%2Fmap");
  });

  it("allows only local non-login return locations", () => {
    expect(safeReturnTo("/map?zoom=7#selected")).toBe("/map?zoom=7#selected");
    expect(safeReturnTo("/login")).toBe("/home");
    expect(safeReturnTo("//attacker.invalid/path")).toBe("/home");
    expect(safeReturnTo("https://attacker.invalid/path")).toBe("/home");
    expect(safeReturnTo(null)).toBe("/home");
  });
});
