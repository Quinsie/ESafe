from app.cli import build_parser


def test_seed_command_is_explicit() -> None:
    assert build_parser().parse_args(["seed"]).command == "seed"
