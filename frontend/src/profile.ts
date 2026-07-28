export type RuntimeProfile = "LIVE" | "DEMO";

export interface ProfileRuntime {
  profile: RuntimeProfile;
  badge: "실시간 연동" | "체험 데이터";
  basePath: "/live/" | "/demo/";
  apiBase: "/live/api/v1" | "/demo/api/v1";
}

export function resolveProfile(pathname: string): ProfileRuntime {
  const firstSegment = pathname.split("/").filter(Boolean)[0]?.toLowerCase();
  const profile: RuntimeProfile = firstSegment === "demo" ? "DEMO" : "LIVE";
  if (profile === "DEMO") {
    return {
      profile,
      badge: "체험 데이터",
      basePath: "/demo/",
      apiBase: "/demo/api/v1",
    };
  }
  return {
    profile,
    badge: "실시간 연동",
    basePath: "/live/",
    apiBase: "/live/api/v1",
  };
}
