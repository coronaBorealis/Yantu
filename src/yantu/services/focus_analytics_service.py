from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..database.repositories.focus_analytics_repository import FocusAnalyticsRepository


class FocusAnalyticsService:
    """Read archived focus sessions from SQLite for both web and desktop clients."""

    def __init__(self, db_path: Path | str) -> None:
        self.repository = FocusAnalyticsRepository(db_path)

    def report(self, *, start: str | None = None, end: str | None = None,
               theme_id: str | None = None, task_id: str | None = None) -> dict[str, Any]:
        try:
            start_date = date.fromisoformat(start) if start else date.today() - timedelta(days=27)
            end_date = date.fromisoformat(end) if end else date.today()
        except (TypeError, ValueError) as exc:
            raise ValueError("日期格式应为 YYYY-MM-DD") from exc
        if end_date < start_date:
            raise ValueError("结束日期不能早于开始日期")
        if end_date > date.today():
            raise ValueError("结束日期不能晚于今天")
        tasks = {item["id"]: item for item in self.repository.tasks()}
        if theme_id and (theme_id not in tasks or not tasks[theme_id]["is_theme"]):
            raise ValueError("长期主题不存在")
        if task_id and task_id not in tasks:
            raise ValueError("子任务不存在")

        def theme_for(identifier: str | None) -> str | None:
            visited: set[str] = set()
            while identifier and identifier not in visited:
                visited.add(identifier)
                task = tasks.get(identifier)
                if not task:
                    break
                if task["is_theme"]:
                    return identifier
                identifier = task["parent_task_id"] or task["parent_id"]
            return None

        rows = self.repository.sessions()
        sessions = []
        for row in rows:
            item = dict(row)
            if not item["ended_at"]:
                continue
            ended_day = datetime.fromisoformat(item["ended_at"]).astimezone().date()
            if start_date <= ended_day <= end_date:
                item["theme_id"] = theme_for(item["task_id"])
                if theme_id and item["theme_id"] != theme_id:
                    continue
                if task_id and item["task_id"] != task_id:
                    continue
                item["theme_title"] = tasks[item["theme_id"]]["title"] if item["theme_id"] else "未归属长期主题"
                item["archive_date"] = ended_day.isoformat()
                sessions.append(item)

        by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"seconds": 0, "sessions": 0})
        by_task: dict[str, int] = defaultdict(int)
        by_domain: dict[str, int] = defaultdict(int)
        by_project: dict[str, int] = defaultdict(int)
        by_theme: dict[str, int] = defaultdict(int)
        by_subtask: dict[str, int] = defaultdict(int)
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
            by_theme[item["theme_id"] or ""] += seconds
            by_subtask[item["task_id"] or f"deleted:{item['task_title']}"] += seconds
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
        apps: dict[str, dict[str, int]] = defaultdict(lambda: {"active_seconds": 0, "idle_seconds": 0, "total_seconds": 0})
        monitored_ids: set[str] = set()
        for usage in self.repository.app_usage([str(item["id"]) for item in sessions]):
            name = str(usage["process_name"])
            active = int(usage["active_seconds"] or 0)
            idle = int(usage["idle_seconds"] or 0)
            apps[name]["active_seconds"] += active
            apps[name]["idle_seconds"] += idle
            apps[name]["total_seconds"] += active + idle
            monitored_ids.add(str(usage["session_id"]))
        app_sample_seconds = sum(item["total_seconds"] for item in apps.values())
        theme_choices = sorted(({"id": item["id"], "title": item["title"]} for item in tasks.values()
                                if item["is_theme"] and not item["deleted_at"]), key=lambda item: item["title"])
        subtask_choices = sorted(({"id": item["id"], "title": item["title"]} for item in tasks.values()
                                  if not item["is_theme"] and not item["deleted_at"]
                                  and (not theme_id or theme_for(item["id"]) == theme_id)), key=lambda item: item["title"])
        theme_breakdown = [{"id": key or None, "name": tasks[key]["title"] if key else "未归属长期主题",
                            "seconds": value} for key, value in
                           sorted(by_theme.items(), key=lambda pair: (-pair[1], pair[0]))]
        subtask_breakdown = [{"id": key if key in tasks else None,
                              "name": tasks[key]["title"] if key in tasks else key.removeprefix("deleted:"),
                              "seconds": value} for key, value in
                             sorted(by_subtask.items(), key=lambda pair: (-pair[1], pair[0]))]
        return {
            "start": start_date.isoformat(), "end": end_date.isoformat(),
            "filters": {"theme_id": theme_id, "task_id": task_id},
            "themes": theme_choices, "subtasks": subtask_choices,
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
            "by_theme": theme_breakdown,
            "by_subtask": subtask_breakdown,
            "by_mode": breakdown(by_mode, "mode"),
            "by_weekday": [{"weekday": key, "seconds": by_weekday[key]} for key in range(7)],
            "by_hour": [{"hour": key, "seconds": by_hour[key]} for key in range(24)],
            "attention": attention,
            "apps": [{"process_name": name, **values} for name, values in
                     sorted(apps.items(), key=lambda pair: (-pair[1]["total_seconds"], pair[0]))],
            "app_coverage": {"monitored_sessions": len(monitored_ids), "total_sessions": len(sessions),
                             "sampled_seconds": app_sample_seconds,
                             "unmonitored_seconds": max(0, total_seconds - app_sample_seconds)},
            "recent_sessions": [{key: item[key] for key in
                                 ("id", "archive_date", "started_at", "ended_at", "task_title",
                                  "task_domain", "project_name", "theme_title", "mode", "status", "elapsed_seconds",
                                  "pause_count", "note")} for item in sessions[:80]],
            "recent_sessions_total": len(sessions),
        }
