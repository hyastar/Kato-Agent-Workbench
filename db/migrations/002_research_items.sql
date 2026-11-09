PRAGMA foreign_keys = ON;

-- 002_research_items.sql — 就业/行业情报研究工作流的增量结构。
-- 不修改 001；保留 tasks / runs / datasets / run_datasets 及既有数据。

CREATE TABLE IF NOT EXISTS research_items (
    item_id            TEXT PRIMARY KEY,
    platform           TEXT NOT NULL
                       CHECK (platform IN ('zhihu', 'xiaohongshu', 'official', 'media', 'other')),
    canonical_url      TEXT NOT NULL,
    title              TEXT NOT NULL,
    summary            TEXT,
    source_type        TEXT NOT NULL
                       CHECK (source_type IN ('official', 'reported', 'ugc', 'search_lead')),
    topic              TEXT NOT NULL
                       CHECK (topic IN ('recruitment', 'experience', 'policy', 'industry',
                                        'salary', 'warning', 'other')),
    cohort             TEXT NOT NULL
                       CHECK (cohort IN ('2026', '2027', 'unknown')),
    recruitment_stage  TEXT NOT NULL
                       CHECK (recruitment_stage IN ('autumn', 'spring', 'makeup', 'early',
                                                    'internship', 'other', 'unknown')),
    company            TEXT,
    city               TEXT,
    published_at       TEXT,
    collected_at       TEXT NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'unverified'
                       CHECK (verification_status IN ('unverified', 'verified',
                                                      'conflicting', 'stale')),
    verification_url   TEXT,
    verified_at        TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- verified 必须有可追溯证据与核验时间。
    CHECK (verification_status != 'verified'
           OR (verification_url IS NOT NULL AND verified_at IS NOT NULL))
);

-- 平台 + 规范化 URL 是研究条目的身份；跨平台同名链接不合并。
CREATE UNIQUE INDEX IF NOT EXISTS ux_research_items_identity
    ON research_items (platform, canonical_url);

CREATE INDEX IF NOT EXISTS idx_research_items_cohort ON research_items(cohort);
CREATE INDEX IF NOT EXISTS idx_research_items_platform ON research_items(platform);
CREATE INDEX IF NOT EXISTS idx_research_items_topic ON research_items(topic);
CREATE INDEX IF NOT EXISTS idx_research_items_verification
    ON research_items(verification_status);

CREATE TABLE IF NOT EXISTS run_research_items (
    run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    item_id    TEXT NOT NULL REFERENCES research_items(item_id) ON DELETE CASCADE,
    action     TEXT NOT NULL
               CHECK (action IN ('discovered', 'imported', 'verified', 'updated')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (run_id, item_id, action)
);

CREATE INDEX IF NOT EXISTS idx_run_research_items_item_id
    ON run_research_items(item_id);
