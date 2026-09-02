"""Configuration loading for the English Coach application.

Configuration is read from an optional ``config.toml`` file located in the
current working directory (or pointed to by the ``ENGLISH_COACH_CONFIG``
environment variable). When absent, safe defaults matching
``config.example.toml`` are used.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class PathsConfig(BaseModel):
    database: str = "data/english_coach.db"
    imported_dir: str = "data/imported"
    backups_dir: str = "data/backups"
    exports_dir: str = "exports"
    reports_dir: str = "reports"


class GeneralConfig(BaseModel):
    timezone: str = "Asia/Tehran"


class AnkiConfig(BaseModel):
    deck_root: str = "English Coach"
    vocabulary_deck: str = "English Coach::Vocabulary"
    expressions_deck: str = "English Coach::Expressions"
    grammar_deck: str = "English Coach::Grammar"
    mistakes_deck: str = "English Coach::Mistakes"


class ContextExportConfig(BaseModel):
    default_item_budget: int = 25
    recent_session_count: int = 5


class LearnerProfileConfig(BaseModel):
    native_language: str = "Persian"
    current_level: str = "B1"
    target_level: str = "C1"
    english_variety: str = "American English"
    pronunciation_standard: str = "General American"
    daily_study_minutes: int = 30
    persian_meaning_policy: str = (
        "Include Persian meanings only when a clear B1-B2 English "
        "definition is unlikely to be sufficient."
    )
    default_timezone: str = "Asia/Tehran"
    professional_background: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "roles": [
                "Senior Robotics Software Engineer",
                "Technical Product Manager",
            ],
            "education": ["MSc in Mechatronics Engineering"],
        }
    )
    learning_goals: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "goals": [
                "International professional communication",
                "Meetings and leadership discussions",
                "Technical and behavioral interviews",
                "Presentations and networking",
                "Possible PhD applications",
            ]
        }
    )


class Settings(BaseModel):
    project_root: Path
    paths: PathsConfig = Field(default_factory=PathsConfig)
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    anki: AnkiConfig = Field(default_factory=AnkiConfig)
    context_export: ContextExportConfig = Field(default_factory=ContextExportConfig)
    learner_profile: LearnerProfileConfig = Field(default_factory=LearnerProfileConfig)

    def resolve(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute():
            return path
        return (self.project_root / path).resolve()

    @property
    def database_path(self) -> Path:
        return self.resolve(self.paths.database)

    @property
    def imported_dir(self) -> Path:
        return self.resolve(self.paths.imported_dir)

    @property
    def backups_dir(self) -> Path:
        return self.resolve(self.paths.backups_dir)

    @property
    def exports_dir(self) -> Path:
        return self.resolve(self.paths.exports_dir)

    @property
    def reports_dir(self) -> Path:
        return self.resolve(self.paths.reports_dir)


def _find_config_file() -> Path | None:
    env_path = os.environ.get("ENGLISH_COACH_CONFIG")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate
        return None
    candidate = Path.cwd() / "config.toml"
    if candidate.is_file():
        return candidate
    return None


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from an explicit path, the environment, or defaults."""
    found = config_path or _find_config_file()
    if found is None:
        return Settings(project_root=Path.cwd())

    with open(found, "rb") as f:
        raw = tomllib.load(f)

    project_root = found.parent
    return Settings(
        project_root=project_root,
        paths=PathsConfig(**raw.get("paths", {})),
        general=GeneralConfig(**raw.get("general", {})),
        anki=AnkiConfig(**raw.get("anki", {})),
        context_export=ContextExportConfig(**raw.get("context_export", {})),
        learner_profile=LearnerProfileConfig(**raw.get("learner_profile", {})),
    )


def get_settings(config_path: Path | None = None) -> Settings:
    """Load settings fresh every call (cheap TOML read; keeps CWD-dependent
    behavior correct across repeated CLI invocations and test runs)."""
    return load_settings(config_path)
