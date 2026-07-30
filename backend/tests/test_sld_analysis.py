from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import cv2
import fitz
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_csrf, require_session
from app.api.sld_analysis import _render_pdf_page
from app.auth import AuthenticatedSession
from app.main import app
from app.security import token_hash
from app.sld_analysis import (
    SldContractError,
    _map_crop_ocr_items,
    extract_equipment,
    parse_upstage_ocr,
    sld_ocr_request_hash,
)
from app.sld_box_pipeline import build_diagram_crops


def _upstage_payload() -> dict[str, object]:
    return {
        "pages": [
            {
                "page": 1,
                "width": 1200,
                "height": 800,
                "words": [
                    {
                        "text": "TR(DRY TYPE) 1000kVA 22.9kV/380V",
                        "confidence": 0.99,
                        "boundingBox": {
                            "vertices": [
                                {"x": 0.1, "y": 0.1},
                                {"x": 0.5, "y": 0.1},
                                {"x": 0.5, "y": 0.14},
                                {"x": 0.1, "y": 0.14},
                            ]
                        },
                    },
                    {
                        "text": "MAIN ACB 4P 1600AF/1250AT",
                        "confidence": 0.98,
                        "boundingBox": {
                            "vertices": [
                                {"x": 0.1, "y": 0.2},
                                {"x": 0.5, "y": 0.2},
                                {"x": 0.5, "y": 0.24},
                                {"x": 0.1, "y": 0.24},
                            ]
                        },
                    },
                    {
                        "text": "GENERATOR 500kW",
                        "confidence": 0.97,
                        "boundingBox": {
                            "vertices": [
                                {"x": 0.1, "y": 0.3},
                                {"x": 0.4, "y": 0.3},
                                {"x": 0.4, "y": 0.34},
                                {"x": 0.1, "y": 0.34},
                            ]
                        },
                    },
                    {
                        "text": "BATTERY BANK DC 110V",
                        "confidence": 0.96,
                        "boundingBox": {
                            "vertices": [
                                {"x": 0.1, "y": 0.4},
                                {"x": 0.4, "y": 0.4},
                                {"x": 0.4, "y": 0.44},
                                {"x": 0.1, "y": 0.44},
                            ]
                        },
                    },
                ],
            }
        ]
    }


def test_upstage_only_pipeline_extracts_fire_related_equipment() -> None:
    ocr_items, pages = parse_upstage_ocr(_upstage_payload())
    equipment = extract_equipment(ocr_items)
    class_ids = {item["classId"] for item in equipment}

    assert pages == [{"page": 1, "width": 1200.0, "height": 800.0}]
    assert {
        "DryTypeTransformer",
        "AirCircuitBreaker",
        "Generator",
        "BatteryBank",
    } <= class_ids
    assert next(item for item in equipment if item["classId"] == "AirCircuitBreaker")[
        "role"
    ] == "MAIN_BREAKER"
    transformer = next(item for item in equipment if item["classId"] == "DryTypeTransformer")
    assert "절연유" not in transformer["fireRisk"]["generalRisk"]


def test_sld_runtime_payload_contains_no_paddle_provenance() -> None:
    ocr_items, _ = parse_upstage_ocr(_upstage_payload())
    equipment = extract_equipment(ocr_items)
    serialized = json.dumps(
        {"ocrItems": ocr_items, "equipment": equipment},
        ensure_ascii=False,
    ).lower()

    assert all(item["provider"] == "upstage_document_ocr" for item in ocr_items)
    assert all(item["provider"] == "upstage_document_ocr" for item in equipment)
    assert "paddle" not in serialized


def test_sld_ocr_request_hash_allows_a_full_restart_per_attempt() -> None:
    first = sld_ocr_request_hash("document-parse", "a" * 64, "analysis-1:v2")

    assert first == sld_ocr_request_hash("document-parse", "a" * 64, "analysis-1:v2")
    assert first != sld_ocr_request_hash("document-parse", "a" * 64, "analysis-1:v3")
    assert first != sld_ocr_request_hash("document-parse", "a" * 64, "analysis-2:v2")


def test_box_pipeline_crops_an_equipment_anchored_enclosure(tmp_path) -> None:
    image = np.full((800, 1200, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (100, 100), (800, 600), (0, 0, 0), 5)
    success, encoded = cv2.imencode(".png", image)
    assert success
    source_path = tmp_path / "diagram.png"
    source_path.write_bytes(bytes(encoded))
    ocr_items = [
        {
            "id": "UPSTAGE-OCR-000001",
            "page": 1,
            "raw_text": "MAIN ACB",
            "confidence": 0.99,
            "bbox_page_pixel": [150.0, 130.0, 100.0, 30.0],
            "provider": "upstage_document_ocr",
        }
    ]

    crops, metrics = build_diagram_crops(
        source_path,
        "image/png",
        [{"page": 1, "width": 1200.0, "height": 800.0}],
        ocr_items,
        tmp_path / "crops",
        lambda text_value: "ACB" in text_value,
        max_crops=4,
        upscale=2.0,
    )

    assert metrics["detectedEnclosureCount"] >= 1
    assert metrics["ocrCropCount"] == 1
    assert crops[0]["method"] == "long_line_closed_region"
    assert Path(crops[0]["path"]).is_file()


def test_box_pipeline_groups_rating_lines_into_the_anchor_crop() -> None:
    items = [
        {
            "id": "UPSTAGE-CROP-OCR-000001",
            "page": 1,
            "raw_text": "MAIN ACB",
            "confidence": 0.99,
            "bbox_page_pixel": [120.0, 100.0, 100.0, 20.0],
            "provider": "upstage_document_ocr_region_crop",
            "ocrMode": "REGION_CORE_2X",
        },
        {
            "id": "UPSTAGE-CROP-OCR-000002",
            "page": 1,
            "raw_text": "4P 1600AF/1250AT",
            "confidence": 0.97,
            "bbox_page_pixel": [125.0, 132.0, 180.0, 20.0],
            "provider": "upstage_document_ocr_region_crop",
            "ocrMode": "REGION_CORE_2X",
        },
    ]
    crops = [
        {
            "cropId": "SLD-CROP-0001",
            "regionId": "SLD-REGION-P001-0001",
            "page": 1,
            "pageWidth": 1200.0,
            "pageHeight": 800.0,
            "bbox": [80.0, 70.0, 300.0, 200.0],
        }
    ]

    equipment = extract_equipment(items, crops)

    assert len(equipment) == 1
    assert equipment[0]["classId"] == "AirCircuitBreaker"
    assert "1600AF/1250AT" in equipment[0]["rawText"]
    assert equipment[0]["cropId"] == "SLD-CROP-0001"
    assert equipment[0]["groupingMethod"] == "upstage_region_crop_anchor_context_v15"


def test_crop_ocr_boxes_are_mapped_back_to_the_full_diagram() -> None:
    crop = {
        "cropId": "SLD-CROP-0001",
        "regionId": "SLD-REGION-P001-0001",
        "page": 1,
        "bbox": [100.0, 200.0, 400.0, 300.0],
    }
    payload = {
        "pages": [
            {
                "page": 1,
                "width": 800,
                "height": 600,
                "words": [
                    {
                        "text": "MAIN ACB",
                        "confidence": 0.99,
                        "boundingBox": {
                            "vertices": [
                                {"x": 0.25, "y": 0.20},
                                {"x": 0.45, "y": 0.20},
                                {"x": 0.45, "y": 0.30},
                                {"x": 0.25, "y": 0.30},
                            ]
                        },
                    }
                ],
            }
        ]
    }

    mapped = _map_crop_ocr_items(payload, crop, 1)

    assert len(mapped) == 1
    assert mapped[0]["bbox_page_pixel"] == pytest.approx([200.0, 260.0, 80.0, 30.0])
    assert mapped[0]["cropId"] == "SLD-CROP-0001"
    assert mapped[0]["page"] == 1


def test_sld_endpoints_require_authentication() -> None:
    with TestClient(app) as client:
        responses = (
            client.get(
                "/api/v1/buildings/11111111-1111-4111-8111-111111111111/sld-document"
            ),
            client.get(
                "/api/v1/buildings/11111111-1111-4111-8111-111111111111/sld-analyses"
            ),
            client.get(
                "/api/v1/sld-analyses/11111111-1111-4111-8111-111111111111"
            ),
            client.get(
                "/api/v1/sld-analyses/11111111-1111-4111-8111-111111111111/pages/1/preview"
            ),
        )

    assert all(response.status_code == 401 for response in responses)


def _session() -> AuthenticatedSession:
    return AuthenticatedSession(
        session_id_hash=token_hash("session"),
        user_id=uuid4(),
        username="manager",
        display_name="관리자",
        csrf_token_hash=token_hash("csrf"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_sld_page_preview_returns_the_registered_image(monkeypatch, tmp_path) -> None:
    analysis_id = uuid4()
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"\x89PNG\r\n\x1a\npreview")
    app.dependency_overrides[require_session] = _session
    monkeypatch.setattr(
        "app.api.sld_analysis.analysis_source",
        AsyncMock(return_value=("analysis/source.png", "diagram.png", "image/png")),
    )
    monkeypatch.setattr(
        "app.api.sld_analysis._resolve_source",
        lambda _storage_root, _relative_path: source_path,
    )
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/sld-analyses/{analysis_id}/pages/1/preview")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "private, max-age=3600"
        assert response.content == source_path.read_bytes()
    finally:
        app.dependency_overrides.clear()


def test_sld_pdf_page_preview_is_rendered_as_png(tmp_path) -> None:
    source_path = tmp_path / "diagram.pdf"
    with fitz.open() as document:
        page = document.new_page(width=600, height=400)
        page.insert_text((40, 60), "TR 1000kVA")
        document.save(str(source_path))

    preview = _render_pdf_page(source_path, 1)

    assert preview.startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(SldContractError, match="요청한 도면 페이지"):
        _render_pdf_page(source_path, 2)


def test_building_sld_document_contract_exposes_the_missing_state(monkeypatch) -> None:
    building_id = uuid4()
    app.dependency_overrides[require_session] = _session
    ensure = AsyncMock(return_value=None)
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.api.sld_analysis.ensure_demo_fire_building_document",
        ensure,
    )
    monkeypatch.setattr("app.api.sld_analysis.building_sld_document", lookup)
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/buildings/{building_id}/sld-document")
        assert response.status_code == 200
        assert response.json()["data"] == {"document": None}
        ensure.assert_awaited_once()
        lookup.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()


def test_equipment_extraction_requires_a_registered_diagram(monkeypatch) -> None:
    building_id = uuid4()
    app.dependency_overrides[require_csrf] = _session
    monkeypatch.setattr(
        "app.api.sld_analysis.ensure_demo_fire_building_document",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.api.sld_analysis.building_sld_document",
        AsyncMock(return_value=None),
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/buildings/{building_id}/sld-analyses/from-document",
                headers={"Idempotency-Key": "test-missing-document"},
            )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SLD_DOCUMENT_REQUIRED"
    finally:
        app.dependency_overrides.clear()
