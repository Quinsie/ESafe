from app.signals.contracts import SignalSource
from app.signals.fixtures import DEFAULT_SCENARIO_ID, load_fixture_batch


def test_all_demo_sources_use_raw_shape_fixtures_and_stable_scenario() -> None:
    for source in SignalSource:
        batch, scenario_id = load_fixture_batch(source)
        assert scenario_id == DEFAULT_SCENARIO_ID
        assert batch.source is source
        assert batch.documents
        assert batch.records
        assert all(record.signal.is_relevant for record in batch.records)


def test_demo_fixture_identifiers_are_repeatable() -> None:
    for source in SignalSource:
        first, _ = load_fixture_batch(source)
        second, _ = load_fixture_batch(source)
        assert [record.signal.external_id for record in first.records] == [
            record.signal.external_id for record in second.records
        ]
