from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


V3_PARSER_DIR = (
    Path(__file__).resolve().parents[2]
    / "sld_equipment_ocr_grammar_v3"
    / "parser"
)
if str(V3_PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(V3_PARSER_DIR))

from sld_equipment_parser_v3 import parse_equipment_v3  # noqa: E402


GROUNDING_LABEL = re.compile(r"^E(?:1|2)?$", re.I)
MOF_PATTERN = re.compile(r"\bMOF\b", re.I)
POWER_FUSE_PATTERN = re.compile(r"\bPF\s*(?:X|×)?\s*[123]\b|\bPOWER\s*FUSE\b", re.I)
VOLTAGE_TRANSFORMER_PATTERN = re.compile(
    r"\bVT\s*(?:X|×)?\s*[123]\b|\bPT\s*(?:X|×)?\s*[123]\b|\bPTT\b",
    re.I,
)
PT_RATIO = re.compile(r"\bPT\s*[:.]?\s*\d+(?:\.\d+)?\s*(?:KV|V)?\s*/\s*\d+(?:\.\d+)?\s*V", re.I)
CT_RATIO = re.compile(r"\bCT\s*[:.]?\s*\d+(?:\.\d+)?\s*/\s*[15]\s*A?", re.I)
OVERCURRENT = re.compile(r"과전류\s*강도|OVER\s*CURRENT", re.I)


def parse_equipment_v4(
    raw_text: str,
    *,
    crop_scope: str = "equipment_description",
    ocr_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parsed = parse_equipment_v3(
        raw_text,
        crop_scope=crop_scope,
        ocr_lines=ocr_lines,
    )
    parsed["grammar_version"] = "sld-equipment-grammar/4.0"
    parsed["special_components"] = special_components(raw_text)
    parsed["grounding_label"] = is_grounding_label(raw_text)
    return parsed


def is_grounding_label(raw_text: str) -> bool:
    return bool(GROUNDING_LABEL.fullmatch(str(raw_text).strip()))


def special_components(raw_text: str) -> list[str]:
    text = str(raw_text)
    components: list[str] = []
    if MOF_PATTERN.search(text):
        components.append("MeteringOutfit")
    if POWER_FUSE_PATTERN.search(text):
        components.append("PowerFuse")
    if VOLTAGE_TRANSFORMER_PATTERN.search(text):
        components.append("VoltageTransformer")
    return components


def is_mof_description(raw_text: str) -> bool:
    text = str(raw_text)
    return bool(
        (PT_RATIO.search(text) and CT_RATIO.search(text))
        or (CT_RATIO.search(text) and OVERCURRENT.search(text))
        or (PT_RATIO.search(text) and OVERCURRENT.search(text))
    )


def component_text(raw_text: str, component: str) -> str:
    text = str(raw_text)
    if component == "PowerFuse":
        matches = []
        patterns = (
            re.compile(r"\bPF\s*(?:X|×)?\s*[123]\b", re.I),
            re.compile(r"\bPOWER\s*FUSE\b", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*KV\b(?!\s*/)", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*A\s*FUSE\b", re.I),
            re.compile(r"\bFUSE\s*[:.]?\s*\d+(?:\.\d+)?\s*A\b", re.I),
        )
        for pattern in patterns:
            matches.extend(match.group(0).strip() for match in pattern.finditer(text))
        return " | ".join(dict.fromkeys(matches)) or text.strip()
    if component == "VoltageTransformer":
        matches = []
        patterns = (
            re.compile(r"\b(?:VT|PT)\s*(?:X|×)?\s*[123](?:\([^)]*\))?(?::?\s*MOLD)?", re.I),
            re.compile(r"\bPTT\b", re.I),
            re.compile(r"\b\d+(?:\.\d+)?\s*VA\b", re.I),
        )
        for pattern in patterns:
            matches.extend(match.group(0).strip() for match in pattern.finditer(text))
        ratio_pattern = re.compile(
            r"\b(\d+(?:\.\d+)?)\s*(KV|V)?\s*/\s*(\d+(?:\.\d+)?)\s*V\b",
            re.I,
        )
        ratios = list(ratio_pattern.finditer(text))
        if ratios:
            def primary_volts(match: re.Match[str]) -> float:
                value = float(match.group(1))
                return value * 1000.0 if str(match.group(2) or "").upper() == "KV" else value

            matches.append(max(ratios, key=primary_volts).group(0).strip())
        return " | ".join(dict.fromkeys(matches)) or text.strip()
    fragments = [
        item.strip()
        for item in re.split(r"[|\r\n]+", text)
        if item.strip()
    ]
    if component == "MeteringOutfit":
        patterns = (MOF_PATTERN, PT_RATIO, CT_RATIO, OVERCURRENT)
    else:
        return text.strip()
    selected = [fragment for fragment in fragments if any(pattern.search(fragment) for pattern in patterns)]
    return " | ".join(dict.fromkeys(selected)) or text.strip()


__all__ = [
    "component_text",
    "is_grounding_label",
    "is_mof_description",
    "parse_equipment_v4",
    "special_components",
]
