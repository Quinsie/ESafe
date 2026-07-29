import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoRemoteControl, DemoScenarioPage } from "./demo";
import { resolveProfile } from "./profile";

function response(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      data,
      meta: {
        requestId: "00000000-0000-4000-8000-000000000000",
        profile: "DEMO",
        asOf: "2026-07-30T00:00:00Z",
      },
      error: null,
    }),
  } as Response;
}

const step = {
  ordinal: 1,
  label: "원천 신호 재생",
  source: "NFDS",
  sourceTime: "2026-07-30T10:00:00+09:00",
  kind: "FIXTURE",
};

function catalog() {
  return {
    items: [
      {
        scenarioId: "s1",
        code: "DS-01",
        name: "화재 전체 여정",
        description: "완료된 시나리오",
        scenarioVersion: 1,
        stepCount: 1,
        steps: [step],
        playback: {
          playbackId: "p1",
          status: "COMPLETED",
          currentStep: 1,
          stepCount: 1,
          generation: 1,
          version: 4,
          updatedAt: "2026-07-30T00:00:00Z",
        },
      },
      {
        scenarioId: "s5",
        code: "DS-05",
        name: "소스 장애·복구",
        description: "현재 초기화 대기 중인 시나리오",
        scenarioVersion: 1,
        stepCount: 1,
        steps: [step],
        playback: {
          playbackId: "p5",
          status: "READY",
          currentStep: 0,
          stepCount: 1,
          generation: 2,
          version: 7,
          updatedAt: "2026-07-30T00:00:00Z",
        },
      },
    ],
  };
}

function renderWithClient(element: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{element}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("DEMO scenario controls", () => {
  it("resets the selected scenario and supplies the active playback version", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/demo/scenarios")) return response(catalog());
      if (url.endsWith("/demo/scenarios/s1/reset")) {
        return response({ command: "RESET" });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    window.history.replaceState({}, "", "/demo/home");
    const runtime = resolveProfile("/demo/home");
    const user = userEvent.setup();
    renderWithClient(<DemoRemoteControl currentPath="/home" runtime={runtime} />);

    await user.click(await screen.findByRole("button", { name: "DS-05 · 소스 장애·복구" }));
    await user.click(screen.getByRole("option", { name: "DS-01 화재 전체 여정" }));
    await user.click(screen.getByRole("button", { name: "초기화" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/demo/api/v1/demo/scenarios/s1/reset",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            expectedVersion: 4,
            activeExpectedVersion: 7,
            confirmed: true,
          }),
        }),
      );
    });
  });

  it("shows scenario descriptions and step details on the dedicated page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(catalog())),
    );
    const runtime = resolveProfile("/demo/demo-scenarios");

    renderWithClient(<DemoScenarioPage runtime={runtime} />);

    expect(await screen.findByRole("heading", { name: "체험 시나리오" })).toBeVisible();
    expect(screen.getByText("화재 전체 여정")).toBeVisible();
    expect(screen.getByText("원천 신호 재생")).toBeVisible();
    expect(screen.getByText("선택만으로 진행 중인 시나리오는 바뀌지 않습니다.")).toBeVisible();
  });
});
