from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from ..database.repositories import FocusHabitRepository, FocusRepository
from .activity_probe import ActivityProbe, default_activity_probe


APP_NAME = re.compile(r"^[^\\/:*?\"<>|\r\n]{1,120}$")


class FocusHabitService:
    """Aggregate foreground-app activity without collecting input content."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        probe: ActivityProbe | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = FocusHabitRepository(db_path)
        self.focus = FocusRepository(db_path)
        self.probe = probe or default_activity_probe()
        self._now = now or (lambda: datetime.now().astimezone())

    def capability(self) -> dict[str, object]:
        return {
            **self.probe.capability(),
            "privacy": {
                "collects": ["前台应用进程名", "活跃/空闲聚合时长", "应用切换次数"],
                "never_collects": ["按键内容", "鼠标坐标", "窗口标题", "网址", "截图", "文档路径"],
            },
        }

    def list_profiles(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        return self.repository.profiles(include_disabled=include_disabled)

    def get_profile(self, profile_id: str, *, require_enabled: bool = True) -> dict[str, Any]:
        profile = self.repository.profile(profile_id)
        if not profile or (require_enabled and not profile["enabled"]):
            raise ValueError("专注习惯方案不存在或已停用")
        return profile

    def save_profile(self, values: Mapping[str, Any], profile_id: str | None = None) -> dict[str, Any]:
        existing = self.repository.profile(profile_id) if profile_id else None
        if profile_id and not existing:
            raise ValueError("专注习惯方案不存在")
        name = str(values.get("name", existing["name"] if existing else "")).strip()
        if not name or len(name) > 60:
            raise ValueError("方案名称长度必须为 1–60 个字符")
        apps_source = values.get("allowed_apps", existing["allowed_apps"] if existing else [])
        if isinstance(apps_source, str):
            apps_source = apps_source.split(",")
        if not isinstance(apps_source, list):
            raise ValueError("目标应用必须是列表")
        apps: list[str] = []
        for value in apps_source:
            app = str(value).strip().lower()
            if not app:
                continue
            if not APP_NAME.fullmatch(app):
                raise ValueError(f"无效的应用进程名：{app}")
            if app not in apps:
                apps.append(app)
        if not 1 <= len(apps) <= 20:
            raise ValueError("每个方案需设置 1–20 个目标应用")
        idle = self._bounded_int(values.get("idle_threshold_seconds", existing["idle_threshold_seconds"] if existing else 60), 15, 600, "空闲阈值")
        warning = self._bounded_int(values.get("switch_warning_count", existing["switch_warning_count"] if existing else 8), 1, 100, "切换提醒次数")
        now = self._now().isoformat()
        return self.repository.save_profile({
            "id": profile_id or str(uuid.uuid4()),
            "name": name,
            "allowed_apps_json": json.dumps(apps, ensure_ascii=False),
            "idle_threshold_seconds": idle,
            "switch_warning_count": warning,
            "enabled": int(bool(values.get("enabled", True))),
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        })

    def disable_profile(self, profile_id: str) -> bool:
        return self.repository.disable_profile(profile_id, self._now().isoformat())

    def validate_profile(self, profile_id: str | None) -> dict[str, Any] | None:
        return self.get_profile(profile_id) if profile_id else None

    def start_session(
        self, session_id: str, profile: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Start either a profile-filtered session or privacy-safe basic tracking."""
        now = self._now().isoformat()
        capability = self.probe.capability()
        available = bool(capability.get("available"))
        profile_id = str(profile["id"]) if profile else None
        profile_name = str(profile["name"]) if profile else "基础前台应用记录"
        allowed_apps = list(profile["allowed_apps"]) if profile else []
        return self.repository.start_tracking({
            "session_id": session_id,
            "profile_id": profile_id,
            "profile_name": profile_name,
            "allowed_apps_json": json.dumps(allowed_apps, ensure_ascii=False),
            "idle_threshold_seconds": int(profile["idle_threshold_seconds"]) if profile else 60,
            "switch_warning_count": int(profile["switch_warning_count"]) if profile else 8,
            "status": "monitoring" if available else "unavailable",
            "platform": str(capability.get("platform") or ""),
            "last_sampled_at": now,
            "started_at": now,
            "unavailable_reason": "" if available else str(capability.get("reason") or "监测不可用"),
        })

    def session(self, session_id: str) -> dict[str, Any] | None:
        return self.repository.session(session_id)

    def current_app(self) -> dict[str, Any]:
        capability = self.probe.capability()
        if not capability.get("available"):
            raise ValueError(str(capability.get("reason") or "应用活动监测不可用"))
        snapshot = self.probe.snapshot()
        return {"process_name": snapshot.process_name, "idle_seconds": round(snapshot.idle_seconds, 1)}

    def sample_session(self, session_id: str) -> dict[str, Any] | None:
        habit = self.repository.session(session_id)
        if not habit or habit["status"] != "monitoring":
            return habit
        now_dt = self._now()
        now = now_dt.isoformat()
        focus = self.focus.get(session_id)
        if focus and focus["status"] in {"completed", "cancelled"}:
            return self.repository.finish(
                session_id,
                status="cancelled" if focus["status"] == "cancelled" else "completed",
                ended_at=str(focus.get("ended_at") or now),
            )
        if not focus or focus["status"] != "running":
            self.repository.touch(session_id, now)
            return self.repository.session(session_id)
        last = datetime.fromisoformat(str(habit["last_sampled_at"]))
        delta = max(0, min(30, int((now_dt - last).total_seconds())))
        if delta <= 0:
            return habit
        try:
            snapshot = self.probe.snapshot()
        except Exception as exc:
            return self.repository.unavailable(session_id, reason=str(exc), sampled_at=now)
        process_name = str(snapshot.process_name or "unknown").strip().lower()[:120]
        allowed = set(habit["allowed_apps"])
        observes_all_apps = not habit.get("profile_id")
        is_allowed = observes_all_apps or process_name in allowed
        is_idle = snapshot.idle_seconds > int(habit["idle_threshold_seconds"])
        previous = str(habit.get("last_process_name") or "")
        switched = not is_idle and bool(previous) and previous != process_name
        violation = (
            not observes_all_apps
            and not is_idle
            and not is_allowed
            and previous != process_name
        )
        return self.repository.add_sample(
            session_id,
            process_name=process_name,
            is_allowed=is_allowed,
            active_seconds=delta if not is_idle and is_allowed else 0,
            idle_seconds=delta if is_idle else 0,
            distraction_seconds=delta if not is_idle and not is_allowed else 0,
            switched=switched,
            violation=violation,
            sampled_at=now,
        )

    def sample_active(self) -> None:
        for session_id in self.repository.monitoring_ids():
            self.sample_session(session_id)

    def reset_anchor(self, session_id: str) -> None:
        if self.repository.session(session_id):
            self.repository.touch(session_id, self._now().isoformat())

    def stats(self, *, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        try:
            end_date = date.fromisoformat(end) if end else date.today()
            start_date = date.fromisoformat(start) if start else end_date - timedelta(days=27)
        except ValueError as exc:
            raise ValueError("日期必须使用 YYYY-MM-DD") from exc
        if end_date < start_date:
            raise ValueError("结束日期不能早于开始日期")
        start_at = datetime.combine(start_date, time.min).astimezone().isoformat()
        end_at = datetime.combine(end_date + timedelta(days=1), time.min).astimezone().isoformat()
        sessions, apps = self.repository.completed_between(start_at, end_at)
        allowed = sum(int(item["active_seconds"]) for item in sessions)
        idle = sum(int(item["idle_seconds"]) for item in sessions)
        distraction = sum(int(item["distraction_seconds"]) for item in sessions)
        total = allowed + idle + distraction
        days = sorted({str(item["started_at"])[:10] for item in sessions if int(item["active_seconds"]) > 0})
        streak = 0
        cursor = end_date
        day_set = set(days)
        if cursor.isoformat() not in day_set:
            cursor -= timedelta(days=1)
        while cursor.isoformat() in day_set:
            streak += 1
            cursor -= timedelta(days=1)
        return {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "completed_sessions": len(sessions),
            "active_seconds": allowed,
            "idle_seconds": idle,
            "distraction_seconds": distraction,
            "quality_score": round(allowed / total * 100) if total else None,
            "study_days": len(days),
            "current_streak_days": streak,
            "switch_count": sum(int(item["switch_count"]) for item in sessions),
            "apps": [{**item, "is_allowed": bool(item["is_allowed"])} for item in apps],
        }

    def finish_session(self, session_id: str, *, cancelled: bool = False) -> dict[str, Any] | None:
        self.sample_session(session_id)
        return self.repository.finish(
            session_id,
            status="cancelled" if cancelled else "completed",
            ended_at=self._now().isoformat(),
        )

    def export_backup(self) -> dict[str, Any]:
        return self.repository.export_backup()

    def import_backup(self, payload: Any) -> dict[str, int]:
        return self.repository.import_backup(payload)

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须是整数") from exc
        if not minimum <= result <= maximum:
            raise ValueError(f"{label}必须在 {minimum}–{maximum} 之间")
        return result


class FocusHabitMonitor:
    def __init__(self, service: FocusHabitService, *, interval_seconds: float = 5.0) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="yantu-focus-habit", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval_seconds + 1)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.service.sample_active()
            except Exception:
                # Monitoring is an optional aid and must never terminate the timer.
                continue
