import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, apiRequest } from "./api";
import type { ProfileRuntime } from "./profile";

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

export function DemoScenarioPanel({ runtime }: { runtime: ProfileRuntime }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const catalog = useQuery({
    queryKey: ["demo-scenarios", runtime.profile],
    queryFn: () => apiRequest<DemoCatalog>(runtime, "/demo/scenarios"),
    enabled: runtime.profile === "DEMO",
    staleTime: 10_000,
  });
  const scenarios = catalog.data?.data.items ?? [];
  const activeScenario = scenarios.find((item) =>
    item.playback ? ["READY", "RUNNING", "PAUSED"].includes(item.playback.status) : false,
  );

  useEffect(() => {
    if (scenarios.length === 0) return;
    const selectedExists = scenarios.some((item) => item.scenarioId === selectedId);
    if (selectedExists) return;
    setSelectedId((activeScenario ?? scenarios[0]).scenarioId);
  }, [activeScenario, scenarios, selectedId]);

  const selected = scenarios.find((item) => item.scenarioId === selectedId) ?? scenarios[0];
  const mutation = useMutation({
    mutationFn: async ({ scenario, command }: { scenario: DemoScenario; command: Command }) => {
      const playback = scenario.playback;
      const body =
        command === "start"
          ? { expectedVersion: playback?.version ?? null }
          : command === "reset"
            ? { expectedVersion: playback?.version, confirmed: true }
            : { expectedVersion: playback?.version };
      return apiRequest(runtime, `/demo/scenarios/${scenario.scenarioId}/${command}`, {
        method: "POST",
        headers: { "Idempotency-Key": commandKey(command) },
        body: JSON.stringify(body),
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["demo-scenarios", runtime.profile] }),
        queryClient.invalidateQueries({ queryKey: ["home-briefing", runtime.profile] }),
        queryClient.invalidateQueries({ queryKey: ["source-health", runtime.profile] }),
        queryClient.invalidateQueries({ queryKey: ["task-summary", runtime.profile] }),
        queryClient.invalidateQueries({ queryKey: ["cases", runtime.profile] }),
      ]);
    },
  });

  if (runtime.profile !== "DEMO") return null;
  if (catalog.isLoading) {
    return <section className="demo-scenario-panel">체험 시나리오를 불러오고 있습니다.</section>;
  }
  if (!catalog.isSuccess || !selected) {
    return (
      <section className="demo-scenario-panel error" role="alert">
        체험 시나리오를 불러오지 못했습니다.
      </section>
    );
  }

  const playback = selected.playback;
  const currentStep = playback?.currentStep ?? 0;
  const nextStep = selected.steps[currentStep];
  const busy = mutation.isPending;
  const errorMessage =
    mutation.error instanceof ApiError
      ? mutation.error.message
      : mutation.isError
        ? "시나리오 명령을 처리하지 못했습니다."
        : null;

  const run = (command: Command) => {
    if (busy) return;
    const target = command === "reset" && activeScenario ? activeScenario : selected;
    if (
      command === "reset" &&
      !window.confirm(`${target.code} 체험 Case·업무·문서 초안을 지우고 처음부터 초기화할까요?`)
    ) {
      return;
    }
    mutation.mutate({ scenario: target, command });
  };

  return (
    <section className="demo-scenario-panel" aria-label="체험 시나리오 제어">
      <div className="demo-scenario-heading">
        <div>
          <span className="status-pill neutral">체험 데이터</span>
          <h2>실시간 상황 시나리오</h2>
          <p>외부 호출 없이 원천 응답부터 한 단계씩 실제 처리 경로를 재생합니다.</p>
        </div>
        <label>
          시나리오
          <select
            disabled={busy || playback?.status === "RUNNING"}
            onChange={(event) => setSelectedId(event.target.value)}
            value={selected.scenarioId}
          >
            {scenarios.map((scenario) => (
              <option key={scenario.scenarioId} value={scenario.scenarioId}>
                {scenario.code} · {scenario.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {activeScenario && activeScenario.scenarioId !== selected.scenarioId ? (
        <div className="demo-active-notice" role="status">
          <strong>{activeScenario.code} 시나리오가 초기화 대기 또는 실행 중입니다.</strong>
          <span>아래 초기화 버튼은 현재 활성 시나리오를 정리합니다.</span>
        </div>
      ) : null}
      <div className="demo-scenario-body">
        <div>
          <strong>{selected.name}</strong>
          <p>{selected.description}</p>
          <span>
            {playback ? statusNames[playback.status] : "시작 전"} · 단계 {currentStep}/
            {selected.stepCount} · 세대 {playback?.generation ?? 0}
          </span>
        </div>
        <div className="demo-next-step">
          <span>{nextStep ? "다음 단계" : "재생 결과"}</span>
          <strong>{nextStep?.label ?? "모든 단계가 완료되었습니다."}</strong>
          {nextStep ? <small>{sourceNames[nextStep.source]} 원천시각 보존</small> : null}
        </div>
        <div className="demo-controls">
          <button
            disabled={busy || playback?.status === "RUNNING" || playback?.status === "COMPLETED"}
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
          <button
            className="danger-action"
            disabled={busy || (!activeScenario && !playback)}
            onClick={() => run("reset")}
            type="button"
          >
            {activeScenario && activeScenario.scenarioId !== selected.scenarioId
              ? `${activeScenario.code} 처음부터 초기화`
              : "처음부터 초기화"}
          </button>
        </div>
      </div>
      {errorMessage ? (
        <div className="auth-error" role="alert">
          {errorMessage}
        </div>
      ) : null}
    </section>
  );
}
