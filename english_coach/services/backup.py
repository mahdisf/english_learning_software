"""SQLite backups using the sqlite3 backup API. Never overwrites an existing backup."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from english_coach.config import Settings


def create_backup(settings: Settings, *, label: str | None = None) -> Path:
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    backup_path = settings.backups_dir / f"backup_{timestamp}{suffix}.db"

    counter = 1
    while backup_path.exists():
        backup_path = settings.backups_dir / f"backup_{timestamp}{suffix}_{counter}.db"
        counter += 1

    source = sqlite3.connect(str(settings.database_path))
    try:
        dest = sqlite3.connect(str(backup_path))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    return backup_path
