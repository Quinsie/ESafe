import json
from pathlib import Path
from uuid import UUID

FIXTURE = Path(__file__).parent / "fixtures" / "rag_evaluation_v1.json"
EXPECTED_CATEGORIES = {
    "OFFICIAL_CURRENT",
    "NORMAL_INCIDENT",
    "MAJOR_INCIDENT",
    "AUTHORITY_PRIORITY",
    "CONFLICT",
    "INSUFFICIENT",
}
KNOWN_EVALUATION_REGION_CODES = {
    "29",
    "29110",
    "29140",
    "29155",
    "29170",
    "29200",
    "46",
    "46170",
    "46710",
    "46720",
    "46790",
    "46860",
    "46870",
    "46880",
}
KNOWN_CASE_TYPES = {"FIRE", "WEATHER_WARNING", "DISASTER_MESSAGE"}


def test_rag_evaluation_fixture_has_30_reviewed_questions() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    questions = payload["questions"]

    assert payload["version"] == "rag-evaluation-v1"
    assert len(questions) == 30
    assert len({question["id"] for question in questions}) == 30
    assert {question["category"] for question in questions} == EXPECTED_CATEGORIES
    assert {
        question["regionCode"] for question in questions
    } <= KNOWN_EVALUATION_REGION_CODES
    assert {question["caseType"] for question in questions} <= KNOWN_CASE_TYPES
    assert all(question["rationale"].strip() for question in questions)
    assert all(question["supportTerms"] for question in questions)


def test_rag_evaluation_expected_ids_are_valid_uuids() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for question in payload["questions"]:
        for key in ("expectedDocumentIds", "expectedChunkIds"):
            for value in question[key]:
                assert str(UUID(value)) == value
