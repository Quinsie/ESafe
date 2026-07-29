from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import struct
import zlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zipfile import BadZipFile, ZipFile

import olefile
from lxml import etree
from pypdf import PdfReader

PARSER_VERSION = "rag-local-parser-v1"
PRIVACY_VERSION = "rag-privacy-ko-v2"
CHUNK_VERSION = "rag-paragraph-chunker-v2"

_MANIFEST_LINE = re.compile(r"^(?P<sha>[0-9a-f]{64})  \./(?P<path>.+)$")
_WHITESPACE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_HWP_EXTENDED_CONTROLS = frozenset(
    {*range(0x0001, 0x0009), 0x0009, 0x000B, 0x000C, *range(0x000E, 0x0018)}
)
_HWP_PARA_TEXT_TAG = 0x43

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_RRN = re.compile(r"(?<!\d)\d{6}\s*[- ]?\s*[1-8]\d{6}(?!\d)")
_PHONE = re.compile(
    r"(?<!\d)(?:\+?82[-.\s]?)?(?:0\d{1,2}[-.\s]?)?\d{3,4}[-.\s]\d{4}(?!\d)"
)
_PERSON_LABEL = re.compile(
    r"(?P<label>성명|담당자|피해자|사망자|부상자|관계인|소유자|임차인|신고자)"
    r"(?P<separator>\s*[:：]?\s*)(?P<value>[가-힣]{2,4})(?![가-힣])"
)
_PRIVATE_NUMBER = re.compile(
    r"(?P<label>고객|계약|수용가|회원|계좌)\s*(?:번호|No\.?)"
    r"(?P<separator>\s*[:：]?\s*)(?P<value>[A-Za-z0-9-]{4,})",
    re.IGNORECASE,
)
_ROAD_NUMBER = re.compile(
    r"(?P<road>[가-힣A-Za-z0-9·]+(?:대로|로|길))\s*"
    r"(?P<number>\d{1,5}(?:-\d{1,5})?)(?!\d)"
)
_LOT_NUMBER = re.compile(
    r"(?P<locality>[가-힣A-Za-z0-9·]+(?:읍|면|동|리))\s*"
    r"(?P<number>산?\s*\d{1,5}(?:-\d{1,5})?)(?!\d)"
)
_PRIVACY_PATTERNS = (
    ("EMAIL", _EMAIL),
    ("RRN", _RRN),
    ("PHONE", _PHONE),
    ("PERSON_NAME", _PERSON_LABEL),
    ("PRIVATE_NUMBER", _PRIVATE_NUMBER),
    ("ROAD_ADDRESS", _ROAD_NUMBER),
    ("LOT_ADDRESS", _LOT_NUMBER),
)


class SourceError(ValueError):
    """A source cannot safely become a searchable document."""


@dataclass(slots=True)
class Paragraph:
    locator: str
    text: str
    heading_path: list[str]
    table_context: dict[str, Any] | None = None


@dataclass(slots=True)
class ParsedDocument:
    title: str
    paragraphs: list[Paragraph]
    page_count: int | None
    table_paragraph_count: int


@dataclass(slots=True)
class PrivacyResult:
    title: str
    paragraphs: list[Paragraph]
    finding_counts: dict[str, int]
    residual_counts: dict[str, int]

    @property
    def verified(self) -> bool:
        return not self.residual_counts


@dataclass(slots=True)
class SourceEntry:
    relative_path: str
    source_sha256: str
    source_size: int
    scope: str


@dataclass(slots=True)
class BuildMetrics:
    source_count: int = 0
    unique_source_count: int = 0
    duplicate_source_count: int = 0
    parsed_count: int = 0
    indexed_candidate_count: int = 0
    review_required_count: int = 0
    failed_count: int = 0
    paragraph_count: int = 0
    chunk_count: int = 0
    masked_finding_count: int = 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def normalize_text(value: str) -> str:
    value = re.sub(r"[\ud800-\udfff]", "", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _WHITESPACE.sub(" ", value)
    value = "\n".join(line.strip() for line in value.splitlines())
    return _BLANK_LINES.sub("\n\n", value).strip()


def _natural_section_key(name: str) -> tuple[int, str]:
    match = re.search(r"(\d+)(?=\.xml$|$)", name)
    return (int(match.group(1)) if match else 2**31 - 1, name)


def _element_local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def parse_hwpx(path: Path) -> ParsedDocument:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False, huge_tree=False)
    try:
        with ZipFile(path) as package:
            section_names = sorted(
                (
                    name
                    for name in package.namelist()
                    if re.fullmatch(r"Contents/section\d+\.xml", name)
                ),
                key=_natural_section_key,
            )
            if not section_names:
                raise SourceError("HWPX_SECTION_MISSING")
            paragraphs: list[Paragraph] = []
            table_count = 0
            for section_index, name in enumerate(section_names):
                root = etree.fromstring(package.read(name), parser=parser)
                paragraph_index = 0
                for element in root.iter():
                    if _element_local_name(element) != "p":
                        continue
                    text_parts: list[str] = []
                    for descendant in element.iter():
                        if _element_local_name(descendant) == "t":
                            text_parts.extend(descendant.itertext())
                    text = normalize_text("".join(text_parts))
                    if not text:
                        continue
                    table_ancestor = next(
                        (
                            ancestor
                            for ancestor in element.iterancestors()
                            if _element_local_name(ancestor) in {"tbl", "tc"}
                        ),
                        None,
                    )
                    table_context = None
                    if table_ancestor is not None:
                        table_count += 1
                        table_context = {"kind": "HWPX_TABLE_CELL"}
                    paragraph_index += 1
                    paragraphs.append(
                        Paragraph(
                            locator=f"section{section_index}/paragraph{paragraph_index}",
                            text=text,
                            heading_path=[],
                            table_context=table_context,
                        )
                    )
    except (BadZipFile, KeyError, etree.XMLSyntaxError, UnicodeDecodeError) as error:
        raise SourceError("HWPX_PARSE_FAILED") from error
    return validate_parsed_document(path.stem, paragraphs, None, table_count)


def _decode_hwp_paragraph(payload: bytes) -> str:
    if len(payload) % 2:
        raise SourceError("HWP_ODD_PARAGRAPH_BYTES")
    units = struct.unpack(f"<{len(payload) // 2}H", payload)
    output: list[str] = []
    index = 0
    while index < len(units):
        code = units[index]
        if code in _HWP_EXTENDED_CONTROLS:
            if code == 0x0009:
                output.append("\t")
            index += min(8, len(units) - index)
            continue
        if code in {0x000A, 0x000D}:
            output.append("\n")
        elif code == 0x0018:
            output.append("-")
        elif code == 0x001E:
            output.append("\u2011")
        elif code == 0x001F:
            output.append(" ")
        elif code >= 0x0020:
            output.append(chr(code))
        index += 1
    return normalize_text("".join(output))


def _hwp_records(data: bytes) -> Iterable[tuple[int, int, bytes]]:
    offset = 0
    while offset < len(data):
        if len(data) - offset < 4:
            raise SourceError("HWP_TRUNCATED_RECORD_HEADER")
        header = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        tag_id = header & 0x3FF
        level = (header >> 10) & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            if len(data) - offset < 4:
                raise SourceError("HWP_TRUNCATED_EXTENDED_SIZE")
            size = struct.unpack_from("<I", data, offset)[0]
            offset += 4
        end = offset + size
        if end > len(data):
            raise SourceError("HWP_TRUNCATED_RECORD")
        yield tag_id, level, data[offset:end]
        offset = end


def parse_hwp(path: Path) -> ParsedDocument:
    try:
        with olefile.OleFileIO(path) as document:
            if not document.exists("FileHeader"):
                raise SourceError("HWP_FILE_HEADER_MISSING")
            header = document.openstream("FileHeader").read()
            if not header.startswith(b"HWP Document File"):
                raise SourceError("HWP_SIGNATURE_INVALID")
            if len(header) < 40:
                raise SourceError("HWP_FILE_HEADER_TRUNCATED")
            properties = struct.unpack_from("<I", header, 36)[0]
            compressed = bool(properties & 0x01)
            encrypted = bool(properties & 0x02)
            distribution = bool(properties & 0x04)
            if encrypted:
                raise SourceError("HWP_ENCRYPTED")
            if distribution:
                raise SourceError("HWP_DISTRIBUTION")
            sections = sorted(
                (
                    "/".join(parts)
                    for parts in document.listdir(streams=True, storages=False)
                    if len(parts) == 2
                    and parts[0] == "BodyText"
                    and parts[1].startswith("Section")
                ),
                key=_natural_section_key,
            )
            if not sections:
                raise SourceError("HWP_SECTION_MISSING")
            paragraphs: list[Paragraph] = []
            for section_index, stream_name in enumerate(sections):
                raw = document.openstream(stream_name).read()
                if compressed:
                    try:
                        raw = zlib.decompress(raw, -15)
                    except zlib.error as error:
                        raise SourceError("HWP_DECOMPRESSION_FAILED") from error
                paragraph_index = 0
                for tag_id, _level, payload in _hwp_records(raw):
                    if tag_id != _HWP_PARA_TEXT_TAG:
                        continue
                    text = _decode_hwp_paragraph(payload)
                    if not text:
                        continue
                    paragraph_index += 1
                    paragraphs.append(
                        Paragraph(
                            locator=f"section{section_index}/paragraph{paragraph_index}",
                            text=text,
                            heading_path=[],
                        )
                    )
    except OSError as error:
        raise SourceError("HWP_OLE_PARSE_FAILED") from error
    return validate_parsed_document(path.stem, paragraphs, None, 0)


def parse_pdf(path: Path) -> ParsedDocument:
    try:
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise SourceError("PDF_PASSWORD_REQUIRED")
        paragraphs: list[Paragraph] = []
        for page_index, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text(extraction_mode="layout") or ""
            blocks = re.split(r"\n\s*\n", raw_text)
            paragraph_index = 0
            for block in blocks:
                text = normalize_text(block)
                if not text:
                    continue
                paragraph_index += 1
                paragraphs.append(
                    Paragraph(
                        locator=f"page{page_index}/paragraph{paragraph_index}",
                        text=text,
                        heading_path=[],
                    )
                )
    except SourceError:
        raise
    except Exception as error:
        raise SourceError("PDF_PARSE_FAILED") from error
    return validate_parsed_document(path.stem, paragraphs, len(reader.pages), 0)


def validate_parsed_document(
    fallback_title: str,
    paragraphs: list[Paragraph],
    page_count: int | None,
    table_count: int,
) -> ParsedDocument:
    if not paragraphs:
        raise SourceError("EMPTY_DOCUMENT")
    character_count = sum(len(paragraph.text) for paragraph in paragraphs)
    if character_count < 30:
        raise SourceError("DOCUMENT_TOO_SHORT")
    if any("\ufffd" in paragraph.text for paragraph in paragraphs):
        raise SourceError("REPLACEMENT_CHARACTER")
    title = next((item.text for item in paragraphs if 3 <= len(item.text) <= 180), fallback_title)
    return ParsedDocument(
        title=title,
        paragraphs=paragraphs,
        page_count=page_count,
        table_paragraph_count=table_count,
    )


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".hwpx":
        return parse_hwpx(path)
    if suffix == ".hwp":
        return parse_hwp(path)
    if suffix == ".pdf":
        return parse_pdf(path)
    raise SourceError("UNSUPPORTED_FORMAT")


def detect_privacy(value: str) -> Counter[str]:
    findings: Counter[str] = Counter()
    for category, pattern in _PRIVACY_PATTERNS:
        count = sum(1 for _ in pattern.finditer(value))
        if count:
            findings[category] = count
    return findings


def mask_privacy(value: str) -> tuple[str, Counter[str]]:
    counts = detect_privacy(value)
    masked = value
    for _ in range(4):
        previous = masked
        masked = _EMAIL.sub("[이메일 마스킹]", masked)
        masked = _RRN.sub("[식별번호 마스킹]", masked)
        masked = _PHONE.sub("[전화번호 마스킹]", masked)
        masked = _PERSON_LABEL.sub(
            lambda match: (
                f"{match.group('label')}{match.group('separator')}[개인명 마스킹]"
            ),
            masked,
        )
        masked = _PRIVATE_NUMBER.sub(
            lambda match: (
                f"{match.group('label')}번호{match.group('separator')}[내부번호 마스킹]"
            ),
            masked,
        )
        masked = _ROAD_NUMBER.sub(
            lambda match: f"{match.group('road')} [상세주소 마스킹]",
            masked,
        )
        masked = _LOT_NUMBER.sub(
            lambda match: f"{match.group('locality')} [상세주소 마스킹]",
            masked,
        )
        if masked == previous:
            break
    return masked, counts


def deidentify_document(document: ParsedDocument) -> PrivacyResult:
    original_fields = [document.title, *(item.text for item in document.paragraphs)]
    finding_counts = detect_privacy("\n".join(original_fields))
    title, _title_counts = mask_privacy(document.title)
    paragraphs: list[Paragraph] = []
    for paragraph in document.paragraphs:
        text, _counts = mask_privacy(paragraph.text)
        paragraphs.append(
            Paragraph(
                locator=paragraph.locator,
                text=text,
                heading_path=paragraph.heading_path,
                table_context=paragraph.table_context,
            )
        )
    title, paragraphs = _mask_cross_field_findings(title, paragraphs)
    residual = detect_privacy("\n".join([title, *(item.text for item in paragraphs)]))
    return PrivacyResult(
        title=title,
        paragraphs=paragraphs,
        finding_counts=dict(sorted(finding_counts.items())),
        residual_counts=dict(sorted(residual.items())),
    )


def _mask_cross_field_findings(
    title: str,
    paragraphs: list[Paragraph],
) -> tuple[str, list[Paragraph]]:
    fields = [title, *(item.text for item in paragraphs)]
    for _ in range(4):
        joined = "\n".join(fields)
        offsets: list[tuple[int, int]] = []
        offset = 0
        for field in fields:
            offsets.append((offset, offset + len(field)))
            offset += len(field) + 1
        affected: dict[int, set[str]] = {}
        for category, pattern in _PRIVACY_PATTERNS:
            for match in pattern.finditer(joined):
                for index, (start, end) in enumerate(offsets):
                    if start < match.end() and end > match.start():
                        affected.setdefault(index, set()).add(category)
        if not affected:
            break
        for index, categories in affected.items():
            labels = ",".join(sorted(categories))
            fields[index] = f"[교차문단 개인정보 마스킹:{labels}]"
    masked_paragraphs = [
        Paragraph(
            locator=paragraph.locator,
            text=fields[index + 1],
            heading_path=paragraph.heading_path,
            table_context=paragraph.table_context,
        )
        for index, paragraph in enumerate(paragraphs)
    ]
    return fields[0], masked_paragraphs


def chunk_paragraphs(paragraphs: list[Paragraph]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[Paragraph] = []
    current_length = 0

    def flush() -> None:
        nonlocal current, current_length
        if not current:
            return
        chunks.append(
            {
                "ordinal": len(chunks) + 1,
                "locator": (
                    current[0].locator
                    if len(current) == 1
                    else f"{current[0].locator}–{current[-1].locator}"
                ),
                "heading_path": current[0].heading_path,
                "text": "\n".join(item.text for item in current),
                "table_context": current[0].table_context,
            }
        )
        current = []
        current_length = 0

    for paragraph in paragraphs:
        length = len(paragraph.text)
        if paragraph.table_context is not None:
            flush()
            current = [paragraph]
            current_length = length
            flush()
            continue
        if current and current_length >= 500 and current_length + 1 + length > 1200:
            flush()
        if length > 1200:
            flush()
            chunks.append(
                {
                    "ordinal": len(chunks) + 1,
                    "locator": paragraph.locator,
                    "heading_path": paragraph.heading_path,
                    "text": paragraph.text,
                    "table_context": paragraph.table_context,
                    "quality_warning": "LONG_SEMANTIC_UNIT_PRESERVED",
                }
            )
            continue
        current.append(paragraph)
        current_length += length + (1 if len(current) > 1 else 0)
    flush()
    return chunks


def load_source_entries(snapshot_root: Path) -> list[SourceEntry]:
    manifest_path = snapshot_root / "manifest.sha256"
    if not manifest_path.is_file():
        raise SourceError("SOURCE_MANIFEST_MISSING")
    entries: list[SourceEntry] = []
    for line_number, raw_line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = _MANIFEST_LINE.fullmatch(raw_line)
        if match is None:
            raise SourceError(f"SOURCE_MANIFEST_INVALID_LINE_{line_number}")
        relative = PurePosixPath(match.group("path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise SourceError(f"SOURCE_MANIFEST_UNSAFE_PATH_{line_number}")
        path = snapshot_root / "raw" / Path(*relative.parts)
        if not path.is_file():
            raise SourceError(f"SOURCE_FILE_MISSING_{line_number}")
        expected_hash = match.group("sha")
        if sha256_file(path) != expected_hash:
            raise SourceError(f"SOURCE_HASH_MISMATCH_{line_number}")
        entries.append(
            SourceEntry(
                relative_path=relative.as_posix(),
                source_sha256=expected_hash,
                source_size=path.stat().st_size,
                scope=relative.parts[0],
            )
        )
    if len(entries) != 246:
        raise SourceError("SOURCE_COUNT_MISMATCH")
    return entries


def classify_document(entry: SourceEntry) -> tuple[str, int, str]:
    path = PurePosixPath(entry.relative_path)
    top_level = path.parts[1]
    title = path.stem
    if entry.scope == "restricted":
        return "INCIDENT_CASE", 4, "RESTRICTED"
    if top_level == "경기도 매뉴얼":
        return "OTHER_REGION_REFERENCE", 5, "PUBLIC"
    if "매뉴얼" in title:
        return "AUTHORITATIVE_MANUAL", 1, "PUBLIC"
    if any(word in title for word in ("계획", "대책", "훈련")):
        return "PLAN_POLICY", 2, "PUBLIC"
    return "OFFICIAL_NOTICE", 2, "PUBLIC"


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def build_snapshot(snapshot_root: Path) -> dict[str, Any]:
    entries = load_source_entries(snapshot_root)
    output_root = (
        snapshot_root
        / "derived"
        / f"{PARSER_VERSION}-{PRIVACY_VERSION}-{CHUNK_VERSION}"
    )
    if output_root.exists():
        raise SourceError("DERIVED_VERSION_ALREADY_EXISTS")

    metrics = BuildMetrics(
        source_count=len(entries),
        unique_source_count=len({entry.source_sha256 for entry in entries}),
    )
    documents: list[dict[str, Any]] = []
    primary_by_hash: dict[str, dict[str, Any]] = {}
    for entry in entries:
        source_path = snapshot_root / "raw" / Path(*PurePosixPath(entry.relative_path).parts)
        family, authority, confidentiality = classify_document(entry)
        document_id = str(uuid5(NAMESPACE_URL, f"esafe-rag:{entry.source_sha256}"))
        primary = primary_by_hash.get(entry.source_sha256)
        if primary is not None:
            metrics.duplicate_source_count += 1
            documents.append(
                {
                    **primary,
                    "source_path": entry.relative_path,
                    "source_size": entry.source_size,
                    "source_status": "DUPLICATE",
                    "duplicate_of_document_id": primary["document_id"],
                }
            )
            continue
        status = "PARSED"
        failure_reason = None
        safe_path = None
        safe_sha256 = None
        privacy_status = "UNKNOWN"
        parse_summary: dict[str, Any] = {}
        try:
            parsed = parse_document(source_path)
            metrics.parsed_count += 1
            privacy = deidentify_document(parsed)
            parse_text_hash = hashlib.sha256(
                "\n".join(item.text for item in parsed.paragraphs).encode("utf-8")
            ).hexdigest()
            if not privacy.verified:
                status = "REVIEW_REQUIRED"
                privacy_status = "REVIEW_REQUIRED"
                metrics.review_required_count += 1
            else:
                privacy_status = (
                    "MASKED_VERIFIED"
                    if confidentiality == "RESTRICTED" or privacy.finding_counts
                    else "PUBLIC_SAFE"
                )
                chunks = chunk_paragraphs(privacy.paragraphs)
                artifact = {
                    "artifact_version": "esafe-rag-safe-document-v1",
                    "document_id": document_id,
                    "title": privacy.title,
                    "source_sha256": entry.source_sha256,
                    "source_format": source_path.suffix[1:].upper(),
                    "document_family": family,
                    "authority_level": authority,
                    "confidentiality": confidentiality,
                    "privacy_status": privacy_status,
                    "parser_version": PARSER_VERSION,
                    "privacy_version": PRIVACY_VERSION,
                    "chunk_version": CHUNK_VERSION,
                    "page_count": parsed.page_count,
                    "paragraph_count": len(privacy.paragraphs),
                    "table_paragraph_count": parsed.table_paragraph_count,
                    "mask_counts": privacy.finding_counts,
                    "chunks": chunks,
                }
                payload = compact_json_bytes(artifact)
                safe_relative = Path("documents") / f"{document_id}.json"
                write_bytes_atomic(output_root / safe_relative, payload)
                safe_path = safe_relative.as_posix()
                safe_sha256 = hashlib.sha256(payload).hexdigest()
                metrics.indexed_candidate_count += 1
                metrics.paragraph_count += len(privacy.paragraphs)
                metrics.chunk_count += len(chunks)
                metrics.masked_finding_count += sum(privacy.finding_counts.values())
            parse_summary = {
                "page_count": parsed.page_count,
                "paragraph_count": len(parsed.paragraphs),
                "table_paragraph_count": parsed.table_paragraph_count,
                "parse_text_sha256": parse_text_hash,
                "mask_counts": privacy.finding_counts,
                "residual_counts": privacy.residual_counts,
            }
        except SourceError as error:
            status = "REVIEW_REQUIRED"
            privacy_status = "REVIEW_REQUIRED"
            failure_reason = str(error)
            metrics.review_required_count += 1
            metrics.failed_count += 1

        document_entry = {
            "document_id": document_id,
            "source_path": entry.relative_path,
            "source_sha256": entry.source_sha256,
            "source_size": entry.source_size,
            "source_status": "PRIMARY",
            "duplicate_of_document_id": None,
            "source_format": source_path.suffix[1:].upper(),
            "document_family": family,
            "authority_level": authority,
            "confidentiality": confidentiality,
            "parse_status": status,
            "privacy_status": privacy_status,
            "failure_reason": failure_reason,
            "safe_copy_path": safe_path,
            "safe_copy_sha256": safe_sha256,
            "parse_summary": parse_summary,
        }
        primary_by_hash[entry.source_sha256] = document_entry
        documents.append(document_entry)

    manifest = {
        "manifest_version": "esafe-rag-derived-manifest-v1",
        "source_snapshot": snapshot_root.name,
        "source_manifest_sha256": sha256_file(snapshot_root / "manifest.sha256"),
        "parser_version": PARSER_VERSION,
        "privacy_version": PRIVACY_VERSION,
        "chunk_version": CHUNK_VERSION,
        "metrics": asdict(metrics),
        "documents": documents,
    }
    write_bytes_atomic(output_root / "build-manifest.json", compact_json_bytes(manifest))
    return manifest


def verify_derived_snapshot(snapshot_root: Path) -> dict[str, int]:
    entries = load_source_entries(snapshot_root)
    output_root = (
        snapshot_root
        / "derived"
        / f"{PARSER_VERSION}-{PRIVACY_VERSION}-{CHUNK_VERSION}"
    )
    manifest_path = output_root / "build-manifest.json"
    if not manifest_path.is_file():
        raise SourceError("DERIVED_MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_manifest_sha256") != sha256_file(snapshot_root / "manifest.sha256"):
        raise SourceError("DERIVED_SOURCE_MANIFEST_MISMATCH")
    documents = manifest.get("documents")
    if not isinstance(documents, list) or len(documents) != len(entries):
        raise SourceError("DERIVED_DOCUMENT_COUNT_MISMATCH")
    expected_sources = {(entry.relative_path, entry.source_sha256) for entry in entries}
    actual_sources: set[tuple[str, str]] = set()
    primary_ids: dict[str, str] = {}
    chunk_count = 0
    for document in documents:
        if not isinstance(document, dict):
            raise SourceError("DERIVED_DOCUMENT_INVALID")
        source_hash = str(document.get("source_sha256", ""))
        source_path = str(document.get("source_path", ""))
        source_key = (source_path, source_hash)
        if source_key not in expected_sources or source_key in actual_sources:
            raise SourceError("DERIVED_DOCUMENT_SOURCE_INVALID")
        actual_sources.add(source_key)
        if (
            document.get("parse_status") != "PARSED"
            or document.get("privacy_status") not in {"PUBLIC_SAFE", "MASKED_VERIFIED"}
            or document.get("failure_reason") is not None
        ):
            raise SourceError("DERIVED_DOCUMENT_NOT_INDEXABLE")
        source_status = document.get("source_status")
        if source_status == "DUPLICATE":
            if (
                source_hash not in primary_ids
                or document.get("duplicate_of_document_id") != primary_ids[source_hash]
                or document.get("document_id") != primary_ids[source_hash]
            ):
                raise SourceError("DERIVED_DUPLICATE_LINK_INVALID")
            continue
        if source_status != "PRIMARY" or source_hash in primary_ids:
            raise SourceError("DERIVED_PRIMARY_INVALID")
        primary_ids[source_hash] = str(document.get("document_id", ""))
        safe_relative = document.get("safe_copy_path")
        safe_hash = document.get("safe_copy_sha256")
        if not isinstance(safe_relative, str) or not isinstance(safe_hash, str):
            raise SourceError("DERIVED_SAFE_COPY_MISSING")
        safe_path = output_root / Path(*PurePosixPath(safe_relative).parts)
        if not safe_path.is_file() or sha256_file(safe_path) != safe_hash:
            raise SourceError("DERIVED_SAFE_COPY_HASH_MISMATCH")
        artifact = json.loads(safe_path.read_text(encoding="utf-8"))
        chunks = artifact.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise SourceError("DERIVED_CHUNKS_MISSING")
        safe_text = "\n".join(
            [str(artifact.get("title", "")), *(str(item.get("text", "")) for item in chunks)]
        )
        if detect_privacy(safe_text):
            raise SourceError("DERIVED_PRIVACY_RESIDUAL")
        chunk_count += len(chunks)
    if actual_sources != expected_sources:
        raise SourceError("DERIVED_DOCUMENT_SOURCE_INCOMPLETE")
    return {
        "verified_sources": len(entries),
        "verified_documents": len(primary_ids),
        "duplicate_sources": len(entries) - len(primary_ids),
        "chunks": chunk_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m esafe_importer.rag_sources")
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--snapshot-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    snapshot_root = args.snapshot_root.resolve()
    if args.command == "verify":
        print(json.dumps(verify_derived_snapshot(snapshot_root), sort_keys=True))
        return
    manifest = build_snapshot(snapshot_root)
    print(json.dumps(manifest["metrics"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
