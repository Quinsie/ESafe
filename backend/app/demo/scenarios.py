from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from app.signals.contracts import SignalSource


@dataclass(frozen=True, slots=True)
class ScenarioStep:
    ordinal: int
    label: str
    source: SignalSource
    source_time: datetime
    kind: Literal["FIXTURE", "SOURCE_STATE"]
    fixture_name: str | None = None
    source_state: Literal["DELAYED", "OUTAGE", "BACKOFF"] | None = None


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


SCENARIO_STEPS: Final[dict[str, tuple[ScenarioStep, ...]]] = {
    "DS-01": (
        ScenarioStep(
            1,
            "광주 건물화재 신규 감지",
            SignalSource.NFDS,
            _time("2026-07-29T10:00:00+09:00"),
            "FIXTURE",
            "ds01_nfds_active.json",
        ),
        ScenarioStep(
            2,
            "동일 화재 대응상태 갱신",
            SignalSource.NFDS,
            _time("2026-07-29T10:12:00+09:00"),
            "FIXTURE",
            "ds01_nfds_updated.json",
        ),
        ScenarioStep(
            3,
            "화재 원천 종료",
            SignalSource.NFDS,
            _time("2026-07-29T11:05:00+09:00"),
            "FIXTURE",
            "ds01_nfds_resolved.json",
        ),
    ),
    "DS-02": (
        ScenarioStep(
            1,
            "광주·전남 호우경보 발표",
            SignalSource.KMA_WARNING,
            _time("2026-07-29T09:00:00+09:00"),
            "FIXTURE",
            "ds02_kma_active.json",
        ),
        ScenarioStep(
            2,
            "영향지역 확대 변경",
            SignalSource.KMA_WARNING,
            _time("2026-07-29T09:40:00+09:00"),
            "FIXTURE",
            "ds02_kma_expanded.json",
        ),
        ScenarioStep(
            3,
            "호우주의보로 하향",
            SignalSource.KMA_WARNING,
            _time("2026-07-29T11:00:00+09:00"),
            "FIXTURE",
            "ds02_kma_downgraded.json",
        ),
        ScenarioStep(
            4,
            "기상특보 해제",
            SignalSource.KMA_WARNING,
            _time("2026-07-29T13:00:00+09:00"),
            "FIXTURE",
            "ds02_kma_resolved.json",
        ),
    ),
    "DS-03": (
        ScenarioStep(
            1,
            "포함·조건부·제외 문자 수집",
            SignalSource.DISASTER_MESSAGE,
            _time("2026-07-29T09:10:00+09:00"),
            "FIXTURE",
            "ds03_messages_page1.html",
        ),
        ScenarioStep(
            2,
            "중복과 다음 페이지 보충",
            SignalSource.DISASTER_MESSAGE,
            _time("2026-07-29T09:20:00+09:00"),
            "FIXTURE",
            "ds03_messages_page2.html",
        ),
    ),
    "DS-04": (
        ScenarioStep(
            1,
            "광주 화재 출동 감지",
            SignalSource.NFDS,
            _time("2026-07-29T14:00:00+09:00"),
            "FIXTURE",
            "ds04_nfds_fire.json",
        ),
        ScenarioStep(
            2,
            "동시간대 재난문자 후보 수집",
            SignalSource.DISASTER_MESSAGE,
            _time("2026-07-29T14:20:00+09:00"),
            "FIXTURE",
            "ds04_message_related.html",
        ),
        ScenarioStep(
            3,
            "원천 화재 상태 갱신",
            SignalSource.NFDS,
            _time("2026-07-29T14:35:00+09:00"),
            "FIXTURE",
            "ds04_nfds_updated.json",
        ),
    ),
    "DS-05": (
        ScenarioStep(
            1,
            "정상 수집",
            SignalSource.NFDS,
            _time("2026-07-29T15:00:00+09:00"),
            "FIXTURE",
            "ds05_nfds_healthy.json",
        ),
        ScenarioStep(
            2,
            "응답 지연",
            SignalSource.NFDS,
            _time("2026-07-29T15:10:00+09:00"),
            "SOURCE_STATE",
            source_state="DELAYED",
        ),
        ScenarioStep(
            3,
            "수집 장애",
            SignalSource.NFDS,
            _time("2026-07-29T15:20:00+09:00"),
            "SOURCE_STATE",
            source_state="OUTAGE",
        ),
        ScenarioStep(
            4,
            "백오프 유지",
            SignalSource.NFDS,
            _time("2026-07-29T15:30:00+09:00"),
            "SOURCE_STATE",
            source_state="BACKOFF",
        ),
        ScenarioStep(
            5,
            "정상 복구",
            SignalSource.NFDS,
            _time("2026-07-29T16:00:00+09:00"),
            "FIXTURE",
            "ds05_nfds_recovered.json",
        ),
    ),
    "DS-06": (
        ScenarioStep(
            1,
            "공식 근거 확인 대상",
            SignalSource.NFDS,
            _time("2026-07-29T16:10:00+09:00"),
            "FIXTURE",
            "ds06_nfds_sufficient.json",
        ),
        ScenarioStep(
            2,
            "과거사례만 있는 대상",
            SignalSource.NFDS,
            _time("2026-07-29T16:20:00+09:00"),
            "FIXTURE",
            "ds06_nfds_insufficient.json",
        ),
        ScenarioStep(
            3,
            "최신 공식근거 충돌 대상",
            SignalSource.NFDS,
            _time("2026-07-29T16:30:00+09:00"),
            "FIXTURE",
            "ds06_nfds_conflict.json",
        ),
    ),
}


def scenario_steps(code: str) -> tuple[ScenarioStep, ...]:
    try:
        return SCENARIO_STEPS[code]
    except KeyError as error:
        raise ValueError(f"unsupported DEMO scenario: {code}") from error


def step_contract(step: ScenarioStep) -> dict[str, object]:
    return {
        "ordinal": step.ordinal,
        "label": step.label,
        "source": step.source.value,
        "sourceTime": step.source_time.isoformat(),
        "kind": step.kind,
    }
