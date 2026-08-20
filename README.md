<div align="center">
  <img src="src/yantu/web/assets/logo-192.png" width="112" alt="Yantu 研途 Logo">

# Yantu · 研途

**面向研究生科研、课程与个人生活的本地优先时间管理工作台**

把任务、课表、专注记录和每日规划放在同一个离线可控的空间中。

![Version](https://img.shields.io/badge/version-0.2.0-235b4e)
![Python](https://img.shields.io/badge/Python-3.11-3776ab)
![Storage](https://img.shields.io/badge/storage-SQLite-5b7487)
![License](https://img.shields.io/badge/license-MIT-7c5c3e)

[快速开始](#快速开始) · [主要功能](#主要功能) · [使用指南](#使用指南) · [开发与测试](#开发与测试) · [系统架构](#系统架构)
</div>

---

Yantu 使用 Flask 提供仅在本机运行的 Web 服务，通过浏览器完成交互，并将数据保存在本地 SQLite 数据库中。它不需要账号或云数据库，适合管理论文阅读、实验、课程、汇报和长期研究任务。

项目当前处于 **v0.2.0 开发阶段**。核心功能已经可用，数据结构和规划流程仍会持续完善。

## 为什么使用 Yantu

| 特点 | 说明 |
| --- | --- |
| 本地优先 | 任务、课表、规划和外观设置保存在本机，不依赖云端账号 |
| 面向科研 | 支持项目、父子任务、预计/实际工时、长期任务和 Deadline |
| 尊重现实日程 | 自动规划会避开课程，并插入任务切换和休息时间 |
| 人工确认优先 | 课表识别、AI 拆解和每日规划均先预览，确认后才写入数据库 |
| 低使用门槛 | Windows 可双击启动，前端无需 Node.js 或额外构建步骤 |

## 快速开始

### 环境要求

- Windows 10/11
- Conda
- Python 3.11

Yantu 的标准开发环境统一使用名为 `planner` 的 Conda 环境。

```powershell
conda create -n planner python=3.11
conda activate planner
pip install -r requirements.txt
```

### 启动应用

最简单的方式是双击仓库根目录的 `start.bat`。启动器会：

1. 定位 `planner` 环境中的 Python；
2. 检查运行依赖；
3. 启动仅监听 `127.0.0.1` 的本地服务；
4. 健康检查通过后打开浏览器。

默认地址为 `http://127.0.0.1:8765`。端口被占用时，启动器会自动尝试其他端口。

也可以从已激活的环境启动：

```powershell
conda activate planner
python server.py --no-browser
```

停止应用时，在启动窗口按 `Ctrl+C`，或双击 `stop.bat`。

### 创建桌面快捷方式

双击 `install-shortcut.bat`，即可在当前用户桌面创建或更新 **Yantu 研途** 快捷方式。该脚本不会修改注册表或开始菜单。

## 主要功能

### 任务与科研工作管理

- 今日、收件箱、科研、课程、个人、未来 7 天和月历视图
- 任务状态、优先级、Deadline、标签、备注和重复规则
- Project 关联与父子任务层级
- 预计工时、实际工时和 TimeEntry 专注记录
- 软删除、回收站、恢复及二次确认后的永久删除
- 任务卡片右键菜单和移动端“⋯”操作入口

### 每日规划与适当休息

- 长期任务按剩余工作量和剩余日期动态计算今日建议投入
- 多任务按优先级、Deadline 和今日工作量自动排序
- 自动避开课程等固定事件，并预留切换缓冲
- 支持 25/5、50/10 番茄节奏和自由专注
- 支持短休息、长休息、连续专注上限和工作时段设置
- 规划结果先预览、后确认；预览不会写入数据库

### 课表识别与课程日历

- 导入 PNG、JPG、XLSX 和 CSV 课表
- 支持学期、节次、起止周、单双周和指定周规则
- 识别低置信度提示、重复导入检测和时间冲突警告
- 导入前可修改或删除识别条目，确认后单事务写入
- 课程与任务共同显示在今日、未来 7 天和月历中
- 支持跳过单次课程，不破坏整学期重复规则

### AI 辅助任务拆解

- 将较大的科研任务拆解为 3–8 个可执行子任务
- 校验模型返回的 JSON、优先级、预计工时和 Deadline
- Preview/Confirm 两阶段流程，模型不能直接修改数据库
- 当前提供 DeepSeek Provider，密钥只从本地环境读取

### 外观与本地体验

- 研林、纸页、晨雾和夜航四套主题
- 浅色、深色和跟随系统模式
- 纯色、渐变及本地图片背景
- 根据背景亮度自动调整文字和面板，保障正文可读性
- 浏览器 favicon、应用 Logo 和 Windows 桌面图标

## 使用指南

### 安排一个长期任务

1. 新建任务并填写预计耗时与 Deadline。
2. 如任务不应立即开始，可设置开始日期。
3. 回到首页查看“今日建议投入”。Yantu 只分配今天合理承担的部分，不会把总工时全部压到第一天。
4. 在“今日时间轴”选择“安排今日”，检查课程避让、任务顺序和休息安排。
5. 确认后保存时间表；也可以从任务菜单直接开始专注。

今日建议投入的核心计算为：

```text
剩余工作量 = max(预计耗时 - 实际耗时, 0)
今日建议投入 = ceil(剩余工作量 / 今天至 Deadline 的剩余天数)
```

没有开始日期且 Deadline 尚远的任务不会被擅自安排到今天；已逾期任务会提示用户重新安排。

### 导入课表

1. 打开侧栏中的“课表”，选择“导入课表”。
2. 选择文件，并填写学期起止日期。
3. 核对课程名、教师、地点、星期、节次、时间和周次。
4. 修正高亮字段或删除错误条目。
5. 确认后写入课程日历。

CSV 推荐列名：

```text
课程名称,教师,地点,星期,节次,周次,开始时间,结束时间
```

时间列可以省略，Yantu 会使用默认节次时间补全。

#### 启用本地图片 OCR

图片识别是可选能力，不影响普通启动和测试：

```powershell
conda activate planner
pip install -r requirements-ocr.txt
```

PaddleOCR 首次使用时可能下载模型，之后在本机运行。未安装 OCR 依赖时，XLSX 和 CSV 导入仍可正常使用。

### 配置 AI

复制 `.env.example` 为 `.env`，填写自己的 DeepSeek API Key：

```ini
YANTU_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
YANTU_AI_TIMEOUT_SECONDS=60
```

重启应用后进入“AI 任务拆解”。`.env` 已被 Git 忽略；请勿把密钥粘贴到 Issue、日志、截图或提交记录中。

### 备份与恢复

应用支持 JSON 备份导入与导出。当前备份格式包含：

- 任务和回收站条目
- 学期、课程、上课规则和课程例外
- 规划偏好与已确认的规划批次
- 外观设置，以及可选的 Base64 本地背景

导入流程继续兼容旧版仅包含任务的备份。

## 系统架构

Yantu 保持单向分层，不允许 API 绕过业务层直接操作数据库：

```mermaid
flowchart LR
    UI["浏览器 UI"] --> API["Flask API"]
    API --> SERVICE["Service"]
    SERVICE --> REPOSITORY["Repository"]
    REPOSITORY --> DB["SQLite / 本地设置文件"]
    SERVICE --> AI["LLM Provider"]
    SERVICE --> OCR["PaddleOCR / XLSX / CSV"]
```

```text
src/yantu/
├── ai/                     # Prompt、Schema、Provider 和 LLM 门面
├── api/                    # Flask API 蓝图
├── database/
│   ├── models.py           # 核心领域模型与枚举
│   ├── repositories/       # 实体数据访问层
│   └── repository.py       # SQLite 初始化、迁移与兼容门面
├── services/               # 业务校验与用例编排
├── web/                    # 原生 HTML、CSS 和 JavaScript 前端
└── main.py                 # 应用装配与本地服务入口
```

详细设计、数据流和边界说明见 [docs/architecture.md](docs/architecture.md)。

### 核心数据模型

| 领域 | 模型 |
| --- | --- |
| 任务 | Project、Task、TimeEntry |
| 课程 | Semester、Course、CourseMeeting、CourseException |
| 规划 | PlanningProfile、PlanningRun、PlanBlock |

数据库默认位于 `data/yantu.db`，当前 Schema 版本为 `4`。迁移只追加表或字段，不删除旧字段和已有数据；高版本数据库不会被旧程序降级。

规划数据从设计上支持 `rule`、`ai` 和 `manual` 三种来源。未来接入新的 AI 排程 API 时，仍需输出同一 Preview 结构，并经过人工确认和服务层复验后才能保存。

## 开发与测试

安装开发依赖：

```powershell
conda activate planner
pip install -r requirements-dev.txt
```

运行完整测试：

```powershell
pytest
```

测试覆盖数据库迁移、Repository/Service、任务与课程 API、AI JSON 校验、课表导入、外观设置、专注记录和多任务规划。普通测试不会下载 OCR 模型，也不访问网络。

前端采用原生 HTML/CSS/JavaScript，无需安装 Node.js 或执行前端构建。

## 数据与安全

| 数据 | 默认位置或边界 |
| --- | --- |
| SQLite 数据库 | `data/yantu.db` |
| 外观设置 | `data/appearance.json` |
| 本地背景 | `data/appearance/` |
| 运行状态 | `data/runtime.json` |
| API 密钥 | `.env` |
| 服务监听 | 仅 `127.0.0.1` |

- 数据库、日志、运行状态和密钥不会提交到 Git。
- 课表文件仅在本机请求期间处理，临时文件会在处理后删除。
- 图片背景保存在本机，不上传第三方。
- 常规删除默认进入回收站；永久删除需要再次确认。
- AI 拆解、课表导入和时间规划的预览阶段均不会写入数据库。

## 项目状态与路线图

当前重点是稳定本地科研时间管理闭环。后续计划包括：

- Project 管理页面与更完整的项目视图
- TimeEntry 历史、周统计和预计/实际偏差复盘
- 时间块拖拽、锁定和跨日重新排程
- 课程关联作业、考试提醒和下一节课程卡片
- AI “稳妥 / 平衡 / 冲刺”规划方案对比
- OpenAI、Qwen 和 Ollama Provider
- 快速添加、全局搜索和键盘命令面板

## 参与贡献

提交修改前，请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [SECURITY.md](SECURITY.md)。项目采用 [MIT License](LICENSE)。
