PRAGMA foreign_keys = ON;

-- 001_init.sql — 第一版 SQLite 结构。
-- 迁移版本记录在 PRAGMA user_version 中，由 scripts/init_db.py 负责推进。
-- 时间字段统一为 UTC ISO-8601 文本（例如 2026-11-06T08:00:00.000Z）。

CREATE TABLE IF NOT EXISTS tasks (
    task_id        TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    source_path    TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'running', 'completed', 'partial', 'failed', 'blocked')),
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at   TEXT,
    report_path   TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_task_id ON runs(task_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id     TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    source         TEXT NOT NULL,
    source_url     TEXT NOT NULL,
    version        TEXT,
    license_name   TEXT,
    license_url    TEXT,
    format         TEXT,
    image_count    INTEGER CHECK (image_count IS NULL OR image_count >= 0),
    status         TEXT NOT NULL DEFAULT 'candidate'
                   CHECK (status IN ('candidate', 'approved', 'downloaded', 'validated', 'failed')),
    raw_path       TEXT,
    processed_path TEXT,
    sha256         TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- 归一化唯一性：version 为 NULL 与空字符串视为同一条记录。
CREATE UNIQUE INDEX IF NOT EXISTS ux_datasets_identity
    ON datasets (source, source_url, COALESCE(version, ''));

CREATE INDEX IF NOT EXISTS idx_datasets_status ON datasets(status);
CREATE INDEX IF NOT EXISTS idx_datasets_source ON datasets(source);

CREATE TABLE IF NOT EXISTS run_datasets (
    run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    action     TEXT NOT NULL
               CHECK (action IN ('discovered', 'approved', 'downloaded', 'validated', 'failed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (run_id, dataset_id, action)
);

CREATE INDEX IF NOT EXISTS idx_run_datasets_dataset_id ON run_datasets(dataset_id);
