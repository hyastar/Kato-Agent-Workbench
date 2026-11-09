"""Campaign、平台、届别与评论分析报告。"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.employment import artifacts, repository

KEYWORDS = (
    "简历",
    "面试",
    "笔试",
    "薪资",
    "offer",
    "补录",
    "学历",
    "实习",
    "AI",
    "焦虑",
    "毁约",
    "转正",
)


def campaign_items(conn: sqlite3.Connection, campaign_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM research_items WHERE campaign_id = ? "
            "ORDER BY platform, cohort, item_id",
            (campaign_id,),
        ).fetchall()
    ]


def campaign_comments(conn: sqlite3.Connection, campaign_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT c.* FROM research_comments c "
            "JOIN research_items r ON r.item_id = c.research_item_id "
            "WHERE r.campaign_id = ? ORDER BY c.comment_level, c.collection_order",
            (campaign_id,),
        ).fetchall()
    ]


def build_summary(conn: sqlite3.Connection, campaign_id: str) -> dict[str, Any]:
    campaign = repository.get_campaign(conn, campaign_id)
    if campaign is None:
        raise KeyError(f"Campaign 不存在：{campaign_id}")
    items = campaign_items(conn, campaign_id)
    comments = campaign_comments(conn, campaign_id)
    top_level = [row for row in comments if int(row["comment_level"]) == 1]
    nested = [row for row in comments if int(row["comment_level"]) > 1]
    keyword_counts = {
        keyword: sum(1 for row in comments if keyword.lower() in (row["content"] or "").lower())
        for keyword in KEYWORDS
    }
    top_liked = sorted(
        [row for row in top_level if row["like_count"] is not None],
        key=lambda row: int(row["like_count"]),
        reverse=True,
    )[:10]
    return {
        "campaign": dict(campaign),
        "items": items,
        "comments_total": len(comments),
        "top_level": len(top_level),
        "nested": len(nested),
        "by_platform": dict(Counter(row["platform"] for row in items)),
        "by_cohort": dict(Counter(row["cohort"] for row in items)),
        "by_topic": dict(Counter(row["topic"] for row in items)),
        "by_coverage": dict(Counter(row["comment_coverage_status"] for row in items)),
        "keyword_counts": keyword_counts,
        "top_liked": top_liked,
    }


def render_campaign_report(summary: dict[str, Any]) -> str:
    campaign = summary["campaign"]
    items = summary["items"]
    lines = [
        f"# Campaign 报告 — {campaign['name']}",
        "",
        f"- Campaign ID：`{campaign['campaign_id']}`",
        f"- 状态：`{campaign['status']}`",
        f"- 目标：{campaign['target_total']} 篇（小红书 {campaign['target_xiaohongshu']}、知乎 {campaign['target_zhihu']}）",
        f"- 实际：{len(items)} 篇",
        f"- 届别目标：2026 届 {campaign['target_2026']}、2027 届 {campaign['target_2027']}",
        "",
        "## 实际分布",
        "",
        "| 维度 | 数量 |",
        "|---|---:|",
        f"| 小红书 | {summary['by_platform'].get('xiaohongshu', 0)} |",
        f"| 知乎 | {summary['by_platform'].get('zhihu', 0)} |",
        f"| 2026 届 | {summary['by_cohort'].get('2026', 0)} |",
        f"| 2027 届 | {summary['by_cohort'].get('2027', 0)} |",
        f"| 一级评论 | {summary['top_level']} |",
        f"| 楼中楼 | {summary['nested']} |",
        "",
        "## 评论覆盖",
        "",
        "| 状态 | 文章数 |",
        "|---|---:|",
    ]
    for status in ("complete", "partial", "not_available", "blocked"):
        lines.append(f"| {status} | {summary['by_coverage'].get(status, 0)} |")
    lines += [
        "",
        "## 评论关键词（出现该词的评论数）",
        "",
        "| 关键词 | 评论数 |",
        "|---|---:|",
    ]
    for keyword, count in sorted(summary["keyword_counts"].items(), key=lambda x: -x[1]):
        lines.append(f"| {keyword} | {count} |")
    lines += ["", "## 高赞一级评论（最多 10 条，不含作者信息）", ""]
    item_titles = {item["item_id"]: item["title"] for item in items}
    for row in summary["top_liked"]:
        content = (row["content"] or "").replace("\n", " ")[:120]
        lines.append(
            f"- {row['like_count']} 赞｜{item_titles.get(row['research_item_id'], '')}：{content}"
        )
    lines += [
        "",
        "## 局限",
        "",
        "- 样本为 UGC，且实际数量远低于 1000 篇目标。",
        "- 评论覆盖按文章分别记录；`partial` / `not_available` 不代表完整评论。",
        "- 未做官方公告交叉核验；岗位、截止日期与薪资数字不能据此确认。",
        "",
    ]
    return "\n".join(lines)


def render_platform_report(
    conn: sqlite3.Connection, campaign_id: str, platform: str
) -> str:
    items = [item for item in campaign_items(conn, campaign_id) if item["platform"] == platform]
    lines = [
        f"# 平台报告 — {platform}",
        "",
        f"- 文章数：{len(items)}",
        f"- 2026 届：{sum(1 for item in items if item['cohort'] == '2026')}",
        f"- 2027 届：{sum(1 for item in items if item['cohort'] == '2027')}",
        f"- 评论覆盖完整：{sum(1 for item in items if item['comment_coverage_status'] == 'complete')}",
        "",
        "| 届别 | 主题 | 标题 | 评论覆盖 | 链接 |",
        "|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(
            f"| {item['cohort']} | {item['topic']} | {item['title']} | "
            f"{item['comment_coverage_status']} | [原文]({item['canonical_url']}) |"
        )
    lines.append("")
    return "\n".join(lines)


def render_cohort_report(
    conn: sqlite3.Connection, campaign_id: str, cohort: str
) -> str:
    items = [item for item in campaign_items(conn, campaign_id) if item["cohort"] == cohort]
    lines = [
        f"# {cohort} 届就业情报报告",
        "",
        f"- 文章数：{len(items)}",
        f"- 小红书：{sum(1 for item in items if item['platform'] == 'xiaohongshu')}",
        f"- 知乎：{sum(1 for item in items if item['platform'] == 'zhihu')}",
        "",
        "| 平台 | 主题 | 标题 | 摘要 | 评论覆盖 |",
        "|---|---|---|---|---|",
    ]
    for item in items:
        summary = (item.get("summary") or "").replace("\n", " ")[:160]
        lines.append(
            f"| {item['platform']} | {item['topic']} | {item['title']} | "
            f"{summary} | {item['comment_coverage_status']} |"
        )
    lines += [
        "",
        "> 以上均为 UGC 摘要，未做官方交叉核验。",
        "",
    ]
    return "\n".join(lines)


def write_reports(
    conn: sqlite3.Connection,
    campaign_id: str,
    *,
    root: str | Path | None = None,
) -> dict[str, str]:
    base = Path(root) if root is not None else artifacts.EMPLOYMENT_ROOT
    summary = build_summary(conn, campaign_id)
    written: dict[str, str] = {}

    def write(path: Path, text: str) -> None:
        meta = artifacts.write_text_artifact(path, text)
        repository.upsert_artifact(
            conn,
            item_id=None,
            artifact_type="report",
            relative_path=str(meta["relative_path"]),
            sha256=str(meta["sha256"]),
        )
        written[path.name] = str(meta["relative_path"])

    campaign_path = base / "reports" / "campaigns" / f"{campaign_id}.md"
    write(campaign_path, render_campaign_report(summary))

    for platform in ("xiaohongshu", "zhihu"):
        write(
            base / "reports" / "platforms" / f"{platform}.md",
            render_platform_report(conn, campaign_id, platform),
        )
    for cohort in ("2026", "2027"):
        write(
            base / "reports" / "cohorts" / f"{cohort}.md",
            render_cohort_report(conn, campaign_id, cohort),
        )
    return written
