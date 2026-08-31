from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ActivitySnapshot:
    """Privacy-preserving activity signal; it never contains input content."""

    process_name: str
    idle_seconds: float


class ActivityProbe:
    def capability(self) -> dict[str, object]:
        raise NotImplementedError

    def snapshot(self) -> ActivitySnapshot:
        raise NotImplementedError


class WindowsActivityProbe(ActivityProbe):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    def capability(self) -> dict[str, object]:
        if os.name != "nt":
            return {
                "available": False,
                "platform": os.name,
                "reason": "应用活动监测目前仅支持 Windows 桌面版",
            }
        return {"available": True, "platform": "windows", "reason": ""}

    def snapshot(self) -> ActivitySnapshot:
        capability = self.capability()
        if not capability["available"]:
            raise RuntimeError(str(capability["reason"]))
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)
        ]

        info = self.LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            raise OSError("无法读取 Windows 活跃状态")
        # LASTINPUTINFO uses the 32-bit tick counter and wraps roughly every
        # 49.7 days, so keep the subtraction in the same unsigned domain.
        now_tick = int(kernel32.GetTickCount()) & 0xFFFFFFFF
        idle_ms = (now_tick - int(info.dwTime)) & 0xFFFFFFFF

        window = user32.GetForegroundWindow()
        if not window:
            return ActivitySnapshot("unknown", idle_ms / 1000.0)
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        handle = kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value
        )
        if not handle:
            return ActivitySnapshot("unknown", idle_ms / 1000.0)
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return ActivitySnapshot("unknown", idle_ms / 1000.0)
            process_name = Path(buffer.value).name.lower() or "unknown"
            return ActivitySnapshot(process_name, idle_ms / 1000.0)
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))


def default_activity_probe() -> ActivityProbe:
    return WindowsActivityProbe()
