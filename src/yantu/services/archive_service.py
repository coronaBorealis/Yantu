from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..common import utc_now
from ..database.repositories.archive_repository import ArchiveRepository


ARCHIVE_FORMAT = "yantu.archive.period.v1"


class ArchiveService:
    """Prepare durable local archive indexes without moving live records."""

    def __init__(self, db_path: Path | str, archive_root: Path | str | None = None) -> None:
        self.repository = ArchiveRepository(db_path)
        self.root = Path(archive_root) if archive_root else Path(db_path).resolve().parent / "archive"

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(
                "# Yantu 本地归档\n\n"
                "此目录使用 `yantu.archive.period.v1` 格式。`weekly` 与 `monthly` "
                "只保存已经明确进入归档流程的快照；实时数据仍以 `yantu.db` 为准。\n"
                "请勿单独编辑 manifest.json 或 entries.ndjson。\n",
                encoding="utf-8",
            )
        schema = self.root / "schema-v1.json"
        if not schema.exists():
            schema.write_text(
                json.dumps(
                    {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "$id": ARCHIVE_FORMAT,
                        "type": "object",
                        "required": ["format", "period", "entries_file", "entry_count"],
                        "properties": {
                            "format": {"const": ARCHIVE_FORMAT},
                            "period": {
                                "type": "object",
                                "required": ["type", "key", "start_date", "end_date"],
                            },
                            "entries_file": {"const": "entries.ndjson"},
                            "entry_count": {"type": "integer", "minimum": 0},
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def prepare(self, value: date | str | None = None) -> list[dict[str, Any]]:
        target = date.fromisoformat(value) if isinstance(value, str) else value or date.today()
        self.ensure_layout()
        monday = target - timedelta(days=target.weekday())
        iso_year, iso_week, _ = target.isocalendar()
        month_start = target.replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        definitions = [
            ("week", f"{iso_year}-W{iso_week:02d}", monday, monday + timedelta(days=6),
             Path("weekly") / str(iso_year) / f"{iso_year}-W{iso_week:02d}"),
            ("month", target.strftime("%Y-%m"), month_start, next_month - timedelta(days=1),
             Path("monthly") / target.strftime("%Y") / target.strftime("%Y-%m")),
        ]
        records = []
        now = utc_now()
        for period_type, key, start, end, relative in definitions:
            folder = self.root / relative
            folder.mkdir(parents=True, exist_ok=True)
            entries = folder / "entries.ndjson"
            entries.touch(exist_ok=True)
            record = self.repository.upsert_period({
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"yantu:{period_type}:{key}")),
                "period_type": period_type,
                "period_key": key,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "relative_path": relative.as_posix(),
                "manifest_version": 1,
                "status": "open",
                "entry_count": 0,
                "created_at": now,
                "updated_at": now,
                "sealed_at": None,
            })
            manifest = {
                "format": ARCHIVE_FORMAT,
                "period": {
                    "type": period_type,
                    "key": key,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "timezone": "Asia/Shanghai",
                },
                "entries_file": "entries.ndjson",
                "entry_count": int(record["entry_count"]),
                "generated_at": now,
            }
            temporary = folder / "manifest.json.tmp"
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(folder / "manifest.json")
            records.append(record)
        return records

    def list_periods(self) -> list[dict[str, Any]]:
        return self.repository.list_periods()

    def export_index(self) -> dict[str, Any]:
        return {"format": ARCHIVE_FORMAT, "periods": self.list_periods()}
