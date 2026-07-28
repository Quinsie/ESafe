from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

import psycopg
from psycopg import Cursor

from esafe_importer.config import ImportConfig, sha256_file
from esafe_importer.domain import stable_uuid

EXPECTED_INCIDENT_COUNT = 197
EXPECTED_STRUCTURED_INCIDENT_COUNT = 159
EXPECTED_FACILITY_COUNT = 4_961
EXPECTED_ACTIVE_FACILITY_COUNT = 4_625

_SIDO_ALIASES = (
    ("서울특별시", "서울특별시"), ("서울", "서울특별시"),
    ("부산광역시", "부산광역시"), ("부산", "부산광역시"),
    ("대구광역시", "대구광역시"), ("대구", "대구광역시"),
    ("인천광역시", "인천광역시"), ("인천", "인천광역시"),
    ("광주광역시", "광주광역시"), ("광주", "광주광역시"),
    ("대전광역시", "대전광역시"), ("대전", "대전광역시"),
    ("울산광역시", "울산광역시"), ("울산", "울산광역시"),
    ("세종특별자치시", "세종특별자치시"), ("세종", "세종특별자치시"),
    ("경기도", "경기도"), ("경기", "경기도"),
    ("강원특별자치도", "강원특별자치도"), ("강원도", "강원특별자치도"), ("강원", "강원특별자치도"),
    ("충청북도", "충청북도"), ("충북", "충청북도"),
    ("충청남도", "충청남도"), ("충남", "충청남도"),
    ("전북특별자치도", "전북특별자치도"), ("전라북도", "전북특별자치도"), ("전북", "전북특별자치도"),
    ("전라남도", "전라남도"), ("전남", "전라남도"),
    ("경상북도", "경상북도"), ("경북", "경상북도"),
    ("경상남도", "경상남도"), ("경남", "경상남도"),
    ("제주특별자치도", "제주특별자치도"), ("제주도", "제주특별자치도"), ("제주", "제주특별자치도"),
)
_FACILITY_RULES = (
    ("ESS", ("ESS", "에너지저장장치")),
    ("데이터센터", ("데이터센터",)),
    ("발전시설", ("발전소", "발전시설")),
    ("공동주택", ("아파트", "빌라", "다세대", "공동주택")),
    ("단독주택", ("단독주택", "주택")),
    ("숙박시설", ("숙박", "호텔", "모텔", "펜션")),
    ("공장", ("공장", "생산시설", "제조")),
    ("동식물 관련시설", ("돈사", "양돈", "축사", "농장", "양계")),
    ("판매시설", ("시장", "판매시설", "대규모점포")),
    ("근린생활시설", ("상가", "근린생활", "PC방", "음식점")),
    ("창고시설", ("창고", "물류")),
    ("자동차 관련시설", ("자동차", "정비소", "주차장")),
    ("교육연구시설", ("학교", "대학교", "연구소")),
    ("의료시설", ("병원", "의료시설", "요양원")),
    ("종교시설", ("교회", "사찰", "성당", "종교시설")),
)
_CAUSE_RULES = (
    ("원인 조사 중", ("조사중", "조사 중", "원인미상", "원인 미상", "미상")),
    ("수전반", ("수전반",)), ("분전반", ("분전반",)),
    ("단락·합선", ("단락", "합선")), ("누전", ("누전",)),
    ("과열", ("과열", "과부하")), ("접촉불량", ("접촉불량", "접촉 불량")),
    ("절연 이상", ("절연열화", "절연 열화", "절연파괴", "절연 파괴")),
    ("배선 이상", ("배선", "전선")), ("전기적 요인", ("전기적",)),
    ("부주의", ("부주의",)), ("방화", ("방화",)),
)
_ACTION_RULES = (
    ("현장 조사", ("현장조사", "현장 조사")), ("원인 조사", ("원인조사", "원인 조사")),
    ("설비 점검", ("점검", "검사")), ("안전 조치", ("안전조치", "안전 조치")),
    ("관계기관 협업", ("관계기관", "소방서", "경찰서")),
    ("재발 방지", ("재발방지", "재발 방지")), ("언론 모니터링", ("언론",)),
)
_EQUIPMENT_RULES = (
    ("수전반", ("수전반",)), ("분전반", ("분전반",)), ("변압기", ("변압기",)),
    ("차단기", ("차단기",)), ("배선", ("배선", "전선")),
    ("ESS", ("ESS", "에너지저장장치")), ("비상발전기", ("비상발전기", "발전기")),
    ("태양광", ("태양광",)),
)


@dataclass(slots=True)
class SimilarityMetrics:
    incident_count: int = 0
    structured_incident_count: int = 0
    metadata_only_incident_count: int = 0
    incident_date_missing: int = 0
    incident_region_missing: int = 0
    public_facility_count: int = 0
    active_public_facility_count: int = 0
    public_facility_region_unmapped: int = 0
    public_facility_duplicate_rows: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "incident_count": self.incident_count,
            "structured_incident_count": self.structured_incident_count,
            "metadata_only_incident_count": self.metadata_only_incident_count,
            "incident_date_missing": self.incident_date_missing,
            "incident_region_missing": self.incident_region_missing,
            "public_facility_count": self.public_facility_count,
            "active_public_facility_count": self.active_public_facility_count,
            "public_facility_region_unmapped": self.public_facility_region_unmapped,
            "public_facility_duplicate_rows": self.public_facility_duplicate_rows,
        }


def parse_report_date(value: str) -> date | None:
    match = re.search(r"(?<!\d)(20\d{2}|\d{2})[.\-_ ]+(\d{1,2})[.\-_ ]+(\d{1,2})(?!\d)", value)
    if match is None:
        return None
    year = int(match.group(1))
    if year < 100:
        year += 2000
    try:
        return date(year, int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_region(value: str) -> tuple[str | None, str | None]:
    sido = next((canonical for alias, canonical in _SIDO_ALIASES if alias in value), None)
    sigungu_candidates = re.findall(r"[가-힣]{1,10}(?:시|군|구)(?=\s|$|[().,_-])", value)
    sigungu = next((item for item in sigungu_candidates if not item.endswith(("광역시", "특별시", "자치시"))), None)
    return sido, sigungu


def classify_first(value: str, rules: tuple[tuple[str, tuple[str, ...]], ...], fallback: str) -> str:
    for label, keywords in rules:
        if any(keyword.lower() in value.lower() for keyword in keywords):
            return label
    return fallback


def classify_many(value: str, rules: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    return [label for label, keywords in rules if any(keyword.lower() in value.lower() for keyword in keywords)]


def incident_type(value: str) -> str:
    return classify_first(
        value,
        (("감전", ("감전",)), ("정전", ("정전",)), ("화재", ("화재",)), ("설비사고", ("사고",))),
        "기타사고",
    )


def damage_categories(value: str) -> list[str]:
    normalized = re.sub(r"\s+", "", value)
    categories: list[str] = []
    if "인명피해" in normalized:
        categories.append("인명피해 없음" if re.search(r"인명피해.{0,12}없음", normalized) else "인명피해 보고")
    if "재산피해" in normalized:
        categories.append("재산피해 없음" if re.search(r"재산피해.{0,12}없음", normalized) else "재산피해 보고")
    for label, keywords in (
        ("건물 전소", ("전소",)), ("건물 반소", ("반소",)), ("건물 일부 소실", ("일부소실", "부분소실")),
    ):
        if any(keyword in normalized for keyword in keywords):
            categories.append(label)
    return categories


def preview_text(path: Path) -> str | None:
    if path.suffix.lower() != ".hwpx":
        return None
    try:
        with ZipFile(path) as package:
            return package.read("Preview/PrvText.txt").decode("utf-8-sig", "strict")
    except (BadZipFile, KeyError, UnicodeDecodeError) as error:
        raise ValueError(f"local HWPX preview parsing failed for hash {sha256_file(path)}") from error


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def nullable_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def parse_date_yyyymmdd(value: Any) -> date | None:
    text = str(value).strip() if value is not None else ""
    if not re.fullmatch(r"\d{8}", text):
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def parse_nonnegative_float(value: Any) -> float | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def incident_rows(config: ImportConfig, metrics: SimilarityMetrics) -> Iterator[tuple[Any, ...]]:
    rag_root = config.source_root / "RAG"
    families = (("GENERAL", rag_root / "일반사고보고"), ("MAJOR", rag_root / "중대사고보고"))
    count = 0
    for family, directory in families:
        for path in sorted(item for item in directory.iterdir() if item.is_file()):
            if path.suffix.lower() not in {".hwp", ".hwpx"}:
                continue
            source_hash = sha256_file(path)
            source_identity = hashlib.sha256(
                f"{family}\0{path.name}".encode()
            ).hexdigest()
            text = preview_text(path)
            parser_status = "STRUCTURED_PREVIEW" if text is not None else "METADATA_ONLY"
            searchable = f"{path.stem} {text or ''}"
            reported_on = parse_report_date(path.stem)
            sido_name, sigungu_name = parse_region(path.stem)
            facility_type = classify_first(path.stem, _FACILITY_RULES, "기타 건축물")
            incident_kind = incident_type(searchable)
            causes = classify_many(text or "", _CAUSE_RULES)
            damages = damage_categories(text or "")
            actions = classify_many(text or "", _ACTION_RULES)
            equipment = classify_many(text or "", _EQUIPMENT_RULES)
            quality_flags: list[str] = []
            if reported_on is None:
                quality_flags.append("SOURCE_DATE_MISSING")
                metrics.incident_date_missing += 1
            if sido_name is None and sigungu_name is None:
                quality_flags.append("SOURCE_REGION_MISSING")
                metrics.incident_region_missing += 1
            if not causes:
                quality_flags.append("CAUSE_UNCLASSIFIED")
            if parser_status == "METADATA_ONLY":
                quality_flags.append("LEGACY_HWP_METADATA_ONLY")
                metrics.metadata_only_incident_count += 1
            else:
                metrics.structured_incident_count += 1
            location = " ".join(item for item in (sido_name, sigungu_name) if item)
            display_title = " ".join(item for item in (location, facility_type, incident_kind, "사고사례") if item)
            yield (
                stable_uuid("historical-incident", source_identity), family, path.suffix.upper().lstrip("."), source_hash,
                reported_on, display_title, incident_kind, sido_name, sigungu_name, facility_type,
                compact_json(causes), compact_json(damages), compact_json(actions), compact_json(equipment),
                parser_status, "DERIVED_NO_PII", compact_json(quality_flags), config.import_id,
            )
            count += 1
    metrics.incident_count = count


def facility_rows(
    config: ImportConfig,
    metrics: SimilarityMetrics,
    region_codes: dict[str, str],
) -> Iterator[tuple[Any, ...]]:
    path = config.source_root / "RAG" / "전국다중이용시설" / "multiuse_facilities_all.csv"
    seen: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            address = nullable_text(row.get("conmAddr")) or ""
            if address.startswith("광주광역시"):
                sido_name = "광주광역시"
            elif address.startswith("전라남도") or address.startswith("전남 "):
                sido_name = "전라남도"
            else:
                continue
            tokens = address.split()
            sigungu_name = tokens[1] if len(tokens) > 1 else None
            address_summary = " ".join(tokens[:2]) if tokens else sido_name
            full_name = " ".join(item for item in (sido_name, sigungu_name) if item)
            region_code = region_codes.get(full_name)
            if region_code is None:
                metrics.public_facility_region_unmapped += 1
            source_key = nullable_text(row.get("mltUtztnBsshSn"))
            if source_key is None:
                raise ValueError("public facility source key is missing")
            source_fingerprint = hashlib.sha256(compact_json(row).encode()).hexdigest()
            previous_fingerprint = seen.get(source_key)
            if previous_fingerprint is not None:
                if previous_fingerprint != source_fingerprint:
                    raise ValueError("public facility source key has conflicting rows")
                metrics.public_facility_duplicate_rows += 1
                continue
            seen[source_key] = source_fingerprint
            facility_name = nullable_text(row.get("conmNm")) or "시설명 미등록"
            is_active = nullable_text(row.get("useYn")) == "Y"
            if is_active:
                metrics.active_public_facility_count += 1
            canonical = {
                "source_key": source_key,
                "facility_name": facility_name,
                "business_type": nullable_text(row.get("tpbizNm")),
                "building_use": nullable_text(row.get("bdstUsgNm")),
                "address_summary": address_summary,
                "structure_name": nullable_text(row.get("bldgStrctrNm")),
                "floor_name": nullable_text(row.get("flrNoNm")),
                "interior_materials": nullable_text(row.get("nlmbltMatrlDsctn")),
                "installation_area_m2": parse_nonnegative_float(row.get("nlmbltInstlArea")),
                "registered_on": str(parse_date_yyyymmdd(row.get("regYmd")) or ""),
                "declared_on": str(parse_date_yyyymmdd(row.get("instlDclrYmd")) or ""),
                "completed_on": str(parse_date_yyyymmdd(row.get("pfcmpYmd")) or ""),
                "closed_on": str(parse_date_yyyymmdd(row.get("sttsScsnYmd")) or ""),
                "is_active": is_active,
            }
            row_hash = hashlib.sha256(compact_json(canonical).encode()).hexdigest()
            yield (
                stable_uuid("public-facility-reference", source_key), source_key, facility_name,
                canonical["business_type"], canonical["building_use"], sido_name, sigungu_name,
                region_code, address_summary, canonical["structure_name"], canonical["floor_name"],
                canonical["interior_materials"], canonical["installation_area_m2"],
                parse_date_yyyymmdd(row.get("regYmd")), parse_date_yyyymmdd(row.get("instlDclrYmd")),
                parse_date_yyyymmdd(row.get("pfcmpYmd")), parse_date_yyyymmdd(row.get("sttsScsnYmd")),
                is_active, row_hash, config.import_id,
            )
    metrics.public_facility_count = len(seen)


def fetch_scalar(cursor: Cursor[Any]) -> Any:
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("database query returned no row")
    return row[0]


def copy_rows(cursor: Cursor[Any], table: str, columns: tuple[str, ...], rows: Iterator[tuple[Any, ...]]) -> None:
    with cursor.copy(f"COPY {table} ({','.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


class SimilarityReferenceImporter:
    def __init__(self, config: ImportConfig) -> None:
        self.config = config
        self.metrics = SimilarityMetrics()

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        with (
            psycopg.connect(
                self.config.database_url, application_name="esafe-similarity-importer"
            ) as connection,
            connection.transaction(),
        ):
                cursor = connection.cursor()
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext('esafe-similarity-import'))")
                cursor.execute("SET LOCAL lock_timeout = '30s'")
                cursor.execute("SET LOCAL statement_timeout = '0'")
                cursor.execute("SELECT full_name, region_code FROM admin_region WHERE level = 'SIGUNGU'")
                region_codes = {str(name): str(code) for name, code in cursor.fetchall()}
                self._create_staging(cursor)
                copy_rows(cursor, "stg_historical_incident", INCIDENT_COLUMNS, incident_rows(self.config, self.metrics))
                copy_rows(cursor, "stg_public_facility", FACILITY_COLUMNS, facility_rows(self.config, self.metrics, region_codes))
                self._validate_staging(cursor)
                self._activate(cursor)
                self._validate_active(cursor)
                cursor.execute("ANALYZE historical_incident")
                cursor.execute("ANALYZE public_facility_reference")
        return {
            "status": "SUCCESS",
            "import_id": self.config.import_id,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "metrics": self.metrics.as_dict(),
        }

    @staticmethod
    def _create_staging(cursor: Cursor[Any]) -> None:
        cursor.execute(
            """
            CREATE TEMP TABLE stg_historical_incident (
                incident_id uuid, source_family text, source_format text, source_hash text,
                reported_on date, display_title text, incident_type text, sido_name text,
                sigungu_name text, facility_type text, cause_categories text, damage_categories text,
                action_categories text, equipment_categories text, parser_status text,
                privacy_status text, quality_flags text, source_version text
            ) ON COMMIT DROP;
            CREATE TEMP TABLE stg_public_facility (
                facility_reference_id uuid, source_key text, facility_name text, business_type text,
                building_use text, sido_name text, sigungu_name text, region_code text,
                address_summary text, structure_name text, floor_name text, interior_materials text,
                installation_area_m2 numeric, registered_on date, declared_on date,
                completed_on date, closed_on date, is_active boolean, row_hash text, source_version text
            ) ON COMMIT DROP;
            """
        )

    def _validate_staging(self, cursor: Cursor[Any]) -> None:
        expected = (
            ("stg_historical_incident", EXPECTED_INCIDENT_COUNT),
            ("stg_public_facility", EXPECTED_FACILITY_COUNT),
        )
        for table, count in expected:
            cursor.execute(f"SELECT count(*) FROM {table}")
            if int(fetch_scalar(cursor)) != count:
                raise ValueError(f"similarity staging count mismatch: {table}")
        checks = (
            ("structured incident count", f"SELECT count(*) = {EXPECTED_STRUCTURED_INCIDENT_COUNT} FROM stg_historical_incident WHERE parser_status = 'STRUCTURED_PREVIEW'"),
            ("incident identity", "SELECT count(*) = count(DISTINCT incident_id) FROM stg_historical_incident"),
            ("incident privacy", "SELECT count(*) = 0 FROM stg_historical_incident WHERE privacy_status <> 'DERIVED_NO_PII' OR display_title ~ '[0-9]{2,4}[- .][0-9]{3,4}[- .][0-9]{4}'"),
            ("active public facility count", f"SELECT count(*) = {EXPECTED_ACTIVE_FACILITY_COUNT} FROM stg_public_facility WHERE is_active"),
            ("public facility duplicate", "SELECT count(*) = count(DISTINCT source_key) FROM stg_public_facility"),
            ("public facility region", "SELECT count(*) = 0 FROM stg_public_facility WHERE sido_name NOT IN ('광주광역시', '전라남도')"),
        )
        for label, query in checks:
            cursor.execute(query)
            if fetch_scalar(cursor) is not True:
                raise ValueError(f"similarity staging validation failed: {label}")

    def _activate(self, cursor: Cursor[Any]) -> None:
        cursor.execute(
            """
            INSERT INTO historical_incident (
                incident_id, source_family, source_format, source_hash, reported_on, display_title,
                incident_type, sido_name, sigungu_name, facility_type, cause_categories,
                damage_categories, action_categories, equipment_categories, parser_status,
                privacy_status, quality_flags, source_version
            )
            SELECT incident_id, source_family, source_format, source_hash, reported_on, display_title,
                   incident_type, sido_name, sigungu_name, facility_type, cause_categories::jsonb,
                   damage_categories::jsonb, action_categories::jsonb, equipment_categories::jsonb,
                   parser_status, privacy_status, quality_flags::jsonb, source_version
            FROM stg_historical_incident
            ON CONFLICT (incident_id) DO UPDATE SET
                source_family = EXCLUDED.source_family, source_format = EXCLUDED.source_format,
                source_hash = EXCLUDED.source_hash, reported_on = EXCLUDED.reported_on,
                display_title = EXCLUDED.display_title, incident_type = EXCLUDED.incident_type,
                sido_name = EXCLUDED.sido_name, sigungu_name = EXCLUDED.sigungu_name,
                facility_type = EXCLUDED.facility_type, cause_categories = EXCLUDED.cause_categories,
                damage_categories = EXCLUDED.damage_categories, action_categories = EXCLUDED.action_categories,
                equipment_categories = EXCLUDED.equipment_categories, parser_status = EXCLUDED.parser_status,
                privacy_status = EXCLUDED.privacy_status, quality_flags = EXCLUDED.quality_flags,
                source_version = EXCLUDED.source_version, ingested_at = CURRENT_TIMESTAMP
            """
        )
        cursor.execute("DELETE FROM historical_incident WHERE source_version <> %s", (self.config.import_id,))
        cursor.execute(
            """
            INSERT INTO public_facility_reference (
                facility_reference_id, source_key, facility_name, business_type, building_use,
                sido_name, sigungu_name, region_code, address_summary, structure_name, floor_name,
                interior_materials, installation_area_m2, registered_on, declared_on, completed_on,
                closed_on, is_active, row_hash, source_version
            )
            SELECT facility_reference_id, source_key, facility_name, business_type, building_use,
                   sido_name, sigungu_name, region_code, address_summary, structure_name, floor_name,
                   interior_materials, installation_area_m2, registered_on, declared_on, completed_on,
                   closed_on, is_active, row_hash, source_version
            FROM stg_public_facility
            ON CONFLICT (facility_reference_id) DO UPDATE SET
                source_key = EXCLUDED.source_key, facility_name = EXCLUDED.facility_name,
                business_type = EXCLUDED.business_type, building_use = EXCLUDED.building_use,
                sido_name = EXCLUDED.sido_name, sigungu_name = EXCLUDED.sigungu_name,
                region_code = EXCLUDED.region_code, address_summary = EXCLUDED.address_summary,
                structure_name = EXCLUDED.structure_name, floor_name = EXCLUDED.floor_name,
                interior_materials = EXCLUDED.interior_materials,
                installation_area_m2 = EXCLUDED.installation_area_m2,
                registered_on = EXCLUDED.registered_on, declared_on = EXCLUDED.declared_on,
                completed_on = EXCLUDED.completed_on, closed_on = EXCLUDED.closed_on,
                is_active = EXCLUDED.is_active, row_hash = EXCLUDED.row_hash,
                source_version = EXCLUDED.source_version, ingested_at = CURRENT_TIMESTAMP
            """
        )
        cursor.execute("DELETE FROM public_facility_reference WHERE source_version <> %s", (self.config.import_id,))

    @staticmethod
    def _validate_active(cursor: Cursor[Any]) -> None:
        cursor.execute("SELECT count(*) FROM historical_incident")
        if int(fetch_scalar(cursor)) != EXPECTED_INCIDENT_COUNT:
            raise ValueError("active historical incident count mismatch")
        cursor.execute("SELECT count(*) FROM public_facility_reference")
        if int(fetch_scalar(cursor)) != EXPECTED_FACILITY_COUNT:
            raise ValueError("active public facility count mismatch")


INCIDENT_COLUMNS = (
    "incident_id", "source_family", "source_format", "source_hash", "reported_on",
    "display_title", "incident_type", "sido_name", "sigungu_name", "facility_type",
    "cause_categories", "damage_categories", "action_categories", "equipment_categories",
    "parser_status", "privacy_status", "quality_flags", "source_version",
)
FACILITY_COLUMNS = (
    "facility_reference_id", "source_key", "facility_name", "business_type", "building_use",
    "sido_name", "sigungu_name", "region_code", "address_summary", "structure_name", "floor_name",
    "interior_materials", "installation_area_m2", "registered_on", "declared_on", "completed_on",
    "closed_on", "is_active", "row_hash", "source_version",
)


def main() -> None:
    try:
        result = SimilarityReferenceImporter(ImportConfig.from_environment()).run()
    except Exception as error:
        print(compact_json({"status": "FAILED", "error_type": type(error).__name__, "message": str(error)}), flush=True)
        raise
    print(compact_json(result), flush=True)


if __name__ == "__main__":
    main()