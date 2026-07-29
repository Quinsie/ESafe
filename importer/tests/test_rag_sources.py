from __future__ import annotations

import struct
import zlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from esafe_importer.rag_sources import (
    Paragraph,
    ParsedDocument,
    SourceError,
    _decode_hwp_paragraph,
    _hwp_records,
    chunk_paragraphs,
    deidentify_document,
    detect_privacy,
    normalize_text,
    parse_hwpx,
)


def test_hwpx_parser_preserves_paragraph_locations(tmp_path: Path) -> None:
    path = tmp_path / "sample.hwpx"
    section = """<?xml version="1.0" encoding="UTF-8"?>
    <hs:sec xmlns:hs="urn:hancom:section" xmlns:hp="urn:hancom:paragraph">
      <hp:p><hp:run><hp:t>현장 조치 매뉴얼</hp:t></hp:run></hp:p>
      <hp:p><hp:run><hp:t>전원을 즉시 차단하고 관계기관에 상황을 전파한 뒤 현장을 점검한다.</hp:t></hp:run></hp:p>
    </hs:sec>""".encode()
    with ZipFile(path, "w", ZIP_DEFLATED) as package:
        package.writestr("Contents/section0.xml", section)

    parsed = parse_hwpx(path)

    assert parsed.title == "현장 조치 매뉴얼"
    assert [item.locator for item in parsed.paragraphs] == [
        "section0/paragraph1",
        "section0/paragraph2",
    ]


def test_hwpx_parser_fails_closed_without_sections(tmp_path: Path) -> None:
    path = tmp_path / "empty.hwpx"
    with ZipFile(path, "w", ZIP_DEFLATED) as package:
        package.writestr("Preview/PrvText.txt", "미리보기만 있는 파일")

    with pytest.raises(SourceError, match="HWPX_SECTION_MISSING"):
        parse_hwpx(path)


def test_hwp_record_and_control_decoder() -> None:
    text_payload = "첫 문단\t둘째 문장".encode("utf-16le")
    header = _record_header(0x43, len(text_payload))
    records = list(_hwp_records(header + text_payload))

    assert records == [(0x43, 0, text_payload)]
    assert _decode_hwp_paragraph("안전\n점검".encode("utf-16le")) == "안전\n점검"


def test_compressed_hwp_payload_remains_parseable() -> None:
    payload = "화재 현장 전원 차단".encode("utf-16le")
    records = _record_header(0x43, len(payload)) + payload
    compressed = zlib.compressobj(level=9, wbits=-15)
    restored = zlib.decompress(compressed.compress(records) + compressed.flush(), -15)

    assert list(_hwp_records(restored))[0][2] == payload


def test_text_normalization_removes_invalid_pdf_surrogates() -> None:
    assert normalize_text("안전\ud800\x00 점검") == "안전 점검"


def test_privacy_masking_removes_all_supported_identifiers() -> None:
    document = ParsedDocument(
        title="담당자: 홍길동 사고 보고",
        paragraphs=[
            Paragraph(
                locator="section0/paragraph1",
                heading_path=[],
                text=(
                    "연락처 010-1234-5678, test@example.com, "
                    "주민번호 900101-1234567, 고객번호 A-12345, "
                    "전남 목포시 안전로 12, 해남읍 123-4"
                ),
            )
        ],
        page_count=None,
        table_paragraph_count=0,
    )

    result = deidentify_document(document)
    combined = result.title + "\n" + result.paragraphs[0].text

    assert result.verified
    assert not detect_privacy(combined)
    assert "홍길동" not in combined
    assert "010-1234-5678" not in combined
    assert "test@example.com" not in combined
    assert "900101-1234567" not in combined
    assert "A-12345" not in combined
    assert "안전로 12" not in combined
    assert "해남읍 123-4" not in combined


def test_privacy_masking_handles_identifiers_split_across_paragraphs() -> None:
    document = ParsedDocument(
        title="비상연락망",
        paragraphs=[
            Paragraph("section0/paragraph1", "담당자", []),
            Paragraph("section0/paragraph2", "홍길동", []),
            Paragraph("section0/paragraph3", "해남읍", []),
            Paragraph("section0/paragraph4", "123-4", []),
        ],
        page_count=None,
        table_paragraph_count=4,
    )

    result = deidentify_document(document)
    combined = result.title + "\n" + "\n".join(item.text for item in result.paragraphs)

    assert result.verified
    assert "홍길동" not in combined
    assert "123-4" not in combined


def test_chunker_keeps_table_paragraph_isolated() -> None:
    paragraphs = [
        Paragraph("s/1", "가" * 520, []),
        Paragraph("s/2", "나" * 520, []),
        Paragraph("s/3", "표 행", [], {"kind": "HWPX_TABLE_CELL"}),
    ]

    chunks = chunk_paragraphs(paragraphs)

    assert [item["ordinal"] for item in chunks] == [1, 2]
    assert chunks[-1]["table_context"] == {"kind": "HWPX_TABLE_CELL"}


def _record_header(tag_id: int, size: int) -> bytes:
    return struct.pack("<I", tag_id | (size << 20))
