"""把浏览器动作返回的原始 payload 规范化为 ArticleResult。"""

from __future__ import annotations

import re
from typing import Any

from scripts.employment.browser.contracts import (
    ArticleResult,
    ArticleTask,
    BrowserExecutionError,
    CommentNode,
)
from scripts.employment.normalize import redact_contacts
from scripts.employment.validate import select_comments

ALLOWED_ITEM_KEYS = {
    "platform_comment_id",
    "content",
    "like_text",
    "time_displayed",
    "comment_level",
    "children",
}


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _to_node(item: dict[str, Any], level: int) -> CommentNode | None:
    content = (item.get("content") or "").strip()
    if not content:
        return None
    content, _ = redact_contacts(content)
    children = [
        node
        for child in item.get("children") or []
        if isinstance(child, dict) and (node := _to_node(child, level + 1))
    ]
    return CommentNode(
        platform_comment_id=item.get("platform_comment_id") or None,
        content=content,
        like_count=_parse_int(item.get("like_text")),
        published_time_displayed=(item.get("time_displayed") or None),
        comment_level=level,
        children=children,
    )


def _count(node: CommentNode) -> int:
    return 1 + sum(_count(child) for child in node.children)


def _strip_site(title: str, platform: str) -> str:
    suffix = {"xiaohongshu": "小红书", "zhihu": "知乎"}.get(platform, "")
    if suffix:
        title = re.sub(rf"\s*-\s*{re.escape(suffix)}\s*$", "", title)
    return re.sub(r"^\(99\+.*?\)\s*", "", title).strip()


def normalize_payload(
    payload: dict[str, Any],
    task: ArticleTask,
    *,
    latest_verified: bool = False,
) -> ArticleResult:
    """规范化浏览器 payload；执行 50 条一级评论规则与覆盖判定。"""
    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list):
        raise BrowserExecutionError("payload.items 必须是数组", "schema_error")

    nodes: list[CommentNode] = []
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        node = _to_node(item, 1)
        if node is None:
            continue
        key = node.platform_comment_id or f"idx-{index}"
        candidates.append(
            {
                "id": key,
                "like_count": node.like_count,
                "order": index,
                "node": node,
            }
        )

    total_displayed = payload.get("displayed_total")
    selected, basis = select_comments(
        candidates,
        int(total_displayed) if total_displayed is not None else len(candidates),
        limit=task.comment_limit,
        latest_verified=latest_verified,
    )
    nodes = [row["node"] for row in selected]

    top_level = len(nodes)
    replies = sum(_count(node) - 1 for node in nodes)
    capped = len(candidates) > task.comment_limit

    if total_displayed is None:
        coverage = "not_available" if top_level + replies == 0 else "partial"
    elif capped or top_level + replies < int(total_displayed):
        coverage = "partial"
    else:
        coverage = "complete"

    reason = None
    if capped:
        reason = (
            "页面未提供可核实的最新排序；按高赞选择并用可见顺序补足 50 条，"
            "其余一级评论未采集。"
            if not latest_verified
            else "按高赞 30 + 最新 20 选择，其余一级评论未采集。"
        )
    elif coverage == "partial":
        reason = "页面显示评论数大于实际可采集数；部分回复未展开或未加载。"
    elif coverage == "not_available":
        reason = "页面未显示评论数，且未加载到评论。"

    return ArticleResult(
        task=task,
        title=_strip_site(str(payload.get("title") or ""), task.platform),
        url=str(payload.get("url") or task.url or ""),
        backend="mcp_batch",
        displayed_total=int(total_displayed) if total_displayed is not None else None,
        collected_top_level=top_level,
        collected_replies=replies,
        coverage_status=coverage,
        sort_basis=basis,
        reason=reason,
        comments=nodes,
        status="ok",
    )
