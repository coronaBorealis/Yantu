# Yantu（研途）

Yantu 是一个面向研零及研究生阶段的本地个人工作台，用于协调科研、课程和个人生活。它运行在 Windows 本机，浏览器仅作为界面，任务数据默认保存在本机 SQLite 数据库中，不需要账号或公网服务器。

## 当前能力

- 今日、收件箱、科研、课程、个人、未来 7 天与月历视图
- 任务新建、编辑、删除、完成、筛选、优先级和 Deadline 管理
- 完整任务字段：预计/实际耗时、状态、完成度、标签、重复规则和备注
- 父子任务、项目、研究课题、时间记录等扩展字段预留
- JSON 备份导入与导出
- AI 任务拆解预览：模型生成后先展示，只有用户确认才写入 SQLite
- 仅绑定 `127.0.0.1`，动态端口回退，启动成功后才打开浏览器
- Windows 双击启动器固定使用 Conda `planner`（Python 3.11）

## 快速开始（Windows）

1. 使用 Conda 创建一次环境：

   ```powershell
   conda create -n planner python=3.11
   conda run -n planner python -m pip install -r requirements.txt
   ```

2. 双击根目录的 `start.bat`。
3. 停止时按启动窗口中的 `Ctrl+C`，或双击 `stop.bat`。

启动器不会调用 PATH 中的系统 Python。它会寻找 `planner` 环境的 `python.exe`，检查 Python 3.11 与依赖，启动后端，等待健康检查成功，再打开实际端口对应的页面。默认尝试 `127.0.0.1:8765`，不可绑定时自动尝试附近端口。

## 配置 AI

AI 功能默认使用 DeepSeek，但 API Key 不会写在代码或 Git 中。

1. 复制 `.env.example` 并命名为 `.env`。
2. 填写：

   ```ini
   YANTU_LLM_PROVIDER=deepseek
   DEEPSEEK_API_KEY=你的密钥
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   DEEPSEEK_MODEL=deepseek-v4-flash
   YANTU_AI_TIMEOUT_SECONDS=60
   ```

3. 重启 Yantu，打开侧栏“AI 任务拆解”。
4. 输入“准备下个月激光雷达组会汇报”，生成预览；确认内容后再加入科研任务。

`.env` 已被 `.gitignore` 排除。请勿把密钥粘贴到 Issue、日志、截图或提交记录中。

## 架构

```text
Yantu/
├── src/yantu/
│   ├── main.py                 # Flask 应用与可靠本地服务
│   ├── api/ai_routes.py        # AI HTTP 端点
│   ├── ai/                     # 模型无关接口、Provider、Prompt 与 Schema
│   ├── database/repository.py  # SQLite 数据访问
│   ├── services/               # 业务编排
│   └── web/                    # 无构建步骤的浏览器界面
├── scripts/                    # Windows 启停脚本
├── tests/                      # API、数据库、端口与 AI 测试
├── docs/architecture.md
├── pyproject.toml
└── requirements.txt
```

任务业务层只依赖 `LLMService`，不直接知道 DeepSeek/OpenAI/Qwen/Ollama。新增模型时实现 Provider 并在工厂中注册即可。详细设计见 [docs/architecture.md](docs/architecture.md)。

## 本地开发与测试

```powershell
conda run -n planner python -m pip install -r requirements-dev.txt
conda run -n planner python -m pytest
```

直接启动后端：

```powershell
conda run -n planner python server.py --no-browser
```

数据库默认位于 `data/yantu.db`，运行时信息位于 `data/runtime.json`；两者均不会提交到 Git。首次启动会自动创建数据库结构。

## 路线图

- 可插拔 OpenAI、Qwen 与 Ollama Provider
- AI 拆解结果的逐项编辑、选择性确认与 Deadline 建议
- 项目/研究课题、番茄钟、时间记录与周期总结
- 计划耗时和实际耗时统计、风险提醒、周报/月报

## 参与贡献与安全

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [SECURITY.md](SECURITY.md)。本项目采用 [MIT License](LICENSE)。

