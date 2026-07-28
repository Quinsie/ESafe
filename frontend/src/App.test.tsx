import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

function response(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}

function envelope(data: unknown) {
  return {
    data,
    meta: {
      requestId: "00000000-0000-4000-8000-000000000000",
      profile: "DEMO",
      asOf: "2026-07-29T00:00:00Z",
    },
    error: null,
  };
}

function sessionEnvelope() {
  return envelope({
    user: { userId: "user", displayName: "사용자" },
    expiresAt: "2026-07-29T12:00:00Z",
  });
}

function installAuthenticatedFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/session")) {
        return response(sessionEnvelope());
      }
      if (url.endsWith("/meta")) {
        return response(
          envelope({
            profile: "DEMO",
            profileBadge: "체험 데이터",
            version: "0.1.0",
            commit: "test",
          }),
        );
      }
      throw new Error(`unexpected request: ${url}`);
    }),
  );
}

function renderApp(pathname = "/demo/home") {
  window.history.replaceState({}, "", pathname);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <App runtime={resolveProfile(pathname)} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("App authentication boundary", () => {
  it("keeps the DEMO badge visible and renders H-01D only after session validation", async () => {
    installAuthenticatedFetch();
    renderApp();

    expect(screen.getByText("세션을 확인하고 있습니다.")).toBeVisible();
    expect(await screen.findByRole("heading", { name: "오늘의 상황 브리핑" })).toBeVisible();
    expect(screen.getByText("체험 데이터")).toBeVisible();
    expect(await screen.findByText("데이터 정상")).toBeVisible();
  });

  it("redirects an anonymous route to AUTH-01 and preserves the full return location", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/session")) {
        return response(
          { data: null, error: { code: "AUTH_REQUIRED", message: "로그인이 필요합니다." } },
          401,
        );
      }
      if (url.endsWith("/auth/login")) {
        return response(sessionEnvelope());
      }
      if (url.endsWith("/meta")) {
        return response(envelope({ profile: "DEMO", profileBadge: "체험 데이터", commit: "test" }));
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderApp("/demo/map?zoom=7&region=29");

    expect(await screen.findByRole("heading", { name: "로그인·세션 확인" })).toBeVisible();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/demo/login");
      expect(new URLSearchParams(window.location.search).get("returnTo")).toBe(
        "/map?zoom=7&region=29",
      );
    });

    await user.type(screen.getByLabelText("사용자 ID"), "user");
    await user.type(screen.getByLabelText("비밀번호"), "secret");
    await user.click(screen.getByRole("button", { name: "로그인" }));

    expect(await screen.findByRole("heading", { name: "위험 지도" })).toBeVisible();
    expect(window.location.pathname).toBe("/demo/map");
    expect(window.location.search).toBe("?zoom=7&region=29");
    expect(fetchMock).toHaveBeenCalledWith(
      "/demo/api/v1/auth/login",
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
  });

  it("labels unfinished authenticated routes honestly", async () => {
    installAuthenticatedFetch();
    renderApp("/demo/map");

    expect(await screen.findByRole("heading", { name: "위험 지도" })).toBeVisible();
    expect(screen.getByText("완료되지 않은 행동을 실제 기능처럼 표시하지 않습니다.")).toBeVisible();
  });
});
