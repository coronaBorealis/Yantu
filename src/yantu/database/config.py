from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AppPaths:
    """Separates immutable application resources from per-user writable data."""

    resource_root: Path
    data_root: Path

    @property
    def database(self) -> Path:
        return self.data_root / "yantu.db"

    @property
    def runtime_file(self) -> Path:
        return self.data_root / "runtime.json"

    @property
    def appearance_config(self) -> Path:
        return self.data_root / "appearance.json"

    @property
    def appearance_directory(self) -> Path:
        return self.data_root / "appearance"

    @property
    def logs_directory(self) -> Path:
        return self.data_root / "logs"


def resolve_app_paths(
    *,
    environ: dict[str, str] | None = None,
    frozen: bool | None = None,
    local_app_data: Path | str | None = None,
) -> AppPaths:
    values = os.environ if environ is None else environ
    override = str(values.get("YANTU_DATA_DIR") or "").strip()
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if override:
        data_root = Path(override).expanduser().resolve()
    elif is_frozen:
        base = Path(local_app_data or values.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        data_root = (base / "Yantu").resolve()
    else:
        data_root = (REPOSITORY_ROOT / "data").resolve()
    return AppPaths(resource_root=REPOSITORY_ROOT, data_root=data_root)


APP_PATHS = resolve_app_paths()
DEFAULT_DB_PATH = APP_PATHS.database
