# Yantu 架构

## 目标与边界

Yantu 是 local-first 的单用户桌面应用：pywebview 提供 Windows 窗口，Flask 在进程内提供本地 API 与静态资源，SQLite 负责持久化。源码模式仍可使用浏览器交互。当前不引入 Node.js、Docker、云数据库或账号系统。

```mermaid
flowchart LR
    SHELL["pywebview 桌面壳 / 浏览器"] --> UI["原生 Web UI"]
    UI --> API["Flask API"]
    API --> TASK["任务业务服务"]
    TASK --> DB["SQLite Repository"]
    API --> BREAKDOWN["TaskBreakdownService"]
    BREAKDOWN --> FACADE["LLMService"]
    FACADE --> PROVIDER["LLM Provider"]
    PROVIDER --> DS["DeepSeek API"]
    UI --> SCHEDULE_API["Schedule API"]
    SCHEDULE_API --> IMPORT["ScheduleImportService"]
    IMPORT --> OCR["PaddleOCR / XLSX / CSV"]
    IMPORT --> SCHEDULE_SERVICE["ScheduleService"]
    SCHEDULE_SERVICE --> SCHEDULE_REPO["ScheduleRepository"]
    SCHEDULE_REPO --> DB
    UI --> APPEARANCE_API["Appearance API"]
    APPEARANCE_API --> APPEARANCE_SERVICE["AppearanceService"]
    APPEARANCE_SERVICE --> APPEARANCE_REPO["AppearanceRepository"]
    APPEARANCE_REPO --> FILES["appearance.json / 本地背景"]
    UI --> FOCUS_API["Focus API"]
    FOCUS_API --> FOCUS_SERVICE["FocusService"]
    FOCUS_SERVICE --> FOCUS_REPO["FocusRepository"]
    FOCUS_REPO --> DB
    UI --> SETTINGS_API["Settings API"]
    SETTINGS_API --> SETTINGS_SERVICE["SettingsService"]
    SETTINGS_SERVICE --> SETTINGS_REPO["SettingsRepository"]
    SETTINGS_SERVICE --> VAULT["Windows Credential Manager"]
    UI --> RESEARCH_API["Research API"]
    RESEARCH_API --> RESEARCH_SERVICE["ResearchService"]
    RESEARCH_SERVICE --> RESEARCH_REPO["ResearchRepository"]
    RESEARCH_REPO --> DB
```

依赖方向固定为 `API -> Service -> Interface/Repository`。任务业务代码不导入任何具体模型 SDK，也不处理 API Key。

## 课程日程边界

课程是固定时间事件，不是可完成的 Task。数据库保存学期、课程和重复规则，`ScheduleService` 只在查询日期范围内展开实际课程实例，避免为整学期预先生成大量记录。

```mermaid
sequenceDiagram
    actor User as 用户
    participant UI as 导入预览
    participant API as Schedule API
    participant Parser as 本地解析器
    participant Service as ScheduleService
    participant DB as SQLite
    User->>UI: 选择图片或表格
    UI->>API: POST /schedule-import/preview
    API->>Parser: OCR / XLSX / CSV 解析
    Parser-->>UI: 草稿、置信度、错误与冲突
    Note over UI,DB: 预览阶段数据库不变
    User->>UI: 修改并确认
    UI->>API: POST /schedule-import/confirm
    API->>Service: 重新校验
    Service->>DB: 单事务保存学期、课程和时段
```

- 图片 OCR 通过接口注入并懒加载；普通启动和自动测试不下载模型。
- 课程周规则支持全部、单周、双周和指定周。
- `CourseException` 保存“跳过本次”，不会破坏整门课程的重复规则。
- 文件哈希用于发现重复导入；字段错误阻止确认，时间重叠只产生警告。
- 课表上传限制为 10 MB，并验证扩展名和文件签名。

## 删除与快捷操作

Task 和 Course 使用 `deleted_at` 软删除。常规查询统一排除回收站条目；恢复会清空该字段，只有回收站中的条目才能永久删除。前端右键菜单和移动端“⋯”菜单调用相同 API，并通过短时撤销降低误删风险。

备份格式版本为 `8`，包含项目、课程、学期、课程例外、回收站任务、规划偏好、已确认规划批次、已结束专注历史、科研文献关联和允许备份的非秘密设置，同时继续接受旧版仅包含 `tasks` 的备份。DeepSeek/Zotero API Key、活动会话和本机请求令牌永不导出。

## 每日容量与专注计时

`TaskService.daily_plan(date)` 是每日建议投入的唯一计算入口。预计工时、实际工时、开始日期和 Deadline 是持久化事实；今日投入、剩余天数、截止倒计时和过期状态是按请求生成的只读投影，不写回任务表：

```text
remaining = max(estimated_minutes - actual_minutes, 0)
today = ceil(remaining / inclusive_days(today, deadline))
```

未来开始的任务不会提前占用今天容量。没有开始日期的普通任务仍不被擅自安排；当任务状态为 `waiting` 时，表示用户已明确将它交给自动规划，因此从查询当天开始按剩余日期动态分摊。Deadline 当天承接全部剩余量。

接口 `GET /api/planning/daily?date=YYYY-MM-DD` 保持原有 `allocations` 合同，并额外返回 `generated_at`、`task_metrics` 与 `refresh`：

| 刷新层级 | 动态内容 | 前端行为 |
| --- | --- | --- |
| 每分钟 | 当前时间、活动专注状态 | 页面可见时刷新；切回窗口立即补刷新 |
| 每小时 | Deadline 剩余小时、容量风险 | 重新查询服务端投影，不依赖旧页面缓存 |
| 每日 | 建议投入、剩余天数、逾期原因 | 跨午夜重新加载当日任务、课程和规划 |

确认后的 `PlanningRun` 是用户认可过的历史快照，不会被后台静默覆盖。`GET /api/planning/plans?date=` 会将快照与当前任务投影比较；实际投入、日期或自动规划范围变化时返回 `plan_state.needs_refresh = true`，界面引导用户重新预览和确认。

专注计时以 `focus_sessions` 保存可恢复的生命周期，TimeEntry 仍是任务实际投入的唯一账本：

```mermaid
sequenceDiagram
    actor User as 用户
    participant Timer as 专注工作台
    participant API as Focus API
    participant Service as FocusService
    participant Repo as Repository
    participant DB as SQLite
    User->>Timer: 启动 25/5、50/10 或自由专注
    Timer->>API: 启动 / 暂停 / 恢复
    Service->>Repo: 持久化 FocusSession 时间戳
    Timer->>API: 到时后人工确认
    API->>Service: 校验状态机与幂等性
    Service->>Repo: 同事务完成会话并创建 TimeEntry
    Repo->>DB: 同步 Task.actual_minutes 与 PlanBlock
```

`focus_sessions` 同一时间只允许一个 `running / paused / awaiting_action` 会话。Service 依据 `elapsed_seconds + last_resumed_at` 恢复重启后的有效经过时间，倒计时超时只进入 `awaiting_action`；重复完成不会重复创建 TimeEntry。休息会话不计入任务工时。接口包括 `/api/focus/active`、会话状态变更、历史和统计；原有 TimeEntry CRUD 保持兼容。

### 多任务规划数据合同

规划层使用四类持久化实体，数据库 `user_version = 8`：

| 实体 | 职责 |
| --- | --- |
| `planning_profiles` | 单用户工作时段、工作日、专注/休息长度、最大连续专注、课程缓冲、是否使用番茄节拍 |
| `planning_runs` | 一次确认规划的日期范围、来源策略、输入快照、容量警告和确认时间 |
| `plan_blocks` | 可执行的专注、短休息、长休息和缓冲时间块；专注块可关联 Task |
| `task_planning_preferences` | 每个任务的自动/手动/暂停模式、会话长度、每日上限、偏好星期和可用时段；为未来 AI 排程提供约束 |

`strategy` 支持 `rule`、`ai`、`manual`。AI 将来只能生成与规则引擎相同的 Preview 数据，不直接写表；`POST /api/planning/confirm` 会复验任务引用、时间格式、块类型和重叠关系，然后在一个事务中写入 PlanningRun 与全部 PlanBlock。Preview ID 同时作为幂等键，重复确认不会生成重复批次。

```mermaid
flowchart LR
    TASKS["任务剩余工时"] --> PREVIEW["Planning Preview"]
    COURSES["课程固定占用"] --> PREVIEW
    PROFILE["专注与休息偏好"] --> PREVIEW
    RULE["规则引擎"] --> PREVIEW
    AI["未来 AI 规划器"] --> PREVIEW
    PREVIEW --> REVIEW["用户检查容量、顺序与休息"]
    REVIEW --> CONFIRM["Confirm 校验"]
    CONFIRM --> RUN["PlanningRun + PlanBlocks"]
```

规划接口：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET / PUT | `/api/planning/profile` | 读取或更新规划偏好 |
| POST | `/api/planning/preview` | 生成不落库的多任务时间表 |
| POST | `/api/planning/confirm` | 校验并原子保存预览 |
| GET | `/api/planning/plans?date=` | 读取指定日期最新确认时间轴 |
| GET / PUT | `/api/planning/tasks/{id}/preference` | 读取或更新任务级排程约束 |

## 科研文献与 Zotero 边界

v7 在 v6 本地数据合同上增加只读 Zotero 适配器；v8 增加科研项目—论文关联与文件夹/检索导入。任务规划与 UI 不直接依赖 Zotero SDK；适配器只负责认证、读取、版本检查和数据转换：

| 实体 | 职责 |
| --- | --- |
| `research_sources` | Zotero 用户/群组/本地文库标识、同步游标与最近同步结果 |
| `research_items` | 论文和附件的稳定外部 Key、题录、DOI、URL、本地附件路径及原始扩展元数据 |
| `task_research_items` | Task 与论文的多对多关联，区分参考、待读、综述、引用和产出 |
| `project_research_items` | 科研 Project 与论文的幂等关联，记录文件夹/检索来源和导入时间 |
| `research_inbox` | 新收集论文的待处理队列；转换或忽略都有显式状态，重复同步不会重复入队 |
| `research_sync_runs` | 每次同步的前后游标、导入/删除数量、错误和完成状态，便于诊断但不保存凭据 |

支持两种读取模式：

- **Local API（默认）**：`http://127.0.0.1:23119/api`，读取不需要 Key，不经过互联网；只允许 loopback 地址。首次连接保存 `Zotero-Server-ID`，后续不匹配时停止同步，避免混用两套本地 Zotero 数据库的版本号。
- **Web API**：只允许 `https://api.zotero.org`；私有文库 Key 保存到 Windows Credential Manager，账户名按来源 ID 隔离，请求使用 `Zotero-API-Key` 头，URL、数据库、日志和备份均不含 Key。

同步使用 `since=<Last-Modified-Version>` 读取变更，并读取 `/deleted?since=` 处理远端删除。只有全部页面和删除清单使用同一文库版本时才推进 `sync_cursor`；失败时保留旧游标，下一次可安全重试。相同来源的 `external_key` 唯一，重复同步采用 upsert，科研收件箱使用 `INSERT OR IGNORE` 避免重复入队。

`zotero_uri` 只接受 `zotero://select/...` 本地直达链接。论文转任务遵循 Preview/Confirm：预览不写库；确认时在一个事务中创建 Task、写入 `task_research_items` 并将收件箱状态改为 `converted`，重复确认返回原任务。

项目论文导入同样遵循 Preview/Confirm。预览直接读取 Zotero 的 Collection 或 `q` 快速检索结果，不写 Yantu；确认阶段按选中的 Item Key 重新读取题录、幂等 upsert `research_items`，再写入 `project_research_items`。文件夹模式可以递归读取子 Collection，同一论文出现在多个文件夹时按 Item Key 去重。该流程不把论文自动转换成任务，也不写回 Zotero。

Zotero 接口：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET / POST | `/api/research/sources` | 列出或保存本机/Web 连接；响应不返回完整 Key |
| POST | `/api/research/sources/{id}/test` | 验证连接、权限、Server ID 和文库版本 |
| POST | `/api/research/sources/{id}/sync` | 手动执行只读增量同步 |
| GET | `/api/research/sources/{id}/collections` | 读取 Zotero 文件夹树 |
| POST | `/api/research/sources/{id}/project-import-preview` | 按文件夹或检索生成项目导入预览，不写数据库 |
| GET | `/api/research/projects/{id}/items` | 读取科研项目已关联论文 |
| POST | `/api/research/projects/{id}/imports` | 确认并幂等导入所选论文 |
| GET | `/api/research/inbox` | 读取待处理论文 |
| POST | `/api/research/inbox/{id}/task-preview` | 生成可编辑任务草稿，不写数据库 |
| POST | `/api/research/inbox/{id}/task-confirm` | 原子创建阅读任务并关联论文 |

本阶段不写回 Zotero、不下载附件、不解析 PDF 全文，也不后台自动同步。Zotero 官方说明本机 API 读取无需认证，Web API 应通过请求头携带 Key，并推荐用 `since` 和 `Last-Modified-Version` 增量读取：[Local API](https://www.zotero.org/support/dev/web_api/v3/local_api) · [Web API Basics](https://www.zotero.org/support/dev/web_api/v3/basics) · [Syncing](https://www.zotero.org/support/dev/web_api/v3/syncing)

## 外观设置边界

外观数据不属于任务业务模型，因此不进入 SQLite，但仍遵循 `API → Service → Repository`：

- `api/appearance_routes.py` 只处理 HTTP、上传与响应。
- `AppearanceService` 校验主题、颜色、渐变角度、透明度、图片类型和 8 MB 上限。
- `AppearanceRepository` 只访问固定的 `data/appearance.json` 与 `data/appearance/`，JSON 和图片都先写同目录临时文件，再原子替换。
- 上传文件名不参与目标路径构造；服务器只保存固定名称 `background.<受控扩展名>`。
- 浏览器 `localStorage` 仅缓存最后一次主题以减少首屏闪烁，后端文件始终是最终来源。

图片亮度分析在浏览器 Canvas 中完成，不上传外部服务。前端以最暗、平均和最亮采样值检查文字与半透明面板的组合；低于 4.5:1 时自动提高面板不透明度或切换文字色。背景读取失败时保留用户配置，但本次显示回退为无图的当前预设。

外观接口：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET / PUT | `/api/appearance` | 读取或保存全局外观 |
| POST / GET / DELETE | `/api/appearance/background` | 保存、读取或移除本地背景 |

备份 v3 的 `appearance` 字段包含设置和可选 Base64 图片；不存在该字段的旧备份仍按原流程导入。

## AI 边界

- `ai/schemas.py`：模型输出的可信边界。所有返回值在进入业务层前进行类型与范围校验。
- `ai/prompt_templates.py`：集中管理 Prompt，避免散落在路由和任务代码中。
- `ai/llm_service.py`：统一 `generate()` 接口、环境配置、错误类型和 DeepSeek Provider。
- `services/task_breakdown_service.py`：任务拆解用例。预览阶段只返回数据，确认阶段才创建父任务和子任务。
- `api/ai_routes.py`：输入校验和 HTTP 状态码映射，不保存密钥、不记录请求头。

```mermaid
sequenceDiagram
    actor User as 用户
    participant UI as 浏览器
    participant API as AI API
    participant LLM as LLMService
    participant DB as SQLite
    User->>UI: 输入任务
    UI->>API: POST /breakdown/preview
    API->>LLM: breakdown_task
    LLM-->>API: 已校验的 JSON
    API-->>UI: 仅预览
    Note over UI,DB: 此时数据库不变
    User->>UI: 确认
    UI->>API: POST /breakdown/confirm
    API->>DB: 原子写入父任务与子任务
    DB-->>UI: 已创建任务
```

未来 Provider 需实现 `name`、`model` 与 `generate(prompt) -> LLMResponse`，再加入环境工厂。OpenAI、Qwen 和 Ollama 的认证、端点与响应差异只存在于各自 Provider 内。

## 数据与安全

- `AppPaths` 是运行路径的唯一解析入口：显式 `YANTU_DATA_DIR` 优先；冻结安装版使用 `%LOCALAPPDATA%\Yantu`；源码开发使用仓库 `data/`。
- 只读资源（Python 包、HTML/CSS/JS、Logo）与可写数据（SQLite、外观、日志、运行状态）分离，业务代码不再自行推导仓库根目录。
- DeepSeek API Key 默认通过 `keyring` 保存到 Windows Credential Manager，服务名 `Yantu`、账户名 `deepseek:default`；`DEEPSEEK_API_KEY` 环境变量优先。
- `app_settings` 只保存非秘密 JSON 设置，包括专注偏好及未来新手引导标记。
- 服务每次启动生成随机请求令牌并注入首屏；所有本地修改型 `/api/*` 请求必须携带匹配的 `X-Yantu-Token`。
- 默认数据库（源码开发）：`data/yantu.db`
- 运行状态（源码开发）：`data/runtime.json`
- 服务地址：仅 `127.0.0.1`
- AI 预览不会自动写入；确认数据会再次经过 Schema 校验，并在一个 SQLite 事务中保存。

## Windows 桌面与发布边界

- `desktop.py` 在同一进程中把 Flask WSGI 应用交给 pywebview，不开放新的公网服务，也不改变 API → Service → Repository 依赖方向。
- Windows 命名 Mutex 保证同一用户只运行一个 Yantu 桌面实例，并与 Inno Setup 的升级前关闭检测共用同一标识。
- PyInstaller 使用 `onedir`，避免 onefile 临时解压目录被误当作可写数据目录；Inno Setup 仅为当前用户安装到 `%LOCALAPPDATA%\Programs\Yantu`，无需管理员权限。
- 安装版的持久数据始终位于 `%LOCALAPPDATA%\Yantu`。覆盖升级或卸载只处理程序资源，不删除任务数据库、背景或 WebView 状态。
- 构建脚本依次执行冻结程序自检、安装器编译、静默安装、已安装程序自检和静默卸载，并生成 SHA-256；标签工作流只在测试与上述检查全部通过后保存 Actions Artifact，面向普通用户的稳定安装器和校验文件同步在仓库 `downloads/`。
