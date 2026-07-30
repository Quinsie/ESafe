import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DataExtract } from "./data_extract";
import { resolveProfile } from "./profile";

type RegionLevel = "SIDO" | "SIGUNGU";

function response(level: RegionLevel): Response {
  const region =
    level === "SIDO"
      ? { code: "29", name: "광주광역시", parentCode: null }
      : { code: "29170", name: "북구", parentCode: "29" };
  const fullName = level === "SIDO" ? region.name : `광주광역시 ${region.name}`;
  return {
    ok: true,
    status: 200,
    json: async () => ({
      data: {
        level,
        levelName: level,
        items: [
          {
            regionCode: region.code,
            name: region.name,
            fullName,
            parentCode: region.parentCode,
            buildingCount: 21720,
            eligibleCounts: { "1": 217, "5": 1086, "10": 2172 },
          },
        ],
        riskReference: {
          referenceMonth: "2026-03",
          horizonDays: 60,
          lineageVersion: "v27.1-focus-2026-03-60d",
          isProbability: false,
        },
      },
      meta: {
        requestId: "00000000-0000-4000-8000-000000000000",
        profile: "DEMO",
        asOf: "2026-07-30T00:00:00Z",
      },
      error: null,
    }),
  } as Response;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("DataExtract", () => {
  it("applies the region hierarchy as chained AND conditions", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const level = url.searchParams.get("level");
      return response(level === "SIGUNGU" ? level : "SIDO");
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    const runtime = resolveProfile("/demo/data-extract");
    render(
      <QueryClientProvider client={queryClient}>
        <DataExtract runtime={runtime} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("2,172개 건축물")).toBeVisible();
    expect(screen.getByText("14열", { exact: true })).toBeVisible();
    expect(screen.getByText("건물 주용도")).toBeVisible();
    expect(screen.queryByText("도로명주소")).not.toBeInTheDocument();
    expect(screen.queryByText("건물 식별번호")).not.toBeInTheDocument();
    expect(screen.queryByText("위험등급")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("읍·면·동")).not.toBeInTheDocument();
    const download = screen.getByRole("link", { name: "Excel(.xlsx)로 추출" });
    expect(download).toHaveAttribute(
      "href",
      "/demo/api/v1/data-extract/buildings.xlsx?level=SIDO&regionCode=29&topPercent=10",
    );

    await screen.findByRole("option", { name: "북구" });
    await user.selectOptions(screen.getByLabelText("시·군·구"), "29170");
    await waitFor(() => {
      expect(download).toHaveAttribute(
        "href",
        "/demo/api/v1/data-extract/buildings.xlsx?level=SIGUNGU&regionCode=29170&topPercent=10",
      );
    });
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("level=SIGUNGU&parentCode=29")),
    ).toBe(true);

    await user.click(screen.getByLabelText("상위 1%"));
    expect(download).toHaveAttribute(
      "href",
      "/demo/api/v1/data-extract/buildings.xlsx?level=SIGUNGU&regionCode=29170&topPercent=1",
    );
  });
});
