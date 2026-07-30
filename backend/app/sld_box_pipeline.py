from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import fitz
import numpy as np


@dataclass(frozen=True)
class Candidate:
    bbox: tuple[int, int, int, int]
    confidence: float
    border_support: dict[str, float]
    method: str


LABEL_ANCHOR = re.compile(
    r"^(?:SHVC?|TRC?|LVC?|LV(?:-R)?|HTP|GCP|GEN|WHM|UPS(?:-IN-PUT)?)$",
    re.I,
)
LABEL_SUFFIX = re.compile(r"^(?:#?\d{1,2}|[RBC]\d?)$", re.I)


def _box_area(box: list[float]) -> float:
    return max(0.0, box[2]) * max(0.0, box[3])


def _center(box: list[float]) -> tuple[float, float]:
    return box[0] + box[2] / 2.0, box[1] + box[3] / 2.0


def _contains_center(outer: list[float], inner: list[float], pad: float = 0.0) -> bool:
    x, y = _center(inner)
    return (
        outer[0] - pad <= x <= outer[0] + outer[2] + pad
        and outer[1] - pad <= y <= outer[1] + outer[3] + pad
    )


def _iou(left: list[float], right: list[float]) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    intersection = max(0.0, min(lx + lw, rx + rw) - max(lx, rx)) * max(
        0.0,
        min(ly + lh, ry + rh) - max(ly, ry),
    )
    union = lw * lh + rw * rh - intersection
    return intersection / union if union > 0 else 0.0


def _strip_support(mask: Any, box: tuple[int, int, int, int]) -> dict[str, float]:
    x, y, width, height = box
    image_height, image_width = mask.shape
    band = max(3, min(image_width, image_height) // 900)

    def ratio(x1: int, y1: int, x2: int, y2: int) -> float:
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image_width, x2), min(image_height, y2)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        return float(np.count_nonzero(mask[y1:y2, x1:x2])) / float(
            (y2 - y1) * (x2 - x1)
        )

    return {
        "top": ratio(x, y - band, x + width, y + band + 1),
        "bottom": ratio(x, y + height - band - 1, x + width, y + height + band),
        "left": ratio(x - band, y, x + band + 1, y + height),
        "right": ratio(x + width - band - 1, y, x + width + band, y + height),
    }


def _long_line_masks(image: Any) -> tuple[Any, Any, Any]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, ink = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    height, width = ink.shape
    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(45, width // 45), 1),
        ),
    )
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (1, max(45, height // 36)),
        ),
    )
    horizontal = cv2.morphologyEx(
        horizontal,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(7, width // 700), 3)),
    )
    vertical = cv2.morphologyEx(
        vertical,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, max(7, height // 500))),
    )
    structure = cv2.dilate(
        cv2.bitwise_or(horizontal, vertical),
        np.ones((3, 3), np.uint8),
        iterations=1,
    )
    return horizontal, vertical, structure


def _deduplicate(candidates: list[Candidate]) -> list[Candidate]:
    selected: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
        candidate_box = [float(value) for value in candidate.bbox]
        if any(
            _iou(candidate_box, [float(value) for value in item.bbox]) >= 0.82
            for item in selected
        ):
            continue
        selected.append(candidate)
    leaves = []
    for candidate in selected:
        candidate_box = [float(value) for value in candidate.bbox]
        children = [
            item
            for item in selected
            if item is not candidate
            and all(
                (
                    item.bbox[0] >= candidate.bbox[0] - 8,
                    item.bbox[1] >= candidate.bbox[1] - 8,
                    item.bbox[0] + item.bbox[2]
                    <= candidate.bbox[0] + candidate.bbox[2] + 8,
                    item.bbox[1] + item.bbox[3]
                    <= candidate.bbox[1] + candidate.bbox[3] + 8,
                )
            )
            and _box_area([float(value) for value in item.bbox])
            < _box_area(candidate_box) * 0.72
        ]
        if len(children) < 2:
            leaves.append(candidate)
    return sorted(leaves, key=lambda item: (item.bbox[1], item.bbox[0]))


def detect_solid_cubicles(image: Any) -> list[Candidate]:
    horizontal, vertical, structure = _long_line_masks(image)
    image_height, image_width = image.shape[:2]
    page_area = image_width * image_height
    candidates: list[Candidate] = []
    contours, _ = cv2.findContours(structure, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area_ratio = (width * height) / page_area
        if width < image_width * 0.055 or height < image_height * 0.045:
            continue
        if not 0.004 <= area_ratio <= 0.38:
            continue
        if width >= image_width * 0.94 or height >= image_height * 0.94:
            continue
        if x >= image_width * 0.86:
            continue
        horizontal_support = _strip_support(horizontal, (x, y, width, height))
        vertical_support = _strip_support(vertical, (x, y, width, height))
        support = {
            "top": horizontal_support["top"],
            "bottom": horizontal_support["bottom"],
            "left": vertical_support["left"],
            "right": vertical_support["right"],
        }
        supported_sides = sum(value >= 0.14 for value in support.values())
        if supported_sides < 3 or min(support["left"], support["right"]) < 0.10:
            continue
        mean_support = sum(support.values()) / 4.0
        candidates.append(
            Candidate(
                bbox=(x, y, width, height),
                confidence=round(
                    min(0.99, 0.35 + 0.50 * mean_support + 0.04 * supported_sides),
                    4,
                ),
                border_support={key: round(value, 4) for key, value in support.items()},
                method="long_line_closed_region",
            )
        )
    return _deduplicate(candidates)


def _light_dashed_line_masks(image: Any) -> tuple[Any, Any, Any]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    otsu, _ = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    _, ink = cv2.threshold(
        gray,
        min(250, int(otsu) + 25),
        255,
        cv2.THRESH_BINARY_INV,
    )
    height, width = ink.shape
    gap = max(9, round(min(width / 175.0, height / 120.0)))
    horizontal_closed = cv2.morphologyEx(
        ink,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (gap, 1)),
    )
    vertical_closed = cv2.morphologyEx(
        ink,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, gap)),
    )
    horizontal = cv2.morphologyEx(
        horizontal_closed,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(45, width // 45), 1)),
    )
    vertical = cv2.morphologyEx(
        vertical_closed,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(45, height // 36))),
    )
    structure = cv2.dilate(
        cv2.bitwise_or(horizontal, vertical),
        np.ones((3, 3), np.uint8),
        iterations=1,
    )
    return horizontal, vertical, structure


def detect_dashed_cells(image: Any) -> list[Candidate]:
    horizontal, vertical, structure = _light_dashed_line_masks(image)
    image_height, image_width = image.shape[:2]
    page_area = image_width * image_height
    candidates: list[Candidate] = []
    contours, _ = cv2.findContours(structure, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area_ratio = (width * height) / page_area
        if width < image_width * 0.025 or height < image_height * 0.015:
            continue
        if not 0.0005 <= area_ratio <= 0.60:
            continue
        if width >= image_width * 0.98 or height >= image_height * 0.98:
            continue
        horizontal_support = _strip_support(horizontal, (x, y, width, height))
        vertical_support = _strip_support(vertical, (x, y, width, height))
        support = {
            "top": horizontal_support["top"],
            "bottom": horizontal_support["bottom"],
            "left": vertical_support["left"],
            "right": vertical_support["right"],
        }
        supported_sides = sum(value >= 0.08 for value in support.values())
        if supported_sides < 3 or min(support["left"], support["right"]) < 0.05:
            continue
        mean_support = sum(support.values()) / 4.0
        candidates.append(
            Candidate(
                bbox=(x, y, width, height),
                confidence=round(
                    min(0.96, 0.30 + 0.48 * mean_support + 0.04 * supported_sides),
                    4,
                ),
                border_support={key: round(value, 4) for key, value in support.items()},
                method="light_dashed_grid_cell",
            )
        )
    return candidates


def _normalized_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get("raw_text", "")).split())


def _anchor_label(anchor: dict[str, Any], items: list[dict[str, Any]]) -> str:
    text = _normalized_text(anchor)
    x, y, width, height = (float(value) for value in anchor["bboxRenderPixel"])
    center_x, center_y = x + width / 2.0, y + height / 2.0
    nearby = []
    for item in items:
        suffix = _normalized_text(item)
        if item is anchor or not LABEL_SUFFIX.fullmatch(suffix):
            continue
        item_x, item_y, item_width, item_height = (
            float(value) for value in item["bboxRenderPixel"]
        )
        dx = abs(item_x + item_width / 2.0 - center_x)
        dy = abs(item_y + item_height / 2.0 - center_y)
        if dx <= 65 and dy <= 45:
            nearby.append((dx + dy * 0.75, suffix))
    return f"{text}-{min(nearby)[1]}" if nearby else text


def select_label_anchored_cells(
    candidates: list[Candidate],
    items: list[dict[str, Any]],
    page_size: tuple[int, int],
) -> list[tuple[Candidate, str]]:
    page_width, page_height = page_size
    anchors = [
        item for item in items if LABEL_ANCHOR.fullmatch(_normalized_text(item))
    ]
    selected: list[tuple[Candidate, str]] = []
    for anchor in anchors:
        anchor_x, anchor_y, _, _ = (
            float(value) for value in anchor["bboxRenderPixel"]
        )
        label = _anchor_label(anchor, items)
        choices: list[tuple[float, Candidate]] = []
        for candidate in candidates:
            x, y, width, height = candidate.bbox
            if (
                y - 30 <= anchor_y <= y + max(120, page_height * 0.045)
                and x - 30 <= anchor_x <= x + width + 30
            ):
                vertical_score = abs((anchor_y - y) - 15)
                left_penalty = (
                    max(0.0, (anchor_x - x) - max(100, page_width * 0.03)) * 0.10
                )
                area_penalty = width * height / (page_width * page_height) * 5.0
                choices.append(
                    (vertical_score + left_penalty + area_penalty, candidate)
                )
            elif (
                0 <= x - anchor_x <= page_width * 0.075
                and y - 30 <= anchor_y <= y + max(120, page_height * 0.045)
            ):
                choices.append(
                    (
                        25 + (x - anchor_x) * 0.15 + abs((anchor_y - y) - 15),
                        candidate,
                    )
                )
        if not choices:
            continue
        base = min(choices, key=lambda item: item[0])[1]
        x, y, width, height = base.bbox
        right, bottom = x + width, y + height
        if width < page_width * 0.09 and not label.upper().startswith("HTP"):
            neighbors = []
            for candidate in candidates:
                nx, ny, nwidth, nheight = candidate.bbox
                gap = nx - right
                overlap = max(0, min(bottom, ny + nheight) - max(y, ny)) / max(
                    1,
                    min(height, nheight),
                )
                if -20 <= gap <= page_width * 0.018 and overlap >= 0.45 and nx > x:
                    neighbors.append(
                        (abs(gap) + abs(ny - y) * 0.15, -(nwidth * nheight), candidate)
                    )
            if neighbors:
                neighbor = min(neighbors, key=lambda item: (item[0], item[1]))[2]
                nx, ny, nwidth, nheight = neighbor.bbox
                right, bottom = max(right, nx + nwidth), max(bottom, ny + nheight)
                x, y = min(x, nx), min(y, ny)
                width, height = right - x, bottom - y
        if width < page_width * 0.07:
            width = min(page_width - x, int(page_width * 0.12))
        if height < page_height * 0.04:
            height = min(page_height - y, int(page_height * 0.07))
        selected.append(
            (
                Candidate(
                    bbox=(int(x), int(y), int(width), int(height)),
                    confidence=base.confidence,
                    border_support=base.border_support,
                    method="light_dashed_grid_with_ocr_label_anchor",
                ),
                label,
            )
        )

    merged: list[tuple[Candidate, list[str]]] = []
    for candidate, label in sorted(
        selected,
        key=lambda item: (item[0].bbox[1], item[0].bbox[0]),
    ):
        duplicate = next(
            (
                item
                for item in merged
                if _iou(
                    [float(value) for value in candidate.bbox],
                    [float(value) for value in item[0].bbox],
                )
                >= 0.70
            ),
            None,
        )
        if duplicate is None:
            merged.append((candidate, [label]))
        elif label not in duplicate[1]:
            duplicate[1].append(label)

    output = []
    for candidate, labels in merged:
        prefix = labels[0].split("-", 1)[0].upper()
        candidate_area = candidate.bbox[2] * candidate.bbox[3]
        nested = False
        for other, other_labels in merged:
            if other is candidate or other_labels[0].split("-", 1)[0].upper() != prefix:
                continue
            x, y, width, height = candidate.bbox
            ox, oy, other_width, other_height = other.bbox
            intersection = max(
                0,
                min(x + width, ox + other_width) - max(x, ox),
            ) * max(0, min(y + height, oy + other_height) - max(y, oy))
            if (
                intersection / max(1, candidate_area) >= 0.75
                and other_width * other_height > candidate_area * 1.45
            ):
                nested = True
                break
        if not nested:
            output.append((candidate, "/".join(labels)))
    return output


def _render_source_pages(
    source_path: Path,
    mime_type: str,
    render_dpi: int,
) -> list[dict[str, Any]]:
    if mime_type == "application/pdf":
        output = []
        with fitz.open(str(source_path)) as document:
            for index, page in enumerate(document):
                scale = render_dpi / 72.0
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height,
                    pixmap.width,
                    3,
                )
                output.append(
                    {
                        "page": index + 1,
                        "image": cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                    }
                )
        return output
    decoded = cv2.imdecode(
        np.frombuffer(source_path.read_bytes(), dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    if decoded is None:
        raise ValueError("SLD_SOURCE_IMAGE_INVALID")
    return [{"page": 1, "image": decoded}]


def _clamp_box(box: list[float], width: float, height: float) -> list[float]:
    left = min(width, max(0.0, box[0]))
    top = min(height, max(0.0, box[1]))
    right = min(width, max(left, box[0] + box[2]))
    bottom = min(height, max(top, box[1] + box[3]))
    return [left, top, right - left, bottom - top]


def build_diagram_crops(
    source_path: Path,
    mime_type: str,
    pages: list[dict[str, Any]],
    ocr_items: list[dict[str, Any]],
    output_dir: Path,
    is_equipment_anchor: Callable[[str], bool],
    *,
    max_crops: int = 24,
    render_dpi: int = 300,
    upscale: float = 2.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page_metadata = {int(item["page"]): item for item in pages}
    items_by_page: dict[int, list[dict[str, Any]]] = {}
    for item in ocr_items:
        items_by_page.setdefault(int(item["page"]), []).append(item)
    rendered_pages = _render_source_pages(source_path, mime_type, render_dpi)
    selected: list[dict[str, Any]] = []
    detected_count = 0
    solid_count = 0
    dashed_count = 0
    for rendered in rendered_pages:
        page_number = int(rendered["page"])
        image = rendered["image"]
        render_height, render_width = image.shape[:2]
        page_info = page_metadata.get(
            page_number,
            {"page": page_number, "width": render_width, "height": render_height},
        )
        page_width = float(page_info["width"])
        page_height = float(page_info["height"])
        page_items = items_by_page.get(page_number, [])
        anchors = [
            item
            for item in page_items
            if is_equipment_anchor(str(item.get("raw_text", "")))
        ]
        solid_regions = detect_solid_cubicles(image)
        solid_count += len(solid_regions)
        regions: list[tuple[Candidate, str | None]] = [
            (candidate, None) for candidate in solid_regions
        ]
        if not regions:
            dashed_regions = detect_dashed_cells(image)
            dashed_count += len(dashed_regions)
            render_items = [
                {
                    **item,
                    "bboxRenderPixel": [
                        float(item["bbox_page_pixel"][0]) / page_width * render_width,
                        float(item["bbox_page_pixel"][1]) / page_height * render_height,
                        float(item["bbox_page_pixel"][2]) / page_width * render_width,
                        float(item["bbox_page_pixel"][3]) / page_height * render_height,
                    ],
                }
                for item in page_items
            ]
            regions = [
                (candidate, label)
                for candidate, label in select_label_anchored_cells(
                    dashed_regions,
                    render_items,
                    (render_width, render_height),
                )
            ]
        detected_count += len(regions)
        mapped_regions = []
        for region_index, (candidate, cubicle_label) in enumerate(regions, 1):
            x, y, width, height = (float(value) for value in candidate.bbox)
            padding = 12.0
            render_box = _clamp_box(
                [x - padding, y - padding, width + padding * 2, height + padding * 2],
                float(render_width),
                float(render_height),
            )
            mapped_regions.append(
                {
                    "regionId": f"SLD-REGION-P{page_number:03d}-{region_index:04d}",
                    "page": page_number,
                    "bboxRenderPixel": render_box,
                    "bbox": [
                        render_box[0] / render_width * page_width,
                        render_box[1] / render_height * page_height,
                        render_box[2] / render_width * page_width,
                        render_box[3] / render_height * page_height,
                    ],
                    "renderWidth": render_width,
                    "renderHeight": render_height,
                    "pageWidth": page_width,
                    "pageHeight": page_height,
                    "confidence": candidate.confidence,
                    "borderSupport": candidate.border_support,
                    "method": candidate.method,
                    "cubicleLabelOcr": cubicle_label,
                    "image": image,
                }
            )
        assigned_anchor_ids: set[str] = set()
        for region in mapped_regions:
            region_anchors = [
                item
                for item in anchors
                if _contains_center(region["bbox"], item["bbox_page_pixel"])
            ]
            region["anchorIds"] = [str(item["id"]) for item in region_anchors]
            region["equipmentAnchorCount"] = len(region_anchors)
            assigned_anchor_ids.update(region["anchorIds"])
            selected.append(region)
        for anchor_index, anchor in enumerate(anchors, 1):
            if str(anchor["id"]) in assigned_anchor_ids:
                continue
            anchor_box = [float(value) for value in anchor["bbox_page_pixel"]]
            context_box = _clamp_box(
                [
                    anchor_box[0] - max(anchor_box[2] * 4.0, page_width * 0.018),
                    anchor_box[1] - max(anchor_box[3] * 4.0, page_height * 0.018),
                    anchor_box[2] + max(anchor_box[2] * 8.0, page_width * 0.036),
                    anchor_box[3] + max(anchor_box[3] * 8.0, page_height * 0.036),
                ],
                page_width,
                page_height,
            )
            selected.append(
                {
                    "regionId": f"SLD-ANCHOR-P{page_number:03d}-{anchor_index:04d}",
                    "page": page_number,
                    "bbox": context_box,
                    "bboxRenderPixel": [
                        context_box[0] / page_width * render_width,
                        context_box[1] / page_height * render_height,
                        context_box[2] / page_width * render_width,
                        context_box[3] / page_height * render_height,
                    ],
                    "renderWidth": render_width,
                    "renderHeight": render_height,
                    "pageWidth": page_width,
                    "pageHeight": page_height,
                    "confidence": float(anchor.get("confidence", 0.0)),
                    "method": "upstage_anchor_context_region",
                    "anchorIds": [str(anchor["id"])],
                    "equipmentAnchorCount": 1,
                    "image": image,
                }
            )
    deduped: list[dict[str, Any]] = []
    for region in sorted(
        selected,
        key=lambda item: (
            -int(item["equipmentAnchorCount"]),
            -float(item["confidence"]),
            _box_area(item["bbox"]),
        ),
    ):
        duplicate = next(
            (
                item
                for item in deduped
                if item["page"] == region["page"]
                and _iou(item["bbox"], region["bbox"]) >= 0.72
            ),
            None,
        )
        if duplicate is not None:
            duplicate["anchorIds"] = list(
                dict.fromkeys([*duplicate["anchorIds"], *region["anchorIds"]])
            )
            duplicate["equipmentAnchorCount"] = len(duplicate["anchorIds"])
            continue
        deduped.append(region)
    output_dir.mkdir(parents=True, exist_ok=True)
    crops = []
    for index, region in enumerate(deduped[:max_crops], 1):
        image = region.pop("image")
        x, y, width, height = [
            int(round(value)) for value in region["bboxRenderPixel"]
        ]
        crop = image[y : y + height, x : x + width]
        if crop.size == 0:
            continue
        if upscale > 1.0:
            enlarged = cv2.resize(
                crop,
                None,
                fx=upscale,
                fy=upscale,
                interpolation=cv2.INTER_LANCZOS4,
            )
            blurred = cv2.GaussianBlur(enlarged, (0, 0), 0.65)
            crop = cv2.addWeighted(enlarged, 1.10, blurred, -0.10, 0)
        crop_id = f"SLD-CROP-{index:04d}"
        crop_path = output_dir / f"{crop_id}.png"
        success, encoded = cv2.imencode(".png", crop)
        if not success:
            raise ValueError("SLD_CROP_ENCODE_FAILED")
        crop_path.write_bytes(bytes(encoded))
        crops.append(
            {
                **region,
                "cropId": crop_id,
                "path": str(crop_path),
                "mimeType": "image/png",
                "cropWidth": int(crop.shape[1]),
                "cropHeight": int(crop.shape[0]),
                "upscaleFactor": upscale,
            }
        )
    return crops, {
        "version": "desktop-v15-upstage-box-port/1.0",
        "provider": "upstage_document_ocr",
        "paddleUsed": False,
        "sourcePolicy": "fresh_source_render_only",
        "renderDpi": render_dpi,
        "solidCubicleCount": solid_count,
        "dashedCellCandidateCount": dashed_count,
        "detectedEnclosureCount": detected_count,
        "equipmentAnchoredRegionCount": len(deduped),
        "ocrCropCount": len(crops),
        "maxOcrCrops": max_crops,
        "upscaleFactor": upscale,
    }


def public_crop_metadata(crops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hidden = {"path", "bboxRenderPixel", "renderWidth", "renderHeight", "image"}
    return [
        {key: value for key, value in crop.items() if key not in hidden}
        for crop in crops
    ]
