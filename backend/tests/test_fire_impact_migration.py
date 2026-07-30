import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260730_0019_fire_impact_radius.py"
    )
    spec = importlib.util.spec_from_file_location("fire_impact_radius_migration", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load migration: {path}")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_fire_impact_migration_allows_100_metres(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _migration()
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    assert migration.down_revision == "20260730_0018"
    assert any("radius_m IN (100, 500, 1000, 3000, 5000)" in sql for sql in statements)
