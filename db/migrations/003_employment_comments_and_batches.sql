PRAGMA foreign_keys = OFF;

-- 003_employment_comments_and_batches.sql — V4 就业情报结构。
-- 不修改 001 / 002。为扩展核验状态并加入评论统计，重建 research_items
-- （迁移期间关闭外键，结束后由 apply_migrations 做 foreign_key_check）。

CREATE TABLE research_items_new (
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
                       CHECK (verification_status IN ('unverified', 'partially_verified',
                                                      'verified', 'contradicted', 'expired')),
    verification_url   TEXT,
    verified_at        TEXT,
    -- V4 评论统计与档案字段
    displayed_comments_total INTEGER,
    displayed_top_level      INTEGER,
    collected_top_level      INTEGER NOT NULL DEFAULT 0,
    displayed_replies_total  INTEGER,
    collected_replies        INTEGER NOT NULL DEFAULT 0,
    comment_coverage_status  TEXT NOT NULL DEFAULT 'not_available'
                             CHECK (comment_coverage_status IN ('complete', 'partial',
                                                                'blocked', 'not_available')),
    comment_sort_basis       TEXT,
    campaign_id              TEXT,
    batch_id                 TEXT,
    post_markdown_path       TEXT,
    comments_markdown_path   TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (verification_status != 'verified'
           OR (verification_url IS NOT NULL AND verified_at IS NOT NULL))
);

INSERT INTO research_items_new (
    item_id, platform, canonical_url, title, summary, source_type, topic, cohort,
    recruitment_stage, company, city, published_at, collected_at, verification_status,
    verification_url, verified_at, created_at, updated_at
)
SELECT
    item_id, platform, canonical_url, title, summary, source_type, topic, cohort,
    recruitment_stage, company, city, published_at, collected_at, verification_status,
    verification_url, verified_at, created_at, updated_at
FROM research_items;

DROP TABLE research_items;
ALTER TABLE research_items_new RENAME TO research_items;

CREATE UNIQUE INDEX IF NOT EXISTS ux_research_items_identity
    ON research_items (platform, canonical_url);
CREATE INDEX IF NOT EXISTS idx_research_items_cohort ON research_items(cohort);
CREATE INDEX IF NOT EXISTS idx_research_items_platform ON research_items(platform);
CREATE INDEX IF NOT EXISTS idx_research_items_topic ON research_items(topic);
CREATE INDEX IF NOT EXISTS idx_research_items_verification
    ON research_items(verification_status);
CREATE INDEX IF NOT EXISTS idx_research_items_campaign ON research_items(campaign_id);
CREATE INDEX IF NOT EXISTS idx_research_items_batch ON research_items(batch_id);

CREATE TABLE IF NOT EXISTS research_comments (
    comment_id              TEXT PRIMARY KEY,
    research_item_id        TEXT NOT NULL REFERENCES research_items(item_id) ON DELETE CASCADE,
    platform_comment_id     TEXT,
    parent_comment_id       TEXT REFERENCES research_comments(comment_id) ON DELETE CASCADE,
    root_comment_id         TEXT REFERENCES research_comments(comment_id) ON DELETE CASCADE,
    comment_level           INTEGER NOT NULL CHECK (comment_level >= 1),
    content                 TEXT NOT NULL,
    content_hash            TEXT NOT NULL,
    like_count              INTEGER CHECK (like_count IS NULL OR like_count >= 0),
    reply_count_displayed   INTEGER CHECK (reply_count_displayed IS NULL OR reply_count_displayed >= 0),
    published_at            TEXT,
    published_time_displayed TEXT,
    collected_at            TEXT NOT NULL,
    collection_order        INTEGER NOT NULL DEFAULT 0,
    sort_basis              TEXT NOT NULL DEFAULT 'visible_order'
                            CHECK (sort_basis IN ('high_likes', 'latest',
                                                  'high_likes_then_latest', 'visible_order')),
    redaction_status        TEXT NOT NULL DEFAULT 'clean',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((comment_level = 1 AND parent_comment_id IS NULL)
           OR (comment_level > 1 AND parent_comment_id IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_research_comments_platform_id
    ON research_comments (research_item_id, platform_comment_id);
CREATE INDEX IF NOT EXISTS idx_research_comments_item ON research_comments(research_item_id);
CREATE INDEX IF NOT EXISTS idx_research_comments_parent ON research_comments(parent_comment_id);
CREATE INDEX IF NOT EXISTS idx_research_comments_root ON research_comments(root_comment_id);
CREATE INDEX IF NOT EXISTS idx_research_comments_fallback
    ON research_comments (research_item_id, parent_comment_id, content_hash, comment_level);

CREATE TABLE IF NOT EXISTS research_campaigns (
    campaign_id       TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'running', 'partial',
                                        'completed', 'blocked', 'failed')),
    target_total      INTEGER,
    target_xiaohongshu INTEGER,
    target_zhihu      INTEGER,
    target_2026       INTEGER,
    target_2027       INTEGER,
    actual_total      INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at        TEXT,
    finished_at       TEXT,
    notes             TEXT
);

CREATE TABLE IF NOT EXISTS research_batches (
    batch_id          TEXT PRIMARY KEY,
    campaign_id       TEXT NOT NULL REFERENCES research_campaigns(campaign_id) ON DELETE CASCADE,
    platform          TEXT NOT NULL
                      CHECK (platform IN ('zhihu', 'xiaohongshu', 'official', 'media', 'other')),
    cohort            TEXT NOT NULL
                      CHECK (cohort IN ('2026', '2027', 'unknown')),
    keyword           TEXT,
    target_articles   INTEGER NOT NULL DEFAULT 0,
    discovered        INTEGER NOT NULL DEFAULT 0,
    succeeded         INTEGER NOT NULL DEFAULT 0,
    failed            INTEGER NOT NULL DEFAULT 0,
    top_level_comments INTEGER NOT NULL DEFAULT 0,
    nested_replies    INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'running', 'partial',
                                        'completed', 'blocked', 'failed')),
    checkpoint_path   TEXT,
    started_at        TEXT,
    finished_at       TEXT,
    error_summary     TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_batches_campaign ON research_batches(campaign_id);
CREATE INDEX IF NOT EXISTS idx_research_batches_status ON research_batches(status);

CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id       TEXT PRIMARY KEY,
    research_item_id  TEXT REFERENCES research_items(item_id) ON DELETE CASCADE,
    artifact_type     TEXT NOT NULL
                      CHECK (artifact_type IN ('post_markdown', 'comments_markdown',
                                               'index', 'report')),
    relative_path     TEXT NOT NULL,
    sha256            TEXT NOT NULL,
    generated_at      TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'present'
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_research_artifacts_path
    ON research_artifacts (relative_path);
CREATE INDEX IF NOT EXISTS idx_research_artifacts_item ON research_artifacts(research_item_id);

PRAGMA foreign_keys = ON;
