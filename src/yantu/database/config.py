from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPOSITORY_ROOT / "data" / "yantu.db"
