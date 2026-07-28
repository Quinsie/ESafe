import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

function renderApp(pathname = "/demo/") {
  window.history.replaceState({}, "", pathname);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <App runtime={resolveProfile(pathname)} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  window.history.replaceState({}, "", "/");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("App shell", () => {
  it("keeps the DEMO badge visible and renders H-01D as home", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          data: { profile: "DEMO", profileBadge: "체험 데이터", version: "0.1.0" },
        }),
      }),
    );

    renderApp();

    expect(screen.getByText("체험 데이터")).toBeVisible();
    expect(screen.getByRole("heading", { name: "오늘의 상황 브리핑" })).toBeVisible();
    expect(await screen.findByText("데이터 정상")).toBeVisible();
  });

  it("labels unfinished routes honestly", () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    renderApp("/demo/map");

    expect(screen.getByRole("heading", { name: "위험 지도" })).toBeVisible();
    expect(screen.getByText("완료되지 않은 행동을 실제 기능처럼 표시하지 않습니다.")).toBeVisible();
  });
});
