from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT / "src"))

from yantu.ai.llm_service import DeepSeekProvider, LLMResponse, LLMService  # noqa: E402
from yantu.ai.prompt_templates import build_task_breakdown_prompt  # noqa: E402
from yantu.ai.schemas import SchemaValidationError, TaskBreakdown  # noqa: E402
from yantu.database.repository import task_count  # noqa: E402
from yantu.main import create_app  # noqa: E402


SAMPLE = {
    "title": "准备下个月激光雷达组会汇报",
    "subtasks": [
        {"name": "明确汇报范围", "priority": "high", "estimated_hours": 1.0, "dependencies": []},
        {"name": "整理实验结果", "priority": "high", "estimated_hours": 4.0, "dependencies": ["明确汇报范围"]},
        {"name": "制作汇报幻灯片", "priority": "medium", "estimated_hours": 3.0, "dependencies": ["整理实验结果"]},
    ],
}


class FakeProvider:
    name = "fake"
    model = "deterministic-test-model"
    configured = True

    def generate(self, prompt: str) -> LLMResponse:
        assert "JSON" in prompt
        return LLMResponse(self.name, self.model, json.dumps(SAMPLE, ensure_ascii=False))


class FakeHTTPResponse:
    def __init__(self, document: dict):
        self.body = json.dumps(document, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self.body


def test_prompt_requires_json_hours_priorities_and_dependencies():
    prompt = build_task_breakdown_prompt("完成单光子激光雷达调研")
    assert "JSON" in prompt
    assert "estimated_hours" in prompt
    assert "priority" in prompt
    assert "dependencies" in prompt


def test_schema_rejects_unexpected_priority():
    invalid = dict(SAMPLE)
    invalid["subtasks"] = [dict(SAMPLE["subtasks"][0], priority="urgent")]
    with pytest.raises(SchemaValidationError):
        TaskBreakdown.from_mapping(invalid)


def test_deepseek_provider_uses_json_mode_without_exposing_key():
    captured = {}
    api_key = "unit-test-placeholder"

    def transport(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return FakeHTTPResponse({"choices": [{"message": {"content": json.dumps(SAMPLE)}}]})

    response = DeepSeekProvider(api_key, transport=transport).generate("Return JSON")
    assert response.provider == "deepseek"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["model"] == "deepseek-v4-flash"
    assert captured["authorization"] == "Bearer " + api_key
    assert api_key not in response.content


def test_preview_does_not_write_and_confirmation_is_explicit():
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "test.db"
        factory = lambda: LLMService(FakeProvider())
        app = create_app(db_path, llm_service_factory=factory)
        app.config.update(TESTING=True)
        client = app.test_client()

        preview = client.post("/api/ai/breakdown/preview", json={"task": SAMPLE["title"]})
        assert preview.status_code == 200
        breakdown = preview.get_json()["breakdown"]
        assert breakdown == SAMPLE
        assert task_count(db_path) == 0

        confirmed = client.post(
            "/api/ai/breakdown/confirm",
            json={"domain": "research", "breakdown": breakdown},
        )
        assert confirmed.status_code == 201
        tasks = confirmed.get_json()["tasks"]
        assert len(tasks) == 4
        assert tasks[0]["parent_id"] is None
        assert all(task["parent_id"] == tasks[0]["id"] for task in tasks[1:])
        assert task_count(db_path) == 4


def test_status_never_returns_api_key():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(Path(directory) / "test.db", lambda: LLMService(FakeProvider()))
        response = app.test_client().get("/api/ai/status")
        assert response.status_code == 200
        assert response.get_json() == {
            "configured": True,
            "model": "deterministic-test-model",
            "provider": "fake",
        }
        assert "key" not in response.get_data(as_text=True).lower()
