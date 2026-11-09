"""文章与评论去重键与内容指纹。"""

from __future__ import annotations

import hashlib

from scripts.employment.normalize import normalize_text, normalize_url


def article_identity(platform: str, canonical_url: str) -> str:
    """与 scripts.db.research_item_identity 保持一致：ri_ + 16 位哈希。"""
    normalized = normalize_url(canonical_url)
    return "ri_" + hashlib.sha256(
        f"{platform}\n{normalized}".encode("utf-8")
    ).hexdigest()[:16]


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def comment_dedupe_key(
    research_item_id: str,
    *,
    platform_comment_id: str | None = None,
    parent_comment_id: str | None = None,
    content: str | None = None,
    comment_level: int = 1,
    published_time_displayed: str | None = None,
) -> str:
    """生成评论去重键。

    有平台评论 ID 时优先使用；否则使用父评论 + 内容指纹 + 层级 + 相对时间。
    不同父评论下的相同文本不会被合并。
    """
    if platform_comment_id:
        return f"pc:{research_item_id}:{platform_comment_id}"
    digest = content_hash(content or "")
    parent = parent_comment_id or "root"
    displayed = normalize_text(published_time_displayed or "")
    return f"cc:{research_item_id}:{parent}:{comment_level}:{digest}:{displayed}"
