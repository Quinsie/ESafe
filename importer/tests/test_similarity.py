from datetime import date

from esafe_importer.similarity import (
    classify_first,
    classify_many,
    damage_categories,
    incident_type,
    parse_date_yyyymmdd,
    parse_nonnegative_float,
    parse_region,
    parse_report_date,
)


def test_report_date_accepts_four_and_two_digit_years() -> None:
    assert parse_report_date("2026.3.24. 사고보고") == date(2026, 3, 24)
    assert parse_report_date("(26.06.13) 중대사고") == date(2026, 6, 13)
    assert parse_report_date("2026.13.40 invalid") is None


def test_region_parser_normalizes_province_aliases() -> None:
    assert parse_region("전남 나주시 2026.03.24 사고") == ("전라남도", "나주시")
    assert parse_region("광주광역시 광산구_화재") == ("광주광역시", "광산구")
    assert parse_region("지역정보 없음") == (None, None)


def test_classifiers_return_only_declared_categories() -> None:
    rules = (("분전 설비", ("분전반",)), ("배선 설비", ("배선", "전선")))
    assert classify_first("분전반 배선 이상", rules, "기타") == "분전 설비"
    assert classify_many("분전반 배선 이상", rules) == ["분전 설비", "배선 설비"]
    assert incident_type("감전 사고와 화재") == "감전"


def test_damage_categories_distinguish_absence_from_report() -> None:
    assert damage_categories("인명 피해 없음, 재산 피해 없음") == [
        "인명피해 없음",
        "재산피해 없음",
    ]
    assert damage_categories("인명피해 1명, 건물 일부 소실") == [
        "인명피해 보고",
        "건물 일부 소실",
    ]


def test_public_facility_value_parsers_fail_closed() -> None:
    assert parse_date_yyyymmdd("20260324") == date(2026, 3, 24)
    assert parse_date_yyyymmdd("20261340") is None
    assert parse_nonnegative_float("12.5") == 12.5
    assert parse_nonnegative_float("-1") is None
    assert parse_nonnegative_float("not-a-number") is None
