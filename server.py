"""Compatibility entry point used by the Windows launcher."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
for dependency_path in (ROOT / "vendor", ROOT / "src"):
    if dependency_path.is_dir():
        sys.path.insert(0, str(dependency_path))

from yantu.main import *  # noqa: F401,F403,E402


if __name__ == "__main__":
    raise SystemExit(main())
