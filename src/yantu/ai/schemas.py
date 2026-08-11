from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


ALLOWED_AI_PRIORITIES = {"high", "medium", "low"}


class SchemaValidationError(ValueError):
    pass


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field} 必须是非空文本")
    return value.strip()


@dataclass(frozen=True)
class SubtaskProposal:
    name: str
    priority: str
    estimated_hours: float
    dependencies: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SubtaskProposal":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("每个子任务必须是 JSON 对象")
        name = _text(value.get("name"), "子任务名称")
        priority = _text(value.get("priority"), "优先级").lower()
        if priority not in ALLOWED_AI_PRIORITIES:
            raise SchemaValidationError("优先级必须是 high、medium 或 low")
        hours = value.get("estimated_hours")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0 < float(hours) <= 10000:
            raise SchemaValidationError("预计时间必须是大于 0 的数字")
        raw_dependencies = value.get("dependencies", [])
        if not isinstance(raw_dependencies, list) or not all(isinstance(item, str) for item in raw_dependencies):
            raise SchemaValidationError("前置依赖必须是文本数组")
        dependencies = tuple(item.strip() for item in raw_dependencies if item.strip())
        return cls(name, priority, float(hours), dependencies)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "priority": self.priority,
            "estimated_hours": self.estimated_hours,
            "dependencies": list(self.dependencies),
        }


@dataclass(frozen=True)
class TaskBreakdown:
    title: str
    subtasks: tuple[SubtaskProposal, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TaskBreakdown":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("AI 返回结果必须是 JSON 对象")
        title = _text(value.get("title"), "任务标题")
        raw_subtasks = value.get("subtasks")
        if not isinstance(raw_subtasks, list) or not raw_subtasks:
            raise SchemaValidationError("subtasks 必须是非空数组")
        if len(raw_subtasks) > 30:
            raise SchemaValidationError("一次最多生成 30 个子任务")
        subtasks = tuple(SubtaskProposal.from_mapping(item) for item in raw_subtasks)
        return cls(title, subtasks)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "subtasks": [item.to_dict() for item in self.subtasks]}


@dataclass(frozen=True)
class LLMResponse:
    provider: str
    model: str
    content: str

