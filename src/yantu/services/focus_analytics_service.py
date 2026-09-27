from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..database.repository import database, init_db


class FocusAnalyticsService:
    """Read archived focus sessions from SQLite for both web and desktop clients."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def report(self, *, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        try:
            start_date = date.fromisoformat(start) if start else date.today() - timedelta(days=27)
            end_date = date.fromisoformat(end) if end else date.today()
        except (TypeError, ValueError) as exc:
            raise ValueError("日期格式应为 YYYY-MM-DD") from exc
        if end_date < start_date:
            raise ValueError("结束日期不能早于开始日期")
        if end_date > date.today():
            raise ValueError("结束日期不能晚于今天")
        with database(self.db_path) as connection:
            rows = connection.execute("""
                SELECT f.id, f.task_id, f.mode, f.status, f.elapsed_seconds,
                       f.target_seconds, f.pause_count, f.paused_seconds,
                       f.started_at, f.ended_at, f.note,
                       COALESCE(f.task_title_snapshot, t.title, '已删除任务') AS task_title,
                       COALESCE(f.task_domain_snapshot, t.domain, 'unknown') AS task_domain,
                       COALESCE(f.project_name_snapshot, p.name, '未归入项目') AS project_name,
                       h.status AS habit_status, h.active_seconds, h.idle_seconds,
                       h.distraction_seconds, h.switch_count, h.quality_score
                FROM focus_sessions f
                LEFT JOIN tasks t ON t.id = f.task_id
                LEFT JOIN projects p ON p.id = t.project_id
                LEFT JOIN focus_habit_sessions h ON h.session_id = f.id
                WHERE f.archived = 1 AND f.session_type = 'focus' AND f.elapsed_seconds > 0
                ORDER BY f.ended_at DESC, f.id DESC
            """).fetchall()
        sessions = []
        for row in rows:
            item = dict(row)
            if not item["ended_at"]:
                continue
            ended_day = datetime.fromisoformat(item["ended_at"]).astimezone().date()
            if start_date <= ended_day <= end_date:
                item["archive_date"] = ended_day.isoformat()
                sessions.append(item)

        by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"seconds": 0, "sessions": 0})
        by_task: dict[str, int] = defaultdict(int)
        by_domain: dict[str, int] = defaultdict(int)
        by_project: dict[str, int] = defaultdict(int)
        by_mode: dict[str, int] = defaultdict(int)
        by_weekday: dict[int, int] = defaultdict(int)
        by_hour: dict[int, int] = defaultdict(int)
        attention = {"sampled_seconds": 0, "active_seconds": 0, "idle_seconds": 0,
                     "distraction_seconds": 0, "switch_count": 0, "sessions": 0}
        total_seconds = 0
        for item in sessions:
            seconds = int(item["elapsed_seconds"])
            total_seconds += seconds
            day = item["archive_date"]
            by_day[day]["seconds"] += seconds
            by_day[day]["sessions"] += 1
            by_task[item["task_title"]] += seconds
            by_domain[item["task_domain"]] += seconds
            by_project[item["project_name"]] += seconds
            by_mode[item["mode"]] += seconds
            by_weekday[date.fromisoformat(day).weekday()] += seconds
            by_hour[datetime.fromisoformat(item["started_at"]).astimezone().hour] += seconds
            sampled = sum(int(item.get(key) or 0) for key in
                          ("active_seconds", "idle_seconds", "distraction_seconds"))
            if item.get("habit_status") in {"completed", "cancelled"} and sampled:
                attention["sampled_seconds"] += sampled
                attention["sessions"] += 1
                for key in ("active_seconds", "idle_seconds", "distraction_seconds", "switch_count"):
                    attention[key] += int(item.get(key) or 0)
        active_dates = sorted(by_day)
        longest_streak = current_streak = 0
        previous: date | None = None
        for key in active_dates:
            current = date.fromisoformat(key)
            current_streak = current_streak + 1 if previous and current - previous == timedelta(days=1) else 1
            longest_streak = max(longest_streak, current_streak)
            previous = current
        def breakdown(source: dict[Any, int], label: str) -> list[dict[str, Any]]:
            return [{label: key, "seconds": value} for key, value in
                    sorted(source.items(), key=lambda pair: (-pair[1], str(pair[0])))]
        return {
            "start": start_date.isoformat(), "end": end_date.isoformat(),
            "basis": "专注会话结束日期；只统计已留档的实际计时时长，放弃且未记录的会话不计入",
            "summary": {
                "seconds": total_seconds, "session_count": len(sessions),
                "active_days": len(active_dates), "longest_streak_days": longest_streak,
                "average_seconds": round(total_seconds / len(sessions)) if sessions else 0,
                "longest_seconds": max((int(item["elapsed_seconds"]) for item in sessions), default=0),
                "pause_count": sum(int(item["pause_count"] or 0) for item in sessions),
                "partial_sessions": sum(item["status"] == "cancelled" for item in sessions),
            },
            "daily": [{"date": key, **by_day[key]} for key in active_dates],
            "by_task": breakdown(by_task, "name"),
            "by_domain": breakdown(by_domain, "domain"),
            "by_project": breakdown(by_project, "name"),
            "by_mode": breakdown(by_mode, "mode"),
            "by_weekday": [{"weekday": key, "seconds": by_weekday[key]} for key in range(7)],
            "by_hour": [{"hour": key, "seconds": by_hour[key]} for key in range(24)],
            "attention": attention,
            "recent_sessions": [{key: item[key] for key in
                                 ("id", "archive_date", "started_at", "ended_at", "task_title",
                                  "task_domain", "project_name", "mode", "status", "elapsed_seconds",
                                  "pause_count", "note")} for item in sessions[:80]],
            "recent_sessions_total": len(sessions),
        }
