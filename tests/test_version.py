import tomllib
from pathlib import Path

import pytest

from coach.version import app_version, parse_version


def test_parse_version_orders_numerically():
    assert parse_version("v0.10.0") > parse_version("0.9.3")
    assert parse_version("0.2.0") == (0, 2, 0)


@pytest.mark.parametrize("bad", ["", "1.2", "1.2.x", "latest"])
def test_parse_version_rejects(bad):
    with pytest.raises(ValueError):
        parse_version(bad)


def test_app_version_matches_pyproject():
    assert app_version() == tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
