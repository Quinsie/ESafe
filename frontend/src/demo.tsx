import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, apiRequest } from "./api";
import type { ProfileRuntime } from "./profile";
import { AppLink } from "./router";

interface DemoStep {
  ordinal: number;
  label: string;
  source: "NFDS" | "KMA_WARNING" | "DISASTER_MESSAGE";
  sourceTime: string;
  kind: "FIXTURE" | "SOURCE_STATE";
}

interface DemoPlayback {
  playbackId: string;
  status: "READY" | "RUNNING" | "PAUSED" | "COMPLETED";
  currentStep: number;
  stepCount: number;
  generation: number;
  version: number;
  updatedAt: string;
}

interface DemoScenario {
  scenarioId: string;
  code: string;
  name: string;
  description: string;
  scenarioVersion: number;
  stepCount: number;
  steps: DemoStep[];
  playback: DemoPlayback | null;
}

interface DemoCatalog {
  items: DemoScenario[];
}

type Command = "start" | "pause" | "next" | "reset";

const activeStatuses = new Set<DemoPlayback["status"]>(["READY", "RUNNING", "PAUSED"]);

const statusNames: Record<DemoPlayback["status"], string> = {
  READY: "처음부터 시작 대기",
  RUNNING: "재생 중",
  PAUSED: "일시정지",
  COMPLETED: "완료",
};

const sourceNames = {
  NFDS: "전국119상황실",
  KMA_WARNING: "기상특보",
  DISASTER_MESSAGE: "재난문자",
} as const;

function commandKey(command: Command): string {
  return `demo-${command}-${crypto.randomUUID()}`;
}

function formatSourceTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul",
  }).format(date);
}

function useDemoController(runtime: ProfileRuntime) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const catalog = useQuery({
    queryKey: ["demo-scenarios", runtime.profile],
    queryFn: () => apiRequest<DemoCatalog>(runtime, "/demo/scenarios"),
    enabled: runtime.profile === "DEMO",
    staleTime: 10_000,
  });
  const scenarios = catalog.data?.data.items ?? [];
  const activeScenario = scenarios.find(
    (item) => item.playback && activeStatuses.has(item.playback.status),
  );

  useEffect(() => {
    if (scenarios.length === 0) return;
    const selectedExists = scenarios.some((item) => item.scenarioId === selectedId);
    if (!selectedExists) {
      setSelectedId((activeScenario ?? scenarios[0]).scenarioId);
    }
  }, [activeScenario, scenarios, selectedId]);

  const selected = scenarios.find((item) => item.scenarioId === selectedId) ?? scenarios[0];
  const mutation = useMutation({
    mutationFn: async ({ scenario, command }: { scenario: DemoScenario; command: Command }) => {
      const playback = scenario.playback;
      const body =
        command === "start"
          ? { expectedVersion: playback?.version ?? null }
          : command === "reset"
            ? {
                expectedVersion: playback?.version ?? null,
                activeExpectedVersion: activeScenario?.playback?.version ?? null,
                confirmed: true,
              }
            : { expectedVersion: playback?.version };
      return apiRequest(runtime, `/demo/scenarios/${scenario.scenarioId}/${command}`, {
        method: "POST",
        headers: { "Idempotency-Key": commandKey(command) },
        body: JSON.stringify(body),
      });
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["demo-scenarios", runtime.profile] }),
        queryClient.invalidateQueries({ queryKey: ["home-briefing", runtime.profile] }),
        queryClient.invalidateQueries({ queryKey: ["source-health", runtime.profile] }),
        queryClient.invalidateQueries({ queryKey: ["task-summary", runtime.profile] }),
        queryClient.invalidateQueries({ queryKey: ["cases", runtime.profile] }),
      ]);
    },
  });

  const run = (command: Command) => {
    if (!selected || mutation.isPending) return;
    if (command === "reset") {
      const replacement =
        activeScenario && activeScenario.scenarioId !== selected.scenarioId
          ? ` 현재 ${activeScenario.code} 체험 데이터는 정리됩니다.`
          : "";
      if (
        !window.confirm(
          `${selected.code}을(를) 처음부터 시작할 준비 상태로 만들까요?${replacement}`,
        )
      ) {
        return;
      }
    }
    mutation.mutate({ scenario: selected, command });
  };

  return {
    activeScenario,
    catalog,
    mutation,
    run,
    scenarios,
    selected,
    selectedId,
    setSelectedId,
  };
}

function commandError(error: unknown, failed: boolean): string | null {
  if (error instanceof ApiError) return error.message;
  return failed ? "시나리오 명령을 처리하지 못했습니다." : null;
}

function ScenarioControls({
  activeScenario,
  busy,
  compact = false,
  run,
  selected,
}: {
  activeScenario: DemoScenario | undefined;
  busy: boolean;
  compact?: boolean;
  run: (command: Command) => void;
  selected: DemoScenario;
}) {
  const playback = selected.playback;
  const currentStep = playback?.currentStep ?? 0;
  const nextStep = selected.steps[currentStep];
  const anotherActive = Boolean(
    activeScenario && activeScenario.scenarioId !== selected.scenarioId,
  );
  return (
    <div className={`demo-controls${compact ? " compact" : ""}`}>
      <button
        disabled={
          busy ||
          anotherActive ||
          playback?.status === "RUNNING" ||
          playback?.status === "COMPLETED"
        }
        onClick={() => run("start")}
        type="button"
      >
        {playback?.status === "PAUSED" ? "재개" : "시작"}
      </button>
      <button
        disabled={busy || playback?.status !== "RUNNING"}
        onClick={() => run("pause")}
        type="button"
      >
        일시정지
      </button>
      <button
        className="primary-action"
        disabled={busy || playback?.status !== "RUNNING" || !nextStep}
        onClick={() => run("next")}
        type="button"
      >
        다음 단계
      </button>
      <button className="danger-action" disabled={busy} onClick={() => run("reset")} type="button">
        초기화
      </button>
    </div>
  );
}

export function DemoRemoteControl({
  currentPath,
  runtime,
}: {
  currentPath: string;
  runtime: ProfileRuntime;
}) {
  const controller = useDemoController(runtime);
  const [open, setOpen] = useState(false);
  if (runtime.profile !== "DEMO") return null;

  const { activeScenario, catalog, mutation, run, scenarios, selected, setSelectedId } = controller;
  if (catalog.isLoading) {
    return <div className="demo-remote loading">체험 리모컨을 준비하고 있습니다.</div>;
  }
  if (!catalog.isSuccess || !selected) {
    return <div className="demo-remote error">시나리오를 불러오지 못했습니다.</div>;
  }
  const playback = selected.playback;
  const anotherActive =
    activeScenario && activeScenario.scenarioId !== selected.scenarioId
      ? activeScenario
      : undefined;
  const errorMessage = commandError(mutation.error, mutation.isError);

  return (
    <section className="demo-remote" aria-label="체험 시나리오 리모컨">
      <div className="demo-remote-heading">
        <span>체험 리모컨</span>
        <strong>
          {playback ? statusNames[playback.status] : "시작 전"} · {playback?.currentStep ?? 0}/
          {selected.stepCount}
        </strong>
      </div>
      <div className="demo-remote-select">
        <button
          aria-expanded={open}
          className="demo-scenario-trigger"
          onClick={() => setOpen((value) => !value)}
          type="button"
        >
          <span>
            {selected.code} · {selected.name}
          </span>
          <b aria-hidden="true">{open ? "▲" : "▼"}</b>
        </button>
        {open ? (
          <div className="demo-scenario-options" role="listbox" aria-label="시나리오 선택">
            {scenarios.map((scenario) => (
              <button
                aria-label={`${scenario.code} ${scenario.name}`}
                aria-selected={scenario.scenarioId === selected.scenarioId}
                key={scenario.scenarioId}
                onClick={() => {
                  setSelectedId(scenario.scenarioId);
                  setOpen(false);
                }}
                role="option"
                type="button"
              >
                <strong>{scenario.code}</strong>
                <span>{scenario.name}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {anotherActive ? (
        <p className="demo-remote-notice">
          {anotherActive.code} 진행 중 · 초기화하면 선택 시나리오로 전환합니다.
        </p>
      ) : null}
      <ScenarioControls
        activeScenario={activeScenario}
        busy={mutation.isPending}
        compact
        run={run}
        selected={selected}
      />
      {errorMessage ? (
        <p className="demo-remote-error" role="alert">
          {errorMessage}
        </p>
      ) : null}
      <AppLink
        className="demo-remote-detail"
        currentPath={currentPath}
        runtime={runtime}
        to="/demo-scenarios"
      >
        시나리오 상세 보기
      </AppLink>
    </section>
  );
}

export function DemoScenarioPage({ runtime }: { runtime: ProfileRuntime }) {
  const controller = useDemoController(runtime);
  const { activeScenario, catalog, mutation, run, scenarios, selected, setSelectedId } = controller;
  if (catalog.isLoading) {
    return (
      <main className="page demo-scenario-page" id="main-content">
        <div className="auth-loading" role="status">
          체험 시나리오를 불러오고 있습니다.
        </div>
      </main>
    );
  }
  if (!catalog.isSuccess || !selected) {
    return (
      <main className="page demo-scenario-page" id="main-content">
        <section className="panel demo-scenario-error" role="alert">
          체험 시나리오를 불러오지 못했습니다.
        </section>
      </main>
    );
  }

  const playback = selected.playback;
  const currentStep = playback?.currentStep ?? 0;
  const anotherActive =
    activeScenario && activeScenario.scenarioId !== selected.scenarioId
      ? activeScenario
      : undefined;
  const errorMessage = commandError(mutation.error, mutation.isError);

  return (
    <main className="page demo-scenario-page" id="main-content">
      <div className="page-heading">
        <div>
          <span className="status-pill neutral">체험 데이터 전용</span>
          <h1>체험 시나리오</h1>
          <p>통제 가능한 원천 신호를 실제 파싱·Case 처리 경로에 한 단계씩 재생합니다.</p>
        </div>
      </div>
      <div className="demo-scenario-layout">
        <aside className="panel demo-scenario-catalog" aria-label="체험 시나리오 목록">
          <h2>시나리오 선택</h2>
          <p>선택만으로 진행 중인 시나리오는 바뀌지 않습니다.</p>
          <div>
            {scenarios.map((scenario) => (
              <button
                className={scenario.scenarioId === selected.scenarioId ? "is-selected" : ""}
                key={scenario.scenarioId}
                onClick={() => setSelectedId(scenario.scenarioId)}
                type="button"
              >
                <span>{scenario.code}</span>
                <strong>{scenario.name}</strong>
                <small>
                  {scenario.playback ? statusNames[scenario.playback.status] : "시작 전"}
                </small>
              </button>
            ))}
          </div>
        </aside>
        <section className="panel demo-scenario-detail">
          <div className="demo-scenario-detail-heading">
            <div>
              <span>{selected.code}</span>
              <h2>{selected.name}</h2>
              <p>{selected.description}</p>
            </div>
            <strong className={`demo-playback-status ${playback?.status.toLowerCase() ?? "new"}`}>
              {playback ? statusNames[playback.status] : "시작 전"}
            </strong>
          </div>
          {anotherActive ? (
            <div className="demo-active-notice" role="status">
              <strong>{anotherActive.code} 시나리오가 현재 활성 상태입니다.</strong>
              <span>
                선택한 {selected.code}의 초기화를 누르면 기존 체험 데이터를 정리하고 전환합니다.
              </span>
            </div>
          ) : null}
          <div className="demo-scenario-progress">
            <span>
              진행 단계 <strong>{currentStep}</strong> / {selected.stepCount}
            </span>
            <span>세대 {playback?.generation ?? 0}</span>
          </div>
          <ol className="demo-step-list">
            {selected.steps.map((step) => {
              const state =
                step.ordinal <= currentStep
                  ? "complete"
                  : step.ordinal === currentStep + 1
                    ? "next"
                    : "waiting";
              return (
                <li className={state} key={step.ordinal}>
                  <span>{step.ordinal}</span>
                  <div>
                    <strong>{step.label}</strong>
                    <small>
                      {sourceNames[step.source]} · 체험 시각 {formatSourceTime(step.sourceTime)}
                    </small>
                  </div>
                  <b>{state === "complete" ? "완료" : state === "next" ? "다음" : "대기"}</b>
                </li>
              );
            })}
          </ol>
          <div className="demo-scenario-action-bar">
            <div>
              <strong>재생 제어</strong>
              <p>초기화는 언제든 선택 시나리오를 처음부터 시작할 준비 상태로 만듭니다.</p>
            </div>
            <ScenarioControls
              activeScenario={activeScenario}
              busy={mutation.isPending}
              run={run}
              selected={selected}
            />
          </div>
          {errorMessage ? (
            <div className="auth-error" role="alert">
              {errorMessage}
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
