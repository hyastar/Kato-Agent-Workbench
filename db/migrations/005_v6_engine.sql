PRAGMA foreign_keys = ON;

-- 005_v6_engine.sql — V6 采集引擎表。
-- 只新增表与索引，不修改 001–004 已应用迁移，不改动历史文章与评论。
-- 候选 URL 与 research_items.canonical_url 使用同一规范化规则。

CREATE TABLE IF NOT EXISTS engine_candidates (
    candidate_id   TEXT PRIMARY KEY,
    engine_run_id  TEXT,
    campaign_id    TEXT NOT NULL,
    platform       TEXT NOT NULL
                   CHECK (platform IN ('zhihu', 'xiaohongshu')),
    canonical_url  TEXT NOT NULL,
    title_hint     TEXT,
    dimension      TEXT NOT NULL,
    keyword        TEXT,
    combined_query TEXT,
    state          TEXT NOT NULL DEFAULT 'discovered'
                   CHECK (state IN ('discovered', 'queued', 'processing', 'accepted',
                                    'rejected', 'retryable_failed', 'blocked',
                                    'completed', 'skipped')),
    attempts       INTEGER NOT NULL DEFAULT 0,
    lease_owner    TEXT,
    lease_until    TEXT,
    last_error     TEXT,
    error_type     TEXT,
    item_id        TEXT,
    discovered_at  TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_engine_candidates_identity
    ON engine_candidates (platform, canonical_url);
CREATE INDEX IF NOT EXISTS ix_engine_candidates_state
    ON engine_candidates (campaign_id, platform, state);
CREATE INDEX IF NOT EXISTS ix_engine_candidates_lease
    ON engine_candidates (state, lease_until);
CREATE INDEX IF NOT EXISTS ix_engine_candidates_run
    ON engine_candidates (engine_run_id);

CREATE TABLE IF NOT EXISTS engine_query_runs (
    query_run_id    TEXT PRIMARY KEY,
    engine_run_id   TEXT,
    campaign_id     TEXT NOT NULL,
    platform        TEXT NOT NULL,
    dimension       TEXT NOT NULL,
    keyword         TEXT NOT NULL,
    combined_query  TEXT NOT NULL,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    duplicates      INTEGER NOT NULL DEFAULT 0,
    opened_details  INTEGER NOT NULL DEFAULT 0,
    accepted        INTEGER NOT NULL DEFAULT 0,
    failure_reason  TEXT,
    duration_ms     INTEGER,
    executed_at     TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_engine_query_runs_query
    ON engine_query_runs (platform, combined_query);
CREATE INDEX IF NOT EXISTS ix_engine_query_runs_dimension
    ON engine_query_runs (campaign_id, platform, dimension);

CREATE TABLE IF NOT EXISTS engine_runs (
    engine_run_id   TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    stop_reason     TEXT,
    articles_added  INTEGER NOT NULL DEFAULT 0,
    comments_added  INTEGER NOT NULL DEFAULT 0,
    target_xiaohongshu INTEGER NOT NULL DEFAULT 0,
    target_zhihu    INTEGER NOT NULL DEFAULT 0,
    profile_dir     TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS engine_metrics (
    metric_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    engine_run_id  TEXT,
    candidate_id   TEXT,
    platform       TEXT,
    article_phase  TEXT,
    phase          TEXT NOT NULL,
    duration_ms    INTEGER NOT NULL,
    outcome        TEXT,
    error_type     TEXT,
    detail         TEXT,
    recorded_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_engine_metrics_phase
    ON engine_metrics (phase, recorded_at);
CREATE INDEX IF NOT EXISTS ix_engine_metrics_candidate
    ON engine_metrics (candidate_id);

ALTER TABLE research_artifacts ADD COLUMN bytes INTEGER;
ALTER TABLE research_artifacts ADD COLUMN updated_at TEXT;
