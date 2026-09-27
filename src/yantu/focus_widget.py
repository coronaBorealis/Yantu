from __future__ import annotations

from pathlib import Path
from typing import Any

from .services.focus_service import FocusService
from .services.task_service import TaskService


def load_focus_widget_html() -> str:
    """Inline package assets so the floating window never needs a web server."""
    web_root = Path(__file__).resolve().parent / "web"
    html = (web_root / "focus-widget.html").read_text(encoding="utf-8")
    css = (web_root / "focus-widget.css").read_text(encoding="utf-8")
    script = (web_root / "focus-widget.js").read_text(encoding="utf-8")
    return html.replace(
        '<link rel="stylesheet" href="focus-widget.css">', f"<style>{css}</style>"
    ).replace(
        '<script src="focus-widget.js"></script>', f"<script>{script}</script>"
    )


class FocusWidgetBridge:
    """A desktop-only bridge; all timer changes still go through FocusService."""

    def __init__(self, focus: FocusService, tasks: TaskService) -> None:
        self.focus = focus
        self.tasks = tasks
        self.main_window: Any = None
        self.widget_window: Any = None

    def _bind_windows(self, main_window: Any, widget_window: Any) -> None:
        self.main_window = main_window
        self.widget_window = widget_window

    def snapshot(self) -> dict[str, Any]:
        session = self.focus.active()
        if not session:
            return {"active": False}
        task = self.tasks.get_record(str(session["task_id"])) if session.get("task_id") else None
        return {
            "active": True,
            "id": session["id"],
            "title": (task or {}).get("title") or "专注任务",
            "session_type": session["session_type"],
            "mode": session["mode"],
            "status": session["status"],
            "target_seconds": session["target_seconds"],
            "elapsed_seconds": session["elapsed_seconds"],
            "last_resumed_at": session.get("last_resumed_at"),
        }

    def show_widget(self) -> bool:
        if not self.widget_window or not self.focus.active():
            return False
        self.widget_window.show()
        return True

    def hide_widget(self) -> None:
        if self.widget_window:
            self.widget_window.hide()

    def toggle_pause(self) -> dict[str, Any]:
        session = self.focus.active()
        if not session:
            return {"active": False}
        if session["status"] == "running":
            self.focus.pause(str(session["id"]))
        elif session["status"] == "paused":
            self.focus.resume(str(session["id"]))
        else:
            raise ValueError("当前阶段需要在主工作台确认")
        return self.snapshot()

    def show_main(self) -> None:
        if self.main_window:
            self.main_window.show()
            self.main_window.restore()
            self.main_window.run_js("openFocus()")
