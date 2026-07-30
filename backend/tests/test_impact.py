from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.automation.impact import _insert_radius_buildings


@pytest.mark.asyncio
async def test_radius_impact_uses_building_footprints_and_selects_one_incident() -> None:
    connection = AsyncMock(spec=AsyncConnection)
    case_id = uuid4()

    await _insert_radius_buildings(connection, case_id, 100)

    statement, params = connection.execute.await_args.args
    sql = str(statement)
    assert "ST_DWithin(\n                      b.geometry::geography" in sql
    assert "ST_Distance(b.geometry::geography" in sql
    assert "ST_Covers(b.geometry, p.location)" in sql
    assert "m.exact_priority = 1" in sql
    assert "ORDER BY is_incident_building DESC, distance_m ASC" in sql
    assert params["case_id"] == case_id
    assert params["radius_m"] == 100
