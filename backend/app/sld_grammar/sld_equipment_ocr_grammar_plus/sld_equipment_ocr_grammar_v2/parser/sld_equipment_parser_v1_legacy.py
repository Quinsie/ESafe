from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


ACRONYM_CANONICAL = {
    "A.C.B": "ACB",
    "A C B": "ACB",
    "M.C.C.B": "MCCB",
    "M C C B": "MCCB",
    "V.C.B": "VCB",
    "V C B": "VCB",
    "L.B.S": "LBS",
    "L B S": "LBS",
    "M.O.F": "MOF",
    "M O F": "MOF",
    "K.E.P.CO": "KEPCO",
    "K.E.P.C.O": "KEPCO",
}

# Corrections are deliberately conservative. They are applied only to tokens that
# already look like an electrical acronym, or digits inside a numeric expression.
TOKEN_CORRECTIONS = {
    "MCC8": "MCCB",
    "VC8": "VCB",
    "VOB": "VCB",
    "VGB": "VCB",
    "AC8": "ACB",
    "0CGR": "OCGR",
    "OCRR": "OCR",
    "UWR": "UVR",
}

PROTECTION_FUNCTIONS = ("OCR", "OCGR", "UVR")
MEASUREMENT_FUNCTIONS = ("V", "A", "KW", "KWH", "PF")


def _normalize_numeric_confusions(text: str) -> str:
    """Fix O/I/L only when surrounded by digits or unit-like suffixes."""
    # O between digits -> 0 (150O/5A, 63OA)
    text = re.sub(r"(?<=\d)[Oo](?=\d|\s*[/.,]|\s*(?:A|V|W|VA|KVA|KA|KV|HZ|AF|AT)\b)", "0", text)
    text = re.sub(r"(?<=\d)[Il](?=\d)", "1", text)
    # Decimal comma between digits -> decimal point; thousands commas are handled later.
    text = re.sub(r"(?<=\d),(?=\d{1,2}(?!\d))", ".", text)
    # Thousands separator (22,900) -> 22900. This runs only when exactly 3 digits follow.
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    return text


def normalize_text(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "")
    text = text.replace("Ø", "Φ").replace("ø", "Φ").replace("φ", "Φ").replace("ϕ", "Φ")
    text = text.replace("×", "x")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("／", "/").replace("：", ":")
    text = re.sub(r"\s+", " ", text.replace("\n", " \n ")).strip()
    upper = text.upper()
    for src, dst in sorted(ACRONYM_CANONICAL.items(), key=lambda kv: -len(kv[0])):
        upper = upper.replace(src, dst)
    upper = _normalize_numeric_confusions(upper)
    # Token-level corrections, not arbitrary substring replacement.
    tokens = re.split(r"(\W+)", upper)
    upper = "".join(TOKEN_CORRECTIONS.get(tok, tok) for tok in tokens)
    # Normalize unit spellings while preserving Korean.
    upper = re.sub(r"\bKVA\b", "kVA", upper)
    upper = re.sub(r"\bMVA\b", "MVA", upper)
    upper = re.sub(r"\bKVAR\b", "kvar", upper)
    upper = re.sub(r"\bKW\b", "kW", upper)
    upper = re.sub(r"\bKWH\b", "kWh", upper)
    upper = re.sub(r"\bKV\b", "kV", upper)
    upper = re.sub(r"\bKA\b", "kA", upper)
    upper = re.sub(r"\bHZ\b", "Hz", upper)
    upper = re.sub(r"\bAH\b", "Ah", upper)
    upper = re.sub(r"\bVA\b", "VA", upper)
    upper = re.sub(r"\s*([/:(),])\s*", r"\1", upper)
    upper = re.sub(r"\s*-\s*", "-", upper)
    upper = re.sub(r"[ \t]+", " ", upper)
    return upper.strip()


def to_volts(value: float, unit: str) -> float:
    return value * 1000.0 if unit.lower() == "kv" else value


def _number(pattern: str, text: str, flags: int = re.I) -> Optional[float]:
    m = re.search(pattern, text, flags)
    return float(m.group(1)) if m else None


def _int(pattern: str, text: str, flags: int = re.I) -> Optional[int]:
    v = _number(pattern, text, flags)
    return int(v) if v is not None else None


def _all_functions(text: str, names: Tuple[str, ...]) -> List[str]:
    found = []
    for name in names:
        m = re.search(rf"(?<![A-Z0-9]){re.escape(name)}(?![A-Z0-9])", text, re.I)
        if m:
            found.append((m.start(), name))
    return [name for _, name in sorted(found)]


def _voltage_matches(text: str) -> List[Tuple[float, str, Tuple[int, int]]]:
    out = []
    for m in re.finditer(r"(?<![A-Z0-9])([0-9]+(?:\.[0-9]+)?)\s*(kV|V)\b", text, re.I):
        out.append((to_volts(float(m.group(1)), m.group(2)), m.group(2), m.span()))
    return out


def _ratio(pattern_prefix: str, text: str) -> Optional[Dict[str, Any]]:
    """Parse a labeled voltage ratio such as PT:13.2kV/110V."""
    m = re.search(
        rf"{pattern_prefix}\s*:?\s*([0-9]+(?:\.[0-9]+)?)\s*(kV|V)?\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*(kV|V)",
        text,
        re.I,
    )
    if not m:
        return None
    p_unit = m.group(2) or m.group(4)
    return {
        "primary": {"value": to_volts(float(m.group(1)), p_unit), "unit": "V"},
        "secondary": {"value": to_volts(float(m.group(3)), m.group(4)), "unit": "V"},
        "raw": m.group(0),
    }


def _unlabeled_voltage_ratio(text: str) -> Optional[Dict[str, Any]]:
    # Supports 22,900V/380-220V and 380/110V.
    m = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*(kV|V)?\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*(?:-|/)?\s*([0-9]+(?:\.[0-9]+)?)?\s*(kV|V)",
        text,
        re.I,
    )
    if not m:
        return None
    p_unit = m.group(2) or m.group(5)
    result: Dict[str, Any] = {
        "primary": {"value": to_volts(float(m.group(1)), p_unit), "unit": "V"},
        "secondary_line": {"value": to_volts(float(m.group(3)), m.group(5)), "unit": "V"},
        "raw": m.group(0),
    }
    if m.group(4):
        result["secondary_line_to_neutral"] = {
            "value": to_volts(float(m.group(4)), m.group(5)),
            "unit": "V",
        }
    return result


def detect_class(text: str) -> Tuple[Optional[str], Optional[str]]:
    t = text
    ordered = [
        ("CurrentTransformerOpenCircuitProtectionDevice", r"\bCTOD\b|변류기\s*2차\s*개방\s*방지\s*보호장치"),
        ("DigitalMultifunctionMeter", r"\bDIGITAL\s+METER\b"),
        ("BranchCircuitMonitoringDevice", r"분기회로\s*감시\s*장치"),
        ("MaximumDemandPowerController", r"최대수요\s*전력\s*제어기"),
        ("UtilityIncoming", r"\bINCOMING\b.*(?:KEPCO|K\.E\.P\.CO)|한전\s*인입"),
        ("RectifierUnitTransformer", r"\bREC\s+UNIT\b.*\bTR\b|\bTR\s*\(DRY\s*TYPE\).*REC"),
        ("PowerTransformer", r"\bTRANSFORMER(?:-?\d+)?\b|\bTR#?\d+\b"),
        ("DryTypeTransformer", r"\bTR\.?\s*\(DRY\)"),
        ("AutomaticTransferCircuitBreaker", r"\bATCB\b"),
        ("AirCircuitBreaker", r"\bACB\b"),
        ("VacuumCircuitBreaker", r"\bVCB\b"),
        ("MoldedCaseCircuitBreaker", r"\bMCCB\b"),
        ("LoadBreakSwitch", r"\bLBS\b"),
        ("MeteringOutfit", r"\bMOF\b"),
        ("CurrentTransformer", r"\bCT\s*x?\s*\d*\b.*\d+\s*/\s*\d+\s*A\b"),
        ("VoltageTransformer", r"\bVT\s*x?\s*\d*\b|\bVOLTAGE\s+TRANSFORMER\b"),
        ("PowerFuse", r"\bPF\s*x\s*\d+\b|\bPOWER\s+FUSE\b"),
        ("LightningArrester", r"\bLA\s*x\s*\d+\b"),
        ("SurgeArrester", r"\bSA\s*x\s*\d+\b"),
        ("SurgeProtectiveDevice", r"\bSPD\b"),
        ("BatteryBank", r"\bBATTERY\b"),
        ("UninterruptiblePowerSupply", r"\bUPS\b"),
        ("EarthLeakageDetector", r"\bELD-[A-Z0-9\-]+\+?|\bELD\b"),
        ("CurrentShunt", r"\bSHUNT\b"),
        ("OverCurrentGroundRelay", r"^\s*OCGR\s*$"),
        ("UnderVoltageRelay", r"^\s*UVR\s*$"),
    ]
    for class_id, pattern in ordered:
        m = re.search(pattern, t, re.I | re.S)
        if m:
            return class_id, m.group(0)
    return None, None


def parse_equipment(raw_text: str, *, crop_scope: str = "equipment_description") -> Dict[str, Any]:
    t = normalize_text(raw_text)
    class_id, identity_span = detect_class(t)
    result: Dict[str, Any] = {
        "raw_text": raw_text,
        "normalized_text": t,
        "class_id": class_id,
        "identity_evidence": identity_span,
        "properties": {},
        "modifiers": [],
        "embedded_functions": [],
        "warnings": [],
        "status": "PARSED" if class_id else "UNRESOLVED",
    }
    if not class_id:
        return result

    p = result["properties"]
    # Generic quantities and phase/pole grammar.
    q = _int(r"\b(?:ACB|ATCB|VCB|MCCB|LBS|PF|CT|VT|LA|SA)\s*x\s*(\d+)\b", t)
    if q is not None:
        p["quantity"] = q
    pole = _int(r"\b([234])\s*P\b", t)
    if pole is not None:
        p["pole_count"] = pole
    phase = _int(r"\b([123])\s*Φ\b", t)
    if phase is not None:
        p["phase_count"] = phase
    phase_wire = re.search(r"\b([123])\s*Φ\s*([234])\s*W\b", t, re.I)
    if phase_wire:
        p["phase_count"] = int(phase_wire.group(1))
        p["wire_count"] = int(phase_wire.group(2))

    if class_id in {"AirCircuitBreaker", "AutomaticTransferCircuitBreaker"}:
        af = _number(r"\b([0-9]+(?:\.[0-9]+)?)\s*AF\b", t)
        at = _number(r"\b([0-9]+(?:\.[0-9]+)?)\s*AT\b", t)
        if af is not None:
            p["frame_current_a"] = af
        if at is not None:
            p["trip_current_a"] = at
        result["embedded_functions"] = _all_functions(t, PROTECTION_FUNCTIONS)

    elif class_id == "MoldedCaseCircuitBreaker":
        explicit = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*AF\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*AT", t, re.I)
        compact = re.search(r"(?<![/\d])([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*(AT|A)\b", t, re.I)
        if explicit:
            p["frame_current_a"] = float(explicit.group(1))
            p["trip_current_a"] = float(explicit.group(2))
            p["current_pair_notation"] = "EXPLICIT_AF_AT"
        elif compact:
            p["frame_current_a"] = float(compact.group(1))
            p["trip_current_a"] = float(compact.group(2))
            p["current_pair_notation"] = "MCCB_SLASH_PAIR_INFERRED_AF_AT"
        else:
            af = _number(r"\b([0-9]+(?:\.[0-9]+)?)\s*AF\b", t)
            at = _number(r"\b([0-9]+(?:\.[0-9]+)?)\s*AT\b", t)
            if af is not None:
                p["frame_current_a"] = af
            if at is not None:
                p["trip_current_a"] = at

    elif class_id == "VacuumCircuitBreaker":
        vm = _voltage_matches(t)
        if vm:
            p["rated_voltage_v"] = vm[0][0]
        # Rated current is the plain A value, not kA and not ratio.
        m = re.search(r"(?<![/\d.])([0-9]+(?:\.[0-9]+)?)\s*A\b", t, re.I)
        if m:
            p["rated_current_a"] = float(m.group(1))
        br = _number(r"([0-9]+(?:\.[0-9]+)?)\s*kA\b", t)
        if br is not None:
            p["breaking_current_ka"] = br
        mva = _number(r"([0-9]+(?:\.[0-9]+)?)\s*MVA\b", t)
        if mva is not None:
            p["breaking_capacity_mva"] = mva

    elif class_id == "LoadBreakSwitch":
        vm = _voltage_matches(t)
        if vm:
            p["rated_voltage_v"] = vm[0][0]
        amp = _number(r"(?<![/\d.])([0-9]+(?:\.[0-9]+)?)\s*A\b", t)
        if amp is not None:
            p["rated_current_a"] = amp
        if "MOTOR DRIVE TYPE" in t:
            p["operating_mechanism"] = "MOTOR_DRIVE"
        elif "MOTOR OPERATING TYPE" in t:
            p["operating_mechanism"] = "MOTOR_OPERATED"
        if "CUBICLE 내장형" in t:
            p["installation_form"] = "CUBICLE_INTERNAL"

    elif class_id == "BatteryBank":
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*V\s*x\s*([0-9]+)\s*CELL", t, re.I)
        if m:
            p["cell_voltage_v"] = float(m.group(1))
            p["cell_count"] = int(m.group(2))
            p["derived_nominal_voltage_v"] = float(m.group(1)) * int(m.group(2))
            p["derived_fields"] = ["derived_nominal_voltage_v"]
        ah = _number(r"([0-9]+(?:\.[0-9]+)?)\s*Ah\b", t)
        if ah is not None:
            p["capacity_ah"] = ah
        if "무보수밀폐형" in t:
            p["construction"] = "MAINTENANCE_FREE_SEALED"

    elif class_id == "CurrentTransformer":
        m = re.search(r"\bCT\s*x\s*([0-9]+)", t, re.I)
        if m:
            p["quantity"] = int(m.group(1))
        r = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*A\b", t, re.I)
        if r:
            p["ct_ratio"] = {"primary_a": float(r.group(1)), "secondary_a": float(r.group(2))}

    elif class_id == "VoltageTransformer":
        m = re.search(r"\bVT\s*x\s*([0-9]+)", t, re.I)
        if m:
            p["quantity"] = int(m.group(1))
        b = _number(r"\(([0-9]+(?:\.[0-9]+)?)\s*VA\)", t)
        if b is not None:
            p["burden_va"] = b
        if "MOLD" in t:
            p["construction"] = "MOLD"
        ratio = _unlabeled_voltage_ratio(t)
        if ratio:
            p["voltage_ratio"] = ratio

    elif class_id == "MeteringOutfit":
        if "MOLD TYPE" in t:
            p["construction"] = "MOLD"
        pt = _ratio(r"\bPT", t)
        if pt:
            # quantity may be written after the secondary voltage: 110Vx3
            qpt = re.search(r"\bPT[^\n]*?/[0-9.]+\s*(?:kV|V)\s*x\s*([0-9]+)", t, re.I)
            if qpt:
                pt["quantity"] = int(qpt.group(1))
            burden = re.search(r"\(([0-9]+(?:\.[0-9]+)?)\s*VA\)", t, re.I)
            if burden:
                pt["burden_va"] = float(burden.group(1))
            p["pt"] = pt
        ct = re.search(r"\bCT\s*:?\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*A", t, re.I)
        if ct:
            p["ct"] = {"primary_a": float(ct.group(1)), "secondary_a": float(ct.group(2)), "raw": ct.group(0)}
        strength = _number(r"과전류강도\s*[:=-]?\s*([0-9]+(?:\.[0-9]+)?)\s*배", t)
        if strength is not None:
            p["overcurrent_strength_multiplier"] = strength

    elif class_id == "PowerFuse":
        m = re.search(r"\bPF\s*x\s*([0-9]+)", t, re.I)
        if m:
            p["quantity"] = int(m.group(1))
        vm = _voltage_matches(t)
        if vm:
            p["rated_voltage_v"] = vm[0][0]
        af = _number(r"([0-9]+(?:\.[0-9]+)?)\s*AF\b", t)
        if af is not None:
            p["fuse_holder_frame_current_a"] = af
        fuse = _number(r"\(([0-9]+(?:\.[0-9]+)?)\s*A\s*FUSE\)", t)
        if fuse is not None:
            p["fuse_link_current_a"] = fuse

    elif class_id in {"LightningArrester", "SurgeArrester"}:
        acronym = "LA" if class_id == "LightningArrester" else "SA"
        m = re.search(rf"\b{acronym}\s*x\s*([0-9]+)", t, re.I)
        if m:
            p["quantity"] = int(m.group(1))
        vm = _voltage_matches(t)
        if vm:
            p["rated_voltage_v"] = vm[0][0]
        ka = _number(r"([0-9]+(?:\.[0-9]+)?)\s*kA\b", t)
        if ka is not None:
            p["nominal_discharge_current_ka"] = ka
        if re.search(r"W/\s*DS", t, re.I):
            p["accessories"] = ["DS"]

    elif class_id == "SurgeProtectiveDevice":
        cls = _int(r"\bCLASS\s*([0-9]+)\b", t)
        if cls is not None:
            p["spd_class"] = cls
        ka = _number(r"([0-9]+(?:\.[0-9]+)?)\s*kA\b", t)
        if ka is not None:
            p["surge_current_ka"] = ka

    elif class_id == "DryTypeTransformer":
        p["construction"] = "DRY"
        kva = _number(r"([0-9]+(?:\.[0-9]+)?)\s*kVA\b", t)
        if kva is not None:
            p["capacity_kva"] = kva

    elif class_id == "RectifierUnitTransformer":
        p["construction"] = "DRY"
        p["application"] = "RECTIFIER_UNIT"
        ratio = _unlabeled_voltage_ratio(t)
        if ratio:
            p["voltage_ratio"] = ratio
        kva = _number(r"([0-9]+(?:\.[0-9]+)?)\s*kVA\b", t)
        if kva is not None:
            p["capacity_kva"] = kva

    elif class_id == "PowerTransformer":
        tag = re.search(r"\b(TRANSFORMER-?\d+|TR#?\d+)\b", t, re.I)
        if tag:
            p["tag"] = tag.group(1)
        if "MOLD" in t:
            p["construction"] = "MOLD"
        if "고효율" in t:
            p["efficiency_descriptor"] = "HIGH_EFFICIENCY"
        if "저소음" in t:
            p["noise_descriptor"] = "LOW_NOISE"
        if "전등전열용" in t or "전등,전열용" in t:
            p["service"] = "LIGHTING_AND_HEATING"
        # Labeled P/S/C form has priority.
        pm = re.search(r"\bP:([0-9]+(?:\.[0-9]+)?)\s*(kV|V)\b", t, re.I)
        sm = re.search(r"\bS:([0-9]+(?:\.[0-9]+)?)\s*[/\-]\s*([0-9]+(?:\.[0-9]+)?)\s*(kV|V)\b", t, re.I)
        cm = re.search(r"\bC:([0-9]+(?:\.[0-9]+)?)\s*kVA\b", t, re.I)
        if pm:
            p["primary_voltage_v"] = to_volts(float(pm.group(1)), pm.group(2))
        if sm:
            p["secondary_line_voltage_v"] = to_volts(float(sm.group(1)), sm.group(3))
            p["secondary_line_to_neutral_voltage_v"] = to_volts(float(sm.group(2)), sm.group(3))
        if cm:
            p["capacity_kva"] = float(cm.group(1))
        if not pm:
            ratio = _unlabeled_voltage_ratio(t)
            if ratio:
                p["voltage_ratio"] = ratio
        if "capacity_kva" not in p:
            kva = _number(r"([0-9]+(?:\.[0-9]+)?)\s*kVA\b", t)
            if kva is not None:
                p["capacity_kva"] = kva
        z = _number(r"Z\s*%?\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*%", t)
        if z is not None:
            p["impedance_percent"] = z
        kf = _number(r"K-?FACTOR\s*([0-9]+(?:\.[0-9]+)?)", t)
        if kf is not None:
            p["k_factor"] = kf

    elif class_id == "UninterruptiblePowerSupply":
        kva = _number(r"([0-9]+(?:\.[0-9]+)?)\s*kVA\b", t)
        if kva is not None:
            p["capacity_kva"] = kva
        # Optional voltage/frequency lines are accepted only if readable.
        vm = _voltage_matches(t)
        if vm:
            p["voltage_candidates_v"] = [v[0] for v in vm]
        hz = _number(r"([0-9]+(?:\.[0-9]+)?)\s*Hz\b", t)
        if hz is not None:
            p["frequency_hz"] = hz

    elif class_id == "DigitalMultifunctionMeter":
        # Restrict parsing to tokens inside the meter description/enclosure.
        p["measurement_functions"] = _all_functions(t, MEASUREMENT_FUNCTIONS)
        p["protection_functions"] = _all_functions(t, PROTECTION_FUNCTIONS)

    elif class_id == "EarthLeakageDetector":
        model = re.search(r"\bELD-[A-Z0-9\-]+\+?", t, re.I)
        if model:
            p["model"] = model.group(0)
        cct = _int(r"\b([0-9]+)\s*CCT\b", t)
        if cct is not None:
            p["circuit_count"] = cct

    elif class_id == "BranchCircuitMonitoringDevice":
        q2 = _int(r"\bx\s*([0-9]+)\b", t)
        p["quantity"] = q2 if q2 is not None else 1

    elif class_id == "MaximumDemandPowerController":
        if "피크제어 장치 설치" in t:
            p["installation_note"] = "피크제어 장치 설치"

    elif class_id == "UtilityIncoming":
        vm = _voltage_matches(t)
        if vm:
            p["rated_voltage_v"] = vm[0][0]
        if re.search(r"kV-Y\b", t, re.I):
            p["connection"] = "Y"
        if re.search(r"\bAC\b", t):
            p["current_type"] = "AC"
        hz = _number(r"([0-9]+(?:\.[0-9]+)?)\s*Hz\b", t)
        if hz is not None:
            p["frequency_hz"] = hz
        p["source_organization"] = "KEPCO"
        fm = re.search(r"FROM:?\s*([^\n]+)", t, re.I)
        if fm:
            p["upstream_source_text"] = fm.group(1).strip()

    elif class_id == "CurrentTransformerOpenCircuitProtectionDevice":
        p["full_name_ko"] = "변류기 2차 개방 방지 보호장치"

    # Standalone relays and shunt have identity only in the supplied references.

    # Validation / semantic disambiguation rules.
    if "frame_current_a" in p and "trip_current_a" in p and p["frame_current_a"] < p["trip_current_a"]:
        result["warnings"].append("FRAME_CURRENT_LT_TRIP_CURRENT")
    if class_id == "CurrentTransformer" and "CCT" in t:
        result["warnings"].append("CCT_MUST_NOT_BE_PARSED_AS_CT")
    if crop_scope != "equipment_description" and class_id in {
        "CurrentTransformer",
        "VoltageTransformer",
        "PowerFuse",
        "LightningArrester",
        "SurgeArrester",
        "OverCurrentGroundRelay",
        "UnderVoltageRelay",
    }:
        result["status"] = "REVIEW_REQUIRED"
        result["warnings"].append("SHORT_ALIAS_REQUIRES_SYMBOL_OR_CROP_CONTEXT")
    return result


__all__ = ["normalize_text", "detect_class", "parse_equipment"]
