from __future__ import annotations


SYSTEM_PROMPT = """你是一名严谨、务实的研究生科研助手。你的任务是把一个目标拆成可执行、可估时、依赖关系清楚的步骤。"""


def build_task_breakdown_prompt(task: str) -> str:
    cleaned = task.strip()
    return f"""请拆解以下研究生阶段任务：

{cleaned}

要求：
1. 返回 3 至 8 个可独立推进的子任务。
2. priority 只能是 high、medium、low。
3. estimated_hours 是大于 0 的数字。
4. dependencies 填写本列表中前置子任务的完整 name；没有依赖时使用空数组。
5. 只返回一个合法 JSON 对象，不要 Markdown、解释或代码围栏。

JSON 结构示例：
{{
  "title": "任务标题",
  "subtasks": [
    {{
      "name": "明确调研范围与输出要求",
      "priority": "high",
      "estimated_hours": 1.5,
      "dependencies": []
    }}
  ]
}}
"""

