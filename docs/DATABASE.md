# 数据库说明

## 基本信息

- 引擎：SQLite 3（Python 标准库 `sqlite3`，无 ORM）。
- 默认路径：`data/catalog/workbench.sqlite3`，可用 `KATO_DB_PATH` 环境变量或 `--db` 参数覆盖。
- 连接设置：`PRAGMA foreign_keys = ON`、`PRAGMA journal_mode = WAL`、`busy_timeout = 5000`。
- 数据库文件与 `-wal` / `-shm` 均在 `.gitignore` 中，不入库。
- 只存元信息、状态、仓库相对路径、来源 URL、许可与哈希；不存图像/视频二进制。

## 迁移机制

- 迁移文件位于 `db/migrations/`，命名 `<版本号>_<描述>.sql`，例如 `001_init.sql`。
- 版本号记录在 `PRAGMA user_version`。`python -m scripts.init_db` 会按版本号升序执行所有大于当前版本的迁移。
- 每个迁移在事务中执行：脚本内容 + 更新 `user_version` 一起提交；失败则回滚，不会留下“半套结构”。
- 重复执行是幂等的：已应用的迁移不会重跑，已有数据不会被删除。
- **已应用的迁移文件不可修改**；结构变化一律新增 `002_*.sql`、`003_*.sql`。
- `connect_ready()` 按 `PRAGMA user_version` 判断待执行迁移：即使 `tasks` / `datasets` 等基础表已存在，也会应用 `002` 等增量迁移，不会因“表齐全”而跳过。
- 升级已有数据库前，使用 SQLite 在线备份 API 写入数据库同目录的 `backups/`（在 `data/catalog/` 下，已被 Git 忽略），并校验备份可读。

## 表结构

### `tasks` — 任务定义快照索引

| 列 | 类型 | 说明 |
|---|---|---|
| `task_id` | TEXT PK | 任务标识，建议由任务路径与内容哈希派生 |
| `name` | TEXT NOT NULL | 任务名称 |
| `source_path` | TEXT NOT NULL | 任务文档相对路径，如 `tasks/CURRENT_TASK.md` |
| `content_sha256` | TEXT NOT NULL | 该版本任务文档的 SHA-256 |
| `created_at` | TEXT | UTC ISO-8601，默认当前时间 |

### `runs` — 每次实际执行

| 列 | 类型 | 说明 |
|---|---|---|
| `run_id` | TEXT PK | UTC 时间戳 + 随机后缀 |
| `task_id` | TEXT NOT NULL FK → `tasks` | 关联任务 |
| `status` | TEXT NOT NULL | `pending` / `running` / `completed` / `partial` / `failed` / `blocked` |
| `started_at` | TEXT NOT NULL | 开始时间 |
| `finished_at` | TEXT | 结束时间，可空 |
| `report_path` | TEXT | 报告相对路径，可空 |
| `error_message` | TEXT | 失败原因，可空 |

索引：`task_id`、`status`。

### `datasets` — 数据集目录

| 列 | 类型 | 说明 |
|---|---|---|
| `dataset_id` | TEXT PK | 由 `source + source_url + version` 稳定派生 |
| `name` | TEXT NOT NULL | 数据集名称 |
| `source` | TEXT NOT NULL | 来源，如 `roboflow` |
| `source_url` | TEXT NOT NULL | 来源页面 URL |
| `version` | TEXT | 版本，可空 |
| `license_name` | TEXT | 许可名称，可空 |
| `license_url` | TEXT | 许可链接，可空 |
| `format` | TEXT | 导出格式，如 `coco` / `yolo` |
| `image_count` | INTEGER | 图片数，可空，非负 |
| `status` | TEXT NOT NULL | `candidate` / `approved` / `downloaded` / `validated` / `failed` |
| `raw_path` | TEXT | 原始文件仓库相对路径 |
| `processed_path` | TEXT | 处理后仓库相对路径 |
| `sha256` | TEXT | 原始包哈希 |
| `created_at` / `updated_at` | TEXT | UTC ISO-8601 |

唯一性：`(source, source_url, COALESCE(version, ''))` 唯一索引。这样 `version` 为 `NULL` 与空字符串不会产生两条记录——不能只靠普通 `UNIQUE(source, source_url, version)`，因为 SQLite 中 `NULL` 互不相等。

### `run_datasets` — 执行与数据集的多对多关系

| 列 | 类型 | 说明 |
|---|---|---|
| `run_id` | TEXT FK → `runs` | 执行 ID，级联删除 |
| `dataset_id` | TEXT FK → `datasets` | 数据集 ID，级联删除 |
| `action` | TEXT | `discovered` / `approved` / `downloaded` / `validated` / `failed` |
| `created_at` | TEXT | 记录时间 |

主键：`(run_id, dataset_id, action)`，重复关联自动拒绝。

### `research_items` — 就业/行业情报条目

| 列 | 类型 | 说明 |
|---|---|---|
| `item_id` | TEXT PK | 由 `(platform, canonical_url)` 稳定派生 |
| `platform` | TEXT NOT NULL | `zhihu` / `xiaohongshu` / `official` / `media` / `other` |
| `canonical_url` | TEXT NOT NULL | 规范化来源 URL（小写 scheme/host、去 fragment） |
| `title` | TEXT NOT NULL | 标题或短描述 |
| `summary` | TEXT | Agent 自写的有限摘要，不存长正文 |
| `source_type` | TEXT NOT NULL | `official` / `reported` / `ugc` / `search_lead` |
| `topic` | TEXT NOT NULL | `recruitment` / `experience` / `policy` / `industry` / `salary` / `warning` / `other` |
| `cohort` | TEXT NOT NULL | `2026` / `2027` / `unknown` |
| `recruitment_stage` | TEXT NOT NULL | `autumn` / `spring` / `makeup` / `early` / `internship` / `other` / `unknown` |
| `company` / `city` | TEXT | 可空 |
| `published_at` | TEXT | 源头发布时间（ISO-8601，可空） |
| `collected_at` | TEXT NOT NULL | 本次观察时间（UTC ISO-8601） |
| `verification_status` | TEXT NOT NULL | `unverified` / `verified` / `conflicting` / `stale` |
| `verification_url` / `verified_at` | TEXT | `verified` 时必须同时提供 |
| `created_at` / `updated_at` | TEXT | 审计时间 |

唯一性：`(platform, canonical_url)`。同一链接跨平台视为不同条目。

约束：`verification_status='verified'` 时数据库层要求 `verification_url` 与 `verified_at` 均非空；CLI 也会在写入前校验。

### `run_research_items` — 执行与研究条目的关系

| 列 | 类型 | 说明 |
|---|---|---|
| `run_id` | TEXT FK → `runs` | 执行 ID，级联删除 |
| `item_id` | TEXT FK → `research_items` | 研究条目，级联删除 |
| `action` | TEXT | `discovered` / `imported` / `verified` / `updated` |
| `created_at` | TEXT | 记录时间 |

主键：`(run_id, item_id, action)`，重复关联自动拒绝。

## 常用操作

```bash
python -m scripts.init_db                     # 初始化/升级数据库
python -m scripts.catalog list                # 查看数据集概要
python -m scripts.catalog list --status candidate --json
python -m scripts.catalog add --name "..." --source roboflow --source-url "https://..."
python -m scripts.catalog add --json-file dataset.json
python -m scripts.research_catalog add --json-file records.json --run-id <run-id>
python -m scripts.research_catalog list --cohort 2027
python -m scripts.research_catalog list --platform zhihu --topic recruitment --json
python -m scripts.research_catalog export --format json
```

`catalog add` 按 `(source, source_url, version)` 做 upsert：已存在则更新非空字段，不会产生重复行。

`catalog` 通过 `db.connect_ready()` 连接：若目标库里缺少必要表（例如 `--db` 指向一个新建路径），会先自动执行迁移再继续，避免出现 `no such table` 这种难以理解的中断；迁移本身仍是幂等的。`init_db` 的额外职责是创建 `data/` 下的各个运行目录。

## 备份与重置

- 备份：`init_db` 与 `connect_ready()` 在升级已有库前会自动用 SQLite 在线备份 API 写入 `data/catalog/backups/`（被 Git 忽略），并校验备份可读。手动备份时也可停止写入后复制 `data/catalog/workbench.sqlite3`（以及同目录的 `-wal` / `-shm`，或先执行 `PRAGMA wal_checkpoint(TRUNCATE)`）。
- 重置：删除数据库文件后重新运行 `python -m scripts.init_db`。这只会丢失索引元信息，不会删除 `data/raw` 中的实际文件；删除任何数据文件仍需用户明确确认。
- 这是单用户本地库，不做云端同步，也不支持多人并发写入。
