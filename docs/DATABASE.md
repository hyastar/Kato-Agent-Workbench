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

## 常用操作

```bash
python -m scripts.init_db                     # 初始化/升级数据库
python -m scripts.catalog list                # 查看数据集概要
python -m scripts.catalog list --status candidate --json
python -m scripts.catalog add --name "..." --source roboflow --source-url "https://..."
python -m scripts.catalog add --json-file dataset.json
```

`catalog add` 按 `(source, source_url, version)` 做 upsert：已存在则更新非空字段，不会产生重复行。

## 备份与重置

- 备份：停止写入后复制 `data/catalog/workbench.sqlite3`（以及同目录的 `-wal` / `-shm`，或先执行 `PRAGMA wal_checkpoint(TRUNCATE)`）。
- 重置：删除数据库文件后重新运行 `python -m scripts.init_db`。这只会丢失索引元信息，不会删除 `data/raw` 中的实际文件；删除任何数据文件仍需用户明确确认。
- 这是单用户本地库，不做云端同步，也不支持多人并发写入。
