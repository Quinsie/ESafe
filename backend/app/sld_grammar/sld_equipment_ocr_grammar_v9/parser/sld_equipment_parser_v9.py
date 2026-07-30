from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


GRAMMAR_ROOT = Path(__file__).resolve().parents[2]
V8_PARSER_DIR = GRAMMAR_ROOT / "sld_equipment_ocr_grammar_v8" / "parser"
if str(V8_PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(V8_PARSER_DIR))

from sld_equipment_parser_v8 import (  # noqa: E402
    detect_v8_class,
    is_grounding_label,
    is_mof_description,
    parse_equipment_v8,
)


ZCT_EXACT = re.compile(r"^\s*Z\s*\.?\s*C\s*\.?\s*T\s*$", re.I)
CT_QUANTITY = re.compile(r"^\s*C\s*\.?\s*T\s*[X×]\s*([38])\s*$", re.I)


def detect_v9_class(raw_text: str, context: dict[str, Any] | None = None) -> str | None:
    context = dict(context or {})
    if context.get("forced_class_id"):
        return str(context["forced_class_id"])
    text = str(raw_text)
    if ZCT_EXACT.fullmatch(text):
        return "ZeroSequenceCurrentTransformer"
    if CT_QUANTITY.fullmatch(text):
        return "CurrentTransformer"
    return detect_v8_class(text, context)


def parse_equipment_v9(
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
    target = detect_v9_class(text, context)
    parsed = parse_equipment_v8(
        text,
        forced_class=target or forced_class,
        context=context,
        crop_scope=crop_scope,
        ocr_lines=ocr_lines,
    )
    if not parsed.get("class_id") and (target or forced_class):
        parsed["class_id"] = target or forced_class
    properties = dict(parsed.get("properties") or {})
    ct_quantity = CT_QUANTITY.fullmatch(text)
    if ct_quantity and (target or forced_class) == "CurrentTransformer":
        properties["quantity"] = int(ct_quantity.group(1))
        properties["quantity_source"] = "EXPLICIT_CTxN"
    parsed["properties"] = properties
    parsed["grammar_version"] = "sld-equipment-grammar/9.0"
    parsed["zct_ctx_same_row_policy"] = {
        "independent_tokens": True,
        "zct_requires_zct_bbox": True,
        "ctx_bbox_never_substitutes_for_zct": True,
        "ctx_is_preserved_as_current_transformer_quantity": True,
    }
    parsed["precedence"] = [
        "EXACT_ZCT_BBOX_BEFORE_ROW_ASSOCIATION",
        "CTxN_NEVER_REWRITTEN_AS_ZCT",
        "ATCB_BEFORE_ATS",
        "CTT_BEFORE_CT",
        "PTT_BEFORE_PT",
        "ONE_EXPLICIT_ANCHOR_ONE_OBJECT",
    ]
    return parsed


__all__ = [
    "detect_v9_class",
    "is_grounding_label",
    "is_mof_description",
    "parse_equipment_v9",
]
