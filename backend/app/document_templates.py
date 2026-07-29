from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import struct
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, cast
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from lxml import etree

HWPX_MIMETYPE = b"application/hwp+zip"
TEMPLATE_VERSION = "2026-07-29-v1"
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
REQUIRED_MEMBERS = frozenset(
    {
        "mimetype",
        "META-INF/manifest.xml",
        "Contents/content.hpf",
        "Contents/header.xml",
        "Contents/section0.xml",
    }
)
TEXT_MEMBER_SUFFIXES = frozenset({".xml", ".hpf", ".rdf", ".txt"})
TOKEN_PATTERN = re.compile(r"\{\{([a-z][a-zA-Z0-9_.]{0,79})\}\}")
XML_CHARACTER_PATTERN = re.compile(
    "[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD]"
)
PRIVACY_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "email": re.compile(
        r"(?<![\w.+-])[\w.+-]{1,64}@(?:[\w-]{1,63}\.)+[A-Za-z]{2,24}(?![\w.-])"
    ),
    "resident_registration_number": re.compile(
        r"(?<!\d)\d{6}\s*-\s*[1-8]\d{6}(?!\d)"
    ),
    "mobile_phone": re.compile(
        r"(?<!\d)01[016789]\s*[-.)]?\s*\d{3,4}\s*[-.]?\s*\d{4}(?!\d)"
    ),
    "telephone": re.compile(
        r"(?<!\d)(?:0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]))"
        r"\s*[-.)]?\s*\d{3,4}\s*[-.]?\s*\d{4}(?!\d)"
    ),
}
METADATA_TEXT_NAMES = frozenset(
    {
        "creator",
        "author",
        "lastmodifiedby",
        "manager",
        "publisher",
        "contributor",
    }
)


class DocumentTemplateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    key: str
    source_sha256: str
    rewrite_mode: Literal["REPLACE_ALL", "PRESERVE_PUBLIC"]
    expected_text_nodes: int
    replacements: Mapping[int, str]
    preview_text: str
    blank_binary_members: frozenset[str] = frozenset()

    @property
    def file_name(self) -> str:
        return f"{self.key}.hwpx"

    @property
    def token_names(self) -> frozenset[str]:
        result: set[str] = set()
        for value in self.replacements.values():
            result.update(TOKEN_PATTERN.findall(value))
        return frozenset(result)


INCIDENT_REPORT_REPLACEMENTS: Mapping[int, str] = {
    0: "{{document.title}}",
    12: "{{document.date}}",
    15: "1. 사고 개요",
    16: " ㅇ 발생일시: {{incident.occurredAt}}",
    17: " ㅇ 발생장소: {{incident.location}}",
    18: " ㅇ 사고원인: {{incident.cause}}",
    19: " ㅇ 상황개요",
    20: "{{incident.summary}}",
    21: "{{incident.detail}}",
    23: "2. 시설 현황",
    24: " ㅇ 시설명: {{facility.name}}",
    25: " ㅇ 주소: {{facility.address}}",
    26: " ㅇ 용도: {{facility.use}}",
    27: " ㅇ 기준 위험도: {{facility.risk}}",
    28: " ㅇ 관할지역: {{facility.region}}",
    29: "{{facility.detail}}",
    34: "3. 피해 현황",
    35: "{{incident.damage}}",
    36: "4. 조치 사항",
    37: "{{response.actions}}",
    38: "{{response.evidence}}",
    39: "{{review.warning}}",
    44: "5. 향후 계획",
    45: "{{response.plan}}",
    46: "6. 참고 자료",
    47: "{{evidence.references}}",
    48: "{{attachments.list}}",
    49: "{{contact.block}}",
}

CRISIS_ASSESSMENT_REPLACEMENTS: Mapping[int, str] = {
    0: "{{document.title}}",
    8: "1. 위기상황 개요",
    9: " ㅇ 재난유형: {{incident.type}}",
    10: " ㅇ 주요내용: {{incident.summary}}",
    11: " ㅇ 보고시각: {{document.date}}",
    12: " ㅇ 관계기관: {{incident.agencies}}",
    13: "{{incident.detail}}",
    21: "2. 판단 근거",
    22: "{{response.evidence}}",
    23: "{{evidence.references}}",
    24: "{{review.warning}}",
    25: "3. 전파 대상",
    26: "{{response.recipients}}",
    33: "4. 상황 모니터링",
    34: "{{monitoring.summary}}",
    35: "{{monitoring.signals}}",
    62: "5. 위기상황 분석",
    63: "{{analysis.result}}",
    64: "{{analysis.uncertainties}}",
    65: "{{analysis.conflicts}}",
    66: "6. 대응 조치",
    67: "{{response.actions}}",
    68: "{{response.plan}}",
    92: "{{attachments.list}}",
    93: "{{author.name}}",
    94: "{{contact.phone}}",
}

OFFICIAL_NOTICE_REPLACEMENTS: Mapping[int, str] = {
    1: "한국전기안전공사",
    2: "수신",
    3: "{{notice.recipient}}",
    5: "제목",
    6: "{{document.title}}",
    7: "{{notice.opening}}",
    8: "{{notice.grounds}}",
    9: "{{notice.request}}",
    10: "{{notice.deadline}}",
    11: "{{review.warning}}",
    35: "붙임",
    36: "{{attachments.list}}",
    43: "한국전기안전공사 사장",
    44: "{{notice.recipient}}",
    45: "{{notice.deliveryRoute}}",
    46: "{{author.name}}",
    47: "{{contact.phone}}",
    48: "{{document.number}}",
}

RESPONSE_PLAN_REPLACEMENTS: Mapping[int, str] = {
    2: "{{document.year}} 대응 계획",
    3: "{{incident.type}}",
    4: "{{document.title}}",
    6: "{{document.date}}",
    8: "한국전기안전공사",
    9: "{{author.department}}",
    13: "상황 개요 및 판단 근거",
    18: "주요 대응 계획",
    22: "세부 실행 과제",
    26: "상황관리 및 협업 체계",
    30: "안전의식 및 예방 홍보",
    33: "1. 근거 문서 및 참고 사례",
    34: "2. 업무별 체크리스트",
    35: "3. 상황 보고 및 승인 절차",
    49: "Ⅰ",
    50: ". 상황 개요 및 판단 근거",
    53: "상황 개요",
    55: "{{incident.summary}}",
    56: "{{incident.detail}}",
    58: "{{analysis.result}}",
    91: "□",
    94: "판단 근거",
    97: "{{response.evidence}}",
    103: "{{evidence.references}}",
    106: "□",
    107: "불확실성 및 충돌",
    109: "{{analysis.uncertainties}}",
    120: "{{review.warning}}",
    121: "{{analysis.conflicts}}",
    175: "□",
    177: "관제 신호",
    178: "{{monitoring.signals}}",
    390: ". 주요 대응 계획",
    395: "{{response.summary}}",
    398: "󰊱 우선 대응체계 구축·가동",
    400: "({{response.priority}})",
    406: "{{response.actions}}",
    410: "{{response.recipients}}",
    441: "(조치계획)",
    443: "{{response.plan}}",
    735: "상황관리 및 협업 체계",
    739: "{{monitoring.summary}}",
    742: "{{response.coordination}}",
    750: "{{response.approvalProcedure}}",
    757: "{{response.reportingProcedure}}",
    763: "(상황보고)",
    766: "{{response.reportingTiming}}",
    768: "(비상대응)",
    769: "{{response.emergencyPlan}}",
}

TEMPLATE_DEFINITIONS: tuple[TemplateDefinition, ...] = (
    TemplateDefinition(
        key="incident-report",
        source_sha256=(
            "d3800fc737170d47cb8a512ba7d9dd3e909f638b5e415c85d076c778658b3256"
        ),
        rewrite_mode="REPLACE_ALL",
        expected_text_nodes=50,
        replacements=INCIDENT_REPORT_REPLACEMENTS,
        preview_text="한국전기안전공사 사고·상황 보고서 템플릿",
    ),
    TemplateDefinition(
        key="crisis-assessment",
        source_sha256=(
            "7af01f8934bae9a3ae4789ee71c6da9f443fd0d1f2db7c3a6b5eb1c705bb420e"
        ),
        rewrite_mode="REPLACE_ALL",
        expected_text_nodes=96,
        replacements=CRISIS_ASSESSMENT_REPLACEMENTS,
        preview_text="한국전기안전공사 위기상황판단 평가보고서 템플릿",
    ),
    TemplateDefinition(
        key="official-notice",
        source_sha256=(
            "7e4be84f80f992e9393eb5488b3d14b8a27d4958efeaf4f2e619a654fb56380a"
        ),
        rewrite_mode="REPLACE_ALL",
        expected_text_nodes=75,
        replacements=OFFICIAL_NOTICE_REPLACEMENTS,
        preview_text="한국전기안전공사 발신 공문 템플릿",
        blank_binary_members=frozenset({"BinData/image1.png"}),
    ),
    TemplateDefinition(
        key="response-plan",
        source_sha256=(
            "b6784d7cffd0cde8e608e7644352c27d70d6747bb7e89e9eec3ec1138ba19e65"
        ),
        rewrite_mode="PRESERVE_PUBLIC",
        expected_text_nodes=1446,
        replacements=RESPONSE_PLAN_REPLACEMENTS,
        preview_text="한국전기안전공사 대응 계획서 템플릿",
    ),
)
TEMPLATE_BY_KEY = {definition.key: definition for definition in TEMPLATE_DEFINITIONS}


@dataclass(frozen=True, slots=True)
class TemplateValidation:
    key: str
    sha256: str
    size_bytes: int
    member_count: int
    text_node_count: int
    token_names: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
            "memberCount": self.member_count,
            "textNodeCount": self.text_node_count,
            "tokenNames": list(self.token_names),
        }


def sha256_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _is_safe_member_name(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def _assert_archive_layout(package: ZipFile) -> tuple[ZipInfo, ...]:
    infos = tuple(package.infolist())
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise DocumentTemplateError("HWPX_DUPLICATE_MEMBER")
    if not infos or infos[0].filename != "mimetype":
        raise DocumentTemplateError("HWPX_MIMETYPE_NOT_FIRST")
    if infos[0].compress_type != ZIP_STORED:
        raise DocumentTemplateError("HWPX_MIMETYPE_COMPRESSED")
    if any(not _is_safe_member_name(name) for name in names):
        raise DocumentTemplateError("HWPX_UNSAFE_MEMBER_PATH")
    for info in infos:
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise DocumentTemplateError("HWPX_SYMLINK_MEMBER")
        if info.file_size > MAX_MEMBER_BYTES:
            raise DocumentTemplateError("HWPX_MEMBER_TOO_LARGE")
    if sum(info.file_size for info in infos) > MAX_PACKAGE_BYTES:
        raise DocumentTemplateError("HWPX_PACKAGE_TOO_LARGE")
    missing = REQUIRED_MEMBERS.difference(names)
    if missing:
        raise DocumentTemplateError(f"HWPX_REQUIRED_MEMBER_MISSING:{sorted(missing)}")
    if package.read("mimetype") != HWPX_MIMETYPE:
        raise DocumentTemplateError("HWPX_MIMETYPE_INVALID")
    return infos


def _xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
        huge_tree=False,
        remove_blank_text=False,
    )


def _parse_xml(data: bytes, member_name: str) -> etree._Element:
    try:
        return etree.fromstring(data, parser=_xml_parser())
    except etree.XMLSyntaxError as error:
        raise DocumentTemplateError(f"HWPX_XML_INVALID:{member_name}") from error


def _serialize_xml(root: etree._Element, original: bytes) -> bytes:
    declaration = original.lstrip().startswith(b"<?xml")
    encoding = "UTF-8"
    tree = root.getroottree()
    docinfo_encoding = tree.docinfo.encoding
    if docinfo_encoding:
        encoding = docinfo_encoding
    return cast(
        bytes,
        etree.tostring(
            root,
            xml_declaration=declaration,
            encoding=encoding,
            standalone=tree.docinfo.standalone,
        ),
    )


def _local_name(element: etree._Element) -> str:
    return cast(str, etree.QName(element).localname.lower())


def _text_nodes(root: etree._Element) -> list[etree._Element]:
    return [element for element in root.iter() if _local_name(element) == "t"]


def _set_element_text(element: etree._Element, value: str) -> None:
    for child in tuple(element):
        element.remove(child)
    element.text = _normalize_xml_text(value)


def _normalize_xml_text(value: str) -> str:
    return XML_CHARACTER_PATTERN.sub("", value).replace("\r\n", "\n").replace("\r", "\n")


def _scrub_privacy(value: str) -> str:
    scrubbed = value
    for pattern in PRIVACY_PATTERNS.values():
        scrubbed = pattern.sub("", scrubbed)
    return scrubbed


def _scrub_metadata(root: etree._Element) -> None:
    for element in root.iter():
        local_name = _local_name(element)
        meta_name = str(element.attrib.get("name", "")).lower()
        if local_name in METADATA_TEXT_NAMES or meta_name in METADATA_TEXT_NAMES:
            _set_element_text(element, "")
        if element.text:
            element.text = _scrub_privacy(element.text)
        if element.tail:
            element.tail = _scrub_privacy(element.tail)
        for key, value in tuple(element.attrib.items()):
            element.attrib[key] = _scrub_privacy(value)


def _sanitize_section(
    data: bytes,
    definition: TemplateDefinition,
) -> tuple[bytes, int]:
    root = _parse_xml(data, "Contents/section0.xml")
    nodes = _text_nodes(root)
    if len(nodes) != definition.expected_text_nodes:
        raise DocumentTemplateError(
            f"HWPX_TEXT_NODE_COUNT_MISMATCH:{len(nodes)}:"
            f"{definition.expected_text_nodes}"
        )
    if any(index < 0 or index >= len(nodes) for index in definition.replacements):
        raise DocumentTemplateError("HWPX_REPLACEMENT_INDEX_INVALID")
    for index, node in enumerate(nodes):
        replacement = definition.replacements.get(index)
        if replacement is not None:
            _set_element_text(node, replacement)
        elif definition.rewrite_mode == "REPLACE_ALL":
            _set_element_text(node, "")
        else:
            if node.text:
                node.text = _scrub_privacy(node.text)
            for child in node.iterdescendants():
                if child.text:
                    child.text = _scrub_privacy(child.text)
                if child.tail:
                    child.tail = _scrub_privacy(child.tail)
    _scrub_metadata(root)
    return _serialize_xml(root, data), len(nodes)


def _blank_preview_png() -> bytes:
    width = 1
    height = 1
    raw = b"\x00\xff\xff\xff\x00"

    def chunk(name: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + name
            + payload
            + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _clone_info(info: ZipInfo) -> ZipInfo:
    cloned = ZipInfo(info.filename, info.date_time)
    cloned.compress_type = info.compress_type
    cloned.comment = info.comment
    cloned.extra = info.extra
    cloned.create_system = info.create_system
    cloned.create_version = info.create_version
    cloned.extract_version = info.extract_version
    cloned.flag_bits = info.flag_bits
    cloned.volume = info.volume
    cloned.internal_attr = info.internal_attr
    cloned.external_attr = info.external_attr
    return cloned


def _privacy_findings(text: str) -> tuple[str, ...]:
    return tuple(
        name for name, pattern in PRIVACY_PATTERNS.items() if pattern.search(text)
    )


def _tokens_in_package(package: ZipFile) -> frozenset[str]:
    tokens: set[str] = set()
    for info in package.infolist():
        if Path(info.filename).suffix.lower() not in TEXT_MEMBER_SUFFIXES:
            continue
        data = package.read(info)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        tokens.update(TOKEN_PATTERN.findall(text))
    return frozenset(tokens)


def _validate_package_references(package: ZipFile) -> None:
    names = frozenset(info.filename for info in package.infolist())
    root = _parse_xml(package.read("Contents/content.hpf"), "Contents/content.hpf")
    for element in root.iter():
        href = element.attrib.get("href")
        if not href or "://" in href or href.startswith("#"):
            continue
        normalized_href = href.removeprefix("./")
        normalized = (
            normalized_href
            if normalized_href in names or normalized_href.startswith("Contents/")
            else str(PurePosixPath("Contents") / normalized_href)
        )
        if not _is_safe_member_name(normalized):
            raise DocumentTemplateError("HWPX_UNSAFE_REFERENCE")
        if normalized not in names:
            raise DocumentTemplateError(f"HWPX_REFERENCE_MISSING:{normalized}")


def validate_template(
    path: Path,
    definition: TemplateDefinition,
    *,
    require_tokens: bool = True,
    require_privacy_clean: bool = True,
) -> TemplateValidation:
    try:
        with ZipFile(path) as package:
            infos = _assert_archive_layout(package)
            text_node_count = 0
            for info in infos:
                suffix = Path(info.filename).suffix.lower()
                data = package.read(info)
                if suffix in {".xml", ".hpf", ".rdf"}:
                    root = _parse_xml(data, info.filename)
                    if info.filename == "Contents/section0.xml":
                        text_node_count = len(_text_nodes(root))
                if require_privacy_clean and suffix in TEXT_MEMBER_SUFFIXES:
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    findings = _privacy_findings(text)
                    if findings:
                        raise DocumentTemplateError(
                            f"HWPX_PRIVACY_FINDING:{info.filename}:{','.join(findings)}"
                        )
            _validate_package_references(package)
            for member_name in definition.blank_binary_members:
                if member_name not in {info.filename for info in infos}:
                    raise DocumentTemplateError(
                        f"HWPX_BLANK_MEMBER_MISSING:{member_name}"
                    )
                if package.read(member_name) != _blank_preview_png():
                    raise DocumentTemplateError(
                        f"HWPX_BLANK_MEMBER_INVALID:{member_name}"
                    )
            tokens = _tokens_in_package(package)
            if require_tokens and tokens != definition.token_names:
                missing = sorted(definition.token_names.difference(tokens))
                extra = sorted(tokens.difference(definition.token_names))
                raise DocumentTemplateError(
                    f"HWPX_TOKEN_MISMATCH:missing={missing}:extra={extra}"
                )
            if not require_tokens and tokens:
                raise DocumentTemplateError(
                    f"HWPX_UNRESOLVED_TOKEN:{sorted(tokens)}"
                )
            if text_node_count != definition.expected_text_nodes:
                raise DocumentTemplateError("HWPX_TEXT_NODE_COUNT_INVALID")
            return TemplateValidation(
                key=definition.key,
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
                member_count=len(infos),
                text_node_count=text_node_count,
                token_names=tuple(sorted(tokens)),
            )
    except BadZipFile as error:
        raise DocumentTemplateError("HWPX_ZIP_INVALID") from error


def sanitize_template(
    source_path: Path,
    output_path: Path,
    definition: TemplateDefinition,
) -> TemplateValidation:
    source_sha256 = sha256_file(source_path)
    if source_sha256 != definition.source_sha256:
        raise DocumentTemplateError(
            f"HWPX_SOURCE_HASH_MISMATCH:{definition.key}:{source_sha256}"
        )
    try:
        with ZipFile(source_path) as source:
            infos = _assert_archive_layout(source)
            rendered: dict[str, bytes] = {}
            for info in infos:
                data = source.read(info)
                suffix = Path(info.filename).suffix.lower()
                if info.filename == "Contents/section0.xml":
                    data, _ = _sanitize_section(data, definition)
                elif suffix in {".xml", ".hpf", ".rdf"}:
                    root = _parse_xml(data, info.filename)
                    _scrub_metadata(root)
                    data = _serialize_xml(root, data)
                elif suffix == ".txt":
                    try:
                        value = data.decode("utf-8")
                    except UnicodeDecodeError:
                        value = data.decode("utf-16", errors="ignore")
                    data = _scrub_privacy(value).encode("utf-8")
                if info.filename == "Preview/PrvText.txt":
                    data = definition.preview_text.encode("utf-8")
                elif (
                    info.filename == "Preview/PrvImage.png"
                    or info.filename in definition.blank_binary_members
                ):
                    data = _blank_preview_png()
                rendered[info.filename] = data
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = output_path.with_suffix(".tmp")
            with ZipFile(temporary_path, mode="w") as target:
                for info in infos:
                    cloned = _clone_info(info)
                    if cloned.filename == "mimetype":
                        cloned.compress_type = ZIP_STORED
                    target.writestr(cloned, rendered[info.filename])
            temporary_path.replace(output_path)
    except BadZipFile as error:
        raise DocumentTemplateError("HWPX_ZIP_INVALID") from error
    return validate_template(output_path, definition)


def _find_source_by_hash(source_root: Path, digest: str) -> Path:
    matches = [
        path
        for path in source_root.rglob("*.hwpx")
        if path.is_file() and sha256_file(path) == digest
    ]
    if len(matches) != 1:
        raise DocumentTemplateError(
            f"HWPX_SOURCE_MATCH_COUNT:{digest}:{len(matches)}"
        )
    return matches[0]


def build_template_set(source_root: Path, output_dir: Path) -> dict[str, object]:
    validations: list[TemplateValidation] = []
    for definition in TEMPLATE_DEFINITIONS:
        source_path = _find_source_by_hash(source_root, definition.source_sha256)
        validations.append(
            sanitize_template(
                source_path,
                output_dir / definition.file_name,
                definition,
            )
        )
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "templateVersion": TEMPLATE_VERSION,
        "templates": [validation.as_dict() for validation in validations],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_template_set(template_dir: Path) -> dict[str, object]:
    validations = [
        validate_template(template_dir / definition.file_name, definition)
        for definition in TEMPLATE_DEFINITIONS
    ]
    expected = {
        "schemaVersion": 1,
        "templateVersion": TEMPLATE_VERSION,
        "templates": [validation.as_dict() for validation in validations],
    }
    manifest_path = template_dir / "manifest.json"
    try:
        actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DocumentTemplateError("HWPX_MANIFEST_INVALID") from error
    if actual != expected:
        raise DocumentTemplateError("HWPX_MANIFEST_MISMATCH")
    return expected


def render_hwpx(
    template_path: Path,
    output_path: Path,
    definition: TemplateDefinition,
    values: Mapping[str, str],
) -> TemplateValidation:
    unknown = set(values).difference(definition.token_names)
    if unknown:
        raise DocumentTemplateError(f"HWPX_UNKNOWN_VALUES:{sorted(unknown)}")
    replacements = {
        token: _normalize_xml_text(values.get(token, ""))
        for token in definition.token_names
    }
    with ZipFile(template_path) as source:
        infos = _assert_archive_layout(source)
        rendered: dict[str, bytes] = {}
        for info in infos:
            data = source.read(info)
            suffix = Path(info.filename).suffix.lower()
            if suffix in {".xml", ".hpf", ".rdf"}:
                root = _parse_xml(data, info.filename)
                for element in root.iter():
                    if element.text:
                        element.text = TOKEN_PATTERN.sub(
                            lambda match: replacements[match.group(1)],
                            element.text,
                        )
                    if element.tail:
                        element.tail = TOKEN_PATTERN.sub(
                            lambda match: replacements[match.group(1)],
                            element.tail,
                        )
                data = _serialize_xml(root, data)
            elif suffix == ".txt":
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = data.decode("utf-16", errors="ignore")
                data = TOKEN_PATTERN.sub(
                    lambda match: replacements[match.group(1)],
                    text,
                ).encode("utf-8")
            rendered[info.filename] = data
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_suffix(".tmp")
        with ZipFile(temporary_path, mode="w") as target:
            for info in infos:
                target.writestr(_clone_info(info), rendered[info.filename])
        temporary_path.replace(output_path)
    return validate_template(
        output_path,
        definition,
        require_tokens=False,
        require_privacy_clean=False,
    )


def _format_manifest(manifest: Mapping[str, object]) -> str:
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.document_templates")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--source-root", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--template-dir", type=Path, required=True)
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(arguments)
    if args.command == "build":
        result = build_template_set(args.source_root, args.output_dir)
    else:
        result = validate_template_set(args.template_dir)
    print(_format_manifest(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
