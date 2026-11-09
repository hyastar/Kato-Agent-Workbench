"""字段、关系与评论选择规则的校验。"""

from __future__ import annotations

from typing import Any, Iterable

from scripts.employment.deduplicate import content_hash
from scripts.employment.models import (
    AUTHOR_FIELDS,
    COHORTS,
    COVERAGE_STATUSES,
    PLATFORMS,
    RECRUITMENT_STAGES,
    SORT_BASES,
    SOURCE_TYPES,
    TOPICS,
    VERIFICATION_STATUSES,
)
from scripts.employment.normalize import (
    ensure_iso8601,
    normalize_enum,
    normalize_text,
    normalize_url,
    redact_contacts,
    relative_time_displayed,
)

COMMENT_LIMIT = 50
HIGH_LIKE_QUOTA = 30
LATEST_QUOTA = 20


class ValidationError(ValueError):
    """输入或关系不合法。"""


def _reject_author_fields(payload: dict[str, Any]) -> None:
    forbidden = sorted(set(payload) & AUTHOR_FIELDS)
    if forbidden:
        raise ValidationError(f"禁止写入评论作者身份字段：{', '.join(forbidden)}")


def _optional_text(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    text = normalize_text(str(value))
    return text or None


def validate_article(payload: dict[str, Any]) -> dict[str, Any]:
    """校验并标准化文章记录；返回可直接写入 research_items 的字段。"""
    _reject_author_fields(payload)
    platform = normalize_enum(payload.get("platform"), PLATFORMS, "platform")
    canonical_url = normalize_url(payload.get("canonical_url") or "")
    title = normalize_text(payload.get("title") or "")
    if not title:
        raise ValidationError("title 不能为空")

    source_type = normalize_enum(payload.get("source_type"), SOURCE_TYPES, "source_type")
    topic = normalize_enum(payload.get("topic"), TOPICS, "topic")
    cohort = normalize_enum(payload.get("cohort"), COHORTS, "cohort")
    stage = normalize_enum(
        payload.get("recruitment_stage"), RECRUITMENT_STAGES, "recruitment_stage"
    )
    status = normalize_enum(
        payload.get("verification_status") or "unverified",
        VERIFICATION_STATUSES,
        "verification_status",
    )
    verification_url = _optional_text(payload, "verification_url")
    verified_at = ensure_iso8601(payload.get("verified_at"), "verified_at")
    if status == "verified" and (verification_url is None or verified_at is None):
        raise ValidationError("verification_status=verified 时必须提供 verification_url 与 verified_at")
    if verification_url is not None and not verification_url.startswith(("http://", "https://")):
        raise ValidationError("verification_url 必须是 http(s) URL")

    summary = _optional_text(payload, "summary")
    if summary:
        summary, _ = redact_contacts(summary)

    return {
        "platform": platform,
        "canonical_url": canonical_url,
        "title": title,
        "summary": summary,
        "source_type": source_type,
        "topic": topic,
        "cohort": cohort,
        "recruitment_stage": stage,
        "company": _optional_text(payload, "company"),
        "city": _optional_text(payload, "city"),
        "published_at": ensure_iso8601(payload.get("published_at"), "published_at"),
        "verification_status": status,
        "verification_url": verification_url,
        "verified_at": verified_at,
    }


def validate_comment(payload: dict[str, Any]) -> dict[str, Any]:
    """校验、脱敏并标准化一条评论。"""
    _reject_author_fields(payload)
    research_item_id = normalize_text(payload.get("research_item_id") or "")
    if not research_item_id:
        raise ValidationError("research_item_id 不能为空")

    content = normalize_text(payload.get("content") or "")
    if not content:
        raise ValidationError("评论内容不能为空")
    content, redacted = redact_contacts(content)

    try:
        level = int(payload.get("comment_level", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("comment_level 必须是整数") from exc
    if level < 1:
        raise ValidationError("comment_level 必须 >= 1")

    parent = _optional_text(payload, "parent_comment_id")
    root = _optional_text(payload, "root_comment_id")
    if level == 1:
        if parent or root:
            raise ValidationError("一级评论不能设置 parent_comment_id / root_comment_id")
    else:
        if not parent:
            raise ValidationError("楼中楼必须提供 parent_comment_id")
        if not root:
            raise ValidationError("楼中楼必须提供 root_comment_id")

    like_count = payload.get("like_count")
    if like_count is not None:
        like_count = int(like_count)
        if like_count < 0:
            raise ValidationError("like_count 不能为负数")
    reply_count = payload.get("reply_count_displayed")
    if reply_count is not None:
        reply_count = int(reply_count)
        if reply_count < 0:
            raise ValidationError("reply_count_displayed 不能为负数")

    sort_basis = normalize_enum(
        payload.get("sort_basis") or "visible_order", SORT_BASES, "sort_basis"
    )
    published_at = ensure_iso8601(payload.get("published_at"), "published_at")
    displayed = relative_time_displayed(payload.get("published_time_displayed"))

    return {
        "research_item_id": research_item_id,
        "platform_comment_id": _optional_text(payload, "platform_comment_id"),
        "parent_comment_id": parent,
        "root_comment_id": root,
        "comment_level": level,
        "content": content,
        "content_hash": content_hash(content),
        "like_count": like_count,
        "reply_count_displayed": reply_count,
        "published_at": published_at,
        "published_time_displayed": displayed,
        "collected_at": ensure_iso8601(payload.get("collected_at"), "collected_at"),
        "collection_order": int(payload.get("collection_order", 0)),
        "sort_basis": sort_basis,
        "redaction_status": "redacted" if redacted else "clean",
    }


def select_comments(
    candidates: Iterable[dict[str, Any]],
    total_displayed: int,
    *,
    limit: int = COMMENT_LIMIT,
) -> tuple[list[dict[str, Any]], str]:
    """按 V4 规则选择一级评论。

    返回 (选中评论列表, 排序策略)。候选需包含 id / like_count / order。
    总数不超过上限时按可见顺序全部返回；超过时高赞前 30 + 最新前 20，
    去重后不足 limit 时从剩余可见候选补足。
    """
    items = list(candidates)
    if limit < 1:
        raise ValidationError("limit 必须 >= 1")
    if total_displayed <= limit:
        return items[:limit], "visible_order"

    if any(item.get("like_count") is None for item in items):
        return items[:limit], "visible_order"

    high = sorted(items, key=lambda item: (-int(item["like_count"]), int(item.get("order", 0))))[
        :HIGH_LIKE_QUOTA
    ]
    latest = sorted(items, key=lambda item: int(item.get("order", 0)), reverse=True)[
        :LATEST_QUOTA
    ]

    selected: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for item in [*high, *latest]:
        key = item.get("id")
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)

    for item in items:
        if len(selected) >= limit:
            break
        key = item.get("id")
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)

    return selected[:limit], "high_likes_then_latest"


def validate_comment_tree(comments: Iterable[dict[str, Any]]) -> None:
    """校验内部评论父子关系：一级评论有 root 自身、楼中楼父节点存在且层级正确。"""
    rows = list(comments)
    by_id = {row["comment_id"]: row for row in rows if row.get("comment_id")}
    for row in rows:
        comment_id = row.get("comment_id")
        level = int(row.get("comment_level", 1))
        parent = row.get("parent_comment_id")
        root = row.get("root_comment_id")
        if level == 1:
            if parent is not None:
                raise ValidationError(f"一级评论 {comment_id} 不应有父评论")
            if comment_id and root not in (None, comment_id):
                raise ValidationError(f"一级评论 {comment_id} 的 root_comment_id 必须为空或自身")
            continue
        if not parent:
            raise ValidationError(f"楼中楼 {comment_id} 缺少父评论")
        if parent not in by_id:
            raise ValidationError(f"楼中楼 {comment_id} 的父评论 {parent} 不存在")
        if parent == comment_id:
            raise ValidationError(f"评论 {comment_id} 不能以自身为父评论")
        if not root:
            raise ValidationError(f"楼中楼 {comment_id} 缺少 root_comment_id")
        if root not in by_id:
            raise ValidationError(f"楼中楼 {comment_id} 的根评论 {root} 不存在")
        if int(by_id[root].get("comment_level", 1)) != 1:
            raise ValidationError(f"楼中楼 {comment_id} 的根评论 {root} 不是一级评论")
        if level <= int(by_id[parent].get("comment_level", 1)):
            raise ValidationError(f"楼中楼 {comment_id} 的层级必须大于父评论")


def validate_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """校验评论统计字段。"""
    try:
        coverage = normalize_enum(
            stats.get("coverage_status"), COVERAGE_STATUSES, "coverage_status"
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    cleaned = {**stats, "coverage_status": coverage}
    for field in (
        "displayed_total",
        "displayed_top_level",
        "collected_top_level",
        "displayed_replies",
        "collected_replies",
    ):
        value = cleaned.get(field)
        if value is not None:
            value = int(value)
            if value < 0:
                raise ValidationError(f"{field} 不能为负数")
            cleaned[field] = value
    return cleaned
