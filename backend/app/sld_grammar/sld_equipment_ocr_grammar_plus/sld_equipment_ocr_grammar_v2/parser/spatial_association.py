from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, asdict
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .sld_equipment_parser import normalize_text


@dataclass(frozen=True)
class BBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def diagonal(self) -> float:
        return math.hypot(self.width, self.height)

    def union(self, other: "BBox") -> "BBox":
        return BBox(
            min(self.x1, other.x1),
            min(self.y1, other.y1),
            max(self.x2, other.x2),
            max(self.y2, other.y2),
        )

    def contains_center(self, other: "BBox") -> bool:
        return self.x1 <= other.cx <= self.x2 and self.y1 <= other.cy <= self.y2

    def vertical_overlap_ratio(self, other: "BBox") -> float:
        overlap = max(0.0, min(self.y2, other.y2) - max(self.y1, other.y1))
        denom = max(1.0, min(self.height, other.height))
        return overlap / denom

    def horizontal_overlap_ratio(self, other: "BBox") -> float:
        overlap = max(0.0, min(self.x2, other.x2) - max(self.x1, other.x1))
        denom = max(1.0, min(self.width, other.width))
        return overlap / denom


@dataclass(frozen=True)
class OcrBlock:
    block_id: str
    text: str
    bbox: BBox
    confidence: float = 1.0
    cubicle_id: Optional[str] = None
    scope_id: Optional[str] = None


@dataclass(frozen=True)
class EquipmentAnchor:
    anchor_id: str
    class_id: str
    text: str
    bbox: BBox
    cubicle_id: str
    confidence: float = 1.0
    scope_id: Optional[str] = None


@dataclass(frozen=True)
class CubicleRegion:
    cubicle_id: str
    bbox: BBox
    parent_id: Optional[str] = None
    region_type: str = "CUBICLE"


@dataclass
class DescriptionGroup:
    group_id: str
    block_ids: List[str]
    blocks: List[OcrBlock]
    bbox: BBox
    combined_text: str
    signatures: List[str] = field(default_factory=list)


@dataclass
class AssociationResult:
    anchor_id: str
    class_id: str
    group_id: str
    descriptor_block_ids: List[str]
    anchor_bbox: Dict[str, float]
    group_bbox: Dict[str, float]
    combined_text: str
    score: float
    status: str
    association_method: str
    score_components: Dict[str, float]
    distance_normalized: float
    semantic_signatures: List[str]
    cubicle_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


MOF_SIGNATURES: Tuple[Tuple[str, re.Pattern[str], float], ...] = (
    (
        "pt_ratio",
        re.compile(
            r"\bPT\s*:?\s*\d+(?:\.\d+)?\s*(?:kV|V)?\s*/\s*"
            r"\d+(?:\.\d+)?\s*(?:kV|V)",
            re.I,
        ),
        0.35,
    ),
    (
        "ct_ratio",
        re.compile(
            r"\bCT\s*:?\s*\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*A",
            re.I,
        ),
        0.35,
    ),
    (
        "overcurrent_strength",
        re.compile(r"과전류강도\s*[:=\-]?\s*\d+(?:\.\d+)?\s*배", re.I),
        0.15,
    ),
    (
        "burden",
        re.compile(r"\d+(?:\.\d+)?\s*VA\b", re.I),
        0.10,
    ),
    (
        "construction",
        re.compile(r"\bMOLD(?:\s*TYPE)?\b", re.I),
        0.05,
    ),
)

COMPETING_EQUIPMENT = re.compile(
    r"\b(?:VCB|ACB|ATCB|ATS|MCCB|LBS|TRANSFORMER|UPS|BATTERY|BUS\s+DUCT)\b",
    re.I,
)


def _bbox_dict(b: BBox) -> Dict[str, float]:
    return {"x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2}


def _median_text_height(blocks: Sequence[OcrBlock]) -> float:
    heights = [b.bbox.height for b in blocks if b.bbox.height > 0]
    return median(heights) if heights else 12.0


def _semantic_signatures(text: str) -> Tuple[List[str], float]:
    normalized = normalize_text(text)
    names: List[str] = []
    score = 0.0
    for name, pattern, weight in MOF_SIGNATURES:
        if pattern.search(normalized):
            names.append(name)
            score += weight
    return names, min(score, 1.0)


def _compatible_for_grouping(a: OcrBlock, b: OcrBlock, text_height: float) -> bool:
    # MOF descriptors are frequently stacked in one column. Allow generous
    # vertical gaps but require x alignment/overlap to avoid swallowing the
    # neighboring VCB/relay description.
    x_overlap = a.bbox.horizontal_overlap_ratio(b.bbox)
    left_alignment = abs(a.bbox.x1 - b.bbox.x1) <= 4.0 * text_height
    center_alignment = abs(a.bbox.cx - b.bbox.cx) <= 8.0 * text_height
    vertical_gap = max(0.0, max(a.bbox.y1, b.bbox.y1) - min(a.bbox.y2, b.bbox.y2))
    horizontal_gap = max(0.0, max(a.bbox.x1, b.bbox.x1) - min(a.bbox.x2, b.bbox.x2))

    stacked = vertical_gap <= 4.5 * text_height and (x_overlap >= 0.15 or left_alignment or center_alignment)
    same_line = horizontal_gap <= 8.0 * text_height and a.bbox.vertical_overlap_ratio(b.bbox) >= 0.25
    return stacked or same_line


def cluster_description_blocks(
    blocks: Sequence[OcrBlock],
    *,
    group_prefix: str = "MOF-GROUP",
) -> List[DescriptionGroup]:
    """Cluster OCR blocks that jointly form a remote equipment description.

    Only blocks with at least one MOF-specific semantic cue are seeded. Nearby
    lines such as burden/overcurrent-strength are then attached.
    """
    if not blocks:
        return []
    h = _median_text_height(blocks)
    normalized = {b.block_id: normalize_text(b.text) for b in blocks}
    seed_ids = {
        b.block_id
        for b in blocks
        if any(pattern.search(normalized[b.block_id]) for _, pattern, _ in MOF_SIGNATURES)
    }
    if not seed_ids:
        return []

    adjacency: Dict[str, set[str]] = {b.block_id: set() for b in blocks}
    by_id = {b.block_id: b for b in blocks}
    for i, a in enumerate(blocks):
        for b in blocks[i + 1 :]:
            if _compatible_for_grouping(a, b, h):
                adjacency[a.block_id].add(b.block_id)
                adjacency[b.block_id].add(a.block_id)

    visited: set[str] = set()
    groups: List[DescriptionGroup] = []
    for seed in sorted(seed_ids):
        if seed in visited:
            continue
        stack = [seed]
        component: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in component:
                continue
            component.add(cur)
            # Include neighboring lines only if they contain a descriptor cue
            # or are close to a cue-bearing line. This prevents whole cubicle
            # text blocks from merging into the MOF group.
            for nxt in adjacency[cur]:
                nxt_text = normalized[nxt]
                cur_text = normalized[cur]
                nxt_sig = any(p.search(nxt_text) for _, p, _ in MOF_SIGNATURES)
                cur_sig = any(p.search(cur_text) for _, p, _ in MOF_SIGNATURES)
                if nxt_sig or cur_sig:
                    stack.append(nxt)
        if not component.intersection(seed_ids):
            continue
        visited.update(component)
        members = sorted((by_id[x] for x in component), key=lambda b: (b.bbox.y1, b.bbox.x1))
        bbox = members[0].bbox
        for member in members[1:]:
            bbox = bbox.union(member.bbox)
        combined = "\n".join(m.text for m in members)
        signatures, _ = _semantic_signatures(combined)
        # Require PT+CT, or one ratio plus two supporting signatures.
        strong = {"pt_ratio", "ct_ratio"}
        if len(strong.intersection(signatures)) < 2 and len(signatures) < 3:
            continue
        groups.append(
            DescriptionGroup(
                group_id=f"{group_prefix}-{len(groups)+1:04d}",
                block_ids=[m.block_id for m in members],
                blocks=members,
                bbox=bbox,
                combined_text=combined,
                signatures=signatures,
            )
        )
    return groups


def _score_mof_candidate(
    anchor: EquipmentAnchor,
    group: DescriptionGroup,
    cubicle: CubicleRegion,
) -> Optional[AssociationResult]:
    effective_scope = anchor.scope_id or anchor.cubicle_id
    if effective_scope != cubicle.cubicle_id:
        return None
    if any((b.scope_id or b.cubicle_id) not in (None, effective_scope) for b in group.blocks):
        return None
    if not cubicle.bbox.contains_center(anchor.bbox) or not cubicle.bbox.contains_center(group.bbox):
        return None

    signatures, semantic_score = _semantic_signatures(group.combined_text)
    if len({"pt_ratio", "ct_ratio"}.intersection(signatures)) < 2 and len(signatures) < 3:
        return None

    distance = math.hypot(anchor.bbox.cx - group.bbox.cx, anchor.bbox.cy - group.bbox.cy)
    cub_diag = max(cubicle.bbox.diagonal, 1.0)
    distance_normalized = distance / cub_diag
    if distance_normalized > 0.72:
        return None

    # Wide-span policy: semantic evidence dominates. A far but complete PT+CT
    # cluster is preferable to a nearby unrelated rating.
    spatial_score = max(0.0, 1.0 - distance_normalized / 0.72)
    same_row = anchor.bbox.vertical_overlap_ratio(group.bbox)
    same_col = anchor.bbox.horizontal_overlap_ratio(group.bbox)
    alignment_score = max(same_row, same_col, 0.25 if distance_normalized <= 0.5 else 0.0)
    ocr_score = max(0.0, min(1.0, sum(b.confidence for b in group.blocks) / len(group.blocks)))
    competing_penalty = 0.18 if COMPETING_EQUIPMENT.search(normalize_text(group.combined_text)) else 0.0

    total = (
        0.65 * semantic_score
        + 0.18 * spatial_score
        + 0.10 * alignment_score
        + 0.07 * ocr_score
        - competing_penalty
    )
    total = max(0.0, min(1.0, total))
    if total >= 0.78:
        status = "AUTO_CANDIDATE"
    elif total >= 0.58:
        status = "REVIEW_REQUIRED"
    else:
        return None

    return AssociationResult(
        anchor_id=anchor.anchor_id,
        class_id=anchor.class_id,
        group_id=group.group_id,
        descriptor_block_ids=group.block_ids,
        anchor_bbox=_bbox_dict(anchor.bbox),
        group_bbox=_bbox_dict(group.bbox),
        combined_text=f"{anchor.text}\n{group.combined_text}",
        score=round(total, 6),
        status=status,
        association_method="MOF_WIDE_SPAN_SEMANTIC_ASSOCIATION_V2",
        score_components={
            "semantic": round(semantic_score, 6),
            "spatial": round(spatial_score, 6),
            "alignment": round(alignment_score, 6),
            "ocr": round(ocr_score, 6),
            "competing_equipment_penalty": competing_penalty,
        },
        distance_normalized=round(distance_normalized, 6),
        semantic_signatures=signatures,
        cubicle_id=effective_scope,
    )


def associate_mof_descriptions(
    anchors: Sequence[EquipmentAnchor],
    blocks: Sequence[OcrBlock],
    cubicles: Sequence[CubicleRegion],
) -> List[AssociationResult]:
    """Associate widely separated MOF labels and PT/CT descriptions.

    The matching is one-to-one across all MOF anchors and descriptor groups.
    It never crosses a cubicle boundary.
    """
    cubicle_map = {c.cubicle_id: c for c in cubicles}
    groups_by_cubicle: Dict[str, List[DescriptionGroup]] = {}
    for cubicle in cubicles:
        local = [
            b for b in blocks
            if (b.scope_id or b.cubicle_id) in (None, cubicle.cubicle_id)
            and cubicle.bbox.contains_center(b.bbox)
        ]
        groups_by_cubicle[cubicle.cubicle_id] = cluster_description_blocks(
            local, group_prefix=f"{cubicle.cubicle_id}-MOF-GROUP"
        )

    candidates: List[AssociationResult] = []
    for anchor in anchors:
        if anchor.class_id != "MeteringOutfit":
            continue
        effective_scope = anchor.scope_id or anchor.cubicle_id
        cubicle = cubicle_map.get(effective_scope)
        if not cubicle:
            continue
        for group in groups_by_cubicle.get(effective_scope, []):
            candidate = _score_mof_candidate(anchor, group, cubicle)
            if candidate:
                candidates.append(candidate)

    # Global greedy maximum assignment. This is deterministic and dependency-free.
    # A Hungarian solver may replace it later, but duplicate group assignment is
    # already prevented here.
    candidates.sort(key=lambda x: (-x.score, x.anchor_id, x.group_id))
    assigned_anchors: set[str] = set()
    assigned_groups: set[str] = set()
    selected: List[AssociationResult] = []
    for candidate in candidates:
        if candidate.anchor_id in assigned_anchors or candidate.group_id in assigned_groups:
            continue
        selected.append(candidate)
        assigned_anchors.add(candidate.anchor_id)
        assigned_groups.add(candidate.group_id)
    return sorted(selected, key=lambda x: x.anchor_id)


def find_orphan_mof_signature_groups(
    blocks: Sequence[OcrBlock],
    cubicles: Sequence[CubicleRegion],
    associated_group_ids: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """Return PT+CT clusters with no MOF anchor. These are review candidates,
    never auto-confirmed MOF equipment.
    """
    used = set(associated_group_ids)
    output: List[Dict[str, Any]] = []
    for cubicle in cubicles:
        local = [
            b for b in blocks
            if (b.scope_id or b.cubicle_id) in (None, cubicle.cubicle_id)
            and cubicle.bbox.contains_center(b.bbox)
        ]
        for group in cluster_description_blocks(local, group_prefix=f"{cubicle.cubicle_id}-ORPHAN-MOF"):
            if group.group_id in used:
                continue
            output.append(
                {
                    "candidate_class_id": "MeteringOutfit",
                    "status": "REVIEW_REQUIRED",
                    "reason": "MOF_SIGNATURE_CLUSTER_WITHOUT_ANCHOR",
                    "cubicle_id": cubicle.cubicle_id,
                    "group_id": group.group_id,
                    "descriptor_block_ids": group.block_ids,
                    "combined_text": group.combined_text,
                    "semantic_signatures": group.signatures,
                    "group_bbox": _bbox_dict(group.bbox),
                }
            )
    return output


__all__ = [
    "BBox",
    "OcrBlock",
    "EquipmentAnchor",
    "CubicleRegion",
    "DescriptionGroup",
    "AssociationResult",
    "cluster_description_blocks",
    "associate_mof_descriptions",
    "find_orphan_mof_signature_groups",
]
