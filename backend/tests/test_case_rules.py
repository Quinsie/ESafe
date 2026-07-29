import pytest

from app.automation.case_rules import (
    CaseStatus,
    CaseType,
    ImpactScopeType,
    SignalFacts,
    case_type_for,
    initial_case_status,
    next_case_status,
    select_impact_scope,
)
from app.signals.contracts import EventType, SourceStatus


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (EventType.FIRE_DISPATCH, CaseType.FIRE),
        (EventType.WEATHER_WARNING, CaseType.WEATHER_WARNING),
        (EventType.DISASTER_MESSAGE, CaseType.DISASTER_MESSAGE),
    ],
)
def test_case_type_is_deterministic(event_type: EventType, expected: CaseType) -> None:
    assert case_type_for(event_type) is expected


def test_resolved_signal_starts_in_review_and_active_signal_starts_active() -> None:
    assert initial_case_status(SourceStatus.RESOLVED) is CaseStatus.SOURCE_RESOLVED_REVIEW
    assert initial_case_status(SourceStatus.ACTIVE) is CaseStatus.ACTIVE


def test_source_resolution_never_closes_the_case() -> None:
    assert (
        next_case_status(CaseStatus.ACTIVE, SourceStatus.RESOLVED)
        is CaseStatus.SOURCE_RESOLVED_REVIEW
    )
    assert (
        next_case_status(CaseStatus.SOURCE_RESOLVED_REVIEW, SourceStatus.ACTIVE)
        is CaseStatus.ACTIVE
    )


@pytest.mark.parametrize("terminal", [CaseStatus.CLOSED, CaseStatus.MERGED])
def test_source_update_does_not_reopen_terminal_case(terminal: CaseStatus) -> None:
    assert next_case_status(terminal, SourceStatus.ACTIVE) is terminal
    assert next_case_status(terminal, SourceStatus.RESOLVED) is terminal


def test_on_hold_is_preserved_until_the_source_resolves() -> None:
    assert next_case_status(CaseStatus.ON_HOLD, SourceStatus.UPDATED) is CaseStatus.ON_HOLD
    assert (
        next_case_status(CaseStatus.ON_HOLD, SourceStatus.RESOLVED)
        is CaseStatus.SOURCE_RESOLVED_REVIEW
    )


def test_point_signal_uses_default_one_kilometre_operational_radius() -> None:
    scope = select_impact_scope(
        SignalFacts(
            event_type=EventType.FIRE_DISPATCH,
            source_status=SourceStatus.ACTIVE,
            region_codes=("29",),
            longitude=126.92,
            latitude=35.15,
        )
    )
    assert scope.scope_type is ImpactScopeType.RADIUS
    assert scope.radius_m == 1000
    assert scope.region_codes == ()


def test_region_signal_keeps_region_and_warns_for_sido_precision() -> None:
    scope = select_impact_scope(
        SignalFacts(
            event_type=EventType.WEATHER_WARNING,
            source_status=SourceStatus.ACTIVE,
            region_codes=("46",),
        )
    )
    assert scope.scope_type is ImpactScopeType.ADMIN_REGION
    assert scope.radius_m is None
    assert scope.region_codes == ("46",)
    assert scope.precision_warning == "LOCATION_PRECISION_SIDO"


@pytest.mark.parametrize("radius_m", [499, 501, 2000, 5001])
def test_unsupported_radius_fails_closed(radius_m: int) -> None:
    with pytest.raises(ValueError):
        select_impact_scope(
            SignalFacts(
                event_type=EventType.FIRE_DISPATCH,
                source_status=SourceStatus.ACTIVE,
                region_codes=("29",),
                longitude=126.92,
                latitude=35.15,
            ),
            radius_m=radius_m,
        )


def test_signal_without_point_or_region_fails_closed() -> None:
    with pytest.raises(ValueError):
        select_impact_scope(
            SignalFacts(
                event_type=EventType.DISASTER_MESSAGE,
                source_status=SourceStatus.ACTIVE,
                region_codes=(),
            )
        )
