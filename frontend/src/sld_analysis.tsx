import { useQuery } from "@tanstack/react-query";
import { type FormEvent, type PointerEvent, useRef, useState, type WheelEvent } from "react";
import { ApiError, apiRequest } from "./api";
import type { ProfileRuntime } from "./profile";

type AnalysisStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "REVIEW_REQUIRED" | "FAILED";

interface SldEquipment {
  equipmentId: string;
  classId: string;
  displayName: string;
  role: string | null;
  page: number;
  bbox: [number, number, number, number] | null;
  coreBbox?: [number, number, number, number];
  cropBbox?: [number, number, number, number];
  cropId?: string | null;
  regionId?: string | null;
  groupingMethod?: string;
  ocrModes?: string[];
  rawText: string;
  ocrConfidence: number;
  properties: Record<string, unknown>;
  reviewStatus: string;
  fireRisk: {
    group: string;
    generalRisk: string;
    inspectionPoints: string[];
  } | null;
}

interface SldExplanationItem {
  equipmentId: string;
  title: string;
  observedFacts: string[];
  fireRiskFactors: string[];
  inspectionPoints: string[];
  warning: string | null;
}

interface SldResult {
  providerPolicy: {
    ocrProvider: string;
    paddleUsed: false;
    legacyCandidateReuse: false;
  };
  pages: Array<{ page: number; width: number; height: number }>;
  ocrItemCount: number;
  fullPageOcrItemCount?: number;
  regionOcrItemCount?: number;
  boxPipeline?: {
    version: string;
    detectedEnclosureCount: number;
    equipmentAnchoredRegionCount: number;
    ocrCropCount: number;
    regionOcrFailureCount: number;
    upscaleFactor: number;
  };
  equipmentCount: number;
  equipment: SldEquipment[];
  explanation: {
    overview: string;
    facilitySummary: string[];
    fireRiskSummary: string[];
    keyEquipment: SldExplanationItem[];
    limitations: string[];
  };
  explanationStatus: "SUCCEEDED" | "REVIEW_REQUIRED";
}

interface SldAnalysis {
  analysisId: string;
  buildingId: string;
  status: AnalysisStatus;
  sourceFileName: string;
  sourceMimeType: string;
  sourceSizeBytes: number;
  ocrProvider: "UPSTAGE_DOCUMENT_OCR";
  ocrModel: string;
  grammarVersion: string;
  explanationModel: string | null;
  result: SldResult | null;
  error: { code: string; message: string } | null;
  createdAt: string;
  completedAt: string | null;
  version: number;
}

interface SldAnalysisList {
  items: SldAnalysis[];
}

interface SldDocument {
  documentId: string;
  buildingId: string;
  sourceFileName: string;
  sourceMimeType: string;
  sourceSizeBytes: number;
  sourceSha256: string;
  documentOrigin: "MANAGER_UPLOAD" | "DEMO_FIXTURE";
  uploadedBy: string | null;
  createdAt: string;
  updatedAt: string;
  version: number;
}

interface SldDocumentResponse {
  document: SldDocument | null;
}

interface SldEquipmentGroup {
  groupId: string;
  label: string;
  anchorId: string;
  equipment: SldEquipment[];
  observedFacts: string[];
  fireRiskFactors: string[];
  inspectionPoints: string[];
  warnings: string[];
}

const equipmentGroupNames: Record<string, string> = {
  TRANSFORMER: "변압기군",
  BREAKER: "차단기군",
  GENERATOR: "예비발전기군",
  BATTERY_UPS: "배터리·UPS군",
  SURGE_PROTECTION: "피뢰·서지보호 설비군",
  REACTIVE_POWER: "콘덴서·리액터군",
  SWITCHING: "개폐 설비군",
};

const statusNames: Record<AnalysisStatus, string> = {
  QUEUED: "분석 대기",
  RUNNING: "Upstage 분석 중",
  SUCCEEDED: "분석 완료",
  REVIEW_REQUIRED: "사람 검토 필요",
  FAILED: "분석 실패",
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "분석 요청을 처리하지 못했습니다.";
}

function simpleProperties(properties: Record<string, unknown>) {
  return Object.entries(properties)
    .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
    .slice(0, 8);
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}

function equipmentGroupId(equipment: SldEquipment): string {
  return equipment.fireRisk?.group || equipment.role || equipment.classId;
}

function buildEquipmentGroups(
  equipment: SldEquipment[],
  explanationById: Map<string, SldExplanationItem>,
): SldEquipmentGroup[] {
  const grouped = new Map<string, SldEquipment[]>();
  for (const item of equipment) {
    const groupId = equipmentGroupId(item);
    grouped.set(groupId, [...(grouped.get(groupId) ?? []), item]);
  }
  return [...grouped.entries()].map(([groupId, items], index) => {
    const explanations = items
      .map((item) => explanationById.get(item.equipmentId))
      .filter((item): item is SldExplanationItem => Boolean(item));
    return {
      groupId,
      label:
        equipmentGroupNames[groupId] ??
        (items.length === 1 ? items[0].displayName : `${items[0].displayName} 설비군`),
      anchorId: `sld-equipment-group-${index + 1}`,
      equipment: items,
      observedFacts: uniqueStrings([
        ...explanations.flatMap((item) => item.observedFacts),
        ...items.map((item) => `OCR 원문: ${item.rawText}`),
      ]),
      fireRiskFactors: uniqueStrings([
        ...explanations.flatMap((item) => item.fireRiskFactors),
        ...items.map((item) => item.fireRisk?.generalRisk),
      ]),
      inspectionPoints: uniqueStrings([
        ...explanations.flatMap((item) => item.inspectionPoints),
        ...items.flatMap((item) => item.fireRisk?.inspectionPoints ?? []),
      ]),
      warnings: uniqueStrings(explanations.map((item) => item.warning)),
    };
  });
}

function validBbox(bbox: SldEquipment["bbox"]): bbox is [number, number, number, number] {
  return Boolean(
    bbox?.every(Number.isFinite) && bbox[0] >= 0 && bbox[1] >= 0 && bbox[2] > 0 && bbox[3] > 0,
  );
}

export function SldAnalysisPanel({
  runtime,
  buildingId,
}: {
  runtime: ProfileRuntime;
  buildingId: string;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const managedDocument = useQuery({
    queryKey: ["sld-document", runtime.profile, buildingId],
    queryFn: () =>
      apiRequest<SldDocumentResponse>(runtime, `/buildings/${buildingId}/sld-document`).then(
        (response) => response.data,
      ),
  });
  const analyses = useQuery({
    queryKey: ["sld-analyses", runtime.profile, buildingId],
    queryFn: () =>
      apiRequest<SldAnalysisList>(runtime, `/buildings/${buildingId}/sld-analyses`).then(
        (response) => response.data,
      ),
    refetchInterval: (query) => {
      const active = query.state.data?.items.some(
        (item) => item.status === "QUEUED" || item.status === "RUNNING",
      );
      return active ? 2000 : false;
    },
  });
  const selected =
    analyses.data?.items.find((item) => item.analysisId === selectedId) ??
    analyses.data?.items[0] ??
    null;

  async function registerDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || submitting) return;
    setSubmitting(true);
    setActionError(null);
    const body = new FormData();
    body.set("document", file);
    try {
      await apiRequest<SldDocumentResponse>(runtime, `/buildings/${buildingId}/sld-document`, {
        method: "PUT",
        body,
      });
      setFile(null);
      await managedDocument.refetch();
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function analyzeDocument() {
    if (!managedDocument.data?.document || submitting) return;
    setSubmitting(true);
    setActionError(null);
    try {
      const response = await apiRequest<SldAnalysis>(
        runtime,
        `/buildings/${buildingId}/sld-analyses/from-document`,
        {
          method: "POST",
          headers: { "Idempotency-Key": crypto.randomUUID() },
        },
      );
      setSelectedId(response.data.analysisId);
      await analyses.refetch();
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function retry() {
    if (!selected || submitting) return;
    setSubmitting(true);
    setActionError(null);
    try {
      await apiRequest<SldAnalysis>(runtime, `/sld-analyses/${selected.analysisId}/retry`, {
        method: "POST",
      });
      await analyses.refetch();
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="sld-analysis" aria-labelledby="sld-analysis-title">
      <div className="sld-analysis-header">
        <div>
          <span className="sld-provider-badge">UPSTAGE OCR ONLY</span>
          <h2 id="sld-analysis-title">단선결선도 분석</h2>
          <p>
            단선결선도에서 설비 후보와 정격을 읽고 변압기·차단기·발전기·배터리 등 화재 위험 점검
            항목을 설명합니다.
          </p>
        </div>
        <strong>PDF · PNG · JPG / 최대 25MB</strong>
      </div>

      <section className="sld-document-manager" aria-labelledby="sld-document-title">
        <div className="sld-document-heading">
          <div>
            <h3 id="sld-document-title">건물 단선결선도 관리</h3>
            <p>관리자가 건물별 원본 도면을 등록하거나 최신 도면으로 교체할 수 있습니다.</p>
          </div>
          {managedDocument.data?.document ? (
            <span className="sld-document-status registered">등록됨</span>
          ) : (
            <span className="sld-document-status missing">미등록</span>
          )}
        </div>
        {managedDocument.isLoading ? (
          <div className="sld-state">등록된 단선결선도를 확인하는 중입니다.</div>
        ) : managedDocument.isError ? (
          <div className="sld-state error">
            단선결선도 등록 상태를 불러오지 못했습니다.
            <button onClick={() => void managedDocument.refetch()} type="button">
              다시 시도
            </button>
          </div>
        ) : managedDocument.data?.document ? (
          <div className="sld-document-card">
            <div>
              <strong>{managedDocument.data.document.sourceFileName}</strong>
              <span>
                {managedDocument.data.document.documentOrigin === "DEMO_FIXTURE"
                  ? "DS-01 화재 건물 기본 도면"
                  : "관리자 등록 도면"}
                {" · "}
                {(managedDocument.data.document.sourceSizeBytes / (1024 * 1024)).toFixed(1)}MB
              </span>
              <small>
                최근 등록{" "}
                {new Date(managedDocument.data.document.updatedAt).toLocaleString("ko-KR")}
              </small>
            </div>
            <a
              className="outline-action"
              href={`${runtime.apiBase}/buildings/${buildingId}/sld-document/source`}
              rel="noreferrer"
              target="_blank"
            >
              등록 도면 보기
            </a>
          </div>
        ) : (
          <div className="sld-document-empty">
            <strong>등록된 단선결선도가 없습니다.</strong>
            <span>관리자가 도면을 등록하면 설비 추출을 시작할 수 있습니다.</span>
          </div>
        )}
        <form className="sld-upload-form" onSubmit={registerDocument}>
          <label>
            <span>
              {managedDocument.data?.document ? "단선결선도 교체 파일" : "단선결선도 등록 파일"}
            </span>
            <input
              accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
              aria-label={
                managedDocument.data?.document ? "단선결선도 교체 파일" : "단선결선도 등록 파일"
              }
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              type="file"
            />
          </label>
          <button className="outline-action" disabled={!file || submitting} type="submit">
            {submitting
              ? "처리 중…"
              : managedDocument.data?.document
                ? "관리 도면 교체"
                : "관리 도면 등록"}
          </button>
        </form>
        <div className="sld-extract-action">
          <div>
            <strong>Upstage OCR 설비 추출</strong>
            <span>등록된 원본에서 변압기·차단기·발전기·배터리 후보를 추출합니다.</span>
          </div>
          <button
            className="primary-action"
            disabled={!managedDocument.data?.document || submitting}
            onClick={() => void analyzeDocument()}
            type="button"
          >
            {submitting ? "처리 중…" : "설비 추출 시작"}
          </button>
        </div>
      </section>
      <p className="sld-safety-note">
        분석 결과는 점검 보조 정보입니다. 실제 결선, 보호협조, 설비 정격과 화재 원인은 도면 원본 및
        현장 확인으로 확정해야 합니다.
      </p>
      {actionError ? (
        <div className="sld-error" role="alert">
          {actionError}
        </div>
      ) : null}

      {analyses.isLoading ? <div className="sld-state">분석 이력을 불러오는 중입니다.</div> : null}
      {analyses.isError ? (
        <div className="sld-state error">
          분석 이력을 불러오지 못했습니다.
          <button onClick={() => void analyses.refetch()} type="button">
            다시 시도
          </button>
        </div>
      ) : null}
      {!analyses.isLoading && !analyses.isError && analyses.data?.items.length === 0 ? (
        <div className="sld-state">등록된 단선결선도 분석이 없습니다.</div>
      ) : null}

      {analyses.data && analyses.data.items.length > 0 ? (
        <div className="sld-workspace">
          <aside className="sld-history" aria-label="단선결선도 분석 이력">
            {analyses.data.items.map((item) => (
              <button
                className={item.analysisId === selected?.analysisId ? "is-active" : ""}
                key={item.analysisId}
                onClick={() => setSelectedId(item.analysisId)}
                type="button"
              >
                <strong>{item.sourceFileName}</strong>
                <span>{statusNames[item.status]}</span>
                <small>{new Date(item.createdAt).toLocaleString("ko-KR")}</small>
              </button>
            ))}
          </aside>

          {selected ? (
            <article className="sld-result">
              <header>
                <div>
                  <span className={`sld-status ${selected.status.toLowerCase()}`}>
                    {statusNames[selected.status]}
                  </span>
                  <h3>{selected.sourceFileName}</h3>
                  <p>
                    {selected.ocrModel} · {selected.grammarVersion}
                  </p>
                </div>
                <a
                  className="outline-action"
                  href={`${runtime.apiBase}/sld-analyses/${selected.analysisId}/source`}
                  rel="noreferrer"
                  target="_blank"
                >
                  원본 보기
                </a>
              </header>

              {selected.status === "QUEUED" || selected.status === "RUNNING" ? (
                <div className="sld-progress" role="status">
                  <i />
                  <strong>Upstage OCR과 설비 문법 분석을 실행하고 있습니다.</strong>
                  <span>페이지 수와 도면 복잡도에 따라 수 분이 걸릴 수 있습니다.</span>
                </div>
              ) : null}
              {selected.status === "FAILED" ? (
                <div className="sld-error" role="alert">
                  <strong>{selected.error?.code ?? "SLD_ANALYSIS_FAILED"}</strong>
                  <span>{selected.error?.message ?? "분석에 실패했습니다."}</span>
                  <button disabled={submitting} onClick={() => void retry()} type="button">
                    다시 분석
                  </button>
                </div>
              ) : null}
              {selected.result ? (
                <SldResultView analysis={selected} key={selected.analysisId} runtime={runtime} />
              ) : null}
            </article>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function SldResultView({ analysis, runtime }: { analysis: SldAnalysis; runtime: ProfileRuntime }) {
  const result = analysis.result;
  const [selectedPage, setSelectedPage] = useState(result?.pages[0]?.page ?? 1);
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const [diagramZoom, setDiagramZoom] = useState(1);
  const [isDiagramDragging, setIsDiagramDragging] = useState(false);
  const diagramZoomRef = useRef(1);
  const diagramViewportRef = useRef<HTMLElement>(null);
  const diagramDragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    scrollLeft: number;
    scrollTop: number;
  } | null>(null);
  if (!result) return null;
  const explanationById = new Map(
    result.explanation.keyEquipment.map((item) => [item.equipmentId, item]),
  );
  const groups = buildEquipmentGroups(result.equipment, explanationById);
  const groupById = new Map(groups.map((group) => [group.groupId, group]));
  const page =
    result.pages.find((candidate) => candidate.page === selectedPage) ?? result.pages[0] ?? null;
  const pageEquipment = page
    ? result.equipment.filter(
        (equipment) => equipment.page === page.page && validBbox(equipment.bbox),
      )
    : [];

  function focusGroup(groupId: string, pageNumber?: number) {
    setActiveGroupId(groupId);
    if (pageNumber !== undefined) setSelectedPage(pageNumber);
    const group = groupById.get(groupId);
    window.requestAnimationFrame(() => {
      const target = group ? document.getElementById(group.anchorId) : null;
      target?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      target?.focus({ preventScroll: true });
    });
  }

  function changeDiagramZoom(nextValue: number, focus?: { x: number; y: number }) {
    const viewport = diagramViewportRef.current;
    const previous = diagramZoomRef.current;
    const next = Math.min(5, Math.max(0.5, Math.round(nextValue * 100) / 100));
    if (next === previous) return;
    const focusX = focus?.x ?? (viewport?.clientWidth ?? 0) / 2;
    const focusY = focus?.y ?? (viewport?.clientHeight ?? 0) / 2;
    diagramZoomRef.current = next;
    setDiagramZoom(next);
    if (!viewport) return;
    window.requestAnimationFrame(() => {
      const ratio = next / previous;
      viewport.scrollLeft = (viewport.scrollLeft + focusX) * ratio - focusX;
      viewport.scrollTop = (viewport.scrollTop + focusY) * ratio - focusY;
    });
  }

  function resetDiagramZoom() {
    diagramZoomRef.current = 1;
    setDiagramZoom(1);
    window.requestAnimationFrame(() => {
      if (!diagramViewportRef.current) return;
      diagramViewportRef.current.scrollLeft = 0;
      diagramViewportRef.current.scrollTop = 0;
    });
  }

  function handleDiagramWheel(event: WheelEvent<HTMLDivElement>) {
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
    changeDiagramZoom(diagramZoomRef.current * factor, {
      x: event.clientX - bounds.left,
      y: event.clientY - bounds.top,
    });
  }

  function startDiagramDrag(event: PointerEvent<HTMLElement>) {
    if (event.button !== 0 || (event.target as HTMLElement).closest?.("button")) return;
    const viewport = diagramViewportRef.current;
    if (!viewport) return;
    diagramDragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.setPointerCapture?.(event.pointerId);
    setIsDiagramDragging(true);
    event.preventDefault();
  }

  function moveDiagramDrag(event: PointerEvent<HTMLElement>) {
    const drag = diagramDragRef.current;
    const viewport = diagramViewportRef.current;
    if (!drag || !viewport || drag.pointerId !== event.pointerId) return;
    viewport.scrollLeft = drag.scrollLeft - (event.clientX - drag.startX);
    viewport.scrollTop = drag.scrollTop - (event.clientY - drag.startY);
    event.preventDefault();
  }

  function stopDiagramDrag(event: PointerEvent<HTMLElement>) {
    const drag = diagramDragRef.current;
    const viewport = diagramViewportRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    viewport?.releasePointerCapture?.(event.pointerId);
    diagramDragRef.current = null;
    setIsDiagramDragging(false);
  }

  return (
    <>
      <div className="sld-summary-metrics">
        <div>
          <span>페이지</span>
          <strong>{result.pages.length}</strong>
        </div>
        <div>
          <span>OCR 항목</span>
          <strong>{result.ocrItemCount.toLocaleString("ko-KR")}</strong>
        </div>
        <div>
          <span>설비 후보</span>
          <strong>{result.equipmentCount.toLocaleString("ko-KR")}</strong>
        </div>
        <div>
          <span>설명 상태</span>
          <strong>{result.explanationStatus === "SUCCEEDED" ? "완료" : "검토 필요"}</strong>
        </div>
      </div>
      <section className="sld-overview">
        <h4>도면 요약</h4>
        <p>{result.explanation.overview}</p>
        <div>
          <ul>
            {result.explanation.facilitySummary.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <ul className="risk">
            {result.explanation.fireRiskSummary.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </section>
      {page ? (
        <section className="sld-diagram-viewer" aria-labelledby="sld-diagram-viewer-title">
          <div className="sld-section-heading">
            <div>
              <h4 id="sld-diagram-viewer-title">도면 설비 추출 위치</h4>
              <span>
                확대 Crop 결과를 원본 도면 한 장에 합성했습니다. 파란 박스를 누르면 해당 설비군
                설명으로 이동합니다.
              </span>
            </div>
            <strong>
              {pageEquipment.length.toLocaleString("ko-KR")}개 위치
              {result.boxPipeline
                ? ` · ${result.boxPipeline.ocrCropCount.toLocaleString("ko-KR")}개 확대 Crop`
                : ""}
            </strong>
          </div>
          {result.pages.length > 1 ? (
            <nav className="sld-page-tabs" aria-label="도면 페이지 선택">
              {result.pages.map((item) => (
                <button
                  aria-current={item.page === page.page ? "page" : undefined}
                  className={item.page === page.page ? "is-active" : ""}
                  key={item.page}
                  onClick={() => {
                    setSelectedPage(item.page);
                    resetDiagramZoom();
                  }}
                  type="button"
                >
                  {item.page}쪽
                </button>
              ))}
            </nav>
          ) : null}
          <div className="sld-diagram-toolbar">
            <span>마우스 휠로 확대·축소 · 빈 도면을 드래그해 이동</span>
            <fieldset className="sld-diagram-zoom-controls">
              <legend className="sr-only">결선도 확대·축소 제어</legend>
              <button
                aria-label="결선도 축소"
                disabled={diagramZoom <= 0.5}
                onClick={() => changeDiagramZoom(diagramZoomRef.current - 0.25)}
                type="button"
              >
                −
              </button>
              <output aria-live="polite">{Math.round(diagramZoom * 100)}%</output>
              <button
                aria-label="결선도 확대"
                disabled={diagramZoom >= 5}
                onClick={() => changeDiagramZoom(diagramZoomRef.current + 0.25)}
                type="button"
              >
                +
              </button>
              <button onClick={resetDiagramZoom} type="button">
                맞춤
              </button>
            </fieldset>
          </div>
          <section
            aria-label="결선도 확대·축소 영역"
            className={`sld-diagram-viewport${isDiagramDragging ? " is-dragging" : ""}`}
            onPointerCancel={stopDiagramDrag}
            onPointerDown={startDiagramDrag}
            onPointerMove={moveDiagramDrag}
            onPointerUp={stopDiagramDrag}
            onWheel={handleDiagramWheel}
            ref={diagramViewportRef}
          >
            <div
              className="sld-diagram-canvas"
              style={{
                aspectRatio: `${page.width} / ${page.height}`,
                width: `${Math.round(diagramZoom * 100)}%`,
              }}
            >
              <img
                alt={`${analysis.sourceFileName} ${page.page}쪽 설비 추출 도면`}
                draggable={false}
                src={`${runtime.apiBase}/sld-analyses/${analysis.analysisId}/pages/${page.page}/preview`}
              />
              <div className="sld-diagram-overlay">
                {pageEquipment.map((equipment) => {
                  const bbox = equipment.bbox as [number, number, number, number];
                  const groupId = equipmentGroupId(equipment);
                  const group = groupById.get(groupId);
                  const left = Math.min(100, Math.max(0, (bbox[0] / page.width) * 100));
                  const top = Math.min(100, Math.max(0, (bbox[1] / page.height) * 100));
                  const width = Math.min(100 - left, (bbox[2] / page.width) * 100);
                  const height = Math.min(100 - top, (bbox[3] / page.height) * 100);
                  return (
                    <button
                      aria-label={`${equipment.displayName} 위치 - ${group?.label ?? "설비군"} 설명으로 이동`}
                      className={activeGroupId === groupId ? "is-active" : ""}
                      key={equipment.equipmentId}
                      onClick={() => focusGroup(groupId, equipment.page)}
                      style={{
                        height: `${height}%`,
                        left: `${left}%`,
                        top: `${top}%`,
                        width: `${width}%`,
                      }}
                      title={`${equipment.displayName} · ${equipment.rawText}`}
                      type="button"
                    >
                      <span>{group?.label ?? equipment.displayName}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </section>
          <p className="sld-diagram-help">
            박스는 Upstage OCR의 인식 좌표입니다. 선택한 설비군은 도면과 아래 설명에서 함께
            강조됩니다.
          </p>
        </section>
      ) : null}
      <section className="sld-equipment-list">
        <div className="sld-section-heading">
          <div>
            <h4>설비군별 설명 및 화재 위험 점검</h4>
            <span>같은 역할의 설비를 묶어 OCR 근거와 점검사항을 설명합니다.</span>
          </div>
          <strong>{groups.length.toLocaleString("ko-KR")}개 설비군</strong>
        </div>
        {result.equipment.length === 0 ? (
          <div className="sld-state">
            문법으로 식별된 설비 후보가 없습니다. OCR 원문을 확인하세요.
          </div>
        ) : (
          groups.map((group) => {
            const pages = uniqueStrings(group.equipment.map((equipment) => `${equipment.page}쪽`));
            return (
              <article
                className={`sld-equipment-card sld-equipment-group-card${
                  activeGroupId === group.groupId ? " is-active" : ""
                }`}
                id={group.anchorId}
                key={group.groupId}
                tabIndex={-1}
              >
                <header>
                  <div>
                    <span>{group.groupId}</span>
                    <h5>{group.label}</h5>
                  </div>
                  <strong>
                    {group.equipment.length.toLocaleString("ko-KR")}개 설비 · {pages.join(", ")}
                  </strong>
                </header>
                <div className="sld-group-members">
                  {group.equipment.map((equipment) => (
                    <button
                      key={equipment.equipmentId}
                      onClick={() => {
                        setActiveGroupId(group.groupId);
                        setSelectedPage(equipment.page);
                      }}
                      type="button"
                    >
                      <strong>{equipment.displayName}</strong>
                      <span>{equipment.rawText}</span>
                      <small>
                        {equipment.page}쪽 위치 보기
                        {equipment.cropId ? ` · ${equipment.cropId}` : ""}
                      </small>
                    </button>
                  ))}
                </div>
                {group.observedFacts.length > 0 ? (
                  <details className="sld-group-evidence">
                    <summary>OCR 근거 및 추출 속성</summary>
                    <ul>
                      {group.observedFacts.slice(0, 12).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                    {group.equipment.map((equipment) =>
                      simpleProperties(equipment.properties).length > 0 ? (
                        <dl key={equipment.equipmentId}>
                          {simpleProperties(equipment.properties).map(([key, value]) => (
                            <div key={key}>
                              <dt>{key}</dt>
                              <dd>{String(value)}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : null,
                    )}
                  </details>
                ) : null}
                {group.fireRiskFactors.length > 0 || group.inspectionPoints.length > 0 ? (
                  <div className="sld-equipment-explanation">
                    <p>{group.label} 공통 설명</p>
                    <div>
                      <section>
                        <h6>일반 화재 위험요인</h6>
                        <ul>
                          {group.fireRiskFactors.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </section>
                      <section>
                        <h6>현장 점검사항</h6>
                        <ul>
                          {group.inspectionPoints.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </section>
                    </div>
                    {group.warnings.map((warning) => (
                      <small key={warning}>{warning}</small>
                    ))}
                  </div>
                ) : null}
              </article>
            );
          })
        )}
      </section>
      <section className="sld-limitations">
        <h4>판독 한계</h4>
        <ul>
          {result.explanation.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>
    </>
  );
}
