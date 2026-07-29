import pytest

from app.signals import (
    EventType,
    PayloadSchemaError,
    SourceStatus,
    parse_disaster_messages,
    parse_kma_warning,
    parse_nfds,
)


def test_nfds_parses_gwangju_record_and_coordinates() -> None:
    payload = """<?xml version="1.0" encoding="UTF-8"?>
    <response><defail><item>
      <sidoOvrNum>29-2026-1004</sidoOvrNum><sidoNm>광주광역시</sidoNm>
      <lawSidoCd>29</lawSidoCd><lawGunguCd>110</lawGunguCd>
      <addr>광주광역시 동구 금남로 1</addr><frfalTypeCd>건물화재</frfalTypeCd>
      <overDate>20260729101500</overDate><progressNm>출동 중</progressNm>
      <longitude>126.92</longitude><latitude>35.15</latitude>
    </item></defail></response>"""
    result = parse_nfds(payload)
    assert len(result) == 1
    assert result[0].external_id == "29-2026-1004"
    assert result[0].event_type == EventType.FIRE_DISPATCH
    assert result[0].region_codes == ("29",)
    assert result[0].location_precision == "COORDINATE"
    assert result[0].is_relevant is True


def test_nfds_preserves_resolved_update_and_filters_other_region() -> None:
    payload = """<defail>
      <item><sidoOvrNum>46-1</sidoOvrNum><sidoNm>전라남도</sidoNm>
        <lawSidoCd>46</lawSidoCd><addr>전남 나주시</addr><progressNm>상황종료</progressNm>
      </item>
      <item><sidoOvrNum>11-1</sidoOvrNum><sidoNm>서울특별시</sidoNm>
        <lawSidoCd>11</lawSidoCd><addr>서울 중구</addr><progressNm>출동 중</progressNm>
      </item>
    </defail>"""
    result = parse_nfds(payload)
    assert result[0].source_status == SourceStatus.RESOLVED
    assert result[0].region_codes == ("46",)
    assert result[1].is_relevant is False


@pytest.mark.parametrize("payload", ["<response/>", "<defail><item>"])
def test_nfds_fails_closed_on_schema_or_xml_change(payload: str) -> None:
    with pytest.raises(PayloadSchemaError):
        parse_nfds(payload)


def test_nfds_accepts_valid_empty_container() -> None:
    assert parse_nfds("<response><defail /></response>") == []


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


def test_kma_requires_official_list_identity_fields() -> None:
    with pytest.raises(PayloadSchemaError):
        parse_kma_warning({"title": "폭염경보"})


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
