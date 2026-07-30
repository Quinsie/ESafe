from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from . import sld_equipment_parser_v1_legacy as legacy


V2_PROTECTION_FUNCTIONS = ("OCR", "OCGR", "UVR", "OVR")
V2_MEASUREMENT_FUNCTIONS = ("V", "A", "KW", "KWH", "PF")

V2_NATIVE_CLASSES = {
    "AutomaticTransferSwitch",
    "CurrentTransformerTestTerminal",
    "PotentialTransformerTestTerminal",
    "StaticCapacitor",
    "SeriesReactor",
    "PowerMeasurementSection",
    "GroundingReference",
    "BusDuct",
}

SYMBOL_HINT_TO_CLASS = {
    "ATS_SYMBOL": "AutomaticTransferSwitch",
    "CTT_SYMBOL": "CurrentTransformerTestTerminal",
    "PTT_SYMBOL": "PotentialTransformerTestTerminal",
    "STATIC_CAPACITOR_SYMBOL": "StaticCapacitor",
    "SERIES_REACTOR_SYMBOL": "SeriesReactor",
    "GROUNDING_SYMBOL": "GroundingReference",
    "MCCB_SYMBOL": "MoldedCaseCircuitBreaker",
    "ACB_SYMBOL": "AirCircuitBreaker",
    "VCB_SYMBOL": "VacuumCircuitBreaker",
    "MOF_SYMBOL": "MeteringOutfit",
    "CT_SYMBOL": "CurrentTransformer",
    "VT_SYMBOL": "VoltageTransformer",
    "PF_SYMBOL": "PowerFuse",
    "BUS_DUCT_SYMBOL": "BusDuct",
}

LEGACY_IDENTITY_PREFIX = {
    "MoldedCaseCircuitBreaker": "MCCB",
    "AirCircuitBreaker": "ACB",
    "VacuumCircuitBreaker": "VCB",
    "MeteringOutfit": "MOF",
    "CurrentTransformer": "CT",
    "VoltageTransformer": "VT",
    "PowerFuse": "PF",
    "LoadBreakSwitch": "LBS",
    "PowerTransformer": "TRANSFORMER",
    "DigitalMultifunctionMeter": "DIGITAL METER",
}


def _levenshtein(a: str, b: str) -> int:
    a, b = a.upper(), b.upper()
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (ca != cb),
            ))
        previous = current
    return previous[-1]


def _replace_token(text: str, token: str, replacement: str) -> str:
    return re.sub(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])", replacement, text, count=1, flags=re.I)


def _repair_identity_by_signature(text: str, context: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """Conservative identity repair. A short/fuzzy token is repaired only when
    an equipment-specific rating signature or an explicit symbol hint exists.
    """
    context = context or {}
    repairs: List[str] = []
    t = text

    direct = {
        "DIGITAR METER": "DIGITAL METER",
        "DIGITAR METER2": "DIGITAL METER",
        "M0LD": "MOLD",
        "0VR": "OVR",
    }
    for src, dst in direct.items():
        if src in t:
            t = t.replace(src, dst)
            repairs.append(f"{src}->{dst}")

    acronym_patterns = [
        (r"(?<![A-Z0-9])A\s*\.\s*T\s*\.\s*S(?![A-Z0-9])", "ATS", "A.T.S->ATS"),
        (r"(?<![A-Z0-9])A\s+T\s+S(?![A-Z0-9])", "ATS", "A T S->ATS"),
        (r"(?<![A-Z0-9])C\s*\.\s*T\s*\.\s*T(?![A-Z0-9])", "CTT", "C.T.T->CTT"),
        (r"(?<![A-Z0-9])C\s+T\s+T(?![A-Z0-9])", "CTT", "C T T->CTT"),
        (r"(?<![A-Z0-9])P\s*\.\s*T\s*\.\s*T(?![A-Z0-9])", "PTT", "P.T.T->PTT"),
        (r"(?<![A-Z0-9])P\s+T\s+T(?![A-Z0-9])", "PTT", "P T T->PTT"),
        (r"(?<![A-Z0-9])S\s*\.\s*C(?![A-Z0-9])", "SC", "S.C->SC"),
        (r"(?<![A-Z0-9])S\s*\.\s*R(?![A-Z0-9])", "SR", "S.R->SR"),
    ]
    for pattern, replacement, label in acronym_patterns:
        t2 = re.sub(pattern, replacement, t, flags=re.I)
        if t2 != t:
            repairs.append(label)
            t = t2

    # MCCB is often crossed by a heavy horizontal conductor. Repair a token
    # within edit distance 1 only when pole count and AF/AT pair are present.
    if "MCCB" not in t and re.search(r"\b[234]\s*P\b", t, re.I) and re.search(
        r"\b\d{2,5}\s*/\s*\d{1,5}\s*(?:AT|A)\b", t, re.I
    ):
        for tok in re.findall(r"\b[A-Z0-9]{3,5}\b", t.upper()):
            if _levenshtein(tok, "MCCB") <= 1:
                t = _replace_token(t, tok, "MCCB")
                repairs.append(f"{tok}->MCCB(signature)")
                break

    # ATS OCR confusion (AT5/AT$) is accepted only with pole/current signature
    # or an ATS symbol hint.
    if "ATS" not in t:
        ats_sig = bool(re.search(r"\b[234]\s*P\b", t, re.I) and re.search(r"\b\d{2,5}\s*AT\b", t, re.I))
        ats_hint = context.get("symbol_hint") == "ATS_SYMBOL"
        if ats_sig or ats_hint:
            for tok in re.findall(r"\b[A-Z0-9]{2,4}\b", t.upper()):
                if tok.startswith("AT") and _levenshtein(tok, "ATS") <= 1:
                    t = _replace_token(t, tok, "ATS")
                    repairs.append(f"{tok}->ATS(signature)")
                    break

    # CTT/PTT OCR confusions are accepted only with their symbol hints.
    hint = context.get("symbol_hint")
    if hint == "CTT_SYMBOL" and not re.search(r"(?<![A-Z0-9])CTT(?![A-Z0-9])", t):
        t2 = re.sub(r"(?<![A-Z0-9])CT[7I](?![A-Z0-9])", "CTT", t, count=1, flags=re.I)
        if t2 != t:
            repairs.append("CT7/CTI->CTT(symbol)")
            t = t2
    if hint == "PTT_SYMBOL" and not re.search(r"(?<![A-Z0-9])PTT(?![A-Z0-9])", t):
        t2 = re.sub(r"(?<![A-Z0-9])PT[7I](?![A-Z0-9])", "PTT", t, count=1, flags=re.I)
        if t2 != t:
            repairs.append("PT7/PTI->PTT(symbol)")
            t = t2

    # Short aliases SR/SC require symbol context if the OCR token itself is damaged.
    if hint == "SERIES_REACTOR_SYMBOL" and not re.search(r"\bSR\b", t):
        for tok in re.findall(r"\b[A-Z0-9.]{1,3}\b", t.upper()):
            if _levenshtein(tok.replace(".", ""), "SR") <= 1:
                t = _replace_token(t, tok, "SR")
                repairs.append(f"{tok}->SR(symbol)")
                break
    if hint == "STATIC_CAPACITOR_SYMBOL" and not re.search(r"\bSC\b", t):
        for tok in re.findall(r"\b[A-Z0-9.]{1,3}\b", t.upper()):
            if _levenshtein(tok.replace(".", ""), "SC") <= 1:
                t = _replace_token(t, tok, "SC")
                repairs.append(f"{tok}->SC(symbol)")
                break

    return t, repairs


def normalize_text(raw: str, context: Optional[Dict[str, Any]] = None) -> str:
    t = legacy.normalize_text(raw)
    t, _ = _repair_identity_by_signature(t, context)
    # Keep bus-duct spelling variants machine-comparable without destroying
    # the source configuration AL-AL / AL+AL.
    t = re.sub(r"\bBUS\s*-?\s*DUCT\b", "BUS DUCT", t, flags=re.I)
    t = re.sub(r"\bFR\s*-?\s*BUS\s+DUCT\b", "FR-BUS DUCT", t, flags=re.I)
    return t


def _all_functions(text: str, names: Tuple[str, ...]) -> List[str]:
    found = []
    for name in names:
        m = re.search(rf"(?<![A-Z0-9]){re.escape(name)}(?![A-Z0-9])", text, re.I)
        if m:
            found.append((m.start(), name))
    return [name for _, name in sorted(found)]


def _number(pattern: str, text: str, flags: int = re.I) -> Optional[float]:
    m = re.search(pattern, text, flags)
    return float(m.group(1)) if m else None


def _int(pattern: str, text: str, flags: int = re.I) -> Optional[int]:
    value = _number(pattern, text, flags)
    return int(value) if value is not None else None


def _to_volts(value: float, unit: str) -> float:
    return value * 1000.0 if unit.lower() == "kv" else value


def _base_result(raw: str, normalized: str, class_id: Optional[str], evidence: Optional[str]) -> Dict[str, Any]:
    return {
        "raw_text": raw,
        "normalized_text": normalized,
        "class_id": class_id,
        "identity_evidence": evidence,
        "properties": {},
        "modifiers": [],
        "embedded_functions": [],
        "warnings": [],
        "status": "PARSED" if class_id else "UNRESOLVED",
        "normalization_repairs": [],
    }


def _detect_v2_class(text: str, context: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str]]:
    context = context or {}
    ordered = [
        ("CurrentTransformerTestTerminal", r"(?<![A-Z0-9])CTT(?![A-Z0-9])"),
        ("PotentialTransformerTestTerminal", r"(?<![A-Z0-9])PTT(?![A-Z0-9])"),
        ("PowerMeasurementSection", r"전력\s*계측부|POWER\s+METERING\s+SECTION"),
        ("AutomaticTransferSwitch", r"(?<![A-Z0-9])ATS(?![A-Z0-9])"),
        ("BusDuct", r"\b(?:FR-)?BUS\s+DUCT\b|\bBUSDUCT\b"),
    ]
    for class_id, pattern in ordered:
        m = re.search(pattern, text, re.I)
        if m:
            return class_id, m.group(0)

    # SC is short and ambiguous. Require a full name, a symbol hint, or the
    # phase+capacity signature visible in the supplied reference crop.
    sc = re.search(r"(?<![A-Z0-9])(?:SC|STATIC\s+(?:CAPACITOR|CONDENSER))(?![A-Z0-9])", text, re.I)
    if sc:
        sc_context = context.get("symbol_hint") == "STATIC_CAPACITOR_SYMBOL"
        sc_signature = bool(re.search(r"\b[123]\s*Φ\b", text) and re.search(r"\d+(?:\.\d+)?\s*(?:kVA|kvar)\b", text, re.I))
        full_name = "STATIC" in sc.group(0).upper()
        if sc_context or sc_signature or full_name:
            return "StaticCapacitor", sc.group(0)

    # SR is intentionally context-gated because it is a two-character alias.
    if re.search(r"(?<![A-Z0-9])SR(?![A-Z0-9])", text, re.I):
        if context.get("symbol_hint") == "SERIES_REACTOR_SYMBOL" or re.search(r"SERIES\s+REACTOR", text, re.I):
            return "SeriesReactor", "SR"

    # Grounding reference is also context-gated. E1/E2 by itself is common noise.
    ground_explicit = re.search(r"\b(?:GROUND|EARTH|접지)\b", text, re.I)
    ground_id = re.search(r"(?<![A-Z0-9])E\s*([0-9]+)(?![A-Z0-9])", text, re.I)
    if ground_explicit or (ground_id and context.get("symbol_hint") == "GROUNDING_SYMBOL"):
        evidence = ground_explicit.group(0) if ground_explicit else ground_id.group(0)
        return "GroundingReference", evidence

    return None, None


def parse_equipment(
    raw_text: str,
    *,
    crop_scope: str = "equipment_description",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context = dict(context or {})
    if "crop_scope" in context:
        crop_scope = str(context["crop_scope"])
    normalized0 = legacy.normalize_text(raw_text)
    t, repairs = _repair_identity_by_signature(normalized0, context)
    t = re.sub(r"\bBUS\s*-?\s*DUCT\b", "BUS DUCT", t, flags=re.I)
    t = re.sub(r"\bFR\s*-?\s*BUS\s+DUCT\b", "FR-BUS DUCT", t, flags=re.I)

    forced = context.get("forced_class_id")
    if not forced:
        hint = context.get("symbol_hint")
        hint_conf = float(context.get("symbol_confidence", 1.0))
        if hint_conf >= 0.80:
            forced = SYMBOL_HINT_TO_CLASS.get(str(hint))

    class_id, evidence = _detect_v2_class(t, context)
    if forced:
        class_id = str(forced)
        evidence = context.get("anchor_text") or evidence or forced

    # Existing v1 classes remain backward compatible. A high-confidence symbol
    # hint may force a legacy class even when the identity text was fully
    # occluded; in that case prepend the canonical identity only for parsing.
    if class_id is None or class_id not in V2_NATIVE_CLASSES:
        legacy_input = t
        if forced and class_id in LEGACY_IDENTITY_PREFIX:
            prefix = LEGACY_IDENTITY_PREFIX[class_id]
            if not re.search(rf"(?<![A-Z0-9]){re.escape(prefix)}(?![A-Z0-9])", legacy_input, re.I):
                legacy_input = f"{prefix} {legacy_input}".strip()
                repairs.append(f"IDENTITY_FROM_SYMBOL_HINT:{prefix}")
        result = legacy.parse_equipment(legacy_input, crop_scope=crop_scope)
        result["raw_text"] = raw_text
        result["normalized_text"] = t
        result["normalization_repairs"] = repairs
        if forced and result.get("class_id") is None:
            result["class_id"] = class_id
            result["identity_evidence"] = context.get("anchor_text") or f"SYMBOL_HINT:{context.get('symbol_hint')}"
            result["status"] = "PARSED"
        # v2 adds OVR to the digital meter's embedded protection function set.
        if result.get("class_id") == "DigitalMultifunctionMeter":
            p = result.setdefault("properties", {})
            p["measurement_functions"] = _all_functions(t, V2_MEASUREMENT_FUNCTIONS)
            p["protection_functions"] = _all_functions(t, V2_PROTECTION_FUNCTIONS)
        if context.get("association_evidence"):
            result["association_evidence"] = context["association_evidence"]
        return result

    result = _base_result(raw_text, t, class_id, evidence)
    result["normalization_repairs"] = repairs
    p = result["properties"]

    pole = _int(r"\b([234])\s*P\b", t)
    phase_wire = re.search(r"\b([123])\s*Φ\s*([234])\s*W\b", t, re.I)
    phase = _int(r"\b([123])\s*Φ\b", t)
    if pole is not None:
        p["pole_count"] = pole
    if phase_wire:
        p["phase_count"] = int(phase_wire.group(1))
        p["wire_count"] = int(phase_wire.group(2))
    elif phase is not None:
        p["phase_count"] = phase

    if class_id == "AutomaticTransferSwitch":
        m = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*(AT|A)\b", t, re.I)
        if m:
            p["rated_current_a"] = float(m.group(1))
            p["current_notation"] = m.group(2).upper()

    elif class_id == "CurrentTransformerTestTerminal":
        p["terminal_function"] = "CT_TEST"

    elif class_id == "PotentialTransformerTestTerminal":
        p["terminal_function"] = "PT_TEST"

    elif class_id == "StaticCapacitor":
        kvar = _number(r"([0-9]+(?:\.[0-9]+)?)\s*kvar\b", t)
        kva = _number(r"([0-9]+(?:\.[0-9]+)?)\s*kVA\b", t)
        if kvar is not None:
            p["reactive_power_kvar"] = kvar
            p["capacity_unit_source"] = "kvar"
        elif kva is not None:
            p["capacity_kva"] = kva
            p["capacity_unit_source"] = "kVA"
            result["warnings"].append("STATIC_CAPACITOR_KVA_PRESERVED_FROM_SOURCE_NOT_CONVERTED")

    elif class_id == "SeriesReactor":
        p["reactor_type"] = "SERIES"
        if context.get("symbol_hint") != "SERIES_REACTOR_SYMBOL" and not re.search(r"SERIES\s+REACTOR", t, re.I):
            result["status"] = "REVIEW_REQUIRED"
            result["warnings"].append("SHORT_ALIAS_SR_REQUIRES_REACTOR_SYMBOL")

    elif class_id == "PowerMeasurementSection":
        p["measurement_functions"] = _all_functions(t, V2_MEASUREMENT_FUNCTIONS)
        m = re.search(r"(디지털\s*(?:보호\s*)?계전기|DIGITAL\s+PROTECTION\s+RELAY)", t, re.I)
        if m:
            p["protection_module_type"] = "DIGITAL_PROTECTION_RELAY"
            p["protection_module_text_raw"] = m.group(0)

    elif class_id == "GroundingReference":
        m = re.search(r"(?<![A-Z0-9])E\s*([0-9]+)(?![A-Z0-9])", t, re.I)
        if m:
            p["reference_designation"] = f"E{int(m.group(1))}"
        if context.get("symbol_hint") != "GROUNDING_SYMBOL" and not re.search(r"\b(?:GROUND|EARTH|접지)\b", t, re.I):
            result["status"] = "REVIEW_REQUIRED"
            result["warnings"].append("GROUND_REFERENCE_REQUIRES_SYMBOL_OR_EXPLICIT_TEXT")

    elif class_id == "BusDuct":
        vm = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(kV|V)\b", t, re.I)
        if vm:
            p["rated_voltage_v"] = _to_volts(float(vm.group(1)), vm.group(2))
        # Current must be taken after/inside BUS DUCT description, not phase/wire digits.
        amps = list(re.finditer(r"([0-9]+(?:\.[0-9]+)?)\s*A\b", t, re.I))
        if amps:
            p["rated_current_a"] = float(amps[-1].group(1))
        p["fire_resistant"] = bool(re.search(r"\bFR-BUS\s+DUCT\b", t, re.I))
        cfg = re.search(r"\b(AL)\s*([+\-])\s*(AL)\b", t, re.I)
        if cfg:
            p["conductor_configuration_raw"] = f"{cfg.group(1).upper()}{cfg.group(2)}{cfg.group(3).upper()}"
            p["conductor_materials"] = [cfg.group(1).upper(), cfg.group(3).upper()]

    if context.get("association_evidence"):
        result["association_evidence"] = context["association_evidence"]
    return result


def parse_mof_associated(
    anchor_text: str,
    description_text: str,
    *,
    association_evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse an MOF anchor and a remote semantic description as one object."""
    combined = "\n".join(x for x in [anchor_text, description_text] if x)
    return parse_equipment(
        combined,
        context={
            "forced_class_id": "MeteringOutfit",
            "anchor_text": anchor_text or "MOF",
            "association_evidence": association_evidence or {
                "association_method": "MOF_WIDE_SPAN_SEMANTIC_ASSOCIATION_V2"
            },
        },
    )


__all__ = [
    "normalize_text",
    "parse_equipment",
    "parse_mof_associated",
]
