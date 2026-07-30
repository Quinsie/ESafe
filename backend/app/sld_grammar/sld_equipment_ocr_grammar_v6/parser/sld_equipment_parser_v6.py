from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


GRAMMAR_ROOT = Path(__file__).resolve().parents[2]
V5_PARSER_DIR = GRAMMAR_ROOT / "sld_equipment_ocr_grammar_v5" / "parser"
PLUS_PARENT = GRAMMAR_ROOT / "sld_equipment_ocr_grammar_plus"
for import_root in (V5_PARSER_DIR, PLUS_PARENT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from sld_equipment_parser_v5 import (  # noqa: E402
    component_text as component_text_v5,
    is_grounding_label,
    is_mof_description,
    parse_equipment_v5,
    special_components as special_components_v5,
)
from sld_equipment_ocr_grammar_v2.parser.sld_equipment_parser import (  # noqa: E402
    parse_equipment as parse_equipment_plus,
)


CTOD = re.compile(r"(?<![A-Z0-9])CTOD(?![A-Z0-9])", re.I)
CTOD_DESCRIPTION = re.compile(r"변류기\s*2\s*차.*(?:개방|OPEN).*(?:보호|방지)", re.I)
STATIC_CAPACITOR = re.compile(r"(?<![A-Z0-9])S\s*\.?\s*C(?![A-Z0-9])", re.I)
SURGE_ARRESTER = re.compile(r"(?<![A-Z0-9])SA\s*[X×]\s*\d+", re.I)
LIGHTNING_ARRESTER = re.compile(r"(?<![A-Z0-9])LA\s*[X×]\s*\d+", re.I)
TRANSFORMER = re.compile(
    r"(?<![A-Z0-9])(?:TRANSFORMER\s*[-#]?\s*\d+|TR\s*[.#]?\s*\d+|TR\s*\.\s*\(\s*DRY\s*\))",
    re.I,
)
DM_TOKEN = re.compile(r"(?<![A-Z0-9])DM(?![A-Z0-9])", re.I)
VAR_TOKEN = re.compile(r"(?<![A-Z0-9])VAR(?![A-Z0-9])", re.I)
PF_IDENTITY = re.compile(r"(?<![A-Z0-9])PF\s*[X×]\s*\d+", re.I)
FUSE_RATING = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*A\s*FUSE\b|\bFUSE\s*[:.]?\s*\d+(?:\.\d+)?\s*A\b)",
    re.I,
)


CLASS_METADATA = {
    "CurrentTransformerOpenCircuitProtectionDevice": {
        "aliases": ["CTOD", "변류기 2차 개방 방지 보호장치"],
        "display_name_ko": "변류기 2차 개방 방지 보호장치(CTOD)",
    },
    "StaticCapacitor": {
        "aliases": ["SC", "S.C", "STATIC CAPACITOR"],
        "display_name_ko": "진상용 콘덴서(SC)",
    },
    "SurgeArrester": {
        "aliases": ["SA", "SURGE ARRESTER"],
        "display_name_ko": "서지보호기(SA)",
    },
    "LightningArrester": {
        "aliases": ["LA", "LIGHTNING ARRESTER"],
        "display_name_ko": "피뢰기(LA)",
    },
    "PowerTransformer": {
        "aliases": ["TR", "TRANSFORMER"],
        "display_name_ko": "전력변압기(TR)",
    },
    "DryTypeTransformer": {
        "aliases": ["TR", "DRY TRANSFORMER"],
        "display_name_ko": "건식변압기(TR)",
    },
    "MeterDM": {
        "aliases": ["DM"],
        "display_name_ko": "DM 계기 기능(의미 확인 필요)",
    },
    "MeterVAR": {
        "aliases": ["VAR"],
        "display_name_ko": "VAR 계기 기능(의미 확인 필요)",
    },
}


def _fragments(raw_text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[|\r\n]+", str(raw_text)) if part.strip()]


def meter_components(raw_text: str) -> list[str]:
    """Return discrete meter labels. DM and VAR are deliberately never merged."""
    output: list[str] = []
    if DM_TOKEN.search(str(raw_text)):
        output.append("MeterDM")
    if VAR_TOKEN.search(str(raw_text)):
        output.append("MeterVAR")
    return output


def special_components(raw_text: str) -> list[str]:
    text = str(raw_text)
    output: list[str] = []
    if CTOD.search(text):
        output.append("CurrentTransformerOpenCircuitProtectionDevice")
    if STATIC_CAPACITOR.search(text):
        output.append("StaticCapacitor")
    if SURGE_ARRESTER.search(text):
        output.append("SurgeArrester")
    if LIGHTNING_ARRESTER.search(text):
        output.append("LightningArrester")
    if TRANSFORMER.search(text):
        output.append("DryTypeTransformer" if re.search(r"\bDRY\b", text, re.I) else "PowerTransformer")
    output.extend(meter_components(text))
    output.extend(component for component in special_components_v5(text) if component not in output)
    return output


def is_pf_accessory_fragment(raw_text: str, owner_text: str) -> bool:
    """A rated FUSE fragment is a PF property only when an explicit PF owns it."""
    return bool(PF_IDENTITY.search(str(owner_text)) and FUSE_RATING.search(str(raw_text)))


def component_text(raw_text: str, component: str) -> str:
    text = str(raw_text)
    if component in {
        "CurrentTransformer",
        "VoltageTransformer",
        "PowerFuse",
        "CurrentTransformerTestTerminal",
        "PotentialTransformerTestTerminal",
        "MeteringOutfit",
    }:
        return component_text_v5(text, component)
    if component == "MeterDM":
        return "DM"
    if component == "MeterVAR":
        return "VAR"
    if component == "CurrentTransformerOpenCircuitProtectionDevice":
        selected = [part for part in _fragments(text) if CTOD.search(part) or CTOD_DESCRIPTION.search(part)]
        return " | ".join(dict.fromkeys(selected)) or "CTOD"
    if component == "StaticCapacitor":
        selected = [
            part
            for part in _fragments(text)
            if STATIC_CAPACITOR.search(part)
            or re.search(r"\b\d+(?:\.\d+)?\s*(?:KVAR|KVA|VAR)\b", part, re.I)
        ]
        return " | ".join(dict.fromkeys(selected)) or text.strip()
    if component in {"SurgeArrester", "LightningArrester"}:
        selected = [
            part
            for part in _fragments(text)
            if SURGE_ARRESTER.search(part)
            or LIGHTNING_ARRESTER.search(part)
            or re.search(r"\b\d+(?:\.\d+)?\s*K[VA]\b", part, re.I)
            or re.search(r"\bW\s*/\s*D(?:ISC)?\b", part, re.I)
        ]
        return " | ".join(dict.fromkeys(selected)) or text.strip()
    if component in {"PowerTransformer", "DryTypeTransformer"}:
        return " | ".join(dict.fromkeys(_fragments(text)))
    return text.strip()


def parse_equipment_v6(
    raw_text: str,
    *,
    forced_class: str | None = None,
    crop_scope: str = "equipment_description",
    ocr_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = str(raw_text)
    base = parse_equipment_v5(text, crop_scope=crop_scope, ocr_lines=ocr_lines)
    components = special_components(text)
    target = forced_class or (components[0] if components else base.get("class_id"))

    plus_context: dict[str, Any] = {}
    if target == "StaticCapacitor":
        plus_context["symbol_hint"] = "STATIC_CAPACITOR_SYMBOL"
    elif target == "CurrentTransformerOpenCircuitProtectionDevice":
        plus_context["forced_class_id"] = target
    plus = parse_equipment_plus(text, context=plus_context, crop_scope=crop_scope)

    if target in CLASS_METADATA:
        base["class_id"] = target
        base["pipeline_class"] = target
        base["identity_evidence"] = component_text(text, target).split(" | ", 1)[0]
        properties = dict(plus.get("properties") or {}) if plus.get("class_id") == target else {}
        properties["search_aliases"] = CLASS_METADATA[target]["aliases"]
        properties["display_name_ko"] = CLASS_METADATA[target]["display_name_ko"]
        if target in {"MeterDM", "MeterVAR"}:
            properties.update(
                {
                    "abbreviation": "DM" if target == "MeterDM" else "VAR",
                    "semantic_expansion_status": "UNRESOLVED_REVIEW_REQUIRED",
                }
            )
        base["properties"] = properties
        base["status"] = "REVIEW_REQUIRED"

    base["grammar_version"] = "sld-equipment-grammar/6.0"
    base["special_components"] = components
    base["meter_split_required"] = len(meter_components(text)) > 1
    base["ultra_close_pf_fuse_rule"] = True
    base["grammar_plus_parser"] = {
        "source": "sld_equipment_ocr_grammar_plus/sld_equipment_ocr_grammar_v2",
        "class_id": plus.get("class_id"),
        "properties": plus.get("properties", {}),
        "normalization_repairs": plus.get("normalization_repairs", []),
    }
    return base


__all__ = [
    "component_text",
    "is_grounding_label",
    "is_mof_description",
    "is_pf_accessory_fragment",
    "meter_components",
    "parse_equipment_v6",
    "special_components",
]
