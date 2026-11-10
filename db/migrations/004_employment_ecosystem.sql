PRAGMA foreign_keys = ON;

-- 004_employment_ecosystem.sql — 就业生态分类与搜索查询记录。
-- 不修改 001–003；旧数据保留，新字段可为空。

ALTER TABLE research_items ADD COLUMN employment_topic TEXT;
ALTER TABLE research_items ADD COLUMN employment_status TEXT;
ALTER TABLE research_items ADD COLUMN industry TEXT;
ALTER TABLE research_items ADD COLUMN graduation_cohort TEXT;
ALTER TABLE research_items ADD COLUMN event_year INTEGER;
ALTER TABLE research_items ADD COLUMN salary_reported INTEGER;
ALTER TABLE research_items ADD COLUMN experience_type TEXT;

CREATE INDEX IF NOT EXISTS idx_research_items_employment_topic
    ON research_items(employment_topic);
CREATE INDEX IF NOT EXISTS idx_research_items_employment_status
    ON research_items(employment_status);
CREATE INDEX IF NOT EXISTS idx_research_items_graduation_cohort
    ON research_items(graduation_cohort);

CREATE TABLE IF NOT EXISTS research_search_queries (
    query_id       TEXT PRIMARY KEY,
    batch_id       TEXT,
    platform       TEXT NOT NULL,
    dimension      TEXT NOT NULL,
    keyword        TEXT NOT NULL,
    raw_count      INTEGER NOT NULL DEFAULT 0,
    unique_count   INTEGER NOT NULL DEFAULT 0,
    new_count      INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    executed_at    TEXT NOT NULL,
    notes          TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_search_queries_batch
    ON research_search_queries(batch_id);
CREATE INDEX IF NOT EXISTS idx_research_search_queries_dimension
    ON research_search_queries(dimension);

CREATE TABLE IF NOT EXISTS research_keyword_candidates (
    keyword        TEXT NOT NULL,
    dimension      TEXT NOT NULL,
    source_batch   TEXT,
    status         TEXT NOT NULL DEFAULT 'candidate',
    notes          TEXT,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (keyword, dimension)
);
