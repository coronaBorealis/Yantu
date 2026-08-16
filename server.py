"""Compatibility entry point used by the Windows launcher."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT / "src"
if SOURCE_ROOT.is_dir():
    sys.path.insert(0, str(SOURCE_ROOT))

from yantu.main import *  # noqa: F401,F403,E402


if __name__ == "__main__":
    raise SystemExit(main())
