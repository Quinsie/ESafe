from __future__ import annotations

import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


V2_PARSER_DIR = (
    Path(__file__).resolve().parents[2]
    / "sld_equipment_ocr_grammar_v2"
    / "parser"
)
if str(V2_PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(V2_PARSER_DIR))

from sld_equipment_parser_v2 import parse_equipment_v2  # noqa: E402


NUMBER_TOKEN = re.compile(r"\d+(?:\.\d+)?")


def parse_equipment_v3(
    raw_text: str,
    *,
    crop_scope: str = "equipment_description",
    ocr_lines: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parsed = parse_equipment_v2(
        raw_text,
        crop_scope=crop_scope,
        ocr_lines=ocr_lines,
    )
    parsed["grammar_version"] = "sld-equipment-grammar/3.0"
    return parsed


def _compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9가-힣]", "", value.upper())


def _numeric_tokens(value: str) -> set[str]:
    return set(NUMBER_TOKEN.findall(value))


def _provenance_numbers(parsed: dict[str, Any]) -> set[str]:
    evidence = " ".join(
        str(item.get("matched_text") or "")
        for item in parsed.get("field_provenance", [])
    )
    return _numeric_tokens(evidence)


def reconcile_upstage_vl(
    upstage_text: str,
    vl_text: str,
    *,
    candidate_class_hint: str | None = None,
    upstage_ocr_lines: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    upstage_parse = parse_equipment_v3(upstage_text, ocr_lines=upstage_ocr_lines)
    vl_parse = parse_equipment_v3(vl_text)
    upstage_compact = _compact(upstage_text)
    vl_compact = _compact(vl_text)
    similarity = (
        SequenceMatcher(None, upstage_compact, vl_compact).ratio()
        if upstage_compact and vl_compact
        else 0.0
    )
    upstage_numbers = _numeric_tokens(upstage_text)
    vl_numbers = _numeric_tokens(vl_text)
    introduced_numbers = sorted(vl_numbers - upstage_numbers)
    removed_numbers = sorted(upstage_numbers - vl_numbers)
    provenance_numbers = _provenance_numbers(vl_parse)
    introduced_are_explicit_fields = all(
        value in provenance_numbers for value in introduced_numbers
    )
    vl_class = vl_parse.get("pipeline_class")
    upstage_class = upstage_parse.get("pipeline_class")
    class_agrees = bool(
        vl_class
        and (
            vl_class == upstage_class
            or vl_class == candidate_class_hint
            or (upstage_class is None and candidate_class_hint is None)
        )
    )
    grammar_gain = float(vl_parse.get("grammar_score", 0.0)) - float(
        upstage_parse.get("grammar_score", 0.0)
    )
    coverage_gain = float(vl_parse.get("required_field_coverage", 0.0)) - float(
        upstage_parse.get("required_field_coverage", 0.0)
    )
    invariant_pass = not vl_parse.get("validation_errors")
    upstage_relation_free = (
        "RELATION_TEXT_MUST_BE_SEPARATED" not in upstage_parse.get("warnings", [])
    )
    vl_relation_free = (
        "RELATION_TEXT_MUST_BE_SEPARATED" not in vl_parse.get("warnings", [])
    )
    confirm = (
        class_agrees
        and similarity >= 0.82
        and not introduced_numbers
        and not removed_numbers
        and invariant_pass
        and upstage_relation_free
        and vl_relation_free
    )
    enhance = (
        not confirm
        and class_agrees
        and similarity >= 0.30
        and grammar_gain >= 0.08
        and coverage_gain >= 0.0
        and invariant_pass
        and vl_relation_free
        and len(introduced_numbers) <= 6
        and introduced_are_explicit_fields
        and bool(vl_parse.get("field_provenance"))
    )
    if enhance:
        decision = "USE_VL_ENHANCEMENT"
        selected_text = vl_text
        selected_parse = vl_parse
    elif confirm:
        decision = "CONFIRM_UPSTAGE"
        selected_text = upstage_text
        selected_parse = upstage_parse
    else:
        decision = "KEEP_BOTH_REVIEW"
        selected_text = upstage_text
        selected_parse = upstage_parse
    return {
        "decision": decision,
        "selected_text": selected_text,
        "selected_parse": selected_parse,
        "upstage_parse": upstage_parse,
        "vl_parse": vl_parse,
        "comparison": {
            "text_similarity": round(similarity, 4),
            "class_agrees": class_agrees,
            "candidate_class_hint": candidate_class_hint,
            "upstage_class": upstage_class,
            "vl_class": vl_class,
            "upstage_numbers": sorted(upstage_numbers),
            "vl_numbers": sorted(vl_numbers),
            "vl_introduced_numbers": introduced_numbers,
            "vl_removed_numbers": removed_numbers,
            "introduced_numbers_have_explicit_field_provenance": introduced_are_explicit_fields,
            "electrical_invariant_pass": invariant_pass,
            "upstage_relation_free": upstage_relation_free,
            "vl_relation_free": vl_relation_free,
        },
        "grammar_score_gain": round(grammar_gain, 4),
        "required_field_coverage_gain": round(coverage_gain, 4),
        "geometry_source": "UPSTAGE_OCR_ONLY",
        "review_required": True,
    }


__all__ = ["parse_equipment_v3", "reconcile_upstage_vl"]
