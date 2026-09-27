from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from yantu.focus_widget import FocusWidgetBridge, load_focus_widget_html
from yantu.database.config import AppPaths


class FakeFocus:
    def __init__(self) -> None:
        self.session: dict[str, Any] | None = None
        self.calls: list[tuple[str, str]] = []

    def active(self) -> dict[str, Any] | None:
        return self.session

    def pause(self, session_id: str) -> None:
        self.calls.append(("pause", session_id))
        assert self.session is not None
        self.session["status"] = "paused"

    def resume(self, session_id: str) -> None:
        self.calls.append(("resume", session_id))
        assert self.session is not None
        self.session["status"] = "running"


class FakeTasks:
    def get_record(self, task_id: str) -> dict[str, str]:
        return {"title": f"阅读论文 {task_id}"}


class FakeWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def show(self) -> None:
        self.calls.append("show")

    def hide(self) -> None:
        self.calls.append("hide")

    def restore(self) -> None:
        self.calls.append("restore")

    def run_js(self, script: str) -> None:
        self.calls.append(script)


def test_widget_uses_services_and_never_starts_a_timer_implicitly() -> None:
    focus = FakeFocus()
    bridge = FocusWidgetBridge(focus, FakeTasks())  # type: ignore[arg-type]
    main, widget = FakeWindow(), FakeWindow()
    bridge._bind_windows(main, widget)
    assert bridge.snapshot() == {"active": False}
    assert bridge.show_widget() is False
    assert widget.calls == []

    focus.session = {
        "id": "focus-1", "task_id": "paper-1", "session_type": "focus",
        "mode": "pomodoro", "status": "running", "target_seconds": 1500,
        "elapsed_seconds": 120, "last_resumed_at": "2026-09-16T09:00:00+08:00",
    }
    assert bridge.show_widget() is True
    assert widget.calls == ["show"]
    assert bridge.snapshot()["title"] == "阅读论文 paper-1"
    assert bridge.toggle_pause()["status"] == "paused"
    assert bridge.toggle_pause()["status"] == "running"
    assert focus.calls == [("pause", "focus-1"), ("resume", "focus-1")]
    focus.session["status"] = "awaiting_action"
    with pytest.raises(ValueError, match="主工作台确认"):
        bridge.toggle_pause()
    bridge.show_main()
    assert main.calls == ["show", "restore", "openFocus()"]
    bridge.hide_widget()
    assert widget.calls[-1] == "hide"


def test_widget_assets_are_inlined_without_http_requests() -> None:
    html = load_focus_widget_html()
    assert '<link rel="stylesheet" href="focus-widget.css">' not in html
    assert '<script src="focus-widget.js"></script>' not in html
    assert "window.pywebview.api.snapshot" in html
    assert "pywebview-drag-region" not in html


def test_desktop_creates_hidden_independent_always_on_top_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yantu import desktop

    windows: list[dict[str, Any]] = []

    def create_window(_title: str, _content: Any = None, **kwargs: Any) -> FakeWindow:
        windows.append(kwargs)
        return FakeWindow()

    fake_webview = SimpleNamespace(
        settings={}, create_window=create_window, start=lambda **_kwargs: None,
        screens=[SimpleNamespace(x=0, y=0, width=1920, height=1080)],
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop, "_configure_windows_identity", lambda: None)
    monkeypatch.setattr(desktop, "_primary_work_area", lambda _screen: (0, 0, 1920, 1080))
    monkeypatch.setattr(
        desktop, "resolve_app_paths",
        lambda: AppPaths(resource_root=tmp_path, data_root=tmp_path / "本地数据"),
    )
    assert desktop.run_desktop() == 0
    assert len(windows) == 2
    assert windows[0]["js_api"] is windows[1]["js_api"]
    assert windows[1]["hidden"] is True
    assert windows[1]["frameless"] is True
    assert windows[1]["on_top"] is True
    assert windows[1]["resizable"] is False
    assert windows[1]["easy_drag"] is False
    assert (windows[1]["x"], windows[1]["y"]) == (1674, 826)
    assert "focus-widget.js" not in windows[1]["html"]


def test_widget_position_uses_work_area_not_taskbar_space() -> None:
    from yantu.desktop import _focus_widget_position

    assert _focus_widget_position((0, 0, 1920, 1040)) == (1674, 786)
    assert _focus_widget_position((0, 0, 300, 300)) == (54, 46)
