# ruff: noqa: E501
import asyncio
import math
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

REFERENCE_MONTH = "2026-03"
HORIZON_DAYS = 60
LINEAGE_VERSION = "v27.1-focus-2026-03-60d"

_BUILDING_USE_RULES = (
    ("ESS", ("에너지저장", "ESS")),
    ("데이터센터", ("데이터센터",)),
    ("발전시설", ("발전",)),
    ("공동주택", ("공동주택", "아파트")),
    ("단독주택", ("단독주택",)),
    ("숙박시설", ("숙박",)),
    ("공장", ("공장",)),
    ("동식물 관련시설", ("동식물", "축사",)),
    ("판매시설", ("판매", "시장",)),
    ("근린생활시설", ("근린생활", "제1종근생", "제2종근생")),
    ("창고시설", ("창고",)),
    ("자동차 관련시설", ("자동차", "주차",)),
    ("교육연구시설", ("교육", "학교", "연구",)),
    ("의료시설", ("의료", "병원", "요양",)),
    ("종교시설", ("종교",)),
)

_FACILITY_COMPONENT_SQL = """
CASE
    WHEN CAST(:facility_type AS varchar) = 'ESS' AND (main_use ILIKE '%에너지저장%' OR main_use ILIKE '%ESS%') THEN 60
    WHEN CAST(:facility_type AS varchar) = '데이터센터' AND main_use ILIKE '%데이터센터%' THEN 60
    WHEN CAST(:facility_type AS varchar) = '발전시설' AND main_use ILIKE '%발전%' THEN 60
    WHEN CAST(:facility_type AS varchar) = '공동주택' AND (main_use ILIKE '%공동주택%' OR main_use ILIKE '%아파트%') THEN 60
    WHEN CAST(:facility_type AS varchar) = '단독주택' AND main_use ILIKE '%단독주택%' THEN 60
    WHEN CAST(:facility_type AS varchar) = '숙박시설' AND main_use ILIKE '%숙박%' THEN 60
    WHEN CAST(:facility_type AS varchar) = '공장' AND main_use ILIKE '%공장%' THEN 60
    WHEN CAST(:facility_type AS varchar) = '동식물 관련시설' AND (main_use ILIKE '%동식물%' OR main_use ILIKE '%축사%') THEN 60
    WHEN CAST(:facility_type AS varchar) = '판매시설' AND (main_use ILIKE '%판매%' OR main_use ILIKE '%시장%') THEN 60
    WHEN CAST(:facility_type AS varchar) = '근린생활시설' AND (main_use ILIKE '%근린생활%' OR main_use ILIKE '%제1종근생%' OR main_use ILIKE '%제2종근생%') THEN 60
    WHEN CAST(:facility_type AS varchar) = '창고시설' AND main_use ILIKE '%창고%' THEN 60
    WHEN CAST(:facility_type AS varchar) = '자동차 관련시설' AND (main_use ILIKE '%자동차%' OR main_use ILIKE '%주차%') THEN 60
    WHEN CAST(:facility_type AS varchar) = '교육연구시설' AND (main_use ILIKE '%교육%' OR main_use ILIKE '%학교%' OR main_use ILIKE '%연구%') THEN 60
    WHEN CAST(:facility_type AS varchar) = '의료시설' AND (main_use ILIKE '%의료%' OR main_use ILIKE '%병원%' OR main_use ILIKE '%요양%') THEN 60
    WHEN CAST(:facility_type AS varchar) = '종교시설' AND main_use ILIKE '%종교%' THEN 60
    ELSE 0
END
"""


@dataclass(frozen=True)
class SimilarityContractError(Exception):
    status_code: int
    code: str
    message: str


def classify_building_use(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower()
    for label, keywords in _BUILDING_USE_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return label
    return None


def condition_match(
    incident_facility: str,
    incident_sido: str | None,
    incident_sigungu: str | None,
    building_use: str | None,
    building_sido: str | None,
    building_sigungu: str | None,
) -> dict[str, Any]:
    building_category = classify_building_use(building_use)
    facility_points = 60 if building_category == incident_facility else 0
    if incident_sigungu and building_sigungu and incident_sigungu == building_sigungu:
        geography_points = 40
        geography_label = "같은 시·군·구"
    elif incident_sido and building_sido and incident_sido == building_sido:
        geography_points = 20
        geography_label = "같은 광역시·도"
    else:
        geography_points = 0
        geography_label = "지역 일치 없음"
    return {
        "score": facility_points + geography_points,
        "isProbability": False,
        "components": [
            {
                "code": "FACILITY_USE",
                "label": "시설 용도 조건",
                "points": facility_points,
                "maximum": 60,
                "detail": (
                    f"사례·건물 용도 분류 일치: {incident_facility}"
                    if facility_points
                    else f"사례 {incident_facility} / 건물 {building_category or '분류 불가'}"
                ),
            },
            {
                "code": "GEOGRAPHY",
                "label": "지역 조건",
                "points": geography_points,
                "maximum": 40,
                "detail": geography_label,
            },
        ],
    }


def evidence_quality(parser_status: str, quality_flags: list[str]) -> dict[str, Any]:
    structured = parser_status == "STRUCTURED_PREVIEW"
    return {
        "status": "DERIVED_STRUCTURED" if structured else "METADATA_ONLY",
        "label": "파생정보 구조화" if structured else "메타데이터만 확인",
        "historicalExampleOnly": True,
        "qualityFlags": quality_flags,
    }


def _incident(row: Any, match: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "incidentId": str(row["incident_id"]),
        "reportedOn": row["reported_on"].isoformat() if row["reported_on"] else None,
        "title": row["display_title"],
        "sourceFamily": row["source_family"],
        "incidentType": row["incident_type"],
        "region": {"sidoName": row["sido_name"], "sigunguName": row["sigungu_name"]},
        "facilityType": row["facility_type"],
        "causeCategories": list(row["cause_categories"]),
        "damageCategories": list(row["damage_categories"]),
        "actionCategories": list(row["action_categories"]),
        "equipmentCategories": list(row["equipment_categories"]),
        "evidenceQuality": evidence_quality(row["parser_status"], list(row["quality_flags"])),
        "conditionMatch": match,
    }


async def _load_incident(connection: AsyncConnection, incident_id: UUID) -> Any:
    row = (
        await connection.execute(
            text("SELECT * FROM historical_incident WHERE incident_id = :incident_id"),
            {"incident_id": incident_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise SimilarityContractError(404, "INCIDENT_NOT_FOUND", "과거 사고사례를 찾을 수 없습니다.")
    return row


async def _load_context(
    connection: AsyncConnection,
    region_code: str | None,
    building_id: UUID | None,
    case_id: UUID | None,
) -> dict[str, Any]:
    explicit_region = None
    if region_code:
        explicit_region = (
            await connection.execute(
                text(
                    """
                    SELECT a.region_code, a.level, a.name, a.full_name,
                           CASE WHEN a.level = 'SIDO' THEN a.full_name ELSE p.full_name END AS sido_name,
                           CASE WHEN a.level = 'SIGUNGU' THEN a.name END AS sigungu_name
                    FROM admin_region a
                    LEFT JOIN admin_region p ON p.region_code = a.parent_code
                    WHERE a.region_code = :region_code
                    """
                ),
                {"region_code": region_code},
            )
        ).mappings().one_or_none()
        if explicit_region is None:
            raise SimilarityContractError(404, "REGION_NOT_FOUND", "지역을 찾을 수 없습니다.")

    case = None
    if case_id:
        case = (
            await connection.execute(
                text(
                    """
                    SELECT c.case_id, c.case_number, c.title, c.case_type, c.status,
                           c.primary_region_code, a.full_name AS region_name,
                           CASE WHEN a.level = 'SIDO' THEN a.full_name ELSE p.full_name END AS sido_name,
                           CASE WHEN a.level = 'SIGUNGU' THEN a.name END AS sigungu_name,
                           c.location IS NOT NULL AS has_location
                    FROM case_record c
                    LEFT JOIN admin_region a ON a.region_code = c.primary_region_code
                    LEFT JOIN admin_region p ON p.region_code = a.parent_code
                    WHERE c.case_id = :case_id
                    """
                ),
                {"case_id": case_id},
            )
        ).mappings().one_or_none()
        if case is None:
            raise SimilarityContractError(404, "CASE_NOT_FOUND", "관제 사건을 찾을 수 없습니다.")

    resolved_building_id = building_id
    inferred_from_case = False
    if resolved_building_id is None and case_id and case is not None and case["has_location"]:
        resolved_building_id = (
            await connection.execute(
                text(
                    """
                    SELECT b.building_id
                    FROM case_record c
                    JOIN building b
                      ON b.geometry_status = 'VALID'
                     AND ST_DWithin(c.location::geography, b.centroid::geography, 500)
                    WHERE c.case_id = :case_id
                    ORDER BY b.centroid <-> c.location, b.building_id
                    LIMIT 1
                    """
                ),
                {"case_id": case_id},
            )
        ).scalar_one_or_none()
        inferred_from_case = resolved_building_id is not None

    building = None
    if resolved_building_id:
        building = (
            await connection.execute(
                text(
                    """
                    SELECT b.building_id, b.building_name, b.road_address, b.lot_address,
                           b.region_code, a.full_name AS region_name, a.name AS sigungu_name,
                           p.full_name AS sido_name, b.customer_data ->> 'main_use_name' AS main_use_name
                    FROM building b
                    JOIN admin_region a ON a.region_code = b.region_code
                    LEFT JOIN admin_region p ON p.region_code = a.parent_code
                    WHERE b.building_id = :building_id
                    """
                ),
                {"building_id": resolved_building_id},
            )
        ).mappings().one_or_none()
        if building is None:
            raise SimilarityContractError(404, "BUILDING_NOT_FOUND", "건물을 찾을 수 없습니다.")

    scoring_sido = building["sido_name"] if building else (case["sido_name"] if case else None)
    scoring_sigungu = building["sigungu_name"] if building else (case["sigungu_name"] if case else None)
    return {
        "explicitRegion": dict(explicit_region) if explicit_region else None,
        "case": (
            {
                "caseId": str(case["case_id"]),
                "caseNumber": case["case_number"],
                "title": case["title"],
                "caseType": case["case_type"],
                "status": case["status"],
                "regionCode": case["primary_region_code"],
                "regionName": case["region_name"],
            }
            if case
            else None
        ),
        "building": (
            {
                "buildingId": str(building["building_id"]),
                "name": building["building_name"] or "건물명 미등록",
                "roadAddress": building["road_address"],
                "lotAddress": building["lot_address"],
                "regionCode": building["region_code"],
                "regionName": building["region_name"],
                "mainUseName": building["main_use_name"],
                "inferredFromCase": inferred_from_case,
            }
            if building
            else None
        ),
        "scoring": {
            "sidoName": scoring_sido,
            "sigunguName": scoring_sigungu,
            "buildingUse": building["main_use_name"] if building else None,
        },
    }


async def incident_search(
    engine: AsyncEngine,
    region_code: str | None,
    building_id: UUID | None,
    case_id: UUID | None,
    page: int,
    page_size: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            context = await _load_context(connection, region_code, building_id, case_id)
            rows = (
                await connection.execute(
                    text("SELECT * FROM historical_incident ORDER BY reported_on DESC NULLS LAST, incident_id")
                )
            ).mappings().all()
        explicit = context["explicitRegion"]
        if explicit:
            rows = [
                row
                for row in rows
                if (
                    row["sido_name"] == explicit["sido_name"]
                    and (explicit["sigungu_name"] is None or row["sigungu_name"] == explicit["sigungu_name"])
                )
            ]
        scoring = context["scoring"]
        scored: list[tuple[Any, dict[str, Any] | None]] = []
        for row in rows:
            match = None
            if scoring["sidoName"] or scoring["buildingUse"]:
                match = condition_match(
                    row["facility_type"],
                    row["sido_name"],
                    row["sigungu_name"],
                    scoring["buildingUse"],
                    scoring["sidoName"],
                    scoring["sigunguName"],
                )
            scored.append((row, match))
        if any(match is not None for _, match in scored):
            scored.sort(
                key=lambda item: (
                    -(item[1]["score"] if item[1] else -1),
                    -(item[0]["reported_on"].toordinal() if item[0]["reported_on"] else 0),
                    str(item[0]["incident_id"]),
                )
            )
        total = len(scored)
        start = (page - 1) * page_size
        items = [_incident(row, match) for row, match in scored[start : start + page_size]]
        return {
            "items": items,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": math.ceil(total / page_size) if total else 0,
            },
            "selection": {key: value for key, value in context.items() if key != "scoring"},
            "matchDefinition": {
                "label": "조건 정합도",
                "isProbability": False,
                "maximum": 100,
                "components": {"facilityUse": 60, "geography": 40},
            },
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))


async def candidate_buildings(
    engine: AsyncEngine,
    reference_incident_id: UUID,
    page: int,
    page_size: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            incident = await _load_incident(connection, reference_incident_id)
            params = {
                "facility_type": incident["facility_type"],
                "sido_name": incident["sido_name"],
                "sigungu_name": incident["sigungu_name"],
                "limit": page_size,
                "offset": (page - 1) * page_size,
            }
            total = int(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT count(*) FROM building b
                            JOIN building_risk_snapshot r ON r.building_id = b.building_id
                            WHERE r.reference_month = DATE '2026-03-01'
                              AND r.horizon_days = 60
                              AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                            """
                        )
                    )
                ).scalar_one()
            )
            rows = (
                await connection.execute(
                    text(
                        f"""
                        WITH scored AS (
                            SELECT b.building_id, b.building_name, b.road_address, b.lot_address,
                                   b.region_code, a.full_name AS region_name, a.name AS sigungu_name,
                                   p.full_name AS sido_name,
                                   b.customer_data ->> 'main_use_name' AS main_use,
                                   b.customer_data ->> 'main_structure' AS main_structure,
                                   b.customer_data ->> 'building_year' AS building_year,
                                   ST_X(b.centroid) AS lng, ST_Y(b.centroid) AS lat,
                                   r.final_score, r.regional_rank, r.top_percentile, r.risk_band,
                                   {_FACILITY_COMPONENT_SQL} AS facility_points,
                                   CASE
                                       WHEN CAST(:sigungu_name AS varchar) IS NOT NULL AND a.name = CAST(:sigungu_name AS varchar) AND p.full_name = CAST(:sido_name AS varchar) THEN 40
                                       WHEN CAST(:sido_name AS varchar) IS NOT NULL AND p.full_name = CAST(:sido_name AS varchar) THEN 20
                                       ELSE 0
                                   END AS geography_points
                            FROM building b
                            JOIN admin_region a ON a.region_code = b.region_code
                            LEFT JOIN admin_region p ON p.region_code = a.parent_code
                            JOIN building_risk_snapshot r ON r.building_id = b.building_id
                            CROSS JOIN LATERAL (SELECT coalesce(b.customer_data ->> 'main_use_name', '') AS main_use) u
                            WHERE r.reference_month = DATE '2026-03-01'
                              AND r.horizon_days = 60
                              AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                        ), selected AS (
                            SELECT * FROM scored
                            ORDER BY facility_points + geography_points DESC, regional_rank, building_id
                            LIMIT :limit OFFSET :offset
                        )
                        SELECT s.*,
                               coalesce(f.linked_count, 0) AS linked_count,
                               f.latest_inspection_date
                        FROM selected s
                        LEFT JOIN LATERAL (
                            SELECT count(*) AS linked_count, max(fe.last_inspection_date) AS latest_inspection_date
                            FROM building_facility_link l
                            JOIN facility_entity fe ON fe.facility_id = l.facility_id
                            WHERE l.building_id = s.building_id
                        ) f ON true
                        ORDER BY s.facility_points + s.geography_points DESC, s.regional_rank, s.building_id
                        """
                    ),
                    params,
                )
            ).mappings().all()
        items = []
        for row in rows:
            match = condition_match(
                incident["facility_type"],
                incident["sido_name"],
                incident["sigungu_name"],
                row["main_use"],
                row["sido_name"],
                row["sigungu_name"],
            )
            priority = {
                "TOP_1": "URGENT",
                "HIGH_1_10": "HIGH",
                "WATCH_10_25": "ATTENTION",
                "GENERAL": "NORMAL",
            }[row["risk_band"]]
            items.append(
                {
                    "buildingId": str(row["building_id"]),
                    "name": row["building_name"] or "건물명 미등록",
                    "roadAddress": row["road_address"],
                    "lotAddress": row["lot_address"],
                    "region": {"regionCode": row["region_code"], "fullName": row["region_name"]},
                    "center": [float(row["lng"]), float(row["lat"])],
                    "attributes": {
                        "mainUseName": row["main_use"],
                        "mainStructure": row["main_structure"],
                        "buildingYear": row["building_year"],
                    },
                    "conditionMatch": match,
                    "risk": {
                        "referenceMonth": REFERENCE_MONTH,
                        "horizonDays": HORIZON_DAYS,
                        "lineageVersion": LINEAGE_VERSION,
                        "finalScore": float(row["final_score"]),
                        "regionalRank": int(row["regional_rank"]),
                        "topPercentile": float(row["top_percentile"]),
                        "riskBand": row["risk_band"],
                        "isProbability": False,
                    },
                    "inspectionPriority": {
                        "level": priority,
                        "basis": "기준 위험구간과 조건 정합도를 분리해 표시",
                    },
                    "facilitySummary": {
                        "linkedFacilityCount": int(row["linked_count"]),
                        "latestInspectionDate": row["latest_inspection_date"].isoformat() if row["latest_inspection_date"] else None,
                    },
                }
            )
        return {
            "referenceIncident": _incident(incident),
            "items": items,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": math.ceil(total / page_size) if total else 0,
            },
            "ordering": ["조건 정합도 높은 순", "광주·전남 위험순위 높은 순", "건물 ID"],
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 2.5))


async def comparison(
    engine: AsyncEngine,
    reference_incident_id: UUID,
    candidate_building_id: UUID,
    timeout_seconds: float,
) -> dict[str, Any]:
    async def query() -> dict[str, Any]:
        async with engine.connect() as connection:
            incident = await _load_incident(connection, reference_incident_id)
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT b.building_id, b.building_name, b.road_address, b.lot_address,
                               b.region_code, a.full_name AS region_name, a.name AS sigungu_name,
                               p.full_name AS sido_name, b.customer_data ->> 'main_use_name' AS main_use,
                               b.customer_data ->> 'main_structure' AS main_structure,
                               b.customer_data ->> 'building_year' AS building_year,
                               ST_X(b.centroid) AS lng, ST_Y(b.centroid) AS lat,
                               r.final_score, r.regional_rank, r.top_percentile, r.risk_band,
                               coalesce(f.linked_count, 0) AS linked_count,
                               f.latest_inspection_date
                        FROM building b
                        JOIN admin_region a ON a.region_code = b.region_code
                        LEFT JOIN admin_region p ON p.region_code = a.parent_code
                        JOIN building_risk_snapshot r
                          ON r.building_id = b.building_id
                         AND r.reference_month = DATE '2026-03-01'
                         AND r.horizon_days = 60
                         AND r.lineage_version = 'v27.1-focus-2026-03-60d'
                        LEFT JOIN LATERAL (
                            SELECT count(*) AS linked_count, max(fe.last_inspection_date) AS latest_inspection_date
                            FROM building_facility_link l
                            JOIN facility_entity fe ON fe.facility_id = l.facility_id
                            WHERE l.building_id = b.building_id
                        ) f ON true
                        WHERE b.building_id = :building_id
                        """
                    ),
                    {"building_id": candidate_building_id},
                )
            ).mappings().one_or_none()
        if row is None:
            raise SimilarityContractError(404, "BUILDING_NOT_FOUND", "후보 건물을 찾을 수 없습니다.")
        match = condition_match(
            incident["facility_type"],
            incident["sido_name"],
            incident["sigungu_name"],
            row["main_use"],
            row["sido_name"],
            row["sigungu_name"],
        )
        priority = {
            "TOP_1": "URGENT",
            "HIGH_1_10": "HIGH",
            "WATCH_10_25": "ATTENTION",
            "GENERAL": "NORMAL",
        }[row["risk_band"]]
        equipment = list(incident["equipment_categories"])
        checklist = [
            {
                "code": "VERIFY_EQUIPMENT",
                "label": f"{', '.join(equipment) if equipment else '주요 전기설비'} 상태를 현장에서 확인",
                "basis": "과거 사고사례 파생 범주",
            },
            {
                "code": "VERIFY_USE",
                "label": "현재 건물 용도와 사고사례 시설 분류의 적용 가능성을 확인",
                "basis": "구조화 건축물 용도",
            },
            {
                "code": "VERIFY_INSPECTION",
                "label": "최근 점검 이력과 현재 설비 변경 여부를 확인",
                "basis": "연결 설비 점검일",
            },
        ]
        return {
            "referenceIncident": _incident(incident),
            "candidateBuilding": {
                "buildingId": str(row["building_id"]),
                "name": row["building_name"] or "건물명 미등록",
                "roadAddress": row["road_address"],
                "lotAddress": row["lot_address"],
                "region": {"regionCode": row["region_code"], "fullName": row["region_name"]},
                "center": [float(row["lng"]), float(row["lat"])],
                "attributes": {
                    "mainUseName": row["main_use"],
                    "mainStructure": row["main_structure"],
                    "buildingYear": row["building_year"],
                },
                "facilitySummary": {
                    "linkedFacilityCount": int(row["linked_count"]),
                    "latestInspectionDate": row["latest_inspection_date"].isoformat() if row["latest_inspection_date"] else None,
                },
                "risk": {
                    "referenceMonth": REFERENCE_MONTH,
                    "horizonDays": HORIZON_DAYS,
                    "lineageVersion": LINEAGE_VERSION,
                    "finalScore": float(row["final_score"]),
                    "regionalRank": int(row["regional_rank"]),
                    "topPercentile": float(row["top_percentile"]),
                    "riskBand": row["risk_band"],
                    "isProbability": False,
                },
            },
            "conditionMatch": match,
            "inspectionPriority": {
                "level": priority,
                "riskBand": row["risk_band"],
                "separateFromConditionMatch": True,
            },
            "inspectionChecklist": checklist,
            "evidence": {
                "status": "INSUFFICIENT",
                "warning": "과거 사고사례는 참고자료입니다. 공식 현행 근거 연결 전에는 대응 근거로 확정할 수 없습니다.",
                "historicalExampleOnly": True,
                "requiresOfficialEvidence": True,
            },
        }

    return await asyncio.wait_for(query(), timeout=max(timeout_seconds, 1.5))