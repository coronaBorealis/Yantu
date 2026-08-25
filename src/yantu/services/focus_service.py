from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from ..common import utc_now
from ..database.repositories import FocusRepository, PlanningRepository, TaskRepository
from .settings_service import SettingsService


class FocusService:
    def __init__(
        self, db_path: Path | str, *, now: Callable[[], datetime] | None = None,
        settings: SettingsService | None = None,
    ) -> None:
        self.repository = FocusRepository(db_path)
        self.tasks = TaskRepository(db_path)
        self.planning = PlanningRepository(db_path)
        self.settings = settings or SettingsService(db_path)
        self._now = now or (lambda: datetime.now().astimezone())

    def active(self) -> dict[str, Any] | None:
        session = self.repository.active()
        return self._reconcile(session) if session else None

    def start(self, values: Mapping[str, Any]) -> dict[str, Any]:
        if self.active():
            raise ValueError("已有正在进行的专注或休息")
        session_type = str(values.get("session_type") or "focus")
        if session_type not in {"focus", "short_break", "long_break"}:
            raise ValueError("无效的会话类型")
        mode = str(values.get("mode") or "pomodoro")
        if mode not in {"pomodoro", "free"}:
            raise ValueError("无效的计时方式")
        task_id = str(values.get("task_id") or "") or None
        if session_type == "focus" and (not task_id or not self.tasks.get(task_id)):
            raise ValueError("请选择有效任务")
        plan_block_id = str(values.get("plan_block_id") or "") or None
        if plan_block_id:
            block = self.repository.get_plan_block(plan_block_id)
            if not block or block.get("task_id") != task_id or block.get("block_type") != "focus":
                raise ValueError("规划时间块与任务不匹配")
        target = self._seconds(values.get("target_seconds", 0), allow_zero=mode == "free")
        if mode == "pomodoro" and target < 60:
            raise ValueError("倒计时至少为 1 分钟")
        now = self._now().isoformat()
        return self.repository.create({
            "id": str(uuid.uuid4()), "task_id": task_id, "plan_block_id": plan_block_id,
            "parent_session_id": values.get("parent_session_id"), "session_type": session_type,
            "mode": mode, "status": "running", "target_seconds": target,
            "elapsed_seconds": 0, "paused_seconds": 0, "pause_count": 0,
            "started_at": now, "last_resumed_at": now, "ended_at": None,
            "time_entry_id": None, "note": str(values.get("note") or "").strip(),
            "created_at": now, "updated_at": now,
        })

    def pause(self, session_id: str) -> dict[str, Any]:
        session = self._required(session_id)
        if session["status"] != "running":
            raise ValueError("只有运行中的会话可以暂停")
        elapsed = self._effective_elapsed(session)
        now = self._now().isoformat()
        result = self.repository.update(session_id, {
            "status": "paused", "elapsed_seconds": elapsed, "last_resumed_at": None,
            "pause_count": int(session["pause_count"]) + 1, "updated_at": now,
        })
        assert result is not None
        return result

    def resume(self, session_id: str) -> dict[str, Any]:
        session = self._required(session_id)
        if session["status"] != "paused":
            raise ValueError("只有暂停中的会话可以继续")
        now_dt = self._now()
        paused = max(0, int((now_dt - datetime.fromisoformat(session["updated_at"])).total_seconds()))
        result = self.repository.update(session_id, {
            "status": "running", "last_resumed_at": now_dt.isoformat(),
            "paused_seconds": int(session["paused_seconds"]) + paused,
            "updated_at": now_dt.isoformat(),
        })
        assert result is not None
        return result

    def complete(self, session_id: str) -> dict[str, Any]:
        session = self._required(session_id)
        if session["status"] == "completed":
            return {"session": session, "next_session": None}
        if session["status"] == "cancelled":
            raise ValueError("已放弃的专注会话不能完成")
        elapsed = self._effective_elapsed(session)
        if session["mode"] == "pomodoro":
            elapsed = min(elapsed, int(session["target_seconds"]))
        now = self._now().isoformat()
        entry = self._time_entry(session, elapsed, now) if session["session_type"] == "focus" and elapsed > 0 else None
        next_session = self._break_after(session, now) if entry else None
        result = self.repository.finish(
            session_id, elapsed_seconds=elapsed, ended_at=now, updated_at=now,
            final_status="completed", time_entry=entry, break_session=next_session,
        )
        return {"session": result, "next_session": self.repository.active() if next_session else None}

    def cancel(self, session_id: str, *, record_partial: bool = False) -> dict[str, Any]:
        session = self._required(session_id)
        if session["status"] == "cancelled":
            return session
        elapsed = self._effective_elapsed(session)
        now = self._now().isoformat()
        entry = self._time_entry(session, elapsed, now) if record_partial and session["session_type"] == "focus" and elapsed > 0 else None
        return self.repository.finish(
            session_id, elapsed_seconds=elapsed, ended_at=now, updated_at=now,
            final_status="cancelled", time_entry=entry, break_session=None,
        )

    def history(self, *, start: Any = None, end: Any = None, task_id: str | None = None) -> list[dict[str, Any]]:
        return self.repository.history(
            start=self._boundary(start), end=self._boundary(end, end=True), task_id=task_id,
            finished_only=True,
        )

    def stats(self, *, start: Any = None, end: Any = None) -> dict[str, Any]:
        start_date = date.fromisoformat(str(start)) if start else date.today() - timedelta(days=6)
        end_date = date.fromisoformat(str(end)) if end else date.today()
        if end_date < start_date:
            raise ValueError("结束日期不能早于开始日期")
        sessions = self.repository.history(
            start=datetime.combine(start_date, time.min).astimezone().isoformat(),
            end=datetime.combine(end_date + timedelta(days=1), time.min).astimezone().isoformat(),
            finished_only=True,
        )
        focus = [
            item for item in sessions
            if item["session_type"] == "focus"
            and int(item.get("elapsed_seconds") or 0) > 0
            and (item["status"] == "completed" or item.get("time_entry_id"))
        ]
        by_day_seconds: dict[str, int] = defaultdict(int)
        by_task_seconds: dict[str, int] = defaultdict(int)
        by_domain_seconds: dict[str, int] = defaultdict(int)
        for item in focus:
            seconds = int(item["elapsed_seconds"])
            for day, share in self._split_by_day(item, seconds).items():
                by_day_seconds[day] += share
            by_task_seconds[str(item.get("task_title") or "已删除任务")] += seconds
            by_domain_seconds[str(item.get("task_domain") or "unknown")] += seconds
        by_day = {key: max(1, round(value / 60)) for key, value in by_day_seconds.items()}
        by_task = {key: max(1, round(value / 60)) for key, value in by_task_seconds.items()}
        by_domain = {key: max(1, round(value / 60)) for key, value in by_domain_seconds.items()}
        tasks = self.tasks.list()
        estimated = sum(int(item.get("estimated_minutes") or 0) for item in tasks)
        actual = sum(int(item.get("actual_minutes") or 0) for item in tasks)
        planned = [item for item in focus if item.get("plan_block_id")]
        completed_planned = 0
        for item in planned:
            block = self.repository.get_plan_block(str(item["plan_block_id"]))
            if block and block.get("status") == "completed":
                completed_planned += 1
        return {
            "start": start_date.isoformat(), "end": end_date.isoformat(),
            "focus_minutes": sum(by_day.values()), "completed_sessions": len(focus),
            "pomodoros": sum(1 for item in focus if item["mode"] == "pomodoro"),
            "pause_count": sum(int(item["pause_count"]) for item in focus),
            "plan_completion_rate": round(completed_planned / len(planned) * 100) if planned else 0,
            "estimated_minutes": estimated, "actual_minutes": actual,
            "estimate_variance_minutes": actual - estimated,
            "actual_to_estimated_ratio": round(actual / estimated, 2) if estimated else None,
            "by_day": [{"date": key, "minutes": by_day[key]} for key in sorted(by_day)],
            "by_task": [{"name": key, "minutes": value} for key, value in sorted(by_task.items(), key=lambda pair: -pair[1])],
            "by_domain": [{"domain": key, "minutes": value} for key, value in sorted(by_domain.items())],
        }

    @staticmethod
    def _split_by_day(session: Mapping[str, Any], elapsed_seconds: int) -> dict[str, int]:
        """Allocate effective work across local dates without counting paused wall time twice."""
        start = datetime.fromisoformat(str(session["started_at"]))
        end_value = session.get("ended_at") or session["started_at"]
        end = max(start, datetime.fromisoformat(str(end_value)).astimezone(start.tzinfo))
        wall_seconds = max(1, int((end - start).total_seconds()))
        spans: list[tuple[str, int]] = []
        cursor = start
        while cursor.date() < end.date():
            boundary = datetime.combine(cursor.date() + timedelta(days=1), time.min, cursor.tzinfo)
            spans.append((cursor.date().isoformat(), max(0, int((boundary - cursor).total_seconds()))))
            cursor = boundary
        spans.append((cursor.date().isoformat(), max(0, int((end - cursor).total_seconds()))))
        allocated: dict[str, int] = {}
        remaining = elapsed_seconds
        for index, (day, span) in enumerate(spans):
            share = remaining if index == len(spans) - 1 else min(remaining, round(elapsed_seconds * span / wall_seconds))
            allocated[day] = allocated.get(day, 0) + share
            remaining -= share
        return allocated

    def export_backup(self) -> list[dict[str, Any]]:
        records = self.repository.history(finished_only=True)
        return [{**item, "time_entry_id": None, "plan_block_id": None} for item in records]

    def import_backup(self, values: Any) -> int:
        return self.repository.import_finished(values if isinstance(values, list) else [])

    def _reconcile(self, session: dict[str, Any]) -> dict[str, Any]:
        if session["status"] != "running" or session["mode"] == "free":
            return session
        elapsed = self._effective_elapsed(session)
        target = int(session["target_seconds"])
        if elapsed < target:
            session["effective_elapsed_seconds"] = elapsed
            return session
        now = self._now().isoformat()
        result = self.repository.update(session["id"], {
            "status": "awaiting_action", "elapsed_seconds": target,
            "last_resumed_at": None, "updated_at": now,
        })
        assert result is not None
        return result

    def _required(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get(session_id)
        if not session:
            raise ValueError("专注会话不存在")
        return self._reconcile(session)

    def _effective_elapsed(self, session: Mapping[str, Any]) -> int:
        elapsed = int(session.get("elapsed_seconds") or 0)
        if session.get("status") == "running" and session.get("last_resumed_at"):
            elapsed += max(0, int((self._now() - datetime.fromisoformat(str(session["last_resumed_at"]))).total_seconds()))
        return elapsed

    def _time_entry(self, session: Mapping[str, Any], seconds: int, ended_at: str) -> dict[str, Any]:
        minutes = max(1, int(math.floor(seconds / 60 + 0.5)))
        return {
            "id": str(uuid.uuid4()), "task_id": session["task_id"],
            "start_time": session["started_at"], "end_time": ended_at,
            "duration": minutes,
            "note": f"{'番茄专注' if session['mode'] == 'pomodoro' else '自由专注'} · {minutes} 分钟",
            "created_at": ended_at,
        }

    def _break_after(self, session: Mapping[str, Any], now: str) -> dict[str, Any] | None:
        preferences = self.settings.get_preferences()
        if not preferences["auto_start_break"] or session["mode"] != "pomodoro":
            return None
        profile = self.planning.get_profile()
        history = self.repository.history(finished_only=True)
        cycle = 1
        for item in history:
            if item["session_type"] == "long_break" and item["status"] == "completed":
                break
            if item["session_type"] == "focus" and item["mode"] == "pomodoro" and item["status"] == "completed":
                cycle += 1
        long_break = cycle % int(profile["long_break_after"]) == 0
        minutes = int(profile["long_break_minutes"] if long_break else profile["short_break_minutes"])
        return {
            "id": str(uuid.uuid4()), "task_id": None, "plan_block_id": None,
            "parent_session_id": session["id"], "session_type": "long_break" if long_break else "short_break",
            "mode": "pomodoro", "status": "running", "target_seconds": minutes * 60,
            "elapsed_seconds": 0, "paused_seconds": 0, "pause_count": 0,
            "started_at": now, "last_resumed_at": now, "ended_at": None,
            "time_entry_id": None, "note": "专注后的主动恢复", "created_at": now, "updated_at": now,
        }

    @staticmethod
    def _seconds(value: Any, *, allow_zero: bool) -> int:
        try:
            seconds = int(value or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("target_seconds 必须是整数") from exc
        if seconds < 0 or (seconds == 0 and not allow_zero) or seconds > 12 * 3600:
            raise ValueError("target_seconds 超出允许范围")
        return seconds

    @staticmethod
    def _boundary(value: Any, *, end: bool = False) -> str | None:
        if not value:
            return None
        try:
            parsed = date.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError("日期必须使用 YYYY-MM-DD") from exc
        if end:
            parsed += timedelta(days=1)
        return datetime.combine(parsed, time.min).astimezone().isoformat()
