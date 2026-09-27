# Yantu 周度 / 月度本地归档规范

## 目标与边界

归档层用于控制长期使用后实时数据库的查询范围，并为复盘、迁移和桌面应用数据层提供稳定快照。实时任务、课程、专注记录与科研文献仍以 `yantu.db` 为唯一可编辑数据源；归档文件不参与日常写入，也不会在后台自动删除实时数据。

Schema v13 只建立目录、周期索引和条目封装规范。自动筛选条目、封存周期、从实时库移除记录以及恢复归档，必须在后续版本中分别设计并经过用户确认。

## 目录结构

归档根目录位于用户数据目录下的 `archive/`：

```text
archive/
├─ README.md
├─ schema-v1.json
├─ weekly/
│  └─ 2026/
│     └─ 2026-W39/
│        ├─ manifest.json
│        └─ entries.ndjson
└─ monthly/
   └─ 2026/
      └─ 2026-09/
         ├─ manifest.json
         └─ entries.ndjson
```

- 周度周期使用 ISO 周键 `YYYY-Www`，星期一至星期日为一个周期。
- 月度周期使用 `YYYY-MM`。
- `relative_path` 始终使用 `/`，不保存设备绝对路径，便于迁移。
- 每次启动只确保当前周、当前月目录和空清单存在，不会自动归档业务条目。

## SQLite 索引

`archive_periods` 保存周期、目录、格式版本、状态和条目数量。状态仅允许：

- `open`：允许后续幂等追加归档快照。
- `sealed`：周期已封存，后续实现不得原地修改，只能通过新的修订周期更正。

`archive_entries` 保存条目索引、完整 JSON 快照、校验和与归档时间。`(period_id, entity_type, entity_id)` 唯一，重复归档必须幂等。

## NDJSON 条目规范

`entries.ndjson` 每行是一个独立 UTF-8 JSON 对象：

```json
{
  "format": "yantu.archive.entry.v1",
  "entity_type": "focus_session",
  "entity_id": "uuid",
  "occurred_at": "2026-09-21T10:30:00+08:00",
  "archived_at": "2026-10-01T00:10:00+08:00",
  "checksum": "sha256:...",
  "payload": {}
}
```

首批允许的 `entity_type` 规划为 `task`、`focus_session`、`time_entry`、`course_event`、`research_item`。`payload` 必须是归档时完整快照，不依赖实时表的外键才能解释。时间使用带时区的 ISO 8601；日期使用 `YYYY-MM-DD`。

## 后续实现顺序

1. 增加归档预览，按结束时间列出候选条目，不自动写入。
2. 用户确认后先写 SQLite 索引与临时文件，校验 SHA-256，再原子替换清单。
3. 周度归档服务近期复盘，月度归档保存稳定长期快照；同一实体可存在于不同粒度周期中。
4. 封存、实时库瘦身和恢复必须拆成独立操作；任何删除实时记录的步骤都要再次确认。
5. 桌面应用和未来网页端共用该格式，不在界面层定义私有字段。
