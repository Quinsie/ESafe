from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pytest
from lxml import etree

from app.document_templates import (
    HWPX_MIMETYPE,
    TEMPLATE_BY_KEY,
    TEMPLATE_DEFINITIONS,
    DocumentTemplateError,
    render_hwpx,
    validate_template,
    validate_template_set,
)

TEMPLATE_DIR = Path(__file__).parents[1] / "app" / "assets" / "document_templates"


def _copy_with_changed_member(
    source_path: Path,
    output_path: Path,
    member_name: str,
    data: bytes,
) -> None:
    with ZipFile(source_path) as source, ZipFile(output_path, "w") as target:
        for source_info in source.infolist():
            info = ZipInfo(source_info.filename, source_info.date_time)
            info.compress_type = source_info.compress_type
            info.external_attr = source_info.external_attr
            info.internal_attr = source_info.internal_attr
            info.create_system = source_info.create_system
            info.extra = source_info.extra
            info.comment = source_info.comment
            if info.filename == "mimetype":
                info.compress_type = ZIP_STORED
            target.writestr(
                info,
                data if info.filename == member_name else source.read(source_info),
            )


def test_committed_template_set_is_valid_and_privacy_clean() -> None:
    manifest = validate_template_set(TEMPLATE_DIR)

    assert manifest["templateVersion"] == "2026-07-30-v2"
    assert [item["key"] for item in manifest["templates"]] == [
        definition.key for definition in TEMPLATE_DEFINITIONS
    ]
    assert (TEMPLATE_DIR / "incident-report.hwpx").read_bytes().startswith(b"PK")


def test_render_hwpx_replaces_all_tokens_and_preserves_package(
    tmp_path: Path,
) -> None:
    definition = TEMPLATE_BY_KEY["incident-report"]
    values = {
        token: f"값 <{index}> & 확인"
        for index, token in enumerate(sorted(definition.token_names))
    }
    values["contact.block"] = "사용자 입력 연락처 010-1234-5678"
    output_path = tmp_path / "rendered.hwpx"

    validation = render_hwpx(
        TEMPLATE_DIR / definition.file_name,
        output_path,
        definition,
        values,
    )

    assert validation.token_names == ()
    with ZipFile(TEMPLATE_DIR / definition.file_name) as template_package:
        template_section = etree.fromstring(
            template_package.read("Contents/section0.xml")
        )
    with ZipFile(output_path) as package:
        assert package.infolist()[0].filename == "mimetype"
        assert package.infolist()[0].compress_type == ZIP_STORED
        assert package.read("mimetype") == HWPX_MIMETYPE
        section = etree.fromstring(package.read("Contents/section0.xml"))
        text = "".join(section.itertext())
    template_layouts = template_section.xpath("//*[local-name()='linesegarray']")
    rendered_layouts = section.xpath("//*[local-name()='linesegarray']")
    assert template_layouts
    assert len(rendered_layouts) == len(template_layouts)
    assert all(len(layout) == 0 for layout in rendered_layouts)
    assert not section.xpath("//*[local-name()='lineseg']")
    assert "값 <0> & 확인" in text
    assert "010-1234-5678" in text
    assert "{{" not in text


def test_official_notice_removes_foreign_agency_image() -> None:
    definition = TEMPLATE_BY_KEY["official-notice"]

    with ZipFile(TEMPLATE_DIR / definition.file_name) as package:
        assert (
            package.read("BinData/image1.png")
            == package.read("Preview/PrvImage.png")
        )


def test_render_hwpx_rejects_unknown_field(tmp_path: Path) -> None:
    definition = TEMPLATE_BY_KEY["official-notice"]

    with pytest.raises(DocumentTemplateError, match="HWPX_UNKNOWN_VALUES"):
        render_hwpx(
            TEMPLATE_DIR / definition.file_name,
            tmp_path / "rendered.hwpx",
            definition,
            {"not.allowed": "value"},
        )


def test_template_validation_rejects_privacy_finding(tmp_path: Path) -> None:
    definition = TEMPLATE_BY_KEY["incident-report"]
    source_path = TEMPLATE_DIR / definition.file_name
    output_path = tmp_path / "privacy.hwpx"
    _copy_with_changed_member(
        source_path,
        output_path,
        "Preview/PrvText.txt",
        "연락처 010-1234-5678".encode(),
    )

    with pytest.raises(DocumentTemplateError, match="HWPX_PRIVACY_FINDING"):
        validate_template(output_path, definition)


def test_template_validation_rejects_unresolved_token_in_artifact(
    tmp_path: Path,
) -> None:
    definition = TEMPLATE_BY_KEY["incident-report"]

    with pytest.raises(DocumentTemplateError, match="HWPX_UNRESOLVED_TOKEN"):
        validate_template(
            TEMPLATE_DIR / definition.file_name,
            definition,
            require_tokens=False,
        )
