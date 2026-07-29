import httpx
import pytest

from app.config import Settings
from app.signals import (
    EventType,
    PayloadSchemaError,
    SourceStatus,
    parse_disaster_messages,
    parse_kma_warning,
    parse_nfds,
)
from app.signals.adapters import (
    SourcePayloadError,
    fetch_disaster_messages,
    fetch_kma_warnings,
    fetch_nfds,
)
from app.signals.contracts import normalize_address
from app.signals.reprocess import parse_stored_kma_payload


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "ESAFE_PROFILE": "LIVE",
            "ESAFE_SESSION_SECRET": "test-session-secret-at-least-32-characters",
            "DATA_GO_KR_SERVICE_KEY": "encoded%2Bkey",
            "NFDS_MONITOR_URL": "https://nfds.test/monitorData.do",
            "KMA_WARNING_BASE_URL": "https://kma.test/WthrWrnInfoService",
            "DISASTER_MESSAGE_URL": "https://safety.test/disasterNotification",
        }
    )


def test_nfds_parses_gwangju_json_record_and_coordinates() -> None:
    payload = {
        "defail": [
            {
                "sidoOvrNum": "29-2026-1004",
                "sidoNm": "광주광역시",
                "lawSidoCd": "29",
                "lawGunguCd": "110",
                "addr": "광주광역시 동구 금남로 1",
                "frfalTypeCd": "건물화재",
                "overDate": "20260729101500",
                "progressNm": "출동 중",
                "longitude": 126.92,
                "latitude": 35.15,
            }
        ]
    }
    result = parse_nfds(payload)
    assert len(result) == 1
    assert result[0].external_id == "29-2026-1004"
    assert result[0].event_type == EventType.FIRE_DISPATCH
    assert result[0].region_codes == ("29",)
    assert result[0].location_precision == "COORDINATE"
    assert result[0].is_relevant is True


def test_nfds_preserves_resolved_update_and_filters_other_region() -> None:
    payload = {
        "defail": [
            {
                "sidoOvrNum": "46-1",
                "sidoNm": "전라남도",
                "lawSidoCd": "46",
                "addr": "전남 나주시",
                "progressNm": "상황종료",
            },
            {
                "sidoOvrNum": "11-1",
                "sidoNm": "서울특별시",
                "lawSidoCd": "11",
                "addr": "서울 중구",
                "progressNm": "출동 중",
            },
        ]
    }
    result = parse_nfds(payload)
    assert result[0].source_status == SourceStatus.RESOLVED
    assert result[0].region_codes == ("46",)
    assert result[1].is_relevant is False


@pytest.mark.parametrize(
    "payload",
    [{"other": []}, {"defail": "changed"}, b"\xff\xfe"],
)
def test_nfds_fails_closed_on_schema_or_json_change(payload: object) -> None:
    with pytest.raises(PayloadSchemaError):
        parse_nfds(payload)  # type: ignore[arg-type]


def test_nfds_accepts_valid_empty_container() -> None:
    assert parse_nfds({"defail": []}) == []


def test_kma_uses_detail_regions_and_stable_announcement_id() -> None:
    item = {
        "stnId": "108",
        "tmFc": "202607291000",
        "tmSeq": 447,
        "title": "[특보] 제07-447호 폭염경보 발표",
    }
    detail = {
        "t1": "폭염경보 발표",
        "t2": "o 폭염경보 : 전라남도(나주, 광양), 광주광역시",
        "t3": "2026년 07월 29일 10시 00분",
    }
    result = parse_kma_warning(item, detail)
    assert result.external_id == "108:202607291000:447"
    assert result.region_codes == ("29", "46")
    assert result.severity == "WARNING"
    assert result.is_relevant is True


def test_kma_does_not_confuse_gyeonggi_gwangju_with_gwangju_metropolitan() -> None:
    result = parse_kma_warning(
        {
            "stnId": "108",
            "tmFc": "202607291100",
            "tmSeq": "448",
            "title": "[특보] 폭염주의보 발표",
        },
        {"t2": "o 폭염주의보 : 경기도(광주, 성남, 여주)"},
    )
    assert result.region_codes == ()
    assert result.is_relevant is False


def test_kma_does_not_use_nationwide_status_appendix_as_announcement_scope() -> None:
    result = parse_kma_warning(
        {
            "stnId": "108",
            "tmFc": "202607291200",
            "tmSeq": "449",
            "title": "[특보] 서울특별시 폭염주의보 발표",
        },
        {
            "t1": "폭염주의보 발표",
            "t2": "o 폭염주의보 : 서울특별시",
            "t6": "현재 특보현황 : 광주광역시와 전라남도 호우경보",
        },
    )
    assert result.region_codes == ()
    assert result.is_relevant is False


def test_kma_requires_official_list_identity_fields() -> None:
    with pytest.raises(PayloadSchemaError):
        parse_kma_warning({"title": "폭염경보"})


def test_stored_kma_payload_reuses_the_canonical_parser() -> None:
    result = parse_stored_kma_payload(
        {
            "listItem": {
                "stnId": "108",
                "tmFc": "202607291200",
                "tmSeq": "449",
                "title": "[특보] 폭염주의보 발표",
            },
            "detailItem": {"t2": "o 폭염주의보 : 전라남도(나주)"},
        }
    )
    assert result.region_codes == ("46",)
    with pytest.raises(PayloadSchemaError):
        parse_stored_kma_payload({"detailItem": {}})


def test_disaster_message_parses_relevant_rows_and_sequence() -> None:
    page = (
        "<html><body><table><thead><tr><th>NO</th><th>내용</th><th>등록일</th></tr></thead>"
        "<tbody><tr><td>56720</td><td>"
        '<a href="/disasterNotificationView?sn=56720">'
        "전라남도 나주시 호우로 침수 위험, 저지대 대피 바랍니다.</a></td>"
        "<td>2026-07-29 10:31</td></tr><tr><td>56719</td><td>"
        '<a href="/disasterNotificationView?sn=56719">서울특별시 교통 통제 안내</a></td>'
        "<td>2026-07-29 10:22</td></tr></tbody></table></body></html>"
    )
    result = parse_disaster_messages(page)
    assert [item.external_id for item in result] == ["56720", "56719"]
    assert result[0].is_relevant is True
    assert result[0].event_subtype == "호우"
    assert result[0].source_published_at is not None
    assert result[1].is_relevant is False


def test_disaster_message_empty_table_is_valid_but_missing_table_is_not() -> None:
    assert parse_disaster_messages("<table><tr><th>내용</th></tr></table>") == []
    with pytest.raises(PayloadSchemaError):
        parse_disaster_messages("<html><body>maintenance</body></html>")


def test_disaster_message_rejects_invalid_encoding() -> None:
    with pytest.raises(PayloadSchemaError):
        parse_disaster_messages(b"\xff\xfe\x00")


def test_repeat_parsing_is_deterministic() -> None:
    page = """
    <table><tr><td>900</td><td><a href="?sn=900">광주광역시 산불 주의 안내</a></td>
    <td>2026-07-29 11:00</td></tr></table>
    """
    assert parse_disaster_messages(page) == parse_disaster_messages(page)


@pytest.mark.asyncio
async def test_nfds_adapter_requests_only_gwangju_and_jeonnam() -> None:
    requested: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        form = (await request.aread()).decode()
        requested.append(form)
        code = form.rsplit("=", 1)[-1]
        return httpx.Response(
            200,
            json={
                "defail": [
                    {
                        "sidoOvrNum": f"{code}-1",
                        "lawSidoCd": code,
                        "sidoNm": "광주광역시" if code == "29" else "전라남도",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await fetch_nfds(_settings(), client)
    assert requested == ["sidoCode=29", "sidoCode=46"]
    assert len(batch.documents) == 2
    assert [record.signal.external_id for record in batch.records] == ["29-1", "46-1"]


@pytest.mark.asyncio
async def test_kma_adapter_joins_list_and_message_windows_by_identity() -> None:
    calls: list[str] = []

    def envelope(items: list[dict[str, object]]) -> dict[str, object]:
        return {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"items": {"item": items}},
            }
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("getWthrWrnList"):
            return httpx.Response(
                200,
                json=envelope(
                    [
                        {
                            "stnId": "108",
                            "tmFc": "202607291000",
                            "tmSeq": "1",
                            "title": "폭염경보 발표",
                        },
                        {
                            "stnId": "108",
                            "tmFc": "202607291100",
                            "tmSeq": "2",
                            "title": "호우주의보 발표",
                        },
                    ]
                ),
            )
        assert request.url.params["fromTmFc"]
        assert request.url.params["toTmFc"]
        assert "tmFc" not in request.url.params
        assert "tmSeq" not in request.url.params
        return httpx.Response(
            200,
            json=envelope(
                [
                    {
                        "stnId": "108",
                        "tmFc": "202607291100",
                        "tmSeq": "2",
                        "t2": "o 호우주의보 : 전라남도(나주)",
                    },
                    {"stnId": "108", "tmFc": "202607291000", "tmSeq": "1"},
                ]
            ),
        )

    known = frozenset({"108:202607291000:1"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await fetch_kma_warnings(_settings(), client, known)
    assert calls == [
        "/WthrWrnInfoService/getWthrWrnList",
        "/WthrWrnInfoService/getWthrWrnMsg",
    ]
    assert len(batch.documents) == 2
    assert len(batch.records) == 1
    assert batch.records[0].signal.external_id == "108:202607291100:2"
    assert batch.records[0].signal.region_codes == ("46",)
    assert batch.records[0].document_index == 1


@pytest.mark.asyncio
async def test_kma_adapter_fails_closed_when_message_identity_is_missing() -> None:
    def envelope(items: list[dict[str, object]]) -> dict[str, object]:
        return {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"items": {"item": items}},
            }
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getWthrWrnList"):
            return httpx.Response(
                200,
                json=envelope(
                    [
                        {
                            "stnId": "108",
                            "tmFc": "202607291100",
                            "tmSeq": "2",
                            "title": "호우주의보 발표",
                        }
                    ]
                ),
            )
        return httpx.Response(200, json=envelope([]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourcePayloadError):
            await fetch_kma_warnings(_settings(), client)


@pytest.mark.asyncio
async def test_disaster_adapter_uses_one_fifty_item_page() -> None:
    page = (
        "<table><tr><td>100</td><td><a href='?sn=100'>"
        "광주광역시 화재로 인근 주민은 대피 바랍니다.</a></td>"
        "<td>2026-07-29 11:30</td></tr></table>"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["currentPage"] == "1"
        assert request.url.params["cntPerPage"] == "50"
        return httpx.Response(200, text=page, headers={"content-type": "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await fetch_disaster_messages(_settings(), client)
    assert len(batch.documents) == 1
    assert batch.records[0].signal.external_id == "100"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [403, 429, 500])
async def test_adapters_surface_block_and_server_status(status_code: int) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError) as error:
            await fetch_disaster_messages(_settings(), client)
    assert str(status_code) in str(error.value)


@pytest.mark.asyncio
async def test_schema_error_keeps_the_received_document() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><body>changed layout</body></html>",
            headers={"content-type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourcePayloadError) as captured:
            await fetch_disaster_messages(_settings(), client)
    assert len(captured.value.documents) == 1


def test_address_normalization_is_conservative_and_deterministic() -> None:
    assert normalize_address(" 광주광역시 동구 금남로 1 (충장동) ") == (
        "광주광역시동구금남로1충장동"
    )
    assert normalize_address(None) is None
