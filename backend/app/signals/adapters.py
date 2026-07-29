import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.signals.contracts import CanonicalSignal, PayloadSchemaError, SignalSource
from app.signals.disaster_message import parse_disaster_messages
from app.signals.kma import parse_kma_warning
from app.signals.nfds import nfds_records, parse_nfds

NFDS_LICENSE_NOTE: Final = "국가화재정보시스템 전국119상황실 화면 내부 요청"
KMA_LICENSE_NOTE: Final = "기상청 기상특보 조회서비스 공공데이터포털 OpenAPI"
DISASTER_LICENSE_NOTE: Final = "재난안전데이터 공유플랫폼 공개 웹 목록 임시 수집"
KST: Final = ZoneInfo("Asia/Seoul")


class SourceRequestError(RuntimeError):
    def __init__(
        self,
        source: SignalSource,
        status_code: int | None,
        error_class: str,
        documents: tuple["FetchedDocument", ...] = (),
    ) -> None:
        super().__init__(f"{source.value} request failed: {error_class}")
        self.source = source
        self.status_code = status_code
        self.error_class = error_class
        self.documents = documents

    def with_documents(self, documents: tuple["FetchedDocument", ...]) -> "SourceRequestError":
        return SourceRequestError(self.source, self.status_code, self.error_class, documents)


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    label: str
    payload_format: str
    body: str
    content_type: str | None
    fetched_at: datetime
    request_metadata: dict[str, object]


class SourcePayloadError(PayloadSchemaError):
    def __init__(self, source: SignalSource, documents: tuple[FetchedDocument, ...]) -> None:
        super().__init__(f"{source.value} response schema changed")
        self.source = source
        self.documents = documents


@dataclass(frozen=True, slots=True)
class SourceRecord:
    signal: CanonicalSignal
    raw_payload: dict[str, object]
    document_index: int


@dataclass(frozen=True, slots=True)
class SourceBatch:
    source: SignalSource
    documents: tuple[FetchedDocument, ...]
    records: tuple[SourceRecord, ...]
    license_note: str


async def _request(
    client: httpx.AsyncClient,
    source: SignalSource,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.TimeoutException as error:
        raise SourceRequestError(source, None, "TIMEOUT") from error
    except httpx.HTTPError as error:
        raise SourceRequestError(source, None, type(error).__name__.upper()) from error
    if response.status_code in (403, 429):
        raise SourceRequestError(
            source, response.status_code, f"HTTP_{response.status_code}_BLOCKED"
        )
    if 500 <= response.status_code <= 599:
        raise SourceRequestError(source, response.status_code, f"HTTP_{response.status_code}")
    if response.status_code >= 400:
        raise SourceRequestError(source, response.status_code, f"HTTP_{response.status_code}")
    return response


def _document(
    label: str,
    payload_format: str,
    response: httpx.Response,
    request_metadata: dict[str, object],
) -> FetchedDocument:
    return FetchedDocument(
        label=label,
        payload_format=payload_format,
        body=response.text,
        content_type=response.headers.get("content-type"),
        fetched_at=datetime.now(UTC),
        request_metadata=request_metadata,
    )


async def fetch_nfds(
    settings: Settings,
    client: httpx.AsyncClient,
) -> SourceBatch:
    documents: list[FetchedDocument] = []
    records: list[SourceRecord] = []
    for sido_code in ("29", "46"):
        try:
            response = await _request(
                client,
                SignalSource.NFDS,
                "POST",
                settings.nfds_monitor_url,
                data={"sidoCode": sido_code},
                headers={"User-Agent": settings.signal_user_agent},
            )
        except SourceRequestError as error:
            raise error.with_documents(tuple(documents)) from error
        document_index = len(documents)
        documents.append(
            _document(
                f"sido-{sido_code}",
                "JSON",
                response,
                {"sidoCode": sido_code},
            )
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise SourcePayloadError(SignalSource.NFDS, tuple(documents)) from error
        try:
            if not isinstance(payload, dict):
                raise PayloadSchemaError("NFDS response root is not an object")
            original = {
                str(item.get("sidoOvrNum", "")): item
                for item in nfds_records(payload)
                if isinstance(item, dict)
            }
            for signal in parse_nfds(payload):
                raw = original.get(signal.external_id, {"externalId": signal.external_id})
                records.append(SourceRecord(signal, dict(raw), document_index))
        except PayloadSchemaError as error:
            raise SourcePayloadError(SignalSource.NFDS, tuple(documents)) from error
    return SourceBatch(SignalSource.NFDS, tuple(documents), tuple(records), NFDS_LICENSE_NOTE)


def _kma_items(payload: object) -> list[dict[str, object]]:
    try:
        response = payload["response"]  # type: ignore[index]
        header = response["header"]
        body = response["body"]
    except (KeyError, TypeError) as error:
        raise PayloadSchemaError("KMA response envelope changed") from error
    if not isinstance(header, dict) or str(header.get("resultCode")) != "00":
        raise PayloadSchemaError("KMA response resultCode is not 00")
    items = body.get("items") if isinstance(body, dict) else None
    if items in (None, ""):
        return []
    if not isinstance(items, dict):
        raise PayloadSchemaError("KMA response items changed")
    item = items.get("item", [])
    if isinstance(item, dict):
        return [{str(key): value for key, value in item.items()}]
    if not isinstance(item, list):
        raise PayloadSchemaError("KMA response item is not an array")
    if not all(isinstance(value, dict) for value in item):
        raise PayloadSchemaError("KMA response contains a non-object item")
    return [{str(key): value for key, value in value.items()} for value in item]


def _kma_url(settings: Settings, operation: str, parameters: dict[str, object]) -> str:
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("DATA_GO_KR_SERVICE_KEY is required for LIVE KMA collection")
    key = settings.data_go_kr_service_key.get_secret_value()
    query = urlencode(parameters)
    return f"{settings.kma_warning_base_url}/{operation}?ServiceKey={key}&{query}"


def _kma_external_id(item: dict[str, object]) -> str:
    return f"{item.get('stnId', '')}:{item.get('tmFc', '')}:{item.get('tmSeq', '')}"


def _kma_query_window(now: datetime | None = None) -> tuple[str, str]:
    instant = now or datetime.now(UTC)
    today = instant.astimezone(KST).date()
    available_through = min(today, instant.astimezone(UTC).date())
    return (
        (today - timedelta(days=6)).strftime("%Y%m%d"),
        available_through.strftime("%Y%m%d"),
    )


async def fetch_kma_warnings(
    settings: Settings,
    client: httpx.AsyncClient,
    known_external_ids: frozenset[str] = frozenset(),
) -> SourceBatch:
    from_tm_fc, to_tm_fc = _kma_query_window()
    parameters: dict[str, object] = {
        "pageNo": 1,
        "numOfRows": 1000,
        "dataType": "JSON",
        "stnId": 108,
        "fromTmFc": from_tm_fc,
        "toTmFc": to_tm_fc,
    }
    list_response = await _request(
        client,
        SignalSource.KMA_WARNING,
        "GET",
        _kma_url(settings, "getWthrWrnList", parameters),
        headers={"User-Agent": settings.signal_user_agent},
    )
    documents = [
        _document(
            "warning-list",
            "JSON",
            list_response,
            {"operation": "list", "windowDays": 7},
        )
    ]
    try:
        list_payload = list_response.json()
    except json.JSONDecodeError as error:
        raise SourcePayloadError(SignalSource.KMA_WARNING, tuple(documents)) from error
    try:
        items = _kma_items(list_payload)
    except PayloadSchemaError as error:
        raise SourcePayloadError(SignalSource.KMA_WARNING, tuple(documents)) from error

    try:
        detail_response = await _request(
            client,
            SignalSource.KMA_WARNING,
            "GET",
            _kma_url(settings, "getWthrWrnMsg", parameters),
            headers={"User-Agent": settings.signal_user_agent},
        )
    except SourceRequestError as error:
        raise error.with_documents(tuple(documents)) from error
    documents.append(
        _document(
            "warning-messages",
            "JSON",
            detail_response,
            {"operation": "messages", "windowDays": 7},
        )
    )
    try:
        detail_items = _kma_items(detail_response.json())
        details_by_id = {_kma_external_id(item): item for item in detail_items}
        if len(details_by_id) != len(detail_items):
            raise PayloadSchemaError("KMA warning messages contain duplicate identities")
    except (json.JSONDecodeError, PayloadSchemaError) as error:
        raise SourcePayloadError(SignalSource.KMA_WARNING, tuple(documents)) from error

    records: list[SourceRecord] = []
    for item in items:
        external_id = _kma_external_id(item)
        if external_id in known_external_ids:
            continue
        detail = details_by_id.get(external_id)
        if detail is None:
            raise SourcePayloadError(SignalSource.KMA_WARNING, tuple(documents))
        try:
            signal = parse_kma_warning(item, detail)
        except PayloadSchemaError as error:
            raise SourcePayloadError(SignalSource.KMA_WARNING, tuple(documents)) from error
        records.append(
            SourceRecord(
                signal,
                {"listItem": item, "detailItem": detail},
                1,
            )
        )
    return SourceBatch(
        SignalSource.KMA_WARNING,
        tuple(documents),
        tuple(records),
        KMA_LICENSE_NOTE,
    )


async def fetch_disaster_messages(
    settings: Settings,
    client: httpx.AsyncClient,
) -> SourceBatch:
    response = await _request(
        client,
        SignalSource.DISASTER_MESSAGE,
        "GET",
        settings.disaster_message_url,
        params={"currentPage": 1, "cntPerPage": 50, "pageSize": 10},
        headers={"User-Agent": settings.signal_user_agent},
    )
    document = _document(
        "message-list-page-1",
        "HTML",
        response,
        {"currentPage": 1, "cntPerPage": 50},
    )
    try:
        signals = parse_disaster_messages(response.text)
    except PayloadSchemaError as error:
        raise SourcePayloadError(SignalSource.DISASTER_MESSAGE, (document,)) from error
    records = tuple(
        SourceRecord(
            signal,
            {
                "externalId": signal.external_id,
                "message": signal.title,
                "sourcePublishedAt": (
                    signal.source_published_at.isoformat()
                    if signal.source_published_at is not None
                    else None
                ),
            },
            0,
        )
        for signal in signals
    )
    return SourceBatch(
        SignalSource.DISASTER_MESSAGE,
        (document,),
        records,
        DISASTER_LICENSE_NOTE,
    )
