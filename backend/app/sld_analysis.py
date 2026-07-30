from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.ai_control import AiCostGate
from app.config import Settings
from app.sld_box_pipeline import build_diagram_crops, public_crop_metadata
from app.upstage import UpstageChatClient

GRAMMAR_VERSION = "sld-equipment-grammar/11.0-upstage-only"
PIPELINE_VERSION = "esafe-sld-upstage-box-v15-port-v2"
DOCUMENT_PROVIDER = "UPSTAGE_DOCUMENT_OCR"
DOCUMENT_MAX_RESERVED_COST_USD = Decimal("5.00000000")
REGION_DOCUMENT_MAX_RESERVED_COST_USD = Decimal("0.25000000")
_GRAMMAR_ROOT = Path(__file__).resolve().parent / "sld_grammar"
_V11_PARSER = _GRAMMAR_ROOT / "sld_equipment_ocr_grammar_v11" / "parser"
if str(_V11_PARSER) not in sys.path:
    sys.path.insert(0, str(_V11_PARSER))

from sld_equipment_parser_v11 import (  # type: ignore[import-not-found]  # noqa: E402
    classify_text_scope,
    detect_v11_class,
    extract_explicit_anchors,
    parse_equipment_v11,
)

EQUIPMENT_CLASSES = frozenset(
    {
        "AirCircuitBreaker",
        "AutomaticTransferCircuitBreaker",
        "MoldedCaseCircuitBreaker",
        "VacuumCircuitBreaker",
        "LoadBreakSwitch",
        "AirInsulatedSwitch",
        "AutomaticLoadTransferSwitch",
        "AutomaticSectionSwitch",
        "AutomaticTransferSwitch",
        "CutOutSwitch",
        "PowerFuse",
        "CurrentTransformer",
        "VoltageTransformer",
        "MeteringOutfit",
        "CurrentTransformerOpenCircuitProtectionDevice",
        "CurrentTransformerTestTerminal",
        "PotentialTransformerTestTerminal",
        "ZeroSequenceCurrentTransformer",
        "LightningArrester",
        "SurgeArrester",
        "SurgeProtectiveDevice",
        "StaticCapacitor",
        "SeriesReactor",
        "PowerTransformer",
        "DryTypeTransformer",
        "BatteryBank",
        "UninterruptiblePowerSupply",
        "Generator",
        "DigitalMultifunctionMeter",
        "EarthLeakageDetector",
        "BranchCircuitMonitoringDevice",
        "MaximumDemandPowerController",
        "PowerMeasurementSection",
        "CurrentShunt",
        "OverCurrentGroundRelay",
        "UnderVoltageRelay",
        "Timer",
        "BusDuct",
        "UtilityIncoming",
        "GroundingReference",
    }
)

FIRE_CLASS_GROUPS = {
    "TRANSFORMER": {"PowerTransformer", "DryTypeTransformer"},
    "BREAKER": {
        "AirCircuitBreaker",
        "AutomaticTransferCircuitBreaker",
        "MoldedCaseCircuitBreaker",
        "VacuumCircuitBreaker",
    },
    "GENERATOR": {"Generator"},
    "BATTERY_UPS": {"BatteryBank", "UninterruptiblePowerSupply"},
    "SURGE_PROTECTION": {
        "LightningArrester",
        "SurgeArrester",
        "SurgeProtectiveDevice",
    },
    "REACTIVE_POWER": {"StaticCapacitor", "SeriesReactor"},
    "SWITCHING": {
        "AutomaticLoadTransferSwitch",
        "AutomaticSectionSwitch",
        "AutomaticTransferSwitch",
        "LoadBreakSwitch",
    },
}

FIRE_GUIDANCE = {
    "TRANSFORMER": {
        "risk": "권선·접속부 과열, 절연 열화 및 유입식 설비의 절연유 착화 가능성",
        "checks": ["과부하·온도 상승 기록", "절연유 누유 또는 절연 열화 징후"],
    },
    "BREAKER": {
        "risk": "접점 열화와 체결 불량에 따른 국부 발열 및 차단 동작 시 아크 가능성",
        "checks": ["접점·단자 열화상 이상", "정격·트립 설정과 보호협조 확인"],
    },
    "GENERATOR": {
        "risk": "권선 과열, 연료·윤활유 계통 누유 및 비상 전환부 접촉 불량 가능성",
        "checks": ["무부하·부하시험 기록", "연료·배기·전환반 상태"],
    },
    "BATTERY_UPS": {
        "risk": "충전 이상, 셀 열화와 단락에 따른 발열 또는 배터리 열폭주 가능성",
        "checks": ["셀 전압·내부저항·온도 편차", "환기와 충전장치 경보"],
    },
    "SURGE_PROTECTION": {
        "risk": "서지 보호소자의 열화 또는 접지 불량에 따른 과열 가능성",
        "checks": ["상태표시·열화 이력", "접지 연결과 체결 상태"],
    },
    "REACTIVE_POWER": {
        "risk": "커패시터 열화·팽창, 고조파 및 리액터 과열 가능성",
        "checks": ["팽창·누유·온도", "고조파와 불평형 전류"],
    },
    "SWITCHING": {
        "risk": "절체·개폐 접점의 반복 동작과 체결 불량에 따른 발열·아크 가능성",
        "checks": ["절체시험과 접점 상태", "인터록 및 제어전원 상태"],
    },
}

CLASS_GUIDANCE = {
    "DryTypeTransformer": {
        "risk": "권선·접속부 과열, 냉각 불량 및 고체 절연물 열화에 따른 연소 가능성",
        "checks": ["권선·철심 온도와 환기 상태", "절연물 변색·탄화 및 단자 체결 상태"],
    },
}


class SldContractError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class EquipmentExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    equipment_id: str = Field(alias="equipmentId", min_length=1)
    title: str = Field(min_length=1, max_length=160)
    observed_facts: list[str] = Field(alias="observedFacts", max_length=8)
    fire_risk_factors: list[str] = Field(alias="fireRiskFactors", max_length=8)
    inspection_points: list[str] = Field(alias="inspectionPoints", max_length=8)
    warning: str | None = Field(default=None, max_length=600)


class SldExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    overview: str = Field(min_length=1, max_length=1200)
    facility_summary: list[str] = Field(alias="facilitySummary", max_length=20)
    fire_risk_summary: list[str] = Field(alias="fireRiskSummary", max_length=20)
    key_equipment: list[EquipmentExplanation] = Field(alias="keyEquipment", max_length=40)
    limitations: list[str] = Field(max_length=12)


EXPLANATION_SYSTEM_PROMPT = """
당신은 전기설비 단선결선도 OCR 결과를 설명하는 검토 보조자다.
입력의 OCR 원문, 설비 분류, 속성 외의 설비·정격·배선·운전상태를 만들지 마라.
화재 원인을 확정하지 말고 일반적인 화재 위험요인과 현장 확인사항으로 표현하라.
주차단기는 OCR에 MAIN, INCOMING, 주차단기 표기가 있을 때만 확정하고,
그 외 차단기는 주차단기 후보 또는 일반 차단기로 표현하라.
배터리 종류나 변압기 절연매질이 입력에 없으면 미확인이라고 명시하라.
각 keyEquipment 항목의 equipmentId는 입력에 있는 값만 사용하라.
OCR과 문법 분석은 오인식 가능성이 있으므로 limitations에 사람 검토 필요성을 포함하라.
모든 문장은 한국어로 간결하게 작성하고 JSON 스키마에 맞는 객체만 반환하라.
""".strip()


def _bbox_from_polygon(points: Any, width: float, height: float) -> list[float] | None:
    if isinstance(points, dict):
        points = points.get("vertices") or points.get("points")
    if not isinstance(points, list) or not points:
        return None
    coordinates: list[tuple[float, float]] = []
    for point in points:
        if isinstance(point, dict) and "x" in point and "y" in point:
            coordinates.append((float(point["x"]), float(point["y"])))
        elif isinstance(point, list | tuple) and len(point) >= 2:
            coordinates.append((float(point[0]), float(point[1])))
    if not coordinates:
        return None
    if max(max(abs(x), abs(y)) for x, y in coordinates) <= 1.01:
        coordinates = [(x * width, y * height) for x, y in coordinates]
    xs = [point[0] for point in coordinates]
    ys = [point[1] for point in coordinates]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def _normalize_bbox(item: dict[str, Any], width: float, height: float) -> list[float] | None:
    bbox = item.get("bbox") or item.get("bounding_box")
    if isinstance(bbox, list | tuple) and len(bbox) == 4:
        values = [float(value) for value in bbox]
        if max(abs(value) for value in values) <= 1.01:
            values = [
                values[0] * width,
                values[1] * height,
                values[2] * width,
                values[3] * height,
            ]
        return values
    for key in ("boundingBox", "bounding_box", "polygon", "vertices", "coordinates"):
        candidate = _bbox_from_polygon(item.get(key), width, height)
        if candidate:
            return candidate
    return None


def parse_upstage_ocr(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pages_value = payload.get("pages")
    pages = pages_value if isinstance(pages_value, list) else []
    containers = [*pages, payload] if pages else [payload]
    output: list[dict[str, Any]] = []
    page_metadata: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int, int, int, int]] = set()
    sequence = 0
    for page_index, page in enumerate(containers, 1):
        if not isinstance(page, dict):
            continue
        width = float(page.get("width") or 1)
        height = float(page.get("height") or 1)
        page_number = int(
            page.get("page")
            or page.get("pageNumber")
            or (1 if page is payload else page_index)
        )
        page_info = {"page": page_number, "width": width, "height": height}
        if page is not payload or not pages:
            page_metadata.append(page_info)
        candidates = page.get("words") or page.get("tokens") or []
        if not isinstance(candidates, list):
            candidates = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            raw_text = str(
                item.get("text") or item.get("value") or item.get("inferText") or ""
            ).strip()
            bbox = _normalize_bbox(item, width, height)
            if not raw_text or bbox is None:
                continue
            key = (
                page_number,
                raw_text,
                round(bbox[0]),
                round(bbox[1]),
                round(bbox[2]),
                round(bbox[3]),
            )
            if key in seen:
                continue
            seen.add(key)
            sequence += 1
            output.append(
                {
                    "id": f"UPSTAGE-OCR-{sequence:06d}",
                    "page": page_number,
                    "raw_text": raw_text,
                    "confidence": float(
                        item.get(
                            "confidence",
                            item.get("score", item.get("inferConfidence", 0.0)),
                        )
                        or 0.0
                    ),
                    "bbox_page_pixel": bbox,
                    "provider": "upstage_document_ocr",
                }
            )
    if output:
        return output, page_metadata
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return output, page_metadata
    for element_index, element in enumerate(elements, 1):
        if not isinstance(element, dict):
            continue
        content = element.get("content")
        raw_text = (
            str(content.get("text") or content.get("markdown") or "").strip()
            if isinstance(content, dict)
            else str(content or "").strip()
        )
        page_number = int(element.get("page") or element.get("pageNumber") or 1)
        page = next(
            (item for item in page_metadata if item["page"] == page_number),
            {"width": 1.0, "height": 1.0},
        )
        bbox = _normalize_bbox(element, float(page["width"]), float(page["height"]))
        if raw_text and bbox is not None:
            output.append(
                {
                    "id": f"UPSTAGE-ELEMENT-{element_index:06d}",
                    "page": page_number,
                    "raw_text": raw_text,
                    "confidence": float(element.get("confidence") or 0.0),
                    "bbox_page_pixel": bbox,
                    "provider": "upstage_document_ocr",
                }
            )
    return output, page_metadata


def _union_bbox(items: list[dict[str, Any]]) -> list[float]:
    boxes = [item["bbox_page_pixel"] for item in items]
    left = min(float(box[0]) for box in boxes)
    top = min(float(box[1]) for box in boxes)
    right = max(float(box[0]) + float(box[2]) for box in boxes)
    bottom = max(float(box[1]) + float(box[3]) for box in boxes)
    return [left, top, right - left, bottom - top]


def _group_ocr_lines(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: list[list[dict[str, Any]]] = []
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_page[int(item["page"])].append(item)
    for page_items in by_page.values():
        lines: list[list[dict[str, Any]]] = []
        for item in sorted(
            page_items,
            key=lambda value: (
                float(value["bbox_page_pixel"][1]),
                float(value["bbox_page_pixel"][0]),
            ),
        ):
            box = item["bbox_page_pixel"]
            center_y = float(box[1]) + float(box[3]) / 2
            matching = None
            for line in reversed(lines[-8:]):
                line_box = _union_bbox(line)
                line_center = float(line_box[1]) + float(line_box[3]) / 2
                tolerance = max(10.0, min(float(box[3]), float(line_box[3])) * 0.75)
                if abs(center_y - line_center) <= tolerance:
                    matching = line
                    break
            if matching is None:
                lines.append([item])
            else:
                matching.append(item)
        for line in lines:
            ordered = sorted(line, key=lambda value: float(value["bbox_page_pixel"][0]))
            segments: list[list[dict[str, Any]]] = []
            for item in ordered:
                if not segments:
                    segments.append([item])
                    continue
                previous_box = segments[-1][-1]["bbox_page_pixel"]
                current_box = item["bbox_page_pixel"]
                gap = float(current_box[0]) - (
                    float(previous_box[0]) + float(previous_box[2])
                )
                height = max(float(previous_box[3]), float(current_box[3]))
                if gap > max(42.0, height * 4.0):
                    segments.append([item])
                else:
                    segments[-1].append(item)
            grouped.extend(segments)
    return grouped


def _sanitize_parser_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if "paddle" in str(key).lower():
                continue
            result[key] = _sanitize_parser_payload(item)
        return result
    if isinstance(value, list):
        return [_sanitize_parser_payload(item) for item in value]
    if isinstance(value, str) and "paddle" in value.lower():
        return "UPSTAGE_OCR_BBOX"
    return value


def _fire_group(class_id: str) -> str | None:
    for group, classes in FIRE_CLASS_GROUPS.items():
        if class_id in classes:
            return group
    return None


def _fire_guidance(class_id: str, fire_group: str | None) -> dict[str, Any] | None:
    return CLASS_GUIDANCE.get(class_id) or FIRE_GUIDANCE.get(fire_group or "")


def _bbox_center(box: list[float]) -> tuple[float, float]:
    return box[0] + box[2] / 2.0, box[1] + box[3] / 2.0


def _bbox_contains(outer: list[float], inner: list[float], pad: float = 0.0) -> bool:
    center_x, center_y = _bbox_center(inner)
    return (
        outer[0] - pad <= center_x <= outer[0] + outer[2] + pad
        and outer[1] - pad <= center_y <= outer[1] + outer[3] + pad
    )


def _bbox_iou(left: list[float], right: list[float]) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    intersection = max(0.0, min(lx + lw, rx + rw) - max(lx, rx)) * max(
        0.0,
        min(ly + lh, ry + rh) - max(ly, ry),
    )
    union = lw * lh + rw * rh - intersection
    return intersection / union if union > 0 else 0.0


def _bbox_distance(left: list[float], right: list[float]) -> float:
    left_x, left_y = _bbox_center(left)
    right_x, right_y = _bbox_center(right)
    return math.hypot(left_x - right_x, left_y - right_y)


def _equipment_classes(text_value: str) -> list[str]:
    classes = [
        str(anchor.get("class_id"))
        for anchor in extract_explicit_anchors(text_value)
        if anchor.get("class_id") in EQUIPMENT_CLASSES
    ]
    detected = detect_v11_class(text_value)
    if detected in EQUIPMENT_CLASSES:
        classes.append(str(detected))
    return list(dict.fromkeys(classes))


def _crop_for_box(
    page: int,
    box: list[float],
    crops: list[dict[str, Any]],
) -> dict[str, Any] | None:
    matches = [
        crop
        for crop in crops
        if int(crop["page"]) == page and _bbox_contains(crop["bbox"], box)
    ]
    return min(matches, key=lambda value: value["bbox"][2] * value["bbox"][3], default=None)


def _is_duplicate_candidate(
    candidates: list[dict[str, Any]],
    class_id: str,
    page: int,
    core_box: list[float],
) -> bool:
    return any(
        item["classId"] == class_id
        and int(item["page"]) == page
        and (
            _bbox_iou(item["coreBbox"], core_box) >= 0.20
            or _bbox_distance(item["coreBbox"], core_box)
            <= max(12.0, min(core_box[2], core_box[3]) * 0.8)
        )
        for item in candidates
    )


def extract_equipment(
    ocr_items: list[dict[str, Any]],
    crops: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    crop_values = crops or []
    lines: list[dict[str, Any]] = []
    for index, line_items in enumerate(_group_ocr_lines(ocr_items), 1):
        raw_text = " ".join(str(item["raw_text"]).strip() for item in line_items).strip()
        if not raw_text:
            continue
        lines.append(
            {
                "id": index,
                "page": int(line_items[0]["page"]),
                "items": line_items,
                "text": raw_text,
                "bbox": _union_bbox(line_items),
                "classes": _equipment_classes(raw_text),
            }
        )

    anchors: list[dict[str, Any]] = []
    for line in lines:
        item_anchors: list[dict[str, Any]] = []
        for item in line["items"]:
            for class_id in _equipment_classes(str(item["raw_text"])):
                item_anchors.append(
                    {
                        "classId": class_id,
                        "items": [item],
                        "coreBbox": [float(value) for value in item["bbox_page_pixel"]],
                    }
                )
        if not item_anchors:
            item_anchors = [
                {
                    "classId": class_id,
                    "items": list(line["items"]),
                    "coreBbox": list(line["bbox"]),
                }
                for class_id in line["classes"]
            ]
        for item_anchor in item_anchors:
            core_box = item_anchor["coreBbox"]
            if any(
                anchor["classId"] == item_anchor["classId"]
                and anchor["page"] == line["page"]
                and (
                    _bbox_iou(anchor["coreBbox"], core_box) >= 0.20
                    or _bbox_distance(anchor["coreBbox"], core_box) <= 10.0
                )
                for anchor in anchors
            ):
                continue
            crop = _crop_for_box(line["page"], core_box, crop_values)
            anchors.append(
                {
                    **item_anchor,
                    "page": line["page"],
                    "lineIds": {line["id"]},
                    "crop": crop,
                }
            )

    for line in lines:
        if line["classes"]:
            continue
        if classify_text_scope(line["text"]).get("suppress_as_equipment"):
            continue
        line_x, line_y = _bbox_center(line["bbox"])
        choices: list[tuple[float, int]] = []
        for anchor_index, anchor in enumerate(anchors):
            if anchor["page"] != line["page"] or line["id"] in anchor["lineIds"]:
                continue
            crop = anchor["crop"]
            if crop is not None and not _bbox_contains(crop["bbox"], line["bbox"]):
                continue
            anchor_x, anchor_y = _bbox_center(anchor["coreBbox"])
            dx = abs(line_x - anchor_x)
            dy = abs(line_y - anchor_y)
            page_width = float(crop["pageWidth"]) if crop else 5000.0
            page_height = float(crop["pageHeight"]) if crop else 3500.0
            if dy > max(page_height * 0.030, line["bbox"][3] * 4.5):
                continue
            if dx > max(page_width * 0.050, anchor["coreBbox"][2] * 2.2):
                continue
            choices.append((math.hypot(dx * 0.35, dy), anchor_index))
        if choices:
            anchors[min(choices)[1]]["lineIds"].add(line["id"])

    candidates: list[dict[str, Any]] = []
    lines_by_id: dict[int, dict[str, Any]] = {
        int(line["id"]): line for line in lines
    }
    for anchor in sorted(
        anchors,
        key=lambda item: (
            item["page"],
            item["coreBbox"][1],
            item["coreBbox"][0],
        ),
    ):
        context_lines: list[dict[str, Any]] = [
            lines_by_id[line_id]
            for line_id in sorted(anchor["lineIds"])
            if line_id in lines_by_id
        ]
        evidence_items = list(
            {
                str(item["id"]): item
                for line in context_lines
                for item in line["items"]
            }.values()
        )
        raw_text = " | ".join(
            dict.fromkeys(line["text"] for line in context_lines)
        ).strip()
        if not raw_text or classify_text_scope(raw_text).get("suppress_as_equipment"):
            continue
        class_id = str(anchor["classId"])
        core_box = [float(value) for value in anchor["coreBbox"]]
        if _is_duplicate_candidate(candidates, class_id, int(anchor["page"]), core_box):
            continue
        parsed = _sanitize_parser_payload(
            parse_equipment_v11(
                raw_text,
                forced_class=class_id,
                ocr_lines=evidence_items,
            )
        )
        bbox = _union_bbox(evidence_items)
        crop = anchor["crop"]
        equipment_id = f"SLD-EQ-{len(candidates) + 1:05d}"
        fire_group = _fire_group(class_id)
        main_marker = bool(
            re.search(r"(?<![A-Z])(MAIN|INCOMING)(?![A-Z])|주\s*차단기", raw_text, re.I)
        )
        role = (
            "MAIN_BREAKER"
            if fire_group == "BREAKER" and main_marker
            else "BREAKER_CANDIDATE"
            if fire_group == "BREAKER"
            else fire_group
        )
        guidance = _fire_guidance(class_id, fire_group)
        candidates.append(
            {
                "equipmentId": equipment_id,
                "classId": class_id,
                "displayName": (parsed.get("properties") or {}).get(
                    "display_name_ko", class_id
                ),
                "role": role,
                "page": int(anchor["page"]),
                "bbox": bbox,
                "coreBbox": core_box,
                "cropBbox": list(crop["bbox"]) if crop else bbox,
                "cropId": crop.get("cropId") if crop else None,
                "regionId": crop.get("regionId") if crop else None,
                "rawText": raw_text,
                "ocrConfidence": round(
                    sum(float(item.get("confidence", 0.0)) for item in evidence_items)
                    / len(evidence_items),
                    6,
                ),
                "sourceOcrIds": [str(item["id"]) for item in evidence_items],
                "properties": parsed.get("properties") or {},
                "grammarEvidence": {
                    "status": parsed.get("status"),
                    "identityEvidence": parsed.get("identity_evidence"),
                    "warnings": parsed.get("warnings") or [],
                    "fieldProvenance": parsed.get("field_provenance") or [],
                    "validationErrors": parsed.get("validation_errors") or [],
                    "scope": parsed.get("scope"),
                    "explicitAnchors": parsed.get("explicit_anchors") or [],
                },
                "reviewStatus": "REVIEW_REQUIRED",
                "groupingMethod": "upstage_region_crop_anchor_context_v15",
                "ocrModes": list(
                    dict.fromkeys(
                        str(item.get("ocrMode", "FULL_PAGE")) for item in evidence_items
                    )
                ),
                "fireRisk": (
                    {
                        "group": fire_group,
                        "generalRisk": guidance["risk"],
                        "inspectionPoints": guidance["checks"],
                    }
                    if guidance
                    else None
                ),
                "provider": "upstage_document_ocr",
            }
        )
    return candidates


def _deterministic_explanation(equipment: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    for item in equipment:
        counts[str(item["displayName"])] += 1
    focus = [item for item in equipment if item.get("fireRisk")][:40]
    return {
        "overview": (
            f"Upstage OCR 근거에서 설비 후보 {len(equipment)}건을 추출했습니다. "
            "정격과 설비 역할은 원문을 대조해 확인해야 합니다."
        ),
        "facilitySummary": [
            f"{name} {count}건" for name, count in sorted(counts.items())
        ][:20],
        "fireRiskSummary": list(
            dict.fromkeys(
                str(item["fireRisk"]["generalRisk"]) for item in focus if item.get("fireRisk")
            )
        )[:20],
        "keyEquipment": [
            {
                "equipmentId": item["equipmentId"],
                "title": f"{item['displayName']} · {item.get('role') or '설비 후보'}",
                "observedFacts": [f"OCR 원문: {item['rawText']}"],
                "fireRiskFactors": [item["fireRisk"]["generalRisk"]],
                "inspectionPoints": item["fireRisk"]["inspectionPoints"],
                "warning": "OCR 기반 후보이므로 도면 원본과 현장 설비를 대조해야 합니다.",
            }
            for item in focus
        ],
        "limitations": [
            "전기적 연결망과 실제 운전 상태는 추론하지 않았습니다.",
            "OCR에 없는 정격·연료·배터리 종류·절연매질은 미확인입니다.",
            "화재 위험 설명은 일반적인 점검 관점이며 화재 원인 판정이 아닙니다.",
        ],
    }


async def _request_document_ocr(
    settings: Settings,
    cost_gate: AiCostGate,
    source_path: Path,
    source_sha256: str,
    mime_type: str,
    execution_key: str,
) -> tuple[dict[str, Any], str]:
    api_key = settings.upstage_api_key
    if api_key is None:
        raise ValueError("UPSTAGE_API_KEY_REQUIRED")
    model = settings.upstage_document_model
    request_sha256 = sld_ocr_request_hash(model, source_sha256, execution_key)
    reservation = await cost_gate.reserve(
        profile=settings.profile,
        feature_name="sld-document-ocr",
        case_reference=None,
        model=model,
        request_kind="DOCUMENT_PARSE",
        request_sha256=request_sha256,
        reserved_cost_usd=DOCUMENT_MAX_RESERVED_COST_USD,
        unit_price_snapshot={
            "currency": "USD",
            "maximumRequestCost": str(DOCUMENT_MAX_RESERVED_COST_USD),
            "priceVersion": "runtime-configured",
        },
    )
    settled = False
    try:
        async with httpx.AsyncClient(
            base_url=settings.upstage_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            timeout=httpx.Timeout(settings.upstage_document_timeout_seconds),
        ) as client:
            payload, provider_request_id = await _call_upstage_document_ocr(
                client,
                source_path,
                mime_type,
                model,
            )
        if not isinstance(payload, dict):
            raise ValueError("UPSTAGE_DOCUMENT_RESPONSE_INVALID")
        pages = payload.get("pages")
        page_count = len(pages) if isinstance(pages, list) else 1
        await cost_gate.settle(
            reservation,
            status="SUCCESS",
            actual_cost_usd=DOCUMENT_MAX_RESERVED_COST_USD,
            usage={"document_pages": page_count},
            provider_request_id=provider_request_id,
        )
        settled = True
        return payload, str(reservation.reservation_id)
    except Exception as error:
        if not settled:
            await cost_gate.settle(
                reservation,
                status="FAILED",
                actual_cost_usd=DOCUMENT_MAX_RESERVED_COST_USD,
                usage={},
                error_type=type(error).__name__[:80],
            )
        raise


async def _call_upstage_document_ocr(
    client: httpx.AsyncClient,
    source_path: Path,
    mime_type: str,
    model: str,
) -> tuple[dict[str, Any], str | None]:
    with source_path.open("rb") as source:
        response = await client.post(
            "/document-digitization",
            files={
                "document": (
                    source_path.name,
                    source,
                    mime_type or "application/octet-stream",
                )
            },
            data={"model": model, "ocr": "force"},
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("UPSTAGE_DOCUMENT_RESPONSE_INVALID")
    return payload, (
        response.headers.get("x-request-id")
        or response.headers.get("x-upstage-request-id")
    )


def _map_crop_ocr_items(
    payload: dict[str, Any],
    crop: dict[str, Any],
    sequence_start: int,
) -> list[dict[str, Any]]:
    local_items, local_pages = parse_upstage_ocr(payload)
    page_info = local_pages[0] if local_pages else {}
    local_width = float(page_info.get("width") or crop["cropWidth"])
    local_height = float(page_info.get("height") or crop["cropHeight"])
    crop_box = [float(value) for value in crop["bbox"]]
    output = []
    for offset, item in enumerate(local_items, 1):
        local_box = [float(value) for value in item["bbox_page_pixel"]]
        output.append(
            {
                **item,
                "id": f"UPSTAGE-CROP-OCR-{sequence_start + offset:06d}",
                "page": int(crop["page"]),
                "bbox_page_pixel": [
                    crop_box[0] + local_box[0] / local_width * crop_box[2],
                    crop_box[1] + local_box[1] / local_height * crop_box[3],
                    local_box[2] / local_width * crop_box[2],
                    local_box[3] / local_height * crop_box[3],
                ],
                "provider": "upstage_document_ocr_region_crop",
                "ocrMode": "REGION_CORE_2X",
                "cropId": crop["cropId"],
                "regionId": crop["regionId"],
            }
        )
    return output


async def _request_region_ocr(
    settings: Settings,
    cost_gate: AiCostGate,
    crops: list[dict[str, Any]],
    source_sha256: str,
    execution_key: str,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
    api_key = settings.upstage_api_key
    if api_key is None:
        raise ValueError("UPSTAGE_API_KEY_REQUIRED")
    model = settings.upstage_document_model
    output: list[dict[str, Any]] = []
    reservation_ids = []
    failures = []
    async with httpx.AsyncClient(
        base_url=settings.upstage_base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
        timeout=httpx.Timeout(settings.upstage_document_timeout_seconds),
    ) as client:
        for crop in crops:
            request_sha256 = sld_ocr_request_hash(
                model,
                source_sha256,
                f"{execution_key}:{crop['cropId']}",
            )
            reservation = await cost_gate.reserve(
                profile=settings.profile,
                feature_name="sld-region-ocr",
                case_reference=None,
                model=model,
                request_kind="DOCUMENT_PARSE",
                request_sha256=request_sha256,
                reserved_cost_usd=REGION_DOCUMENT_MAX_RESERVED_COST_USD,
                unit_price_snapshot={
                    "currency": "USD",
                    "maximumRequestCost": str(REGION_DOCUMENT_MAX_RESERVED_COST_USD),
                    "priceVersion": "runtime-configured",
                    "scope": "region-core-2x",
                },
            )
            settled = False
            try:
                payload, provider_request_id = await _call_upstage_document_ocr(
                    client,
                    Path(str(crop["path"])),
                    str(crop["mimeType"]),
                    model,
                )
                mapped = _map_crop_ocr_items(payload, crop, len(output))
                await cost_gate.settle(
                    reservation,
                    status="SUCCESS",
                    actual_cost_usd=REGION_DOCUMENT_MAX_RESERVED_COST_USD,
                    usage={"document_pages": 1, "ocr_items": len(mapped)},
                    provider_request_id=provider_request_id,
                )
                settled = True
                reservation_ids.append(str(reservation.reservation_id))
                output.extend(mapped)
            except Exception as error:
                if not settled:
                    await cost_gate.settle(
                        reservation,
                        status="FAILED",
                        actual_cost_usd=REGION_DOCUMENT_MAX_RESERVED_COST_USD,
                        usage={},
                        error_type=type(error).__name__[:80],
                    )
                failures.append(
                    {
                        "cropId": str(crop["cropId"]),
                        "error": type(error).__name__,
                    }
                )
    return output, reservation_ids, failures


def _compact_ocr_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9가-힣]", "", value.upper())


def fuse_upstage_ocr_items(
    full_page_items: list[dict[str, Any]],
    crop_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output = [dict(item, ocrMode=item.get("ocrMode", "FULL_PAGE")) for item in crop_items]
    for item in full_page_items:
        item_box = [float(value) for value in item["bbox_page_pixel"]]
        compact = _compact_ocr_text(str(item["raw_text"]))
        duplicate = next(
            (
                existing
                for existing in output
                if int(existing["page"]) == int(item["page"])
                and _compact_ocr_text(str(existing["raw_text"])) == compact
                and (
                    _bbox_iou(existing["bbox_page_pixel"], item_box) >= 0.15
                    or _bbox_distance(existing["bbox_page_pixel"], item_box) <= 12.0
                )
            ),
            None,
        )
        if duplicate is None:
            output.append(dict(item, ocrMode="FULL_PAGE"))
        elif float(item.get("confidence", 0.0)) > float(
            duplicate.get("confidence", 0.0)
        ):
            duplicate["confidence"] = float(item.get("confidence", 0.0))
    return sorted(
        output,
        key=lambda item: (
            int(item["page"]),
            float(item["bbox_page_pixel"][1]),
            float(item["bbox_page_pixel"][0]),
        ),
    )


def sld_ocr_request_hash(model: str, source_sha256: str, execution_key: str) -> str:
    return hashlib.sha256(
        f"{model}:{source_sha256}:{execution_key}".encode(),
    ).hexdigest()


async def create_analysis(
    engine: AsyncEngine,
    *,
    analysis_id: UUID,
    profile: str,
    building_id: UUID,
    source_file_name: str,
    source_mime_type: str,
    source_size_bytes: int,
    source_sha256: str,
    source_storage_path: str,
    user_id: UUID,
    idempotency_key: str,
    document_model: str,
) -> dict[str, Any]:
    async with engine.begin() as connection:
        building = (
            await connection.execute(
                text("SELECT building_id FROM building WHERE building_id = :building_id"),
                {"building_id": building_id},
            )
        ).scalar_one_or_none()
        if building is None:
            raise SldContractError(404, "BUILDING_NOT_FOUND", "건물을 찾을 수 없습니다.")
        existing = (
            await connection.execute(
                text(
                    """
                    SELECT sld_analysis_id
                    FROM sld_analysis
                    WHERE profile = :profile AND idempotency_key = :idempotency_key
                    """
                ),
                {"profile": profile, "idempotency_key": idempotency_key},
            )
        ).scalar_one_or_none()
        if existing is not None:
            return await analysis_detail(engine, UUID(str(existing)))
        await connection.execute(
            text(
                """
                INSERT INTO sld_analysis (
                    sld_analysis_id, building_id, profile, status,
                    source_file_name, source_mime_type, source_size_bytes,
                    source_sha256, source_storage_path, ocr_model,
                    grammar_version, idempotency_key, created_by
                )
                VALUES (
                    :analysis_id, :building_id, :profile, 'QUEUED',
                    :source_file_name, :source_mime_type, :source_size_bytes,
                    :source_sha256, :source_storage_path, :ocr_model,
                    :grammar_version, :idempotency_key, :user_id
                )
                """
            ),
            {
                "analysis_id": analysis_id,
                "building_id": building_id,
                "profile": profile,
                "source_file_name": source_file_name,
                "source_mime_type": source_mime_type,
                "source_size_bytes": source_size_bytes,
                "source_sha256": source_sha256,
                "source_storage_path": source_storage_path,
                "ocr_model": document_model,
                "grammar_version": GRAMMAR_VERSION,
                "idempotency_key": idempotency_key,
                "user_id": user_id,
            },
        )
    return await analysis_detail(engine, analysis_id)


def _analysis_payload(row: Any) -> dict[str, Any]:
    result = dict(row["result_json"]) if row["result_json"] is not None else None
    return {
        "analysisId": str(row["sld_analysis_id"]),
        "buildingId": str(row["building_id"]),
        "status": row["status"],
        "sourceFileName": row["source_file_name"],
        "sourceMimeType": row["source_mime_type"],
        "sourceSizeBytes": int(row["source_size_bytes"]),
        "sourceSha256": row["source_sha256"],
        "ocrProvider": row["ocr_provider"],
        "ocrModel": row["ocr_model"],
        "grammarVersion": row["grammar_version"],
        "explanationModel": row["explanation_model"],
        "result": result,
        "error": (
            {"code": row["error_code"], "message": row["error_message"]}
            if row["error_code"]
            else None
        ),
        "createdAt": row["created_at"].isoformat(),
        "startedAt": row["started_at"].isoformat() if row["started_at"] else None,
        "completedAt": row["completed_at"].isoformat() if row["completed_at"] else None,
        "version": int(row["version"]),
    }


async def analysis_detail(engine: AsyncEngine, analysis_id: UUID) -> dict[str, Any]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT *
                    FROM sld_analysis
                    WHERE sld_analysis_id = :analysis_id
                    """
                ),
                {"analysis_id": analysis_id},
            )
        ).mappings().one_or_none()
    if row is None:
        raise SldContractError(404, "SLD_ANALYSIS_NOT_FOUND", "분석을 찾을 수 없습니다.")
    return _analysis_payload(row)


async def building_analyses(engine: AsyncEngine, building_id: UUID) -> dict[str, Any]:
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    """
                    SELECT *
                    FROM sld_analysis
                    WHERE building_id = :building_id
                    ORDER BY created_at DESC, sld_analysis_id DESC
                    LIMIT 20
                    """
                ),
                {"building_id": building_id},
            )
        ).mappings().all()
    return {"items": [_analysis_payload(row) for row in rows]}


async def clear_building_analysis_history(
    engine: AsyncEngine,
    *,
    profile: str,
    storage_root: Path,
    source_building_key: str,
) -> dict[str, Any]:
    async with engine.begin() as connection:
        building_id = (
            await connection.execute(
                text(
                    """
                    SELECT building_id
                    FROM building
                    WHERE source_building_key = :source_building_key
                    LIMIT 1
                    """
                ),
                {"source_building_key": source_building_key},
            )
        ).scalar_one_or_none()
        if building_id is None:
            return {
                "buildingId": None,
                "deletedAnalysisCount": 0,
                "deletedStorageCount": 0,
            }
        rows = (
            await connection.execute(
                text(
                    """
                    DELETE FROM sld_analysis
                    WHERE profile = :profile AND building_id = :building_id
                    RETURNING source_storage_path
                    """
                ),
                {"profile": profile, "building_id": building_id},
            )
        ).all()
    root = await asyncio.to_thread(storage_root.resolve)
    deleted_storage_count = 0
    for row in rows:
        source_path = await asyncio.to_thread((root / str(row[0])).resolve)
        analysis_dir = source_path.parent
        if root not in analysis_dir.parents or analysis_dir.parent != root:
            continue
        if analysis_dir.name == "documents":
            continue
        if await asyncio.to_thread(analysis_dir.is_dir):
            await asyncio.to_thread(shutil.rmtree, analysis_dir)
            deleted_storage_count += 1
    return {
        "buildingId": str(building_id),
        "deletedAnalysisCount": len(rows),
        "deletedStorageCount": deleted_storage_count,
    }


async def retry_analysis(engine: AsyncEngine, analysis_id: UUID) -> dict[str, Any]:
    async with engine.begin() as connection:
        result = await connection.execute(
            text(
                """
                UPDATE sld_analysis
                SET status = 'QUEUED', error_code = NULL, error_message = NULL,
                    started_at = NULL, completed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP, version = version + 1
                WHERE sld_analysis_id = :analysis_id
                  AND status IN ('FAILED', 'REVIEW_REQUIRED')
                """
            ),
            {"analysis_id": analysis_id},
        )
        if result.rowcount != 1:
            raise SldContractError(
                409,
                "SLD_ANALYSIS_NOT_RETRYABLE",
                "현재 상태에서는 분석을 다시 실행할 수 없습니다.",
            )
    return await analysis_detail(engine, analysis_id)


async def analysis_source(engine: AsyncEngine, analysis_id: UUID) -> tuple[str, str, str]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT source_storage_path, source_file_name, source_mime_type
                    FROM sld_analysis
                    WHERE sld_analysis_id = :analysis_id
                    """
                ),
                {"analysis_id": analysis_id},
            )
        ).one_or_none()
    if row is None:
        raise SldContractError(404, "SLD_ANALYSIS_NOT_FOUND", "분석을 찾을 수 없습니다.")
    return str(row[0]), str(row[1]), str(row[2])


async def run_sld_analysis(settings: Settings, analysis_id: UUID) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    cost_gate = AiCostGate(settings)
    try:
        async with engine.begin() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        UPDATE sld_analysis
                        SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP,
                            completed_at = NULL, updated_at = CURRENT_TIMESTAMP,
                            error_code = NULL, error_message = NULL,
                            version = version + 1
                        WHERE sld_analysis_id = :analysis_id
                          AND status = 'QUEUED'
                        RETURNING *
                        """
                    ),
                    {"analysis_id": analysis_id},
                )
            ).mappings().one_or_none()
        if row is None:
            return {"analysisId": str(analysis_id), "status": "SKIPPED"}

        execution_key = f"{analysis_id}:v{row['version']}"
        storage_root = Path(settings.sld_storage_root).resolve()  # noqa: ASYNC240
        source_path = (storage_root / str(row["source_storage_path"])).resolve()
        if storage_root not in source_path.parents or not source_path.is_file():
            raise ValueError("SLD_SOURCE_FILE_INVALID")
        ocr_payload, ocr_reservation_id = await _request_document_ocr(
            settings,
            cost_gate,
            source_path,
            str(row["source_sha256"]),
            str(row["source_mime_type"]),
            execution_key,
        )
        full_page_ocr_items, pages = parse_upstage_ocr(ocr_payload)
        crop_dir = source_path.parent / "crops" / f"v{row['version']}"
        crops, box_pipeline = await asyncio.to_thread(
            build_diagram_crops,
            source_path,
            str(row["source_mime_type"]),
            pages,
            full_page_ocr_items,
            crop_dir,
            lambda value: bool(_equipment_classes(value)),
            max_crops=settings.sld_max_region_ocr_crops,
            render_dpi=settings.sld_region_render_dpi,
            upscale=settings.sld_region_crop_upscale,
        )
        region_ocr_items, region_reservation_ids, region_ocr_failures = (
            await _request_region_ocr(
                settings,
                cost_gate,
                crops,
                str(row["source_sha256"]),
                execution_key,
            )
        )
        ocr_items = fuse_upstage_ocr_items(full_page_ocr_items, region_ocr_items)
        equipment = extract_equipment(ocr_items, crops)
        deterministic = _deterministic_explanation(equipment)
        explanation_status = "SUCCEEDED"
        explanation_error = None
        try:
            chat = UpstageChatClient(settings, cost_gate)
            chat_result = await chat.complete_json(
                system_prompt=EXPLANATION_SYSTEM_PROMPT,
                user_prompt=json.dumps(
                    {
                        "execution": {
                            "analysisId": str(analysis_id),
                            "attempt": int(row["version"]),
                        },
                        "document": {
                            "fileName": row["source_file_name"],
                            "pageCount": len(pages),
                            "regionCropCount": len(crops),
                        },
                        "equipment": equipment[:120],
                        "deterministicSummary": deterministic,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                feature_name="sld-fire-risk-explanation",
                privacy_verified=True,
                response_schema=SldExplanation.model_json_schema(by_alias=True),
                schema_name="sld_analysis",
            )
            explanation = SldExplanation.model_validate(chat_result.payload).model_dump(
                by_alias=True
            )
            chat_reservation_id = chat_result.reservation_id
        except Exception as error:
            explanation = deterministic
            chat_reservation_id = None
            explanation_status = "REVIEW_REQUIRED"
            explanation_error = type(error).__name__
        result_json = {
            "schemaVersion": "esafe-sld-analysis/1.0",
            "pipelineVersion": PIPELINE_VERSION,
            "providerPolicy": {
                "ocrProvider": "upstage_document_ocr",
                "paddleUsed": False,
                "legacyCandidateReuse": False,
            },
            "pages": pages,
            "ocrItemCount": len(ocr_items),
            "fullPageOcrItemCount": len(full_page_ocr_items),
            "regionOcrItemCount": len(region_ocr_items),
            "ocrItems": ocr_items,
            "boxPipeline": {
                **box_pipeline,
                "regionOcrFailureCount": len(region_ocr_failures),
                "regionOcrFailures": region_ocr_failures,
            },
            "diagramCrops": public_crop_metadata(crops),
            "equipmentCount": len(equipment),
            "equipment": equipment,
            "explanation": explanation,
            "explanationStatus": explanation_status,
            "explanationError": explanation_error,
            "reservations": {
                "documentOcr": ocr_reservation_id,
                "regionOcr": region_reservation_ids,
                "explanation": chat_reservation_id,
            },
        }
        final_status = "SUCCEEDED" if explanation_status == "SUCCEEDED" else "REVIEW_REQUIRED"
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE sld_analysis
                    SET status = :status, result_json = CAST(:result_json AS jsonb),
                        explanation_model = :explanation_model,
                        completed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        error_code = NULL, error_message = NULL
                    WHERE sld_analysis_id = :analysis_id
                    """
                ),
                {
                    "analysis_id": analysis_id,
                    "status": final_status,
                    "result_json": json.dumps(result_json, ensure_ascii=False),
                    "explanation_model": settings.upstage_chat_model,
                },
            )
        return {
            "analysisId": str(analysis_id),
            "status": final_status,
            "equipmentCount": len(equipment),
        }
    except Exception as error:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE sld_analysis
                    SET status = 'FAILED', error_code = :error_code,
                        error_message = :error_message,
                        completed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE sld_analysis_id = :analysis_id
                    """
                ),
                {
                    "analysis_id": analysis_id,
                    "error_code": type(error).__name__[:80],
                    "error_message": str(error)[:1000],
                },
            )
        raise
    finally:
        await cost_gate.close()
        await engine.dispose()


def new_analysis_id() -> UUID:
    return uuid4()
