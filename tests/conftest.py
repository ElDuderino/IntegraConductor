from __future__ import annotations

from pathlib import Path

import pytest

from integra7_conductor.catalog import database, parser
from integra7_conductor.config import load_config
from integra7_conductor.midi.mock_backend import MockBackend
from integra7_conductor.services.core import AppContext

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = REPO / "data" / "sources"


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Never read or write the developer's real config, catalog or lock file."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    for name in list(__import__("os").environ):
        if name.startswith("INTEGRA7_"):
            monkeypatch.delenv(name)


@pytest.fixture(scope="session")
def full_db(tmp_path_factory) -> Path:
    """Catalog built once from the bundled upstream source files."""
    path = tmp_path_factory.mktemp("catalog") / "patches.db"
    database.build_catalog(
        path,
        parser.parse_file(SOURCES / "roland-integra-7-full.txt"),
        [parser.parse_file(SOURCES / "roland-integra-7.txt")],
    )
    return path


@pytest.fixture
def fixture_db(tmp_path) -> Path:
    path = tmp_path / "fixture.db"
    database.build_catalog(
        path,
        parser.parse_file(FIXTURES / "sample-cubase.txt"),
        [parser.parse_file(FIXTURES / "sample-compare.txt")],
    )
    return path


@pytest.fixture
def backend() -> MockBackend:
    return MockBackend()


@pytest.fixture
def make_ctx(full_db, backend, tmp_path):
    def factory(**overrides) -> AppContext:
        values = {"backend": "mock", "db_path": str(full_db), **overrides}
        part_channels = values.pop("part_channels", None)
        cfg = load_config(tmp_path / "config.toml", values)
        if part_channels:
            cfg.part_channels = dict(part_channels)
        return AppContext(cfg, backend)

    return factory


@pytest.fixture
def ctx(make_ctx) -> AppContext:
    return make_ctx()
