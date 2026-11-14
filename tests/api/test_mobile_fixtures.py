from pathlib import Path

from tests import mobile_fixtures


def test_fixtures_a_jour(tmp_path: Path, coach_home):
    mobile_fixtures.generate(tmp_path)
    for name in ("active.sql", "between.sql", "expected.json"):
        committed = (mobile_fixtures.FIXTURES_DIR / name).read_bytes()
        assert (tmp_path / name).read_bytes() == committed, (
            "Fixtures mobiles périmées : uv run python -m tests.mobile_fixtures"
        )
