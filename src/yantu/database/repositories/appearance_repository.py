from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class AppearanceRepository:
    """Local file persistence for UI appearance, independent from SQLite."""

    def __init__(self, config_path: Path | str, background_dir: Path | str) -> None:
        self.config_path = Path(config_path)
        self.background_dir = Path(background_dir)

    def read(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def write(self, value: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix="appearance-", suffix=".tmp", dir=self.config_path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.config_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def background(self) -> Path | None:
        if not self.background_dir.exists():
            return None
        for extension in (".png", ".jpg", ".webp"):
            candidate = self.background_dir / f"background{extension}"
            if candidate.is_file():
                return candidate
        return None

    def write_background(self, content: bytes, extension: str) -> Path:
        self.background_dir.mkdir(parents=True, exist_ok=True)
        target = self.background_dir / f"background{extension}"
        handle, temporary_name = tempfile.mkstemp(
            prefix="background-", suffix=".tmp", dir=self.background_dir
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target)
            for sibling in self.background_dir.glob("background.*"):
                if sibling != target:
                    sibling.unlink(missing_ok=True)
            return target
        finally:
            temporary_path.unlink(missing_ok=True)

    def delete_background(self) -> bool:
        removed = False
        if self.background_dir.exists():
            for candidate in self.background_dir.glob("background.*"):
                if candidate.is_file():
                    candidate.unlink()
                    removed = True
        return removed
