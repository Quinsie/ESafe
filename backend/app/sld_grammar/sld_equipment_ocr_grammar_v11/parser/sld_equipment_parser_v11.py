from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


GRAMMAR_ROOT = Path(__file__).resolve().parents[2]
V10_PARSER_DIR = GRAMMAR_ROOT / "sld_equipment_ocr_grammar_v10" / "parser"
if str(V10_PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(V10_PARSER_DIR))

from sld_equipment_parser_v10 import (  # noqa: E402
    is_grounding_label,
    is_mof_description,
    parse_equipment_v10,
)


TOKEN = {
    "AutomaticTransferCircuitBreaker": r"(?<![A-Z0-9])A\s*\.?\s*T\s*\.?\s*C\s*\.?\s*B(?![A-Z0-9])",
    "CurrentTransformerOpenCircuitProtectionDevice": r"(?<![A-Z0-9])C\s*\.?\s*T\s*\.?\s*O\s*\.?\s*D(?![A-Z0-9])",
    "CurrentTransformerTestTerminal": r"(?<![A-Z0-9])C\s*\.?\s*T\s*\.?\s*T(?![A-Z0-9])",
    "PotentialTransformerTestTerminal": r"(?<![A-Z0-9])P\s*\.?\s*T\s*\.?\s*T(?![A-Z0-9])",
    "ZeroSequenceCurrentTransformer": r"(?<![A-Z0-9])Z\s*\.?\s*C\s*\.?\s*T(?![A-Z0-9])",
    "AirInsulatedSwitch": r"(?<![A-Z0-9])A\s*\.?\s*I\s*\.?\s*S\s*\.?\s*S(?![A-Z0-9])",
    "AutomaticLoadTransferSwitch": r"(?<![A-Z0-9])A\s*\.?\s*L\s*\.?\s*T\s*\.?\s*S(?![A-Z0-9])",
    "AutomaticSectionSwitch": r"(?<![A-Z0-9])A\s*\.?\s*S\s*\.?\s*S(?![A-Z0-9])",
    "AutomaticTransferSwitch": r"(?<![A-Z0-9])A\s*\.?\s*T\s*\.?\s*S(?![A-Z0-9])",
    "MoldedCaseCircuitBreaker": r"(?<![A-Z0-9])M\s*\.?\s*C\s*\.?\s*C\s*\.?\s*B(?![A-Z0-9])",
    "AirCircuitBreaker": r"(?<![A-Z0-9])A\s*\.?\s*C\s*\.?\s*B(?![A-Z0-9])",
    "VacuumCircuitBreaker": r"(?<![A-Z0-9])V\s*\.?\s*C\s*\.?\s*B(?![A-Z0-9])",
    "LoadBreakSwitch": r"(?<![A-Z0-9])L\s*\.?\s*B\s*\.?\s*S(?![A-Z0-9])",
    "CutOutSwitch": r"(?<![A-Z0-9])C\s*\.?\s*O\s*\.?\s*S(?:\s*[X×]\s*\d+)?(?![A-Z0-9])",
    "MeteringOutfit": r"(?<![A-Z0-9])M\s*\.?\s*O\s*\.?\s*F(?![A-Z0-9])",
    "EarthLeakageDetector": r"(?<![A-Z0-9])E\s*\.?\s*L\s*\.?\s*D(?:\s*-\s*[A-Z0-9+]+)?(?![A-Z0-9])",
    "SurgeProtectiveDevice": r"(?<![A-Z0-9])S\s*\.?\s*P\s*\.?\s*D(?![A-Z0-9])",
    "BranchCircuitMonitoringDevice": r"분기\s*회로\s*감시\s*장치|BRANCH\s+CIRCUIT\s+MONITOR",
    "MaximumDemandPowerController": r"최대\s*수요\s*전력\s*제어기|MAX(?:IMUM)?\s+DEMAND\s+(?:POWER\s+)?CONTROLLER",
    "PowerMeasurementSection": r"전력\s*계측부|POWER\s+(?:MEASUREMENT|METERING)\s+SECTION",
    "DigitalMultifunctionMeter": r"DIGITA[LR]\s+(?:METER|보호계전[,\s]*계측기)|디지털\s*(?:메터|계전기|보호\s*계전[,\s]*계측기)",
    "BatteryBank": r"(?<![A-Z0-9])BATTERY(?![A-Z0-9])|축전지",
    "UninterruptiblePowerSupply": r"(?<![A-Z0-9])UPS(?![A-Z0-9])|무정전\s*전원",
    "Generator": r"(?<![A-Z0-9])GENERATOR(?![A-Z0-9])|비상\s*발전기|발전기",
    "BusDuct": r"(?<![A-Z0-9])(?:FR\s*[- ]\s*)?BUS\s*[- ]?\s*DUCT(?![A-Z0-9])|버스\s*덕트",
    "UtilityIncoming": r"INCOMING\s+(?:K\.?E\.?P\.?C\.?O\.?|KEPCO)|FROM\s+KEPCO\s+INCOMING|한전\s*인입",
    "CurrentShunt": r"(?<![A-Z0-9])SHUNT(?![A-Z0-9])",
    "OverCurrentGroundRelay": r"(?<![A-Z0-9])OCGR(?![A-Z0-9])",
    "UnderVoltageRelay": r"(?<![A-Z0-9])UVR(?![A-Z0-9])",
    "Timer": r"(?<![A-Z0-9])(?:24\s*HOURS?\s+)?TIMER(?![A-Z0-9])",
    "SeriesReactor": r"(?<![A-Z0-9])S\s*\.?\s*R(?![A-Z0-9])|SERIES\s+REACTOR|직렬\s*리액터",
    "StaticCapacitor": r"(?<![A-Z0-9])S\s*\.?\s*C(?![A-Z0-9])|STATIC\s+(?:CAPACITOR|CONDENSER)|진상용?\s*콘덴서",
    "LightningArrester": r"(?<![A-Z0-9])L\s*\.?\s*A\s*(?:[X×]\s*\d+|\b)|LIGHTNING\s+ARRESTER|피뢰기",
    "SurgeArrester": r"(?<![A-Z0-9])S\s*\.?\s*A\s*(?:[X×]\s*\d+|\b)|SURGE\s+ARRESTER",
    "PowerFuse": r"(?<![A-Z0-9])P\s*\.?\s*F\s*(?:[X×]\s*\d+|\b)|POWER\s+FUSE|전력\s*퓨즈",
    "Fuse": r"(?<![A-Z0-9])FUSE(?![A-Z0-9])|(?<![A-Z0-9])F(?![A-Z0-9])",
    "VoltageTransformer": r"(?<![A-Z0-9])(?:V\s*\.?\s*T|P\s*\.?\s*T)\s*(?:[X×]\s*\d+|\b)|계기용\s*변압기",
    "CurrentTransformer": r"(?<![A-Z0-9])C\s*\.?\s*T\s*(?:[X×]\s*\d+|\b)|(?<![A-Z0-9])\d+\s*[- ]\s*CT(?![A-Z0-9])|변류기",
}

TRANSFORMER = re.compile(
    r"(?<![A-Z0-9])(?:TRANS(?:FORMER)?\s*[-#]?\s*\d*|"
    r"T\s*\.?\s*R\s*\.?\s*(?:[-#]?\s*\d+|\s*\(\s*(?:PAD\s*)?(?:DRY|OIL)(?:\s*TYPE)?\s*\)))"
    r"(?![A-Z0-9])|(?:전력\s*)?변압기",
    re.I,
)

EXACT_GROUND = re.compile(r"^\s*E\s*([0-9]+)\s*$", re.I)
DM = re.compile(r"(?<![A-Z0-9])D\s*\.?\s*M(?![A-Z0-9])", re.I)
VAR = re.compile(r"(?<![A-Z0-9])VAR(?![A-Z0-9])", re.I)
INTERLOCK = re.compile(r"INTER\s*[- ]?\s*LOCK|인터록", re.I)
CONDUCTOR = re.compile(
    r"\b(?:FR[- ]?)?CNCO\b|\bCV\b|\bCABLE\b|\bWIRE\b|전선|케이블",
    re.I,
)

PRECEDENCE = [
    "ATCB_BEFORE_ATS",
    "CTOD_BEFORE_CTT_BEFORE_CT",
    "PTT_BEFORE_PT_OR_VT",
    "ZCT_BEFORE_CT",
    "MOF_OWNS_ITS_PT_AND_CT_RATIOS",
    "DIGITAL_METER_OWNS_PF_AS_MEASUREMENT_FUNCTION",
    "PF_OWNS_ULTRA_CLOSE_FUSE_RATING",
    "ONE_EXPLICIT_ANCHOR_ONE_OBJECT",
    "NO_SYMBOL_ONLY_OBJECTS",
]

STRONG_SPLIT_ANCHOR = {
    "AirCircuitBreaker": r"(?<![A-Z0-9])ACB(?![A-Z0-9])",
    "AutomaticTransferCircuitBreaker": r"(?<![A-Z0-9])ATCB(?![A-Z0-9])",
    "MoldedCaseCircuitBreaker": r"(?<![A-Z0-9])MCCB(?![A-Z0-9])",
    "VacuumCircuitBreaker": r"(?<![A-Z0-9])VCB(?![A-Z0-9])",
    "LoadBreakSwitch": r"(?<![A-Z0-9])L\s*\.?\s*B\s*\.?\s*S(?![A-Z0-9])",
    "CurrentTransformer": r"(?<![A-Z0-9])C\s*\.?\s*T\s*(?:[X×]\s*\d+|\b)",
    "VoltageTransformer": r"(?<![A-Z0-9])(?:V\s*\.?\s*T|P\s*\.?\s*T)\s*(?:[X×]\s*\d+|\b)",
    "PowerTransformer": (
        r"(?<![A-Z0-9])(?:TRANS(?:FORMER)?\s*[-#]?\s*\d*|"
        r"T\s*\.?\s*R\s*\.?\s*(?:[-#]?\s*\d+|\(\s*(?:PAD\s*)?OIL))"
    ),
    "DryTypeTransformer": r"(?<![A-Z0-9])T\s*\.?\s*R\s*\.?\s*\(\s*DRY",
}

CLASS_METADATA: dict[str, tuple[str, str, str]] = {
    "AirInsulatedSwitch": ("AISS", "기중절연 스위치(AISS)", "EQUIPMENT"),
    "AutomaticLoadTransferSwitch": ("ALTS", "자동부하절체 스위치(ALTS)", "EQUIPMENT"),
    "AutomaticSectionSwitch": ("ASS", "자동구분 스위치(ASS)", "EQUIPMENT"),
    "CutOutSwitch": ("COS", "컷아웃 스위치(COS)", "EQUIPMENT"),
    "Fuse": ("F/FUSE", "퓨즈", "EQUIPMENT"),
    "Timer": ("TIMER", "타이머", "EQUIPMENT"),
    "Generator": ("GENERATOR", "발전기", "EQUIPMENT"),
    "MeterDM": ("DM", "수요전력계 기능(DM)", "METER_FUNCTION"),
    "MeterVAR": ("VAR", "무효전력계 기능(VAR)", "METER_FUNCTION"),
}


def _find(class_id: str, text: str) -> re.Match[str] | None:
    return re.search(TOKEN[class_id], text, re.I)


def extract_explicit_anchors(raw_text: str) -> list[dict[str, Any]]:
    text = str(raw_text)
    output: list[dict[str, Any]] = []
    for class_id, pattern in TOKEN.items():
        if class_id == "Fuse" and _find("PowerFuse", text):
            continue
        if class_id in {"CurrentTransformer", "VoltageTransformer"} and _find(
            "MeteringOutfit", text
        ):
            continue
        if class_id == "PowerFuse" and _find("DigitalMultifunctionMeter", text):
            continue
        for match in re.finditer(pattern, text, re.I):
            output.append(
                {
                    "class_id": class_id,
                    "text": match.group(0),
                    "span": [match.start(), match.end()],
                }
            )
    for match in TRANSFORMER.finditer(text):
        output.append(
            {
                "class_id": (
                    "DryTypeTransformer"
                    if re.search(r"\bDRY\b", match.group(0), re.I)
                    else "PowerTransformer"
                ),
                "text": match.group(0),
                "span": [match.start(), match.end()],
            }
        )
    for class_id, pattern in (("MeterDM", DM), ("MeterVAR", VAR)):
        for match in pattern.finditer(text):
            output.append(
                {
                    "class_id": class_id,
                    "text": match.group(0),
                    "span": [match.start(), match.end()],
                }
            )
    output.sort(key=lambda item: (item["span"][0], -(item["span"][1] - item["span"][0])))

    # Keep the longest token at the same start and suppress embedded short aliases.
    filtered: list[dict[str, Any]] = []
    for item in output:
        start, end = item["span"]
        if any(
            start >= kept["span"][0]
            and end <= kept["span"][1]
            and (end - start) < (kept["span"][1] - kept["span"][0])
            for kept in filtered
        ):
            continue
        filtered.append(item)
    return filtered


def detect_v11_class(
    raw_text: str, context: dict[str, Any] | None = None
) -> str | None:
    context = dict(context or {})
    if context.get("forced_class_id"):
        return str(context["forced_class_id"])
    text = str(raw_text)
    if INTERLOCK.search(text):
        return None
    ground = EXACT_GROUND.fullmatch(text)
    if ground:
        return "GroundingReference"
    anchors = extract_explicit_anchors(text)
    if not anchors:
        return None

    # The extraction list is in reading order, but identity precedence is semantic.
    ordered_classes = [
        "AutomaticTransferCircuitBreaker",
        "CurrentTransformerOpenCircuitProtectionDevice",
        "CurrentTransformerTestTerminal",
        "PotentialTransformerTestTerminal",
        "ZeroSequenceCurrentTransformer",
        "MeteringOutfit",
        "DigitalMultifunctionMeter",
        "AirInsulatedSwitch",
        "AutomaticLoadTransferSwitch",
        "AutomaticSectionSwitch",
        "AutomaticTransferSwitch",
        "MoldedCaseCircuitBreaker",
        "AirCircuitBreaker",
        "VacuumCircuitBreaker",
        "LoadBreakSwitch",
        "CutOutSwitch",
        "DryTypeTransformer",
        "PowerTransformer",
        "UninterruptiblePowerSupply",
        "BatteryBank",
        "Generator",
        "EarthLeakageDetector",
        "BranchCircuitMonitoringDevice",
        "MaximumDemandPowerController",
        "PowerMeasurementSection",
        "BusDuct",
        "UtilityIncoming",
        "SurgeProtectiveDevice",
        "LightningArrester",
        "SurgeArrester",
        "PowerFuse",
        "VoltageTransformer",
        "CurrentTransformer",
        "StaticCapacitor",
        "SeriesReactor",
        "CurrentShunt",
        "OverCurrentGroundRelay",
        "UnderVoltageRelay",
        "Timer",
        "Fuse",
        "MeterDM",
        "MeterVAR",
    ]
    present = {anchor["class_id"] for anchor in anchors}
    return next((class_id for class_id in ordered_classes if class_id in present), None)


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.I)
    return float(match.group(1)) if match else None


def _properties(text: str, class_id: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    pole = _number(r"(?<!\d)([234])\s*P\b", text)
    quantity = re.search(
        r"(?<![A-Z0-9])(?:ACB|MCCB|VCB|CT|VT|PT|PF|LA|SA)\s*[X×]\s*(\d+)",
        text,
        re.I,
    )
    if pole is not None:
        properties["pole_count"] = int(pole)
    if quantity:
        properties["quantity"] = int(quantity.group(1))
        properties["quantity_source"] = "EXPLICIT_XN"

    af_at = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*AF\s*/?\s*(\d+(?:\.\d+)?)\s*AT\b",
        text,
        re.I,
    )
    slash_at = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*AT\b",
        text,
        re.I,
    )
    if af_at:
        properties["frame_current_a"] = float(af_at.group(1))
        properties["trip_current_a"] = float(af_at.group(2))
    elif slash_at and class_id in {
        "AirCircuitBreaker",
        "AutomaticTransferCircuitBreaker",
        "MoldedCaseCircuitBreaker",
    }:
        properties["frame_current_a"] = float(slash_at.group(1))
        properties["trip_current_a"] = float(slash_at.group(2))
    else:
        frame = _number(r"(?<!\d)(\d+(?:\.\d+)?)\s*AF\b", text)
        trip = _number(r"(?<!\d)(\d+(?:\.\d+)?)\s*AT\b", text)
        amp = _number(r"(?<![/\d])(\d+(?:\.\d+)?)\s*A\b", text)
        if frame is not None:
            properties["frame_current_a"] = frame
        if trip is not None:
            properties["trip_current_a"] = trip
        if amp is not None:
            properties["rated_current_a"] = amp

    voltage = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(KV|V)\b", text, re.I)
    if voltage:
        value = float(voltage.group(1))
        properties["rated_voltage_v"] = (
            value * 1000.0 if voltage.group(2).upper() == "KV" else value
        )
    breaking = _number(r"(?<!\d)(\d+(?:\.\d+)?)\s*KA\b", text)
    if breaking is not None:
        properties["breaking_or_discharge_current_ka"] = breaking
    mva = _number(r"(?<!\d)(\d+(?:\.\d+)?)\s*MVA\b", text)
    if mva is not None:
        properties["interrupting_capacity_mva"] = mva
    kva_values = [
        float(value)
        for value in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*KVA\b", text, re.I)
    ]
    kvar = _number(r"(?<![\d.])(\d+(?:\.\d+)?)\s*KVAR\b", text)
    if kva_values:
        properties["capacity_kva"] = kva_values[0]
        if len(kva_values) > 1:
            properties["capacity_kva_values"] = kva_values
    if kvar is not None:
        properties["reactive_power_kvar"] = kvar

    ct_ratio = re.search(
        r"(?:(?:CT|C\.T)\s*[:.]?\s*)?(\d+(?:\.\d+)?)\s*/\s*([15])\s*A\b",
        text,
        re.I,
    )
    if ct_ratio and class_id in {
        "CurrentTransformer",
        "MeteringOutfit",
        "ZeroSequenceCurrentTransformer",
    }:
        properties["ct_ratio"] = {
            "primary_a": float(ct_ratio.group(1)),
            "secondary_a": float(ct_ratio.group(2)),
        }
    ratio = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*(KV|V)?\s*/\s*(\d+(?:\.\d+)?)\s*V\b",
        text,
        re.I,
    )
    if ratio and class_id in {
        "VoltageTransformer",
        "MeteringOutfit",
        "PowerTransformer",
        "DryTypeTransformer",
    }:
        primary = float(ratio.group(1))
        if str(ratio.group(2) or "").upper() == "KV":
            primary *= 1000.0
        properties["voltage_ratio_v"] = [primary, float(ratio.group(3))]

    burden = _number(r"(?<!\d)(\d+(?:\.\d+)?)\s*VA\b", text)
    if burden is not None and class_id in {
        "CurrentTransformer",
        "VoltageTransformer",
    }:
        properties["burden_va"] = burden
    protection = [
        name
        for name in ("OCR", "OCGR", "OCGF", "UVR", "OVR")
        if re.search(rf"(?<![A-Z0-9]){name}(?![A-Z0-9])", text, re.I)
    ]
    if protection:
        properties["embedded_protection_functions"] = protection
    if re.search(r"\bDRY\b", text, re.I):
        properties["construction"] = "DRY"
    elif re.search(r"\bMOLD\b", text, re.I):
        properties["construction"] = "MOLD"
    elif re.search(r"\bOIL\b", text, re.I):
        properties["construction"] = "OIL"
    fuse_link = re.search(
        r"(?:FUSE\s*[:.]?\s*|\()(\d+(?:\.\d+)?)\s*A\s*(?:FUSE)?\)?",
        text,
        re.I,
    )
    if fuse_link and class_id == "PowerFuse":
        properties["fuse_link_current_a"] = float(fuse_link.group(1))
        properties["fuse_is_owned_property"] = True
    cct = [
        int(value)
        for value in re.findall(r"(?<!\d)(\d{1,3})\s*CCT\b", text, re.I)
    ]
    if cct and class_id == "EarthLeakageDetector":
        properties["circuit_counts"] = cct
        properties["cct_is_not_ct_equipment"] = True
    return properties


def classify_text_scope(raw_text: str) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(raw_text)).strip()
    upper = text.upper()
    reasons: list[str] = []
    role = "SLD_BODY"
    suppress = False

    if INTERLOCK.search(text):
        role, suppress = "RELATION", True
        reasons.append("INTERLOCK_IS_RELATION_NOT_EQUIPMENT")
    elif re.search(r"단선\s*결선도|PROJECT\s+TITLE|DRAWING\s+TITLE", text, re.I):
        role, suppress = "TITLE_BLOCK", True
        reasons.append("DRAWING_TITLE")
    elif re.search(
        r"\b(?:NOTE|LEGEND)\b|(?:^|[\s:])주\s*기(?:$|[\s:#])|범\s*례",
        text,
        re.I,
    ):
        role, suppress = "NOTE_OR_LEGEND", True
        reasons.append("EXPLICIT_NOTE_OR_LEGEND")
    elif re.search(r"\bLOAD\s+NAME\b|부하\s*명|설비\s*목록", text, re.I):
        role, suppress = "EQUIPMENT_SCHEDULE", True
        reasons.append("SCHEDULE_HEADER")
    elif len(re.findall(r"\d+(?:\.\d+)?\s*KVA\s*[X×]\s*\d+", text, re.I)) >= 3:
        role, suppress = "EQUIPMENT_SCHEDULE", True
        reasons.append("REPEATED_CAPACITY_QUANTITY_LIST")
    elif CONDUCTOR.search(text) and not _find("BusDuct", text):
        role, suppress = "CONDUCTOR_ANNOTATION", True
        reasons.append("WIRE_OR_CABLE_IS_ANNOTATION")
    else:
        legend_descriptor = re.search(
            r"(?:차단기|단로기|개폐기|변압기|변류기|계기용|피뢰기|전력\s*퓨즈)"
            r"\s*(?:\)|$)",
            text,
            re.I,
        )
        rating = re.search(
            r"\d+(?:\.\d+)?\s*(?:KV|V|KA|KVA|KVAR|A|AF|AT|VA)\b",
            text,
            re.I,
        )
        if legend_descriptor and not rating and extract_explicit_anchors(text):
            role, suppress = "LEGEND_DEFINITION", True
            reasons.append("GENERIC_EQUIPMENT_DEFINITION_WITHOUT_RATING")
        elif len(text) >= 45 and re.search(
            r"설치|사용|시공|공사|협의|변경|접속|적용|구성|확인|주의|기준",
            text,
            re.I,
        ):
            role, suppress = "NOTE", True
            reasons.append("SENTENCE_LIKE_NOTE")

    return {
        "role": role,
        "suppress_as_equipment": suppress,
        "reasons": reasons,
        "normalized_scope_text": upper,
    }


def parse_equipment_v11(
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
    target = detect_v11_class(text, context)
    parsed = parse_equipment_v10(
        text,
        forced_class=target or forced_class,
        context=context,
        crop_scope=crop_scope,
        ocr_lines=ocr_lines,
    )
    if target:
        parsed["class_id"] = target
        parsed["pipeline_class"] = target
    class_id = str(parsed.get("class_id") or target or forced_class or "")
    inherited = dict(parsed.get("properties") or {})
    inherited.update(_properties(text, class_id))
    if class_id in CLASS_METADATA:
        alias, display_name, object_kind = CLASS_METADATA[class_id]
        inherited["search_aliases"] = [alias]
        inherited["display_name_ko"] = display_name
    else:
        object_kind = (
            "REFERENCE"
            if class_id == "GroundingReference"
            else "EQUIPMENT"
        )
    anchors = extract_explicit_anchors(text)
    same_class_anchors = [
        anchor for anchor in anchors if anchor["class_id"] == class_id
    ]
    strong_split_count = len(
        re.findall(STRONG_SPLIT_ANCHOR.get(class_id, r"(?!x)x"), text, re.I)
    )
    parsed["properties"] = inherited
    parsed["grammar_version"] = "sld-equipment-grammar/11.0"
    parsed["reference_basis"] = {
        "image_count": 178,
        "inventory": "v15_reference_analysis/reference_image_inventory_v15.json",
        "all_reference_images_audited": True,
    }
    parsed["scope"] = classify_text_scope(text)
    parsed["object_kind"] = object_kind
    parsed["explicit_anchors"] = anchors
    parsed["identity_anchor_count"] = len(same_class_anchors)
    parsed["split_required"] = (
        strong_split_count > 1
        or (DM.search(text) is not None and VAR.search(text) is not None)
    )
    parsed["strong_split_anchor_count"] = strong_split_count
    parsed["meter_components"] = [
        class_name
        for class_name, pattern in (("MeterDM", DM), ("MeterVAR", VAR))
        if pattern.search(text)
    ]
    parsed["precedence"] = PRECEDENCE
    parsed["no_symbol_only_objects"] = True
    parsed["geometry_policy"] = {
        "ocr_text_bbox_required": True,
        "split_uses_individual_ocr_token_bboxes": True,
        "symbol_bbox_never_creates_object_without_text": True,
    }
    return parsed


__all__ = [
    "PRECEDENCE",
    "classify_text_scope",
    "detect_v11_class",
    "extract_explicit_anchors",
    "is_grounding_label",
    "is_mof_description",
    "parse_equipment_v11",
]
