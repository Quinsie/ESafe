from __future__ import annotations

import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


V1_PARSER_DIR = (
    Path(__file__).resolve().parents[2]
    / "sld_equipment_ocr_grammar_v1"
    / "parser"
)
if str(V1_PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(V1_PARSER_DIR))

from sld_equipment_parser import normalize_text, parse_equipment  # noqa: E402


PIPELINE_CLASS = {
    "AirCircuitBreaker": "AirCircuitBreaker",
    "AutomaticTransferCircuitBreaker": "AutomaticTransferSwitch",
    "AutomaticTransferSwitch": "AutomaticTransferSwitch",
    "MoldedCaseCircuitBreaker": "MoldedCaseCircuitBreaker",
    "VacuumCircuitBreaker": "VacuumCircuitBreaker",
    "LoadBreakSwitch": "LoadBreakSwitch",
    "PowerFuse": "Fuse",
    "Fuse": "Fuse",
    "CurrentTransformer": "CurrentTransformer",
    "ZeroSequenceCurrentTransformer": "CurrentTransformer",
    "VoltageTransformer": "PotentialTransformer",
    "MeteringOutfit": "MeteringOutfit",
    "LightningArrester": "SurgeArrester",
    "SurgeArrester": "SurgeArrester",
    "SurgeProtectiveDevice": "SurgeProtectiveDevice",
    "BatteryBank": "Battery",
    "PowerTransformer": "PowerTransformer",
    "DryTypeTransformer": "PowerTransformer",
    "RectifierUnitTransformer": "PowerTransformer",
    "UninterruptiblePowerSupply": "UninterruptiblePowerSupply",
    "DigitalMultifunctionMeter": "Meter",
    "EarthLeakageDetector": "EarthLeakageDetector",
    "BranchCircuitMonitoringDevice": "BranchCircuitMonitoringDevice",
    "MaximumDemandPowerController": "MaximumDemandPowerController",
    "UtilityIncoming": "UtilityIncoming",
    "CurrentShunt": "CurrentShunt",
    "CurrentTransformerOpenCircuitProtectionDevice": "ProtectiveRelay",
    "Generator": "Generator",
    "ProtectiveRelay": "ProtectiveRelay",
    "PanelBoard": "PanelBoard",
    "MotorControlCenter": "PanelBoard",
    "BusDuct": "BusDuct",
    "Rectifier": "Rectifier",
    "AutomaticPowerFactorController": "ProtectiveRelay",
}


CLASS_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("Generator", re.compile(r"\b(?:DIESEL\s+ENGINE\s+)?GEN(?:ERATOR)?\b|비상\s*발전기", re.I)),
    ("AutomaticTransferSwitch", re.compile(r"\bATS\b|AUTO(?:MATIC)?\s+TRANSFER\s+SWITCH", re.I)),
    ("AutomaticPowerFactorController", re.compile(r"\bA\.?P\.?F\.?R\.?\b|자동\s*역률\s*조정", re.I)),
    ("MotorControlCenter", re.compile(r"\bMOTOR\s+CONTROL\s+CENTER\b|\bMCC\s+PANEL\b", re.I)),
    ("PanelBoard", re.compile(r"\bPANEL\s+NAME\b|\bLOAD\s+NAME\b.*\bMCCB\b", re.I | re.S)),
    ("BusDuct", re.compile(r"\bBUS\s*DUCT\b", re.I)),
    ("Rectifier", re.compile(r"\b(?:SILICON\s+)?RECTIFIER\b", re.I)),
    ("VoltageTransformer", re.compile(r"\bPTT\b|\bPT\s*:\s*[0-9]", re.I)),
    ("ZeroSequenceCurrentTransformer", re.compile(r"\bZCT(?:\s*X?\s*\d+)?\b", re.I)),
    ("DigitalMultifunctionMeter", re.compile(r"\bDM\b.*\bVAR\b", re.I | re.S)),
    (
        "ProtectiveRelay",
        re.compile(
            r"(?:^|\|)\s*(?:OCR|OCGR|UVR|OVR|DGR|GFR|51N?|50N?)"
            r"(?:[ ,/&+]+(?:OCR|OCGR|UVR|OVR|DGR|GFR|51N?|50N?))*\s*(?:\||$)|"
            r"\bPROTECTIVE\s+RELAY\b|보호\s*계전기",
            re.I,
        ),
    ),
    ("Fuse", re.compile(r"\bFUSE\b", re.I)),
]


REQUIRED_GROUPS: dict[str, list[tuple[str, ...]]] = {
    "AirCircuitBreaker": [("frame_current_a", "rated_current_a")],
    "AutomaticTransferCircuitBreaker": [("frame_current_a", "rated_current_a")],
    "AutomaticTransferSwitch": [("rated_current_a", "frame_current_a")],
    "MoldedCaseCircuitBreaker": [("frame_current_a", "trip_current_a")],
    "VacuumCircuitBreaker": [("rated_voltage_v",), ("rated_current_a",)],
    "LoadBreakSwitch": [("rated_voltage_v",), ("rated_current_a",)],
    "PowerTransformer": [("capacity_kva",), ("voltage_ratio", "primary_voltage_v")],
    "DryTypeTransformer": [("capacity_kva",)],
    "Generator": [("capacity_kva", "rated_output_kw"), ("rated_voltage_v", "voltage_candidates_v")],
    "CurrentTransformer": [("ct_ratio",)],
    "VoltageTransformer": [("voltage_ratio",)],
    "MeteringOutfit": [("pt", "ct")],
    "PowerFuse": [("rated_voltage_v", "fuse_link_current_a")],
    "Fuse": [("fuse_current_a", "rated_current_a")],
    "BatteryBank": [("capacity_ah", "cell_count")],
    "UninterruptiblePowerSupply": [("capacity_kva",)],
    "BusDuct": [("rated_current_a",)],
    "Rectifier": [("rated_current_a", "capacity_kva", "capacity_kw")],
    "PanelBoard": [("schedule_header",)],
}


RELATION_PATTERN = re.compile(
    r"\bINTER\s*LOCK\b|\bINTERLOCK\b|(?:^|\|)\s*(?:TO|FROM)\s*[:\-]",
    re.I,
)
EMBEDDED_PROTECTION = re.compile(r"\b(?:W\s*/\s*)?(OCR|OCGR|UVR|OVR|DGR|GFR)\b", re.I)
NUMBER_TOKEN = re.compile(r"\d+(?:\.\d+)?")


def _match_new_class(text: str) -> tuple[str | None, str | None]:
    for class_id, pattern in CLASS_RULES:
        match = pattern.search(text)
        if match:
            return class_id, match.group(0).strip(" |")
    return None, None


def _span_evidence(
    raw_text: str,
    normalized_text: str,
    property_name: str,
    value: Any,
    pattern: str,
) -> dict[str, Any] | None:
    match = re.search(pattern, normalized_text, re.I | re.S)
    if not match:
        return None
    before = normalized_text[: match.start()]
    line_index = before.count("|")
    lines = [part.strip() for part in raw_text.split("|")]
    source_line = lines[line_index] if line_index < len(lines) else raw_text
    return {
        "property": property_name,
        "value": value,
        "evidence_type": "EXPLICIT_OCR",
        "normalized_span": [match.start(), match.end()],
        "matched_text": match.group(0),
        "source_line_index": line_index,
        "source_line": source_line,
    }


def _add_property(
    result: dict[str, Any],
    raw_text: str,
    normalized_text: str,
    name: str,
    value: Any,
    pattern: str,
) -> None:
    if value is None:
        return
    result["properties"][name] = value
    evidence = _span_evidence(raw_text, normalized_text, name, value, pattern)
    if evidence:
        result["field_provenance"].append(evidence)


def _first_number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.I)
    return float(match.group(1)) if match else None


def _volts(value: str, unit: str) -> float:
    return float(value) * (1000.0 if unit.upper() == "KV" else 1.0)


def _augment_new_class(result: dict[str, Any], raw_text: str, text: str) -> None:
    class_id = result["class_id"]
    if class_id == "Generator":
        kva = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*KVA\b", text)
        kw = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*KW\b", text)
        voltage = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(KV|V)\b", text, re.I)
        _add_property(result, raw_text, text, "capacity_kva", kva, r"[0-9.]+\s*KVA\b")
        _add_property(result, raw_text, text, "rated_output_kw", kw, r"[0-9.]+\s*KW\b")
        if voltage:
            _add_property(
                result,
                raw_text,
                text,
                "rated_voltage_v",
                _volts(voltage.group(1), voltage.group(2)),
                r"[0-9.]+\s*(?:KV|V)\b",
            )
        frequency = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*HZ\b", text)
        _add_property(result, raw_text, text, "frequency_hz", frequency, r"[0-9.]+\s*HZ\b")
        phase_wire = re.search(r"([13])\s*(?:Φ|PH)\s*([234])\s*W", text, re.I)
        if phase_wire:
            _add_property(result, raw_text, text, "phase_count", int(phase_wire.group(1)), phase_wire.group(0))
            _add_property(result, raw_text, text, "wire_count", int(phase_wire.group(2)), phase_wire.group(0))
        components = []
        for token in ("AVR", "AUTO STARTING PANEL", "BATTERY", "CHARGER"):
            if token in text:
                components.append(token)
        result["embedded_components"] = components

    elif class_id == "AutomaticTransferSwitch":
        pole = _first_number(r"\b([234])\s*P\b", text)
        current = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*(?:AT|A)\b", text)
        _add_property(result, raw_text, text, "pole_count", int(pole) if pole else None, r"\b[234]\s*P\b")
        _add_property(result, raw_text, text, "rated_current_a", current, r"[0-9.]+\s*(?:AT|A)\b")

    elif class_id == "AutomaticPowerFactorController":
        kvar = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*KVAR\b", text)
        step = _first_number(r"\b([0-9]+)\s*(?:STEP|단계)\b", text)
        _add_property(result, raw_text, text, "reactive_power_kvar", kvar, r"[0-9.]+\s*KVAR\b")
        _add_property(result, raw_text, text, "step_count", int(step) if step else None, r"[0-9]+\s*(?:STEP|단계)\b")

    elif class_id in {"PanelBoard", "MotorControlCenter"}:
        header = re.search(r"(?:PANEL|LOAD)\s+NAME", text, re.I)
        if header:
            _add_property(result, raw_text, text, "schedule_header", header.group(0).upper(), r"(?:PANEL|LOAD)\s+NAME")
        rows = [line.strip() for line in raw_text.split("|") if re.search(r"\b\d{2,4}\b", line)]
        result["properties"]["schedule_row_count_candidate"] = len(rows)
        result["properties"]["schedule_rows_raw"] = rows

    elif class_id == "BusDuct":
        current = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*A\b", text)
        voltage = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(KV|V)\b", text, re.I)
        _add_property(result, raw_text, text, "rated_current_a", current, r"[0-9.]+\s*A\b")
        if voltage:
            _add_property(result, raw_text, text, "rated_voltage_v", _volts(voltage.group(1), voltage.group(2)), r"[0-9.]+\s*(?:KV|V)\b")
        material = re.search(r"\b(?:AL|CU|A1)\b", text, re.I)
        if material:
            value = "AL" if material.group(0).upper() == "A1" else material.group(0).upper()
            _add_property(result, raw_text, text, "conductor_material", value, r"\b(?:AL|CU|A1)\b")

    elif class_id == "Rectifier":
        current = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*A\b", text)
        kva = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*KVA\b", text)
        kw = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*KW\b", text)
        _add_property(result, raw_text, text, "rated_current_a", current, r"[0-9.]+\s*A\b")
        _add_property(result, raw_text, text, "capacity_kva", kva, r"[0-9.]+\s*KVA\b")
        _add_property(result, raw_text, text, "capacity_kw", kw, r"[0-9.]+\s*KW\b")

    elif class_id == "Fuse":
        current = _first_number(r"([0-9]+(?:\.[0-9]+)?)\s*A\s*FUSE\b", text)
        if current is None:
            current = _first_number(r"\bFUSE\s*([0-9]+(?:\.[0-9]+)?)\s*A\b", text)
        _add_property(result, raw_text, text, "fuse_current_a", current, r"(?:[0-9.]+\s*A\s*FUSE|FUSE\s*[0-9.]+\s*A)")

    elif class_id == "ProtectiveRelay":
        functions = [match.group(1).upper() for match in EMBEDDED_PROTECTION.finditer(text)]
        result["properties"]["protection_functions"] = list(dict.fromkeys(functions))

    elif class_id == "DigitalMultifunctionMeter":
        measurement = [
            token
            for token in ("V", "A", "KW", "KWH", "PF", "VAR")
            if re.search(rf"(?<![A-Z0-9]){token}(?![A-Z0-9])", text, re.I)
        ]
        result["properties"]["measurement_functions"] = measurement

    elif class_id == "VoltageTransformer":
        ratio = re.search(
            r"(?:PTT?|VT)\s*:?\s*([0-9.]+)\s*(KV|V)?\s*/\s*([0-9.]+)\s*(KV|V)",
            text,
            re.I,
        )
        if ratio:
            value = {
                "primary": {"value": _volts(ratio.group(1), ratio.group(2) or ratio.group(4)), "unit": "V"},
                "secondary": {"value": _volts(ratio.group(3), ratio.group(4)), "unit": "V"},
                "raw": ratio.group(0),
            }
            _add_property(result, raw_text, text, "voltage_ratio", value, ratio.group(0))


def _copy_base_provenance(result: dict[str, Any], raw_text: str, text: str) -> None:
    known_patterns = {
        "pole_count": r"\b[1-4]\s*P\b",
        "frame_current_a": r"[0-9.]+\s*AF\b|[0-9.]+\s*/\s*[0-9.]+\s*(?:AT|A)\b",
        "trip_current_a": r"[0-9.]+\s*AT\b|[0-9.]+\s*/\s*[0-9.]+\s*(?:AT|A)\b",
        "rated_current_a": r"(?<![/\d.])[0-9.]+\s*A\b",
        "rated_voltage_v": r"[0-9.]+\s*(?:KV|V)\b",
        "capacity_kva": r"[0-9.]+\s*KVA\b",
        "capacity_ah": r"[0-9.]+\s*AH\b",
        "frequency_hz": r"[0-9.]+\s*HZ\b",
        "ct_ratio": r"[0-9.]+\s*/\s*[0-9.]+\s*A\b",
        "voltage_ratio": r"[0-9.]+\s*(?:KV|V)?\s*/\s*[0-9.]+(?:\s*[-/]\s*[0-9.]+)?\s*(?:KV|V)\b",
        "pt": r"\bPT\s*:?[^|]+",
        "tag": r"\b(?:TRANSFORMER-?\d+|TR#?\d+)\b",
    }
    present = {item["property"] for item in result["field_provenance"]}
    for name, value in result["properties"].items():
        if name in present or name not in known_patterns:
            continue
        evidence = _span_evidence(raw_text, text, name, value, known_patterns[name])
        if evidence:
            result["field_provenance"].append(evidence)


def _validate(result: dict[str, Any]) -> None:
    props = result["properties"]
    errors = result["validation_errors"]
    warnings = result["warnings"]
    frame = props.get("frame_current_a")
    trip = props.get("trip_current_a")
    if frame is not None and trip is not None and float(trip) > float(frame):
        errors.append("TRIP_CURRENT_EXCEEDS_FRAME_CURRENT")
    ratio = props.get("ct_ratio")
    if isinstance(ratio, dict):
        secondary = ratio.get("secondary_a")
        if secondary is not None and float(secondary) not in {1.0, 5.0}:
            warnings.append("UNUSUAL_CT_SECONDARY_CURRENT")
    primary = props.get("primary_voltage_v")
    secondary = props.get("secondary_voltage_v")
    if isinstance(secondary, list):
        secondary = max(secondary) if secondary else None
    if primary is not None and secondary is not None and float(primary) <= float(secondary):
        warnings.append("TRANSFORMER_PRIMARY_NOT_ABOVE_SECONDARY")
    if RELATION_PATTERN.search(result["normalized_text"]):
        warnings.append("RELATION_TEXT_MUST_BE_SEPARATED")
        result["relation_fragments"] = [
            line.strip()
            for line in result["raw_text"].split("|")
            if RELATION_PATTERN.search(line)
        ]
    identity_pattern = {
        "CurrentTransformer": r"\bCT\s*X?\s*\d*\b",
        "ZeroSequenceCurrentTransformer": r"\bZCT\s*X?\s*\d*\b",
        "VoltageTransformer": r"\b(?:PTT?|VT)\b",
    }.get(result.get("class_id"))
    if identity_pattern and len(re.findall(identity_pattern, result["normalized_text"], re.I)) > 2:
        warnings.append("MULTIPLE_REPEATED_IDENTITIES_SPLIT_REQUIRED")


def _coverage(result: dict[str, Any]) -> tuple[float, list[list[str]]]:
    required = REQUIRED_GROUPS.get(result["class_id"], [])
    if not required:
        return (1.0 if result["class_id"] else 0.0), []
    missing: list[list[str]] = []
    for group in required:
        if not any(name in result["properties"] for name in group):
            missing.append(list(group))
    return (len(required) - len(missing)) / len(required), missing


def parse_equipment_v2(
    raw_text: str,
    *,
    crop_scope: str = "equipment_description",
    ocr_lines: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = normalize_text(raw_text.replace("\n", " | "))
    base = parse_equipment(raw_text.replace("|", "\n"), crop_scope=crop_scope)
    new_class, identity = _match_new_class(text)
    new_class_has_priority = new_class in {
        "Generator",
        "AutomaticTransferSwitch",
        "AutomaticPowerFactorController",
        "PanelBoard",
        "MotorControlCenter",
        "BusDuct",
    }
    if new_class and (not base.get("class_id") or new_class_has_priority):
        base["class_id"] = new_class
        base["identity_evidence"] = identity
        base["properties"] = {}
        base["embedded_functions"] = []
        base["warnings"] = []
        base["status"] = "PARSED"
    base["raw_text"] = raw_text
    base["normalized_text"] = text
    base["pipeline_class"] = PIPELINE_CLASS.get(base.get("class_id"), base.get("class_id"))
    base["field_provenance"] = []
    base["validation_errors"] = []
    base["relation_fragments"] = []
    base["ocr_lines"] = list(ocr_lines or [])
    base["grammar_version"] = "sld-equipment-grammar/2.0"
    if base.get("class_id") in {name for name, _ in CLASS_RULES}:
        _augment_new_class(base, raw_text, text)
    if base.get("class_id"):
        _copy_base_provenance(base, raw_text, text)
    _validate(base)
    coverage, missing = _coverage(base)
    base["required_field_coverage"] = round(coverage, 4)
    base["missing_required_field_groups"] = missing
    identity_score = 1.0 if base.get("identity_evidence") else 0.0
    unit_score = min(1.0, len(base["field_provenance"]) / max(1, len(base["properties"])))
    multiline_score = 1.0 if len([line for line in raw_text.split("|") if line.strip()]) >= 2 else 0.65
    penalty = min(0.5, 0.2 * len(base["validation_errors"]) + 0.06 * len(base["warnings"]))
    score = 0.35 * identity_score + 0.4 * coverage + 0.15 * unit_score + 0.1 * multiline_score - penalty
    base["grammar_score"] = round(max(0.0, min(1.0, score)), 4)
    if not base.get("class_id"):
        base["status"] = "UNRESOLVED"
    elif base["validation_errors"] or missing or base["grammar_score"] < 0.72:
        base["status"] = "REVIEW_REQUIRED"
    else:
        base["status"] = "GRAMMAR_MATCHED_CANDIDATE"
    return base


def needs_vl_verification(parsed: dict[str, Any], ocr_confidence: float) -> list[str]:
    reasons: list[str] = []
    if ocr_confidence < 0.78:
        reasons.append("LOW_PRIMARY_OCR_CONFIDENCE")
    if parsed.get("grammar_score", 0.0) < 0.72:
        reasons.append("LOW_GRAMMAR_SCORE")
    if parsed.get("missing_required_field_groups"):
        reasons.append("MISSING_REQUIRED_FIELDS")
    if parsed.get("validation_errors"):
        reasons.append("ELECTRICAL_INVARIANT_FAILURE")
    if parsed.get("class_id") is None:
        reasons.append("UNRESOLVED_CLASS")
    if "RELATION_TEXT_MUST_BE_SEPARATED" in parsed.get("warnings", []):
        reasons.append("RELATION_CONTAMINATION")
    if "MULTIPLE_REPEATED_IDENTITIES_SPLIT_REQUIRED" in parsed.get("warnings", []):
        reasons.append("MULTIPLE_IDENTITIES_SPLIT_REQUIRED")
    return reasons


def _compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9가-힣]", "", normalize_text(value).upper())


def compare_primary_and_vl(primary_text: str, vl_text: str) -> dict[str, Any]:
    primary = _compact(primary_text)
    vl = _compact(vl_text)
    similarity = SequenceMatcher(None, primary, vl).ratio() if primary and vl else 0.0
    primary_numbers = set(NUMBER_TOKEN.findall(normalize_text(primary_text)))
    vl_numbers = set(NUMBER_TOKEN.findall(normalize_text(vl_text)))
    introduced = sorted(vl_numbers - primary_numbers)
    return {
        "text_similarity": round(similarity, 4),
        "primary_numbers": sorted(primary_numbers),
        "vl_numbers": sorted(vl_numbers),
        "vl_introduced_numbers": introduced,
        "numeric_grounding_pass": not introduced,
    }


def choose_verified_text(primary_text: str, primary_parse: dict[str, Any], vl_text: str) -> dict[str, Any]:
    vl_parse = parse_equipment_v2(vl_text)
    comparison = compare_primary_and_vl(primary_text, vl_text)
    score_gain = float(vl_parse.get("grammar_score", 0.0)) - float(primary_parse.get("grammar_score", 0.0))
    same_class = vl_parse.get("pipeline_class") == primary_parse.get("pipeline_class")
    accept = (
        vl_parse.get("class_id") is not None
        and same_class
        and comparison["text_similarity"] >= 0.5
        and comparison["numeric_grounding_pass"]
        and score_gain >= 0.05
        and not vl_parse.get("validation_errors")
    )
    confirm = (
        not accept
        and vl_parse.get("class_id") is not None
        and same_class
        and comparison["text_similarity"] >= 0.82
        and comparison["numeric_grounding_pass"]
        and not vl_parse.get("validation_errors")
    )
    decision = "ACCEPT_VL_TEXT" if accept else ("CONFIRM_PRIMARY" if confirm else "KEEP_PRIMARY_AND_FLAG")
    return {
        "decision": decision,
        "selected_text": vl_text if accept else primary_text,
        "selected_parse": vl_parse if accept else primary_parse,
        "vl_parse": vl_parse,
        "comparison": comparison,
        "grammar_score_gain": round(score_gain, 4),
        "geometry_source": "PADDLEOCR_PRIMARY_ONLY",
    }


__all__ = [
    "PIPELINE_CLASS",
    "compare_primary_and_vl",
    "choose_verified_text",
    "needs_vl_verification",
    "parse_equipment_v2",
]
