import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveProfile } from "./profile";
import { SldAnalysisPanel } from "./sld_analysis";

function envelope(data: unknown): Response {
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

const analysis = {
  analysisId: "11111111-1111-4111-8111-111111111111",
  buildingId: "22222222-2222-4222-8222-222222222222",
  status: "SUCCEEDED",
  sourceFileName: "단선결선도.pdf",
  sourceMimeType: "application/pdf",
  sourceSizeBytes: 1000,
  ocrProvider: "UPSTAGE_DOCUMENT_OCR",
  ocrModel: "ocr",
  grammarVersion: "sld-equipment-grammar/11.0-upstage-only",
  explanationModel: "solar-pro3",
  result: {
    providerPolicy: {
      ocrProvider: "upstage_document_ocr",
      paddleUsed: false,
      legacyCandidateReuse: false,
    },
    pages: [{ page: 1, width: 1200, height: 800 }],
    ocrItemCount: 20,
    equipmentCount: 1,
    equipment: [
      {
        equipmentId: "SLD-EQ-00001",
        classId: "DryTypeTransformer",
        displayName: "건식변압기(TR)",
        role: "TRANSFORMER",
        page: 1,
        bbox: [120, 80, 480, 32],
        rawText: "TR(DRY TYPE) 1000kVA",
        ocrConfidence: 0.99,
        properties: { capacity_kva: 1000 },
        reviewStatus: "REVIEW_REQUIRED",
        fireRisk: {
          group: "TRANSFORMER",
          generalRisk: "권선 및 접속부 과열 가능성",
          inspectionPoints: ["온도 상승 기록"],
        },
      },
    ],
    explanation: {
      overview: "Upstage OCR 근거에서 설비 후보를 추출했습니다.",
      facilitySummary: ["건식변압기 1건"],
      fireRiskSummary: ["권선 및 접속부 과열 가능성"],
      keyEquipment: [
        {
          equipmentId: "SLD-EQ-00001",
          title: "건식변압기",
          observedFacts: ["OCR 원문 확인"],
          fireRiskFactors: ["권선 및 접속부 과열 가능성"],
          inspectionPoints: ["온도 상승 기록"],
          warning: "현장 확인이 필요합니다.",
        },
      ],
      limitations: ["실제 결선은 도면 원본과 대조해야 합니다."],
    },
    explanationStatus: "SUCCEEDED",
  },
  error: null,
  createdAt: "2026-07-30T00:00:00Z",
  completedAt: "2026-07-30T00:01:00Z",
  version: 2,
};

const managedDocument = {
  documentId: "33333333-3333-4333-8333-333333333333",
  buildingId: analysis.buildingId,
  sourceFileName: "본사 사옥 수변전 설비 단선 결선도 -1.pdf",
  sourceMimeType: "application/pdf",
  sourceSizeBytes: 4006323,
  sourceSha256: "f8a1149f7c5268a06d259b8a39dcec8466813bc86bf404e641ab7647f1e76c0e",
  documentOrigin: "DEMO_FIXTURE",
  uploadedBy: null,
  createdAt: "2026-07-30T00:00:00Z",
  updatedAt: "2026-07-30T00:00:00Z",
  version: 1,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SldAnalysisPanel", () => {
  it("manages a building diagram separately and extracts equipment from it", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(`/buildings/${analysis.buildingId}/sld-document`)) {
        return envelope({ document: managedDocument });
      }
      if (url.endsWith(`/buildings/${analysis.buildingId}/sld-analyses/from-document`)) {
        return envelope(analysis);
      }
      if (url.endsWith(`/buildings/${analysis.buildingId}/sld-analyses`)) {
        return envelope({ items: [analysis] });
      }
      throw new Error(`unexpected request: ${url} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    const runtime = resolveProfile("/demo/buildings/22222222-2222-4222-8222-222222222222");
    render(
      <QueryClientProvider client={queryClient}>
        <SldAnalysisPanel buildingId={analysis.buildingId} runtime={runtime} />
      </QueryClientProvider>,
    );

    expect(screen.getByText("UPSTAGE OCR ONLY")).toBeVisible();
    expect(await screen.findByText("건식변압기(TR)")).toBeVisible();
    expect(screen.getByText(/DS-01 화재 건물 기본 도면/)).toBeVisible();
    expect(screen.getByText("본사 사옥 수변전 설비 단선 결선도 -1.pdf")).toBeVisible();
    expect(screen.getAllByText("권선 및 접속부 과열 가능성")).toHaveLength(2);
    expect(screen.getByAltText("단선결선도.pdf 1쪽 설비 추출 도면")).toHaveAttribute(
      "src",
      "/demo/api/v1/sld-analyses/11111111-1111-4111-8111-111111111111/pages/1/preview",
    );
    const viewport = screen.getByLabelText("결선도 확대·축소 영역");
    const canvas = viewport.querySelector(".sld-diagram-canvas") as HTMLElement;
    expect(screen.getByText("100%")).toBeVisible();
    expect(canvas).toHaveStyle({ width: "100%" });
    fireEvent.wheel(viewport, { clientX: 240, clientY: 160, deltaY: -120 });
    expect(screen.getByText("112%")).toBeVisible();
    expect(canvas).toHaveStyle({ width: "112%" });
    await user.click(screen.getByRole("button", { name: "맞춤" }));
    expect(screen.getByText("100%")).toBeVisible();
    viewport.scrollLeft = 100;
    viewport.scrollTop = 80;
    fireEvent.pointerDown(viewport, { button: 0, clientX: 240, clientY: 160, pointerId: 7 });
    expect(viewport).toHaveClass("is-dragging");
    fireEvent.pointerMove(viewport, { clientX: 190, clientY: 120, pointerId: 7 });
    expect(viewport.scrollLeft).toBe(150);
    expect(viewport.scrollTop).toBe(120);
    fireEvent.pointerUp(viewport, { pointerId: 7 });
    expect(viewport).not.toHaveClass("is-dragging");
    const overlay = screen.getByRole("button", {
      name: "건식변압기(TR) 위치 - 변압기군 설명으로 이동",
    });
    await user.click(overlay);
    expect(screen.getByText("변압기군 공통 설명")).toBeVisible();
    expect(screen.getByRole("heading", { name: "변압기군" }).closest("article")).toHaveClass(
      "is-active",
    );
    expect(screen.queryByText(/Paddle/i)).not.toBeInTheDocument();

    const file = new File(["%PDF-1.7"], "new-diagram.pdf", {
      type: "application/pdf",
    });
    await user.upload(screen.getByLabelText("단선결선도 교체 파일"), file);
    await user.click(screen.getByRole("button", { name: "관리 도면 교체" }));

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
      expect(put).toBeDefined();
      const init = put?.[1] as RequestInit;
      expect(init.body).toBeInstanceOf(FormData);
      expect(new Headers(init.headers).has("Content-Type")).toBe(false);
    });

    await user.click(screen.getByRole("button", { name: "설비 추출 시작" }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([input, init]) =>
          String(input).endsWith(`/buildings/${analysis.buildingId}/sld-analyses/from-document`) &&
          init?.method === "POST",
      );
      expect(post).toBeDefined();
      const init = post?.[1] as RequestInit;
      expect(new Headers(init.headers).has("Idempotency-Key")).toBe(true);
    });
  });

  it("shows the missing state and disables extraction without a managed diagram", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith(`/buildings/${analysis.buildingId}/sld-document`)) {
          return envelope({ document: null });
        }
        if (url.endsWith(`/buildings/${analysis.buildingId}/sld-analyses`)) {
          return envelope({ items: [] });
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const runtime = resolveProfile("/demo/buildings/22222222-2222-4222-8222-222222222222");
    render(
      <QueryClientProvider client={queryClient}>
        <SldAnalysisPanel buildingId={analysis.buildingId} runtime={runtime} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("등록된 단선결선도가 없습니다.")).toBeVisible();
    expect(screen.getByRole("button", { name: "설비 추출 시작" })).toBeDisabled();
    expect(screen.getByLabelText("단선결선도 등록 파일")).toBeVisible();
  });
});
