from __future__ import annotations

import base64
import binascii
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..common import utc_now
from ..database.repositories.appearance_repository import AppearanceRepository


MAX_BACKGROUND_BYTES = 8 * 1024 * 1024
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
PRESETS = {"forest", "paper", "mist", "night"}
MODES = {"system", "light", "dark"}
BACKGROUND_TYPES = {"none", "solid", "gradient", "image"}
MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
DEFAULT_APPEARANCE: dict[str, Any] = {
    "version": 1,
    "preset": "forest",
    "mode": "system",
    "background": {
        "type": "none",
        "color": "#e8eee8",
        "gradient_start": "#e5efe8",
        "gradient_end": "#dbe7ee",
        "gradient_angle": 135,
    },
    "surface_opacity": 0.92,
}


class AppearanceService:
    def __init__(self, config_path: Path | str, background_dir: Path | str) -> None:
        self.repository = AppearanceRepository(config_path, background_dir)

    def get(self) -> dict[str, Any]:
        stored = self.repository.read()
        try:
            settings = self.validate(stored or DEFAULT_APPEARANCE)
        except ValueError:
            settings = deepcopy(DEFAULT_APPEARANCE)
        return self._public(settings)

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.validate(payload)
        settings["updated_at"] = utc_now()
        self.repository.write(settings)
        return self._public(settings)

    def validate(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("外观设置必须是 JSON 对象")
        preset = str(payload.get("preset", DEFAULT_APPEARANCE["preset"]))
        mode = str(payload.get("mode", DEFAULT_APPEARANCE["mode"]))
        if preset not in PRESETS:
            raise ValueError("未知的主题预设")
        if mode not in MODES:
            raise ValueError("显示模式必须是 system、light 或 dark")
        source_background = payload.get("background", DEFAULT_APPEARANCE["background"])
        if not isinstance(source_background, dict):
            raise ValueError("背景设置必须是对象")
        background_type = str(source_background.get("type", "none"))
        if background_type not in BACKGROUND_TYPES:
            raise ValueError("不支持的背景类型")
        background = {
            "type": background_type,
            "color": self._color(source_background.get("color", "#e8eee8")),
            "gradient_start": self._color(source_background.get("gradient_start", "#e5efe8")),
            "gradient_end": self._color(source_background.get("gradient_end", "#dbe7ee")),
            "gradient_angle": self._number(source_background.get("gradient_angle", 135), 0, 360, "渐变角度"),
        }
        opacity = self._number(payload.get("surface_opacity", 0.92), 0.84, 0.98, "面板不透明度")
        result = {
            "version": 1,
            "preset": preset,
            "mode": mode,
            "background": background,
            "surface_opacity": opacity,
        }
        if payload.get("updated_at"):
            result["updated_at"] = str(payload["updated_at"])
        return result

    def save_background(self, filename: str, mime_type: str, content: bytes) -> dict[str, Any]:
        if not content:
            raise ValueError("背景图片不能为空")
        if len(content) > MAX_BACKGROUND_BYTES:
            raise ValueError("背景图片不能超过 8 MB")
        extension = Path(filename or "").suffix.lower()
        if extension == ".jpeg":
            extension = ".jpg"
        expected = MIME_EXTENSIONS.get(mime_type.lower())
        if expected is None or extension != expected:
            raise ValueError("仅支持 PNG、JPG 和 WebP 图片")
        detected = self._detect_image(content)
        if detected != extension:
            raise ValueError("图片内容与文件类型不一致")
        path = self.repository.write_background(content, extension)
        current = self.get()
        current["background"]["type"] = "image"
        saved = self.save(current)
        saved["background_mime"] = mime_type
        saved["background_size"] = path.stat().st_size
        return saved

    def delete_background(self) -> dict[str, Any]:
        self.repository.delete_background()
        current = self.get()
        if current["background"]["type"] == "image":
            current["background"]["type"] = "none"
            current = self.save(current)
        return current

    def background_path(self) -> Path | None:
        return self.repository.background()

    def export_backup(self, include_image: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {"settings": self.get()}
        background = self.background_path()
        if include_image and background:
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[background.suffix]
            payload["background"] = {
                "mime_type": mime,
                "data_base64": base64.b64encode(background.read_bytes()).decode("ascii"),
            }
        return payload

    def import_backup(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("外观备份必须是对象")
        settings = self.save(payload.get("settings") or payload)
        encoded = payload.get("background")
        if isinstance(encoded, dict) and encoded.get("data_base64"):
            try:
                content = base64.b64decode(str(encoded["data_base64"]), validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValueError("背景图片 Base64 无效") from error
            mime = str(encoded.get("mime_type", ""))
            extension = MIME_EXTENSIONS.get(mime)
            if not extension:
                raise ValueError("备份中的背景图片类型无效")
            settings = self.save_background(f"background{extension}", mime, content)
        return settings

    def _public(self, settings: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(settings)
        background = self.repository.background()
        result["has_background_image"] = bool(background)
        if background:
            result["background_url"] = f"/api/appearance/background?v={background.stat().st_mtime_ns}"
        else:
            result["background_url"] = None
        return result

    @staticmethod
    def _color(value: Any) -> str:
        color = str(value)
        if not HEX_COLOR.fullmatch(color):
            raise ValueError("颜色必须使用 #RRGGBB 格式")
        return color.lower()

    @staticmethod
    def _number(value: Any, minimum: float, maximum: float, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label}必须是数字") from error
        if not minimum <= number <= maximum:
            raise ValueError(f"{label}必须在 {minimum} 到 {maximum} 之间")
        return round(number, 3)

    @staticmethod
    def _detect_image(content: bytes) -> str | None:
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if content.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return ".webp"
        return None
