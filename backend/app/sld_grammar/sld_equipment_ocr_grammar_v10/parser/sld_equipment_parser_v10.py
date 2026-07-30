from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


GRAMMAR_ROOT = Path(__file__).resolve().parents[2]
V9_PARSER_DIR = GRAMMAR_ROOT / "sld_equipment_ocr_grammar_v9" / "parser"
if str(V9_PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(V9_PARSER_DIR))

from sld_equipment_parser_v9 import (  # noqa: E402
    detect_v9_class,
    is_grounding_label,
    is_mof_description,
    parse_equipment_v9,
)


DRY_TRANSFORMER = re.compile(
    r"(?<![A-Z0-9])TR\s*\.?\s*\(\s*DRY(?:\s+TYPE)?\s*\)",
    re.I,
)
CAPACITY_KVA = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*KVA\b", re.I)
PHASE = re.compile(r"(?<!\d)([13])\s*(?:[ØΦφ]|PH|PHASE)\b", re.I)
VOLTAGE_RATIO = re.compile(
    r"(?<!\d)(\d{2,5}(?:\.\d+)?)\s*/\s*(\d{2,5}(?:\.\d+)?)\s*V\b",
    re.I,
)
OCR_PHASE_CAPACITY = re.compile(r"^\s*3[0O]?\s+(\d+(?:\.\d+)?)\s*KVA\s*$", re.I)


def detect_v10_class(raw_text: str, context: dict[str, Any] | None = None) -> str | None:
    context = dict(context or {})
    if context.get("forced_class_id"):
        return str(context["forced_class_id"])
    if DRY_TRANSFORMER.search(str(raw_text)):
        return "DryTypeTransformer"
    return detect_v9_class(str(raw_text), context)


def parse_equipment_v10(
    raw_text: str,
    *,
    forced_class: str | None = None,
    context: dict[str, Any] | None = None,
    crop_scope: str = "equipment_description",
    ocr_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = dict(context or {})
    if forced_class:
        context["forced_class_id"] = forced_class
    text = str(raw_text)
    target = detect_v10_class(text, context)
    parsed = parse_equipment_v9(
        text,
        forced_class=target or forced_class,
        context=context,
        crop_scope=crop_scope,
        ocr_lines=ocr_lines,
    )
    if not parsed.get("class_id") and (target or forced_class):
        parsed["class_id"] = target or forced_class
    properties = dict(parsed.get("properties") or {})
    if (target or forced_class) == "DryTypeTransformer":
        properties["construction"] = "DRY"
        capacity = CAPACITY_KVA.search(text)
        if capacity:
            properties["capacity_kva"] = float(capacity.group(1))
        ocr_capacity = OCR_PHASE_CAPACITY.search(text.split("|")[-1])
        if ocr_capacity and "capacity_kva" not in properties:
            properties["capacity_kva"] = float(ocr_capacity.group(1))
            properties["phase_ocr_repair"] = "30/3O->3PHASE"
        phase = PHASE.search(text)
        if phase:
            properties["phase_count"] = int(phase.group(1))
        elif re.search(r"(?:^|\|)\s*3[0O]?\s+\d+\s*KVA", text, re.I):
            properties["phase_count"] = 3
            properties["phase_ocr_repair"] = "30/3O->3PHASE"
        ratio = VOLTAGE_RATIO.search(text)
        if ratio:
            properties["voltage_ratio_v"] = [
                float(ratio.group(1)),
                float(ratio.group(2)),
            ]
    parsed["properties"] = properties
    parsed["grammar_version"] = "sld-equipment-grammar/10.0"
    parsed["multiline_policy"] = {
        "dry_transformer_anchor": "TR.(DRY) or TR(DRY TYPE)",
        "attach_below_capacity_and_voltage": True,
        "local_paddle_geometry_is_authoritative": True,
    }
    return parsed


__all__ = [
    "detect_v10_class",
    "is_grounding_label",
    "is_mof_description",
    "parse_equipment_v10",
]
