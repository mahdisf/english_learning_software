import shutil
from pathlib import Path

import pytest

from english_coach.config import Settings
from english_coach.db import get_engine, get_session_factory
from english_coach.migrate import seed_singletons
from english_coach.models import Base

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings(project_root=tmp_path)
    for d in (s.database_path.parent, s.imported_dir, s.backups_dir, s.exports_dir, s.reports_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s


@pytest.fixture
def db_settings(settings) -> Settings:
    """Settings backed by a freshly created (non-Alembic) schema, for fast unit tests."""
    engine = get_engine(settings, create_parent=True)
    Base.metadata.create_all(engine)
    seed_singletons(settings)
    return settings


@pytest.fixture
def db_session(db_settings):
    factory = get_session_factory(db_settings)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def cli_project(tmp_path, monkeypatch):
    """A temp project directory with real alembic assets and its own config.toml."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    shutil.copy(REPO_ROOT / "alembic.ini", project_dir / "alembic.ini")
    shutil.copytree(
        REPO_ROOT / "alembic",
        project_dir / "alembic",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    config_toml = project_dir / "config.toml"
    config_toml.write_text(
        "[paths]\n"
        'database = "data/english_coach.db"\n'
        'imported_dir = "data/imported"\n'
        'backups_dir = "data/backups"\n'
        'exports_dir = "exports"\n'
        'reports_dir = "reports"\n'
        "\n"
        "[general]\n"
        'timezone = "Asia/Tehran"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(project_dir)
    return project_dir
