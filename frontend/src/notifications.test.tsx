import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { resolveProfile } from "./profile";

function envelope(data: unknown) {
  return {
    data,
    meta: { requestId: "test", profile: "DEMO", asOf: "2026-07-29T00:00:00Z" },
    error: null,
  };
}

function response(data: unknown): Response {
  return { ok: true, status: 200, json: async () => data } as Response;
}

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/session"))
        return response(
          envelope({
            user: { userId: "user", displayName: "사용자" },
            expiresAt: "2026-07-29T12:00:00Z",
          }),
        );
      if (url.endsWith("/sources/health"))
        return response(envelope({ summary: "HEALTHY", dataAsOf: null, sources: [] }));
      if (url.includes("/approvals?pageSize=50"))
        return response(
          envelope({
            items: [
              {
                approvalRequestId: "00000000-0000-4000-8000-000000000801",
                caseNumber: "DEMO-20260729-000001",
                caseTitle: "광주 북구 화재",
                title: "대응안 승인 요청",
                status: "APPROVAL_PENDING",
                requestedAt: "2026-07-29T01:00:00Z",
                version: 1,
              },
            ],
          }),
        );
      if (url.includes("/cases?page=1&pageSize=50&sort=updated"))
        return response(
          envelope({
            items: [
              {
                caseId: "00000000-0000-4000-8000-000000000802",
                caseNumber: "DEMO-20260729-000001",
                title: "광주 북구 화재",
                status: "ACTIVE",
                sourceStatus: "ACTIVE",
                monitoringPriority: "URGENT",
                impactBuildingCount: 24,
                highRiskBuildingCount: 3,
                updatedAt: "2026-07-29T02:00:00Z",
                version: 2,
              },
            ],
          }),
        );
      if (url.includes("/automation/runs?page=1&pageSize=50"))
        return response(
          envelope({
            items: [
              {
                entryId: "00000000-0000-4000-8000-000000000803",
                entryType: "AUTOMATION_RUN",
                status: "SUCCEEDED",
                category: "RAG_RETRIEVAL",
                source: null,
                occurredAt: "2026-07-29T03:00:00Z",
                case: {
                  caseId: "00000000-0000-4000-8000-000000000802",
                  caseNumber: "DEMO-20260729-000001",
                },
              },
            ],
          }),
        );
      throw new Error(`unexpected request: ${url}`);
    }),
  );
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("notification center", () => {
  it("aggregates truthful approval, Case and automation records and stores read state", async () => {
    installFetch();
    window.history.replaceState({}, "", "/demo/notifications");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <App runtime={resolveProfile("/demo/notifications")} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { name: "알림 센터" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "승인 대기" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "위험·재난" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "자동화 완료" })).toBeInTheDocument();
    expect(await screen.findByText("대응안 승인 요청")).toBeInTheDocument();
    expect(screen.getByText("읽지 않음 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "모두 읽음 처리" }));
    expect(screen.getByText("읽지 않음 0")).toBeInTheDocument();
    expect(localStorage.getItem("esafe-notifications-read-demo")).toContain("approval:");
    expect(
      screen.getByText(/위험점수 상승이나 실행 결과를 새로 추정하지 않습니다/),
    ).toBeInTheDocument();
  });
});
