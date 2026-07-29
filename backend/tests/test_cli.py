from app.cli import build_parser
from app.security import (
    hash_password,
    request_fingerprint,
    token_hash,
    tokens_match,
    verify_password,
)


def test_mutating_commands_are_explicit() -> None:
    assert build_parser().parse_args(["seed"]).command == "seed"
    assert build_parser().parse_args(["reprocess-kma"]).command == "reprocess-kma"
    assert build_parser().parse_args(["repair-kma-source"]).command == "repair-kma-source"
    assert build_parser().parse_args(["init-ai-control"]).command == "init-ai-control"
    assert (
        build_parser().parse_args(["probe-upstage-embedding"]).command
        == "probe-upstage-embedding"
    )


def test_argon2id_password_contract() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "correct horse battery staple")
    assert not verify_password(password_hash, "incorrect")


def test_session_tokens_are_one_way_and_constant_time_comparable() -> None:
    raw_token = "raw-session-token"
    stored = token_hash(raw_token)

    assert raw_token not in stored
    assert tokens_match(stored, raw_token)
    assert not tokens_match(stored, "other")
    assert request_fingerprint("s" * 32, "client") == request_fingerprint("s" * 32, "client")
