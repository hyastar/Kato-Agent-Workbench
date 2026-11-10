"""评论树构建：把浏览器返回的扁平/嵌套结构恢复成父子关系。

- 小红书：DOM 已给出包含关系，浏览器脚本返回嵌套数组，直接转换；
- 知乎：DOM 没有稳定评论 ID，只能按缩进（left px）判断层级，
  这里用栈构建，缩进差 ≤ 阈值视为同一层。

只用数据，不依赖浏览器。
"""

from __future__ import annotations

from typing import Any, Iterable

from kato_engine.collection.models import CommentNode

INDENT_THRESHOLD_PX = 15


def _parse_int(value: Any) -> int | None:
    import re

    if value is None:
        return None
    match = re.search(r"\d+", str(value).replace(",", ""))
    return int(match.group(0)) if match else None


def clean_date_text(text: Any) -> str | None:
    """只保留时间片段，丢弃 IP 归属地等附加信息。"""
    import re

    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    raw = re.sub(r"^\s*(编辑于|发布于|修改于)\s*", "", raw)
    pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?"
        r"|\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?"
        r"|昨天(?:\s*\d{1,2}:\d{2})?"
        r"|前天(?:\s*\d{1,2}:\d{2})?"
        r"|\d+\s*(?:秒|分钟|小时|天|周|个月|年)前)"
    )
    match = pattern.match(raw)
    return match.group(1).strip() if match else None


def node_from_nested(raw: dict[str, Any], level: int = 1) -> CommentNode | None:
    """小红书：嵌套结构 → CommentNode。"""
    content = str(raw.get("content") or "").strip() or "[无文字内容]"
    children = [
        node
        for child in raw.get("children") or []
        if isinstance(child, dict) and (node := node_from_nested(child, level + 1)) is not None
    ]
    comment_id = raw.get("id")
    return CommentNode(
        content=content,
        platform_comment_id=(str(comment_id) if comment_id else None),
        like_count=_parse_int(raw.get("like_text")),
        published_time_displayed=clean_date_text(raw.get("date_text")),
        reply_count_displayed=_parse_int(raw.get("reply_text")),
        level=level,
        children=children,
    )


def nodes_from_nested(raw_nodes: Iterable[dict[str, Any]]) -> list[CommentNode]:
    nodes: list[CommentNode] = []
    for raw in raw_nodes or []:
        if not isinstance(raw, dict):
            continue
        node = node_from_nested(raw, 1)
        if node is not None and node.content:
            nodes.append(node)
    return nodes


def nodes_from_indentation(
    flat_nodes: Iterable[dict[str, Any]],
    *,
    threshold_px: int = INDENT_THRESHOLD_PX,
) -> list[CommentNode]:
    """知乎：按 left 缩进恢复层级（不做文本去重）。"""
    prepared: list[tuple[int, CommentNode]] = []
    for raw in flat_nodes or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        prepared.append(
            (
                int(raw.get("left") or 0),
                CommentNode(
                    content=text,
                    platform_comment_id=None,
                    like_count=_parse_int(raw.get("like_text")),
                    published_time_displayed=clean_date_text(raw.get("time_text")),
                ),
            )
        )

    roots: list[CommentNode] = []
    stack: list[tuple[int, CommentNode]] = []
    for left, node in prepared:
        while stack and left <= stack[-1][0] + threshold_px:
            stack.pop()
        if stack:
            parent = stack[-1][1]
            node.level = parent.level + 1
            parent.children.append(node)
        else:
            node.level = 1
            roots.append(node)
        stack.append((left, node))
    return roots
