"""文章、评论与索引的 Markdown 导出。"""

from __future__ import annotations

from typing import Any, Iterable

AUTHOR_KEYS = ("author", "nickname", "author_id", "user_id", "avatar", "profile_url", "location")


def _ensure_no_author(record: dict[str, Any]) -> None:
    present = [key for key in AUTHOR_KEYS if key in record and record[key] is not None]
    if present:
        raise ValueError(f"评论档案不能包含作者身份字段：{', '.join(present)}")


def render_post_markdown(article: dict[str, Any], stats: dict[str, Any] | None = None) -> str:
    stats = stats or {}
    lines = [
        f"# {article['title']}",
        "",
        f"- 平台：{article['platform']}",
        f"- 规范 URL：{article['canonical_url']}",
        f"- 届别：{article['cohort']}",
        f"- 招聘阶段：{article['recruitment_stage']}",
        f"- 主题：{article['topic']}",
        f"- 来源类型：{article['source_type']}",
        f"- 发布时间：{article.get('published_at') or '未核实'}",
        f"- 采集时间：{article.get('collected_at') or article.get('created_at') or '未记录'}",
        f"- 核验状态：{article['verification_status']}",
        "",
        "## 摘要",
        "",
        article.get("summary") or "未提供摘要。",
        "",
        "## 评论覆盖",
        "",
        f"- 页面显示评论总数：{stats.get('displayed_total', '未记录')}",
        f"- 页面显示一级评论总数：{stats.get('displayed_top_level', '未记录')}",
        f"- 实际采集一级评论：{stats.get('collected_top_level', 0)}",
        f"- 页面显示回复总数：{stats.get('displayed_replies', '未记录')}",
        f"- 实际采集楼中楼：{stats.get('collected_replies', 0)}",
        f"- 排序策略：{stats.get('sort_basis', '未记录')}",
        f"- 覆盖状态：{stats.get('coverage_status', '未记录')}",
        "",
    ]
    if stats.get("reason"):
        lines += [f"- 未采集原因：{stats['reason']}", ""]
    return "\n".join(lines)


def render_comments_markdown(
    article: dict[str, Any],
    comments: Iterable[dict[str, Any]],
    stats: dict[str, Any],
) -> str:
    rows = list(comments)
    for row in rows:
        _ensure_no_author(row)

    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for row in rows:
        _ensure_no_author(row)
        by_parent.setdefault(row.get("parent_comment_id"), []).append(row)
    for group in by_parent.values():
        group.sort(key=lambda row: int(row.get("collection_order", 0)))

    lines = [
        f"# 评论档案 — {article['title']}",
        "",
        f"- 文章：{article['canonical_url']}",
        f"- 页面显示评论总数：{stats.get('displayed_total', '未记录')}",
        f"- 页面显示一级评论总数：{stats.get('displayed_top_level', '未记录')}",
        f"- 实际采集一级评论：{stats.get('collected_top_level', 0)}",
        f"- 页面显示回复总数：{stats.get('displayed_replies', '未记录')}",
        f"- 实际采集楼中楼：{stats.get('collected_replies', 0)}",
        f"- 排序策略：{stats.get('sort_basis', '未记录')}",
        f"- 覆盖状态：{stats.get('coverage_status', '未记录')}",
        "",
        "> 本档案不包含评论作者昵称、头像、用户 ID、主页或联系方式。",
        "",
        "## 一级评论",
        "",
    ]

    def emit(comment: dict[str, Any], depth: int) -> None:
        indent = "  " * depth
        likes = comment.get("like_count")
        like_text = "点赞未显示" if likes is None else f"{likes} 赞"
        time_text = comment.get("published_at") or comment.get("published_time_displayed") or "时间未显示"
        lines.append(f"{indent}- {comment.get('content', '').strip()}")
        lines.append(f"{indent}  - {like_text} · {time_text}")
        for child in by_parent.get(comment.get("comment_id"), []):
            emit(child, depth + 1)

    top_level = by_parent.get(None, [])
    if not top_level:
        lines.append("（未采集到一级评论）")
    for comment in top_level:
        emit(comment, 0)
    lines += ["", "## 说明", "", stats.get("reason") or "无。", ""]
    return "\n".join(lines)


def render_index(articles: Iterable[dict[str, Any]], title: str = "就业情报索引") -> str:
    rows = list(articles)
    lines = [
        f"# {title}",
        "",
        f"共 {len(rows)} 篇。",
        "",
        "| 届别 | 平台 | 主题 | 标题 | 发布时间 | 核验 | 链接 |",
        "|---|---|---|---|---|---|---|",
    ]
    for article in rows:
        lines.append(
            f"| {article['cohort']} | {article['platform']} | {article['topic']} | "
            f"{article['title']} | {article.get('published_at') or '未核实'} | "
            f"{article['verification_status']} | [原文]({article['canonical_url']}) |"
        )
    lines.append("")
    return "\n".join(lines)
