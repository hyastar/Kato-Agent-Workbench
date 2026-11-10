PRAGMA foreign_keys = ON;

-- 006_v62_keyword_scheduler.sql — V6.2 关键词库与调度统计扩展。
-- 只新增列与索引，不修改已应用迁移、不改动历史文章与评论。
-- 新列全部允许为空/有默认值，旧数据无需回填。

-- 分类辅助维度（按正文内容判定，不依赖搜索关键词）
ALTER TABLE research_items ADD COLUMN employment_type TEXT;
ALTER TABLE research_items ADD COLUMN benefits TEXT;

CREATE INDEX IF NOT EXISTS idx_research_items_employment_type
    ON research_items(employment_type);
CREATE INDEX IF NOT EXISTS idx_research_items_benefits
    ON research_items(benefits);

-- 搜索效率拆解：区分批内重复、历史重复、无效 URL、相关性合格
ALTER TABLE engine_query_runs ADD COLUMN new_candidates INTEGER NOT NULL DEFAULT 0;
ALTER TABLE engine_query_runs ADD COLUMN duplicate_in_batch INTEGER NOT NULL DEFAULT 0;
ALTER TABLE engine_query_runs ADD COLUMN duplicate_with_history INTEGER NOT NULL DEFAULT 0;
ALTER TABLE engine_query_runs ADD COLUMN invalid_urls INTEGER NOT NULL DEFAULT 0;
ALTER TABLE engine_query_runs ADD COLUMN relevance_passed INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_engine_query_runs_keyword
    ON engine_query_runs (campaign_id, platform, keyword);

-- 动态关键词候选（从真实文章中发现，需人工/规则复核后才进入查询队列）
CREATE TABLE IF NOT EXISTS engine_dynamic_keywords (
    keyword        TEXT NOT NULL,
    dimension      TEXT,
    source_platform TEXT,
    occurrences    INTEGER NOT NULL DEFAULT 1,
    status         TEXT NOT NULL DEFAULT 'candidate'
                   CHECK (status IN ('candidate', 'approved', 'rejected')),
    sample_item_id TEXT,
    first_seen_at  TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (keyword, source_platform)
);
