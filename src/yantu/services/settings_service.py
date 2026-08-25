from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from ..common import utc_now
from ..database.config import REPOSITORY_ROOT
from ..database.repositories import SettingsRepository


SERVICE_NAME = "Yantu"
CREDENTIAL_ACCOUNT = "deepseek:default"
PREFERENCE_DEFAULTS = {
    "sound_enabled": True,
    "notification_enabled": False,
    "auto_start_break": True,
    "auto_start_focus": False,
    "volume": 60,
}
AI_DEFAULTS = {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "timeout": 60,
}


class CredentialStore(Protocol):
    def get(self) -> str: ...
    def set(self, value: str) -> None: ...
    def delete(self) -> None: ...


class SystemCredentialStore:
    def get(self) -> str:
        try:
            import keyring

            return str(keyring.get_password(SERVICE_NAME, CREDENTIAL_ACCOUNT) or "")
        except Exception as exc:
            raise ValueError(f"无法读取 Windows 凭据库：{exc}") from exc

    def set(self, value: str) -> None:
        try:
            import keyring

            keyring.set_password(SERVICE_NAME, CREDENTIAL_ACCOUNT, value)
        except Exception as exc:
            raise ValueError(f"无法写入 Windows 凭据库：{exc}") from exc

    def delete(self) -> None:
        try:
            import keyring

            try:
                keyring.delete_password(SERVICE_NAME, CREDENTIAL_ACCOUNT)
            except keyring.errors.PasswordDeleteError:
                pass
        except Exception as exc:
            raise ValueError(f"无法清除 Windows 凭据库：{exc}") from exc


class SettingsService:
    def __init__(
        self,
        db_path: Path | str,
        *,
        credential_store: CredentialStore | None = None,
        environment: Mapping[str, str] | None = None,
        transport=urlopen,
    ) -> None:
        self.repository = SettingsRepository(db_path)
        self.credentials = credential_store or SystemCredentialStore()
        if environment is None:
            load_dotenv(REPOSITORY_ROOT / ".env")
            self.environment: Mapping[str, str] = os.environ
        else:
            self.environment = environment
        self.transport = transport
        if not self.repository.get("installation.id"):
            self.repository.set("installation.id", str(uuid.uuid4()), utc_now())
        if self.repository.get("onboarding.status") is None:
            self.repository.set("onboarding.status", "skipped", utc_now())
            self.repository.set("onboarding.version", 1, utc_now())

    def get_preferences(self) -> dict[str, Any]:
        saved = self.repository.get("focus.preferences", {})
        return {**PREFERENCE_DEFAULTS, **(saved if isinstance(saved, dict) else {})}

    def update_preferences(self, values: Mapping[str, Any]) -> dict[str, Any]:
        allowed = set(PREFERENCE_DEFAULTS)
        candidate = {**self.get_preferences(), **{k: values[k] for k in allowed if k in values}}
        normalized = {
            key: self._boolean(candidate[key], key)
            for key in ("sound_enabled", "notification_enabled", "auto_start_break", "auto_start_focus")
        }
        try:
            volume = int(candidate["volume"])
        except (TypeError, ValueError) as exc:
            raise ValueError("音量必须是 0 到 100 的整数") from exc
        if not 0 <= volume <= 100:
            raise ValueError("音量必须是 0 到 100 的整数")
        normalized["volume"] = volume
        self.repository.set("focus.preferences", normalized, utc_now())
        return normalized

    def _stored_ai(self) -> dict[str, Any]:
        value = self.repository.get("ai.config", {})
        return self._normalize_ai({**AI_DEFAULTS, **(value if isinstance(value, dict) else {})})

    def get_ai(self) -> dict[str, Any]:
        config = self._resolved_non_secret_ai()
        env_key = str(self.environment.get("DEEPSEEK_API_KEY") or "").strip()
        credential_error = ""
        try:
            stored_key = "" if env_key else self.credentials.get()
        except ValueError as exc:
            stored_key = ""
            credential_error = str(exc)
        key = env_key or stored_key
        source = "environment" if env_key else "credential_manager" if stored_key else "none"
        return {
            **config,
            "configured": bool(key),
            "credential_source": source,
            "masked_hint": f"••••{key[-4:]}" if key else "",
            "managed_by_environment": bool(env_key),
            "credential_error": credential_error,
        }

    def resolved_ai(self) -> dict[str, Any]:
        config = self._resolved_non_secret_ai()
        env_key = str(self.environment.get("DEEPSEEK_API_KEY") or "").strip()
        key = env_key or self.credentials.get()
        return {**config, "api_key": key}

    def _resolved_non_secret_ai(self) -> dict[str, Any]:
        stored = self._stored_ai()
        values = {
            **stored,
            "provider": self.environment.get("YANTU_LLM_PROVIDER", stored["provider"]),
            "base_url": self.environment.get("DEEPSEEK_BASE_URL", stored["base_url"]),
            "model": self.environment.get("DEEPSEEK_MODEL", stored["model"]),
            "timeout": self.environment.get("YANTU_AI_TIMEOUT_SECONDS", stored["timeout"]),
        }
        return self._normalize_ai(values)

    def update_ai(self, values: Mapping[str, Any]) -> dict[str, Any]:
        current = self._stored_ai()
        config = self._normalize_ai({**current, **{k: values[k] for k in AI_DEFAULTS if k in values}})
        self.repository.set("ai.config", config, utc_now())
        key = str(values.get("api_key") or "").strip()
        if key:
            if str(self.environment.get("DEEPSEEK_API_KEY") or "").strip():
                raise ValueError("当前 API Key 由环境变量管理，请先移除 DEEPSEEK_API_KEY")
            if len(key) < 12 or any(char.isspace() for char in key):
                raise ValueError("API Key 格式无效")
            self.credentials.set(key)
        return self.get_ai()

    def delete_ai_key(self) -> dict[str, Any]:
        if str(self.environment.get("DEEPSEEK_API_KEY") or "").strip():
            raise ValueError("环境变量中的 API Key 不能从软件内删除")
        self.credentials.delete()
        return self.get_ai()

    def test_ai(self) -> dict[str, Any]:
        config = self.resolved_ai()
        if not config["api_key"]:
            raise ValueError("请先保存 API Key")
        request = Request(
            f"{config['base_url']}/models",
            headers={"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"},
        )
        try:
            with self.transport(request, timeout=config["timeout"]) as response:
                import json

                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 401:
                raise ValueError("API Key 验证失败") from exc
            raise ValueError(f"DeepSeek 连接失败（HTTP {exc.code}）") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise ValueError(f"无法连接 DeepSeek：{exc}") from exc
        models = [str(item.get("id")) for item in payload.get("data", []) if isinstance(item, dict)]
        return {"ok": True, "model_available": config["model"] in models, "models": models}

    def export_backup(self) -> dict[str, Any]:
        return {
            "focus.preferences": self.get_preferences(),
            "ai.config": self._stored_ai(),
            "onboarding.status": self.repository.get("onboarding.status", "skipped"),
            "onboarding.version": self.repository.get("onboarding.version", 1),
        }

    def import_backup(self, values: Any) -> None:
        if not isinstance(values, Mapping):
            return
        if isinstance(values.get("focus.preferences"), Mapping):
            self.update_preferences(values["focus.preferences"])
        if isinstance(values.get("ai.config"), Mapping):
            config = self._normalize_ai({**AI_DEFAULTS, **values["ai.config"]})
            self.repository.set("ai.config", config, utc_now())

    @staticmethod
    def _normalize_ai(values: Mapping[str, Any]) -> dict[str, Any]:
        provider = str(values.get("provider") or "deepseek").strip().lower()
        if provider != "deepseek":
            raise ValueError("当前仅支持 DeepSeek")
        base_url = str(values.get("base_url") or AI_DEFAULTS["base_url"]).strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            raise ValueError("Base URL 必须使用 HTTPS")
        model = str(values.get("model") or AI_DEFAULTS["model"]).strip()
        if not model or len(model) > 100:
            raise ValueError("模型名称无效")
        try:
            timeout = int(values.get("timeout", 60))
        except (TypeError, ValueError) as exc:
            raise ValueError("超时时间必须是整数") from exc
        if not 5 <= timeout <= 300:
            raise ValueError("超时时间必须在 5 到 300 秒之间")
        return {"provider": provider, "base_url": base_url, "model": model, "timeout": timeout}

    @staticmethod
    def _boolean(value: Any, field: str) -> bool:
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"{field} 必须是布尔值")
