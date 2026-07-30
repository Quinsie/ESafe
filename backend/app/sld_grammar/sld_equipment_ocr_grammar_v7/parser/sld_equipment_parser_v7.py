from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


GRAMMAR_ROOT = Path(__file__).resolve().parents[2]
V6_PARSER_DIR = GRAMMAR_ROOT / "sld_equipment_ocr_grammar_v6" / "parser"
if str(V6_PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(V6_PARSER_DIR))

from sld_equipment_parser_v6 import (  # noqa: E402
    component_text as component_text_v6,
    is_grounding_label,
    is_mof_description,
    parse_equipment_v6,
    special_components as special_components_v6,
)


CTT = re.compile(r"(?<![A-Z0-9])C\s*\.?\s*T\s*\.?\s*T(?![A-Z0-9])", re.I)
PTT = re.compile(r"(?<![A-Z0-9])P\s*\.?\s*T\s*\.?\s*T(?![A-Z0-9])", re.I)
FUZZY_CTT = re.compile(r"(?<![A-Z0-9])CT[7I](?![A-Z0-9])", re.I)
FUZZY_PTT = re.compile(r"(?<![A-Z0-9])PT[7I](?![A-Z0-9])", re.I)
ATCB = re.compile(r"(?<![A-Z0-9])ATCB(?![A-Z0-9])", re.I)
ATS = re.compile(r"(?<![A-Z0-9])A\s*\.?\s*T\s*\.?\s*S(?![A-Z0-9])", re.I)
FUZZY_ATS = re.compile(r"(?<![A-Z0-9])AT[5$](?![A-Z0-9])", re.I)
SR = re.compile(r"(?<![A-Z0-9])S\s*\.?\s*R(?![A-Z0-9])", re.I)
ELD = re.compile(r"(?<![A-Z0-9])ELD(?:\s*-\s*[A-Z0-9+]+)?(?![A-Z0-9])", re.I)
ZCT = re.compile(r"(?<![A-Z0-9])ZCT(?:\s*[X×]\s*\d+)?(?![A-Z0-9])|영상\s*변류기", re.I)
PANEL_ZCT_CONFUSION = re.compile(r"(?<![A-Z0-9])CT\s*[X×]\s*[38](?![A-Z0-9])", re.I)
POLE = re.compile(r"(?<!\d)([234])\s*P\b", re.I)
CURRENT = re.compile(r"(?<!\d)(\d{2,5}(?:\.\d+)?)\s*(AT|A)\b", re.I)
CCT_COUNT = re.compile(r"(?<!\d)(\d{1,3})\s*CCT(?:\s*[X×]\s*\d+)?\b", re.I)
CCT_MULTIPLICITY = re.compile(r"(?<!\d)(\d{1,3})\s*CCT\s*[X×]\s*(\d+)\b", re.I)
CORRUPT_CCT_COUNT = re.compile(r"(?<!\d)(\d{1,3})\s*CC\b", re.I)


CLASS_METADATA = {
    "CurrentTransformerTestTerminal": ("CTT", "CT 시험단자(CTT)"),
    "PotentialTransformerTestTerminal": ("PTT", "PT 시험단자(PTT)"),
    "SeriesReactor": ("SR", "직렬 리액터(SR)"),
    "EarthLeakageDetector": ("ELD", "누전 검출기(ELD)"),
    "ZeroSequenceCurrentTransformer": ("ZCT", "영상 변류기(ZCT)"),
    "AutomaticTransferSwitch": ("ATS", "자동 절체 스위치(ATS)"),
    "AutomaticTransferCircuitBreaker": ("ATCB", "자동 절체 차단기(ATCB)"),
}


def _fragments(raw_text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[|\r\n]+", str(raw_text)) if part.strip()]


def _context_confirms(context: dict[str, Any], class_id: str) -> bool:
    return bool(
        context.get("forced_class_id") == class_id
        or context.get("vl_confirmed_class") == class_id
        or context.get("symbol_hint")
        == {
            "CurrentTransformerTestTerminal": "CTT_SYMBOL",
            "PotentialTransformerTestTerminal": "PTT_SYMBOL",
            "SeriesReactor": "SERIES_REACTOR_SYMBOL",
            "ZeroSequenceCurrentTransformer": "ZCT_SYMBOL",
            "AutomaticTransferSwitch": "ATS_SYMBOL",
        }.get(class_id)
    )


def detect_v7_class(raw_text: str, context: dict[str, Any] | None = None) -> str | None:
    """Detect the identity with long-token precedence and gated OCR repairs."""
    text = str(raw_text)
    context = dict(context or {})
    forced = context.get("forced_class_id")
    if forced:
        return str(forced)
    if ATCB.search(text):
        return "AutomaticTransferCircuitBreaker"
    if CTT.search(text) or (FUZZY_CTT.search(text) and _context_confirms(context, "CurrentTransformerTestTerminal")):
        return "CurrentTransformerTestTerminal"
    if PTT.search(text) or (FUZZY_PTT.search(text) and _context_confirms(context, "PotentialTransformerTestTerminal")):
        return "PotentialTransformerTestTerminal"
    if ELD.search(text):
        return "EarthLeakageDetector"
    if ZCT.search(text):
        return "ZeroSequenceCurrentTransformer"
    if PANEL_ZCT_CONFUSION.search(text) and context.get("panel_repetition_zct_confirmed"):
        return "ZeroSequenceCurrentTransformer"
    if ATS.search(text):
        return "AutomaticTransferSwitch"
    if FUZZY_ATS.search(text):
        signature = bool(POLE.search(text) and CURRENT.search(text))
        if signature or _context_confirms(context, "AutomaticTransferSwitch"):
            return "AutomaticTransferSwitch"
    if SR.search(text):
        if (
            _context_confirms(context, "SeriesReactor")
            or context.get("series_branch_confirmed")
            or re.search(r"SERIES\s+REACTOR|직렬\s*리액터", text, re.I)
        ):
            return "SeriesReactor"
    return None


def special_components(raw_text: str, context: dict[str, Any] | None = None) -> list[str]:
    target = detect_v7_class(raw_text, context)
    output = [target] if target else []
    for component in special_components_v6(raw_text):
        if component not in output:
            output.append(component)
    return output


def component_text(raw_text: str, component: str) -> str:
    text = str(raw_text)
    if component not in CLASS_METADATA:
        return component_text_v6(text, component)
    fragments = _fragments(text)
    if component == "EarthLeakageDetector":
        selected = [part for part in fragments if ELD.search(part) or CCT_COUNT.search(part) or CORRUPT_CCT_COUNT.search(part)]
    elif component in {"AutomaticTransferSwitch", "AutomaticTransferCircuitBreaker"}:
        selected = [part for part in fragments if ATS.search(part) or ATCB.search(part) or POLE.search(part) or CURRENT.search(part)]
    elif component == "ZeroSequenceCurrentTransformer":
        selected = [part for part in fragments if ZCT.search(part) or PANEL_ZCT_CONFUSION.search(part)]
    else:
        selected = [part for part in fragments if detect_v7_class(part, {"forced_class_id": component}) == component]
    return " | ".join(dict.fromkeys(selected)) or CLASS_METADATA[component][0]


def _v7_properties(text: str, class_id: str, context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    aliases, display_name = CLASS_METADATA[class_id]
    properties: dict[str, Any] = {"search_aliases": [aliases], "display_name_ko": display_name}
    repairs: list[str] = []
    if class_id == "CurrentTransformerTestTerminal":
        properties["terminal_function"] = "CT_TEST"
        if FUZZY_CTT.search(text):
            repairs.append("CT7/CTI->CTT(context-confirmed)")
    elif class_id == "PotentialTransformerTestTerminal":
        properties["terminal_function"] = "PT_TEST"
        if FUZZY_PTT.search(text):
            repairs.append("PT7/PTI->PTT(context-confirmed)")
    elif class_id == "SeriesReactor":
        properties["reactor_type"] = "SERIES"
    elif class_id == "EarthLeakageDetector":
        model = ELD.search(text)
        if model:
            properties["model"] = re.sub(r"\s+", "", model.group(0).upper())
        counts = [int(value) for value in CCT_COUNT.findall(text)]
        if not counts and context.get("vl_confirmed_cct"):
            counts = [int(value) for value in CORRUPT_CCT_COUNT.findall(text)]
            if counts:
                repairs.append("CC->CCT(2x-VL-confirmed)")
        if counts:
            properties["circuit_counts"] = counts
            if len(counts) == 1:
                properties["circuit_count"] = counts[0]
        multiplicity = CCT_MULTIPLICITY.search(text)
        if multiplicity:
            properties["circuit_group_count"] = int(multiplicity.group(2))
            properties["circuit_count_per_group"] = int(multiplicity.group(1))
        properties["cct_is_circuit_count_not_ct_equipment"] = True
    elif class_id == "ZeroSequenceCurrentTransformer":
        properties["application"] = "EARTH_LEAKAGE_SENSING"
        if PANEL_ZCT_CONFUSION.search(text):
            repairs.append("CTx3/CTx8->ZCT(panel-repeat+2x-VL)")
    elif class_id in {"AutomaticTransferSwitch", "AutomaticTransferCircuitBreaker"}:
        pole = POLE.search(text)
        current = CURRENT.search(text)
        if pole:
            properties["pole_count"] = int(pole.group(1))
        if current:
            properties["rated_current_a"] = float(current.group(1))
            properties["current_notation"] = current.group(2).upper()
        if FUZZY_ATS.search(text):
            repairs.append("AT5/AT$->ATS(signature-or-2x-VL)")
    return properties, repairs


def parse_equipment_v7(
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
    target = detect_v7_class(text, context)
    base = parse_equipment_v6(text, forced_class=target or forced_class, crop_scope=crop_scope, ocr_lines=ocr_lines)
    if target in CLASS_METADATA:
        properties, repairs = _v7_properties(text, target, context)
        inherited = dict(base.get("properties") or {})
        inherited.update(properties)
        base.update(
            {
                "class_id": target,
                "pipeline_class": target,
                "identity_evidence": component_text(text, target).split(" | ", 1)[0],
                "properties": inherited,
                "normalization_repairs_v7": repairs,
                "status": "REVIEW_REQUIRED",
            }
        )
    base["grammar_version"] = "sld-equipment-grammar/7.0"
    base["special_components"] = special_components(text, context)
    base["precedence"] = ["ATCB_BEFORE_ATS", "CTT_BEFORE_CT", "PTT_BEFORE_PT", "ZCT_BEFORE_CT"]
    base["context_gated_repairs"] = True
    return base


__all__ = [
    "component_text",
    "detect_v7_class",
    "is_grounding_label",
    "is_mof_description",
    "parse_equipment_v7",
    "special_components",
]
