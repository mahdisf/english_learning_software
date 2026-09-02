"""Programmatic Alembic migration runner and singleton-row seeding."""
from __future__ import annotations

from alembic import command
from alembic.config import Config

from english_coach.config import Settings
from english_coach.db import get_session_factory
from english_coach.models import LearnerProfile, MemoryState


def _alembic_config(settings: Settings) -> Config:
    alembic_ini = settings.project_root / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(settings.project_root / "alembic"))
    return cfg


def upgrade_to_head(settings: Settings) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = _alembic_config(settings)
    command.upgrade(cfg, "head")


def seed_singletons(settings: Settings) -> None:
    factory = get_session_factory(settings)
    db = factory()
    try:
        if db.get(LearnerProfile, 1) is None:
            lp = settings.learner_profile
            db.add(
                LearnerProfile(
                    id=1,
                    native_language=lp.native_language,
                    current_level=lp.current_level,
                    target_level=lp.target_level,
                    english_variety=lp.english_variety,
                    pronunciation_standard=lp.pronunciation_standard,
                    daily_study_minutes=lp.daily_study_minutes,
                    persian_meaning_policy=lp.persian_meaning_policy,
                    professional_background=lp.professional_background,
                    learning_goals=lp.learning_goals,
                    default_timezone=lp.default_timezone,
                )
            )
        if db.get(MemoryState, 1) is None:
            db.add(MemoryState(id=1))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
