from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


GRAMMAR_ROOT = Path(__file__).resolve().parents[2]
V7_PARSER_DIR = GRAMMAR_ROOT / "sld_equipment_ocr_grammar_v7" / "parser"
if str(V7_PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(V7_PARSER_DIR))

from sld_equipment_parser_v7 import (  # noqa: E402
    component_text as component_text_v7,
    detect_v7_class,
    is_grounding_label,
    is_mof_description,
    parse_equipment_v7,
    special_components as special_components_v7,
)


ATCB = re.compile(r"(?<![A-Z0-9])ATCB(?![A-Z0-9])", re.I)
FUSED_ATS = re.compile(r"(?<![A-Z0-9])ATS(?:A)?\s*([234])\s*P(?![A-Z0-9])", re.I)
PIT_AS_PTT = re.compile(r"^\s*P[I1]T\s*$", re.I)
SINGLE_C = re.compile(r"^\s*C\s*$", re.I)
ACB_QUANTITY = re.compile(r"(?<![A-Z0-9])ACB\s*[X×]\s*(\d+)(?![A-Z0-9])", re.I)
POLE = re.compile(r"(?<!\d)([234])\s*P\b", re.I)
PROTECTION_FUNCTION = re.compile(r"(?<![A-Z0-9])(W/?OCR|OCR|OCGR|OCGF|UVR|OVR)(?![A-Z0-9])", re.I)
METER_CLASSES = {"Meter", "DigitalMultifunctionMeter"}


def _confirmed(context: dict[str, Any], class_id: str) -> bool:
    return bool(
        context.get("vl_confirmed_class") == class_id
        or context.get("forced_class_id") == class_id
        or context.get("repeated_terminal_layout")
        or context.get("symbol_hint")
        == {
            "CurrentTransformerTestTerminal": "CTT_SYMBOL",
            "PotentialTransformerTestTerminal": "PTT_SYMBOL",
        }.get(class_id)
    )


def detect_v8_class(raw_text: str, context: dict[str, Any] | None = None) -> str | None:
    text = str(raw_text)
    context = dict(context or {})
    forced = context.get("forced_class_id")
    if forced:
        return str(forced)
    if ATCB.search(text):
        return "AutomaticTransferCircuitBreaker"
    inherited = detect_v7_class(text, context)
    if inherited:
        return inherited
    if FUSED_ATS.search(text):
        return "AutomaticTransferSwitch"
    if PIT_AS_PTT.fullmatch(text) and _confirmed(context, "PotentialTransformerTestTerminal"):
        return "PotentialTransformerTestTerminal"
    if SINGLE_C.fullmatch(text) and _confirmed(context, "CurrentTransformerTestTerminal"):
        return "CurrentTransformerTestTerminal"
    if context.get("panel_row_zct_confirmed"):
        return "ZeroSequenceCurrentTransformer"
    return None


def component_text(raw_text: str, component: str) -> str:
    text = str(raw_text)
    if component == "AutomaticTransferSwitch" and FUSED_ATS.search(text):
        pole = FUSED_ATS.search(text).group(1)
        return f"ATS {pole}P"
    if component == "PotentialTransformerTestTerminal" and PIT_AS_PTT.fullmatch(text):
        return "PTT"
    if component == "CurrentTransformerTestTerminal" and SINGLE_C.fullmatch(text):
        return "CTT"
    return component_text_v7(text, component)


def special_components(raw_text: str, context: dict[str, Any] | None = None) -> list[str]:
    target = detect_v8_class(raw_text, context)
    output = [target] if target else []
    for component in special_components_v7(raw_text, context):
        if component not in output:
            output.append(component)
    return output


def parse_equipment_v8(
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
    target = detect_v8_class(text, context)
    normalized = text
    repairs: list[str] = []
    fused_ats = FUSED_ATS.search(normalized)
    if fused_ats:
        normalized = FUSED_ATS.sub(f"ATS {fused_ats.group(1)}P", normalized)
        repairs.append("ATSA4P/ATS4P->ATS 4P")
    if target == "PotentialTransformerTestTerminal" and PIT_AS_PTT.fullmatch(normalized):
        normalized = "PTT"
        repairs.append("PIT->PTT(repeated-layout-or-2x-VL)")
    if target == "CurrentTransformerTestTerminal" and SINGLE_C.fullmatch(normalized):
        normalized = "CTT"
        repairs.append("C->CTT(repeated-layout+2x-VL)")
    base = parse_equipment_v7(
        normalized,
        forced_class=target or forced_class,
        context=context,
        crop_scope=crop_scope,
        ocr_lines=ocr_lines,
    )
    class_id = str(base.get("class_id") or target or forced_class or "")
    properties = dict(base.get("properties") or {})
    quantity = ACB_QUANTITY.search(text)
    if class_id == "AirCircuitBreaker" and quantity:
        properties["quantity"] = int(quantity.group(1))
        properties["quantity_source"] = "EXPLICIT_ACBxN"
    if class_id == "AutomaticTransferSwitch" and fused_ats:
        properties["pole_count"] = int(fused_ats.group(1))
    if class_id in METER_CLASSES:
        functions = list(dict.fromkeys(match.group(1).upper() for match in PROTECTION_FUNCTION.finditer(text)))
        if functions:
            properties["embedded_protection_functions"] = functions
            properties["protection_rows_are_meter_properties"] = True
    if class_id in {
        "CurrentTransformerTestTerminal",
        "PotentialTransformerTestTerminal",
        "ZeroSequenceCurrentTransformer",
        "AutomaticTransferSwitch",
    }:
        base["identity_evidence"] = component_text(text, class_id)
    base["properties"] = properties
    base["normalization_repairs_v8"] = repairs
    base["grammar_version"] = "sld-equipment-grammar/8.0"
    base["special_components"] = special_components(text, context)
    base["precedence"] = [
        "ATCB_BEFORE_ATS",
        "CTT_BEFORE_CT",
        "PTT_BEFORE_PT",
        "ZCT_BEFORE_CT",
        "ONE_EXPLICIT_ANCHOR_ONE_OBJECT",
    ]
    base["one_explicit_anchor_one_object"] = True
    return base


__all__ = [
    "component_text",
    "detect_v8_class",
    "is_grounding_label",
    "is_mof_description",
    "parse_equipment_v8",
    "special_components",
]
