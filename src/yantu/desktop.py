from __future__ import annotations

import argparse
import ctypes
import os
import secrets
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from . import __version__
from .database.config import resolve_app_paths
from .main import create_app


APP_MUTEX_NAME = "Yantu-8EAA093B-3C62-4C9B-9555-A7DB272E35B3"
APP_USER_MODEL_ID = "Yantu.ResearchWorkbench"


def _message(title: str, text: str, *, error: bool = False) -> None:
    if os.name == "nt":
        flags = 0x10 if error else 0x40
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    else:
        print(f"{title}: {text}", file=sys.stderr if error else sys.stdout)


class SingleInstance:
    """A process-lifetime Windows mutex used by both the app and installer."""

    def __init__(self) -> None:
        self.handle: int | None = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
        if not handle:
            raise OSError("无法创建 Yantu 单实例锁")
        self.handle = int(handle)
        return kernel32.GetLastError() != 183

    def close(self) -> None:
        if self.handle and os.name == "nt":
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None

    def __enter__(self) -> "SingleInstance":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def _configure_windows_identity() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def smoke_test(data_dir: Path | None = None) -> int:
    context = tempfile.TemporaryDirectory(prefix="yantu-smoke-") if data_dir is None else None
    try:
        root = Path(context.name) if context else data_dir
        assert root is not None
        app = create_app(root / "yantu.db")
        app.config["INSTANCE_ID"] = "desktop-smoke"
        app.config["REQUEST_TOKEN"] = "desktop-smoke-token"
        client = app.test_client()
        health = client.get("/api/health")
        page = client.get("/")
        icon = client.get("/assets/logo-32.png")
        if health.status_code != 200 or page.status_code != 200 or icon.status_code != 200:
            return 1
        if "desktop-smoke-token" not in page.get_data(as_text=True):
            return 1
        # A frozen smoke test must also load the Windows renderer integration;
        # this catches missing CLR/WebView runtime DLLs before publishing.
        if getattr(sys, "frozen", False):
            import webview  # noqa: F401
            from webview.platforms import edgechromium  # noqa: F401
        return 0
    finally:
        if context:
            context.cleanup()


def run_desktop() -> int:
    _configure_windows_identity()
    paths = resolve_app_paths()
    paths.data_root.mkdir(parents=True, exist_ok=True)
    app = create_app(paths.database)
    app.config["INSTANCE_ID"] = str(uuid.uuid4())
    app.config["REQUEST_TOKEN"] = secrets.token_urlsafe(32)

    try:
        import webview
    except Exception as exc:
        _message("Yantu 启动失败", f"桌面运行组件无法加载：{exc}", error=True)
        return 1

    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    icon = Path(__file__).resolve().parent / "web" / "assets" / "yantu.ico"
    window = webview.create_window(
        "Yantu · 研途",
        app,
        width=1280,
        height=820,
        min_size=(390, 640),
        background_color="#132019",
        text_select=True,
        zoomable=True,
    )
    del window
    webview.start(
        debug=False,
        private_mode=False,
        storage_path=str(paths.data_root / "webview"),
        icon=str(icon),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yantu Windows desktop application")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.smoke_test:
        return smoke_test(args.data_dir)

    with SingleInstance() as instance:
        if not instance.acquire():
            _message("Yantu · 研途", "Yantu 已经在运行。请切换到现有窗口。")
            return 0
        try:
            return run_desktop()
        except Exception as exc:
            _message("Yantu 启动失败", str(exc), error=True)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
