from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


GRAMMAR_ROOT = Path(__file__).resolve().parents[2]
V4_PARSER_DIR = GRAMMAR_ROOT / "sld_equipment_ocr_grammar_v4" / "parser"
PLUS_PARENT = GRAMMAR_ROOT / "sld_equipment_ocr_grammar_plus"
for import_root in (V4_PARSER_DIR, PLUS_PARENT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from sld_equipment_parser_v4 import (  # noqa: E402
    is_grounding_label,
    is_mof_description,
    parse_equipment_v4,
)
from sld_equipment_ocr_grammar_v2.parser.sld_equipment_parser import (  # noqa: E402
    parse_equipment as parse_equipment_plus,
)


MOF = re.compile(r"\bMOF\b", re.I)
CT = re.compile(
    r"\bCT\s*(?:X|×)\s*[123]\b|\bCT\b\s*[:.]?\s*\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*A\b",
    re.I,
)
VT = re.compile(
    r"\b(?:VT|PT)\s*(?:X|×)\s*[123]\b|\bVT\b[^|\r\n]{0,80}\d+(?:\.\d+)?\s*(?:KV|V)?\s*/\s*\d+(?:\.\d+)?\s*V\b",
    re.I,
)
PF = re.compile(r"\bPF\s*(?:X|×)\s*[123]\b|\bPOWER\s*FUSE\b", re.I)
CTT = re.compile(r"(?<![A-Z0-9])CTT(?![A-Z0-9])", re.I)
PTT = re.compile(r"(?<![A-Z0-9])PTT(?![A-Z0-9])", re.I)
DIGITAL_METER = re.compile(r"\bDIGITAL\s+METER\b", re.I)
LBS_ACCESSORY_FUSE = re.compile(r"\bLBS\b.*\bWITH\s+\d+(?:\.\d+)?\s*A\s+POWER\s+FUSE\b", re.I | re.S)

ALIASES = {
    "CurrentTransformer": ["CT", "CURRENT TRANSFORMER", "변류기"],
    "VoltageTransformer": ["VT", "PT", "VOLTAGE TRANSFORMER", "계기용 변압기"],
    "PowerFuse": ["PF", "POWER FUSE", "전력퓨즈"],
    "CurrentTransformerTestTerminal": ["CTT", "CT TEST TERMINAL"],
    "PotentialTransformerTestTerminal": ["PTT", "PT TEST TERMINAL"],
}

DISPLAY_NAMES_KO = {
    "CurrentTransformer": "변류기(CT)",
    "VoltageTransformer": "계기용 변압기(VT/PT)",
    "PowerFuse": "전력퓨즈(PF)",
    "CurrentTransformerTestTerminal": "CT 시험단자(CTT)",
    "PotentialTransformerTestTerminal": "PT 시험단자(PTT)",
}


def special_components(raw_text: str) -> list[str]:
    text = str(raw_text)
    if MOF.search(text):
        return ["MeteringOutfit"]
    components: list[str] = []
    if CTT.search(text):
        components.append("CurrentTransformerTestTerminal")
    if PTT.search(text):
        components.append("PotentialTransformerTestTerminal")
    if CT.search(text):
        components.append("CurrentTransformer")
    if VT.search(text):
        components.append("VoltageTransformer")
    if PF.search(text) and not DIGITAL_METER.search(text) and not LBS_ACCESSORY_FUSE.search(text):
        components.append("PowerFuse")
    return components


def _fragments(raw_text: str) -> list[str]:
    return [
        fragment.strip()
        for fragment in re.split(r"[|\r\n]+", str(raw_text))
        if fragment.strip()
    ]


def _largest_voltage_ratio(text: str) -> str | None:
    pattern = re.compile(
        r"\b(\d+(?:\.\d+)?)\s*(KV|V)?\s*/\s*(\d+(?:\.\d+)?)\s*V\b",
        re.I,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return None

    def primary_volts(match: re.Match[str]) -> float:
        value = float(match.group(1))
        return value * 1000.0 if str(match.group(2) or "").upper() == "KV" else value

    return max(matches, key=primary_volts).group(0).strip()


def component_text(raw_text: str, component: str) -> str:
    text = str(raw_text)
    fragments = _fragments(text)
    if component == "MeteringOutfit":
        selected = [
            fragment
            for fragment in fragments
            if MOF.search(fragment)
            or re.search(r"\b(?:PT|CT)\s*[:.]?\s*\d", fragment, re.I)
            or re.search(r"과전류\s*강도|OVER\s*CURRENT", fragment, re.I)
        ]
        return " | ".join(dict.fromkeys(selected)) or text.strip()
    if component == "CurrentTransformerTestTerminal":
        return "CTT"
    if component == "PotentialTransformerTestTerminal":
        return "PTT"
    if component == "CurrentTransformer":
        patterns = (
            re.compile(r"\bCT\s*(?:X|×)\s*[123]\b", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*A\b", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*VA\b", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*CL\b", re.I),
        )
        selected = [match.group(0).strip() for pattern in patterns for match in pattern.finditer(text)]
        return " | ".join(dict.fromkeys(selected)) or text.strip()
    if component == "VoltageTransformer":
        patterns = (
            re.compile(r"\b(?:VT|PT)\s*(?:X|×)\s*[123](?:\([^)]*\))?(?::?\s*MOLD)?", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*VA\b", re.I),
        )
        selected = [match.group(0).strip() for pattern in patterns for match in pattern.finditer(text)]
        ratio = _largest_voltage_ratio(text)
        if ratio:
            selected.append(ratio)
        selected = [fragment for fragment in selected if not PTT.fullmatch(fragment.strip())]
        return " | ".join(dict.fromkeys(selected)) or text.strip()
    if component == "PowerFuse":
        patterns = (
            re.compile(r"\bPF\s*(?:X|×)\s*[123]\b", re.I),
            re.compile(r"\bPOWER\s*FUSE\b", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*KV\b", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*AF\b", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*A\s*FUSE\b", re.I),
            re.compile(r"\bFUSE\s*[:.]?\s*\d+(?:\.\d+)?\s*A\b", re.I),
        )
        selected = [match.group(0).strip() for pattern in patterns for match in pattern.finditer(text)]
        return " | ".join(dict.fromkeys(selected)) or text.strip()
    return text.strip()


def _manual_special_properties(text: str, component: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    quantity = re.search(r"\b(?:CT|VT|PT|PF)\s*(?:X|×)\s*([123])\b", text, re.I)
    if quantity:
        properties["quantity"] = int(quantity.group(1))
    if component == "CurrentTransformer":
        ratio = re.search(r"\b(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*A\b", text, re.I)
        if ratio:
            properties["ct_ratio"] = {
                "primary_a": float(ratio.group(1)),
                "secondary_a": float(ratio.group(2)),
            }
    elif component == "VoltageTransformer":
        burden = re.search(r"\b(\d+(?:\.\d+)?)\s*VA\b", text, re.I)
        if burden:
            properties["burden_va"] = float(burden.group(1))
        if re.search(r"\bMOLD\b", text, re.I):
            properties["construction"] = "MOLD"
    elif component == "PowerFuse":
        voltage = re.search(r"\b(\d+(?:\.\d+)?)\s*KV\b", text, re.I)
        holder = re.search(r"\b(\d+(?:\.\d+)?)\s*AF\b", text, re.I)
        link = re.search(
            r"(?:\b(\d+(?:\.\d+)?)\s*A\s*FUSE\b|\bFUSE\s*[:.]?\s*(\d+(?:\.\d+)?)\s*A\b)",
            text,
            re.I,
        )
        if voltage:
            properties["rated_voltage_v"] = float(voltage.group(1)) * 1000.0
        if holder:
            properties["fuse_holder_frame_current_a"] = float(holder.group(1))
        if link:
            properties["fuse_link_current_a"] = float(link.group(1) or link.group(2))
    elif component == "CurrentTransformerTestTerminal":
        properties["terminal_function"] = "CT_TEST"
    elif component == "PotentialTransformerTestTerminal":
        properties["terminal_function"] = "PT_TEST"
    return properties


def parse_equipment_v5(
    raw_text: str,
    *,
    crop_scope: str = "equipment_description",
    ocr_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = parse_equipment_v4(raw_text, crop_scope=crop_scope, ocr_lines=ocr_lines)
    components = special_components(raw_text)
    special = next(
        (
            component
            for component in components
            if component
            in {
                "CurrentTransformer",
                "VoltageTransformer",
                "PowerFuse",
                "CurrentTransformerTestTerminal",
                "PotentialTransformerTestTerminal",
            }
        ),
        None,
    )
    plus_input = raw_text
    if special == "VoltageTransformer":
        plus_input = re.sub(r"\bPT\s*(?:X|×)", "VTx", plus_input, flags=re.I)
    plus = parse_equipment_plus(plus_input, crop_scope=crop_scope)
    if special:
        base["class_id"] = special
        base["pipeline_class"] = special
        base["identity_evidence"] = special
        base["status"] = "REVIEW_REQUIRED"
        properties = dict(plus.get("properties") or {}) if plus.get("class_id") == special else {}
        properties.update(_manual_special_properties(raw_text, special))
        properties["search_aliases"] = ALIASES[special]
        properties["display_name_ko"] = DISPLAY_NAMES_KO[special]
        base["properties"] = properties
    base["grammar_version"] = "sld-equipment-grammar/5.0-plus"
    base["grammar_plus_parser"] = {
        "source": "sld_equipment_ocr_grammar_plus/sld_equipment_ocr_grammar_v2",
        "class_id": plus.get("class_id"),
        "properties": plus.get("properties", {}),
        "normalization_repairs": plus.get("normalization_repairs", []),
    }
    base["special_components"] = components
    return base


__all__ = [
    "component_text",
    "is_grounding_label",
    "is_mof_description",
    "parse_equipment_v5",
    "special_components",
]
