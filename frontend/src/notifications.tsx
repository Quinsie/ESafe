import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ApiError, apiRequest } from "./api";
import { formatKst } from "./home";
import type { ProfileRuntime } from "./profile";
import { AppLink } from "./router";
import "./notifications.css";

type NotificationKind = "APPROVAL" | "RISK" | "AUTOMATION";

interface ApprovalData {
  items: Array<{
    approvalRequestId: string;
    caseNumber: string | null;
    caseTitle: string | null;
    title: string;
    status: string;
    requestedAt: string;
    version: number;
  }>;
}

interface CaseData {
  items: Array<{
    caseId: string;
    caseNumber: string;
    title: string;
    status: string;
    sourceStatus: string;
    monitoringPriority: string;
    impactBuildingCount: number;
    highRiskBuildingCount: number;
    updatedAt: string;
    version: number;
  }>;
}

interface AutomationData {
  items: Array<{
    entryId: string;
    entryType: string;
    status: string;
    category: string;
    source: string | null;
    occurredAt: string;
    case: { caseId: string; caseNumber: string | null } | null;
  }>;
}

interface NotificationItem {
  id: string;
  kind: NotificationKind;
  badge: string;
  title: string;
  summary: string;
  occurredAt: string;
  to: string;
  action: string;
}

const kindLabels: Record<NotificationKind, string> = {
  APPROVAL: "승인 대기",
  RISK: "위험·재난",
  AUTOMATION: "자동화 완료",
};

function storageKey(runtime: ProfileRuntime) {
  return `esafe-notifications-read-${runtime.profile.toLowerCase()}`;
}

function initialRead(runtime: ProfileRuntime): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey(runtime)) ?? "[]");
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

function queryError(error: unknown) {
  return error instanceof ApiError ? error.message : "알림 원천을 불러오지 못했습니다.";
}

export function NotificationCenter({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const approvals = useQuery({
    queryKey: ["notifications-approvals", runtime.profile],
    queryFn: () =>
      apiRequest<ApprovalData>(runtime, "/approvals?pageSize=50").then((result) => result.data),
    staleTime: 15_000,
  });
  const cases = useQuery({
    queryKey: ["notifications-cases", runtime.profile],
    queryFn: () =>
      apiRequest<CaseData>(runtime, "/cases?page=1&pageSize=50&sort=updated").then(
        (result) => result.data,
      ),
    staleTime: 15_000,
  });
  const automation = useQuery({
    queryKey: ["notifications-automation", runtime.profile],
    queryFn: () =>
      apiRequest<AutomationData>(runtime, "/automation/runs?page=1&pageSize=50&hours=24").then(
        (result) => result.data,
      ),
    staleTime: 15_000,
  });
  const items = useMemo<NotificationItem[]>(() => {
    const approvalItems = (approvals.data?.items ?? [])
      .filter((item) => item.status === "APPROVAL_PENDING")
      .map((item) => ({
        id: `approval:${item.approvalRequestId}:v${item.version}`,
        kind: "APPROVAL" as const,
        badge: "사용자 확인 필요",
        title: item.title,
        summary: item.caseNumber
          ? `${item.caseNumber} · ${item.caseTitle ?? "연결 Case"}`
          : "Case 없이 생성된 승인 요청",
        occurredAt: item.requestedAt,
        to: `/approvals/${item.approvalRequestId}`,
        action: "승인 설명 열기",
      }));
    const caseItems = (cases.data?.items ?? [])
      .filter(
        (item) =>
          item.status !== "CLOSED" &&
          (item.monitoringPriority !== "NORMAL" || item.sourceStatus !== "ACTIVE"),
      )
      .map((item) => ({
        id: `case:${item.caseId}:v${item.version}`,
        kind: "RISK" as const,
        badge:
          item.sourceStatus === "RESOLVED"
            ? "원천 종료 확인"
            : item.monitoringPriority === "URGENT"
              ? "긴급 확인"
              : "상황 확인",
        title: `${item.caseNumber} · ${item.title}`,
        summary: `영향 ${item.impactBuildingCount.toLocaleString()}개소 · 상위 10% ${item.highRiskBuildingCount.toLocaleString()}개소 · ${item.status}`,
        occurredAt: item.updatedAt,
        to: `/cases/${item.caseId}`,
        action: "Case 상황판 열기",
      }));
    const automationItems = (automation.data?.items ?? [])
      .filter((item) => item.entryType === "AUTOMATION_RUN" && item.status === "SUCCEEDED")
      .slice(0, 20)
      .map((item) => ({
        id: `automation:${item.entryId}`,
        kind: "AUTOMATION" as const,
        badge: "백그라운드 작업 완료",
        title: `${item.category} 작업 완료`,
        summary: `${item.source ?? "내부 자동화"}${item.case?.caseNumber ? ` · ${item.case.caseNumber}` : ""}`,
        occurredAt: item.occurredAt,
        to: `/automation/runs?selected=${item.entryId}`,
        action: "자동화 기록 열기",
      }));
    return [...approvalItems, ...caseItems, ...automationItems].sort(
      (left, right) => Date.parse(right.occurredAt) - Date.parse(left.occurredAt),
    );
  }, [approvals.data, automation.data, cases.data]);
  const [readIds, setReadIds] = useState<string[]>(() => initialRead(runtime));
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("id"),
  );
  const read = new Set(readIds);
  const selected = items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  const unread = items.filter((item) => !read.has(item.id)).length;
  const setRead = (next: string[]) => {
    const bounded = [...new Set(next)].slice(-500);
    setReadIds(bounded);
    localStorage.setItem(storageKey(runtime), JSON.stringify(bounded));
  };
  const select = (item: NotificationItem) => {
    setSelectedId(item.id);
    if (!read.has(item.id)) setRead([...readIds, item.id]);
  };
  const errors = [approvals, cases, automation].filter((query) => query.isError);
  return (
    <main className="page notifications-page" id="main-content">
      <div className="page-heading notification-heading">
        <div>
          <p className="eyebrow">공통 / COM-01B</p>
          <h1>알림 센터</h1>
          <p>승인 요청, 위험·재난 Case와 최근 자동화 완료를 실제 업무 기록에서 확인합니다.</p>
        </div>
        <div className="notification-heading-actions">
          <span className="notification-unread">읽지 않음 {unread}</span>
          <button
            disabled={!unread}
            onClick={() => setRead(items.map((item) => item.id))}
            type="button"
          >
            모두 읽음 처리
          </button>
        </div>
      </div>
      {errors.length ? (
        <div className="panel-error" role="alert">
          {errors.map((query) => queryError(query.error)).join(" · ")}
        </div>
      ) : null}
      <section className="panel notification-summary">
        {(Object.keys(kindLabels) as NotificationKind[]).map((kind) => (
          <div key={kind}>
            <span className={`notification-kind ${kind.toLowerCase()}`}>{kindLabels[kind]}</span>
            <strong>{items.filter((item) => item.kind === kind).length}건</strong>
          </div>
        ))}
        <small>마지막 동기화 {formatKst(new Date().toISOString())}</small>
      </section>
      <div className="notification-layout">
        <div className="notification-columns">
          {(Object.keys(kindLabels) as NotificationKind[]).map((kind) => {
            const grouped = items.filter((item) => item.kind === kind);
            return (
              <section className={`panel notification-column ${kind.toLowerCase()}`} key={kind}>
                <div className="notification-column-heading">
                  <h2>{kindLabels[kind]}</h2>
                  <span>{grouped.length}건</span>
                </div>
                {grouped.length ? (
                  <ol>
                    {grouped.map((item) => (
                      <li
                        className={`${selected?.id === item.id ? "selected" : ""} ${read.has(item.id) ? "read" : "unread"}`}
                        key={item.id}
                      >
                        <button onClick={() => select(item)} type="button">
                          <span>{item.badge}</span>
                          <strong>{item.title}</strong>
                          <small>{item.summary}</small>
                          <time>{formatKst(item.occurredAt)}</time>
                        </button>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="notification-empty">현재 해당 알림이 없습니다.</p>
                )}
              </section>
            );
          })}
        </div>
        <aside className="panel notification-detail">
          <h2>선택한 알림 상세</h2>
          {selected ? (
            <>
              <span className={`notification-kind ${selected.kind.toLowerCase()}`}>
                {selected.badge}
              </span>
              <h3>{selected.title}</h3>
              <p>{selected.summary}</p>
              <dl>
                <div>
                  <dt>유형</dt>
                  <dd>{kindLabels[selected.kind]}</dd>
                </div>
                <div>
                  <dt>기록 시각</dt>
                  <dd>{formatKst(selected.occurredAt)}</dd>
                </div>
                <div>
                  <dt>읽음 상태</dt>
                  <dd>{read.has(selected.id) ? "읽음" : "읽지 않음"}</dd>
                </div>
              </dl>
              <AppLink
                className="primary-action"
                currentPath={currentPath}
                runtime={runtime}
                to={selected.to}
              >
                {selected.action}
              </AppLink>
              <p className="notification-truth-note">
                이 알림은 기존 업무 기록을 요약하며 위험점수 상승이나 실행 결과를 새로 추정하지
                않습니다.
              </p>
            </>
          ) : (
            <p className="notification-empty">표시할 실제 알림이 없습니다.</p>
          )}
        </aside>
      </div>
    </main>
  );
}
