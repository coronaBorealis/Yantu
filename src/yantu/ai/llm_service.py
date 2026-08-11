from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from .prompt_templates import SYSTEM_PROMPT, build_task_breakdown_prompt
from .schemas import LLMResponse, SchemaValidationError, TaskBreakdown


class LLMError(RuntimeError):
    pass


class LLMConfigurationError(LLMError):
    pass


class LLMAPIError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, prompt: str) -> LLMResponse: ...


Transport = Callable[..., object]


class DeepSeekProvider:
    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        timeout: float = 60,
        transport: Transport = urlopen,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str) -> LLMResponse:
        if not self.configured:
            raise LLMConfigurationError("尚未配置 DEEPSEEK_API_KEY")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 2500,
            "stream": False,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(2):
            try:
                with self.transport(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                raise LLMAPIError(f"DeepSeek 请求失败（HTTP {exc.code}）：{detail}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                raise LLMAPIError(f"无法连接 DeepSeek：{exc}") from exc
            try:
                document = json.loads(raw)
                content = document["choices"][0]["message"]["content"]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise LLMResponseError("DeepSeek 返回了无法识别的响应") from exc
            if isinstance(content, str) and content.strip():
                return LLMResponse(self.name, self.model, content.strip())
            if attempt == 1:
                raise LLMResponseError("DeepSeek 连续返回空内容，请稍后重试")
        raise LLMResponseError("DeepSeek 未返回内容")


class LLMService:
    """Business-facing LLM facade. Provider details never leak to task services."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    @classmethod
    def from_environment(cls, repository_root: Path | None = None) -> "LLMService":
        root = repository_root or Path(__file__).resolve().parents[3]
        load_dotenv(root / ".env")
        provider_name = os.getenv("YANTU_LLM_PROVIDER", "deepseek").strip().lower()
        if provider_name != "deepseek":
            raise LLMConfigurationError(f"暂不支持提供商：{provider_name}")
        try:
            timeout = float(os.getenv("YANTU_AI_TIMEOUT_SECONDS", "60"))
        except ValueError as exc:
            raise LLMConfigurationError("YANTU_AI_TIMEOUT_SECONDS 必须是数字") from exc
        return cls(
            DeepSeekProvider(
                api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                timeout=timeout,
            )
        )

    def generate(self, prompt: str) -> LLMResponse:
        if not isinstance(prompt, str) or not prompt.strip():
            raise LLMResponseError("提示词不能为空")
        return self.provider.generate(prompt.strip())

    def breakdown_task(self, task: str) -> TaskBreakdown:
        response = self.generate(build_task_breakdown_prompt(task))
        try:
            return TaskBreakdown.from_mapping(json.loads(response.content))
        except json.JSONDecodeError as exc:
            raise LLMResponseError("模型没有返回合法 JSON") from exc
        except SchemaValidationError as exc:
            raise LLMResponseError(f"模型返回结构不符合要求：{exc}") from exc

    def status(self) -> dict[str, object]:
        return {
            "provider": self.provider.name,
            "model": self.provider.model,
            "configured": bool(getattr(self.provider, "configured", True)),
        }

