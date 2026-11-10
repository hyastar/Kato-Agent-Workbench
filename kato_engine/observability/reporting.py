"""统计与报告：从 SQLite 汇总真实结果，不估算、不补造。

输出分三块：
1. 数据结果：文章、评论、楼中楼、主题/届别/平台分布、覆盖状态；
2. 执行质量：成功/失败/重试、关键词命中、去重率、恢复情况；
3. 性能：分阶段耗时、每小时产出、每篇平均耗时。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from scripts import db

from kato_engine.config.settings import Settings
from kato_engine.storage.markdown import verify_artifacts


def _rows(conn, sql: str, params: tuple = ()):  # noqa: ANN001
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def build_report(
    repo,
    settings: Settings,
    campaign_id: str,
    *,
    engine_run_id: str | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    conn = repo.conn
    campaign = repo.get_campaign(campaign_id)
    if campaign is None:
        raise KeyError(f"Campaign 不存在：{campaign_id}")

    platform_counts = repo.campaign_article_counts(campaign_id)
    dimension_counts = repo.dimension_article_counts(campaign_id)
    cohort_counts = {
        row["graduation_cohort"] or "unknown": row["n"]
        for row in conn.execute(
            "SELECT COALESCE(graduation_cohort, 'unknown') AS graduation_cohort, COUNT(*) AS n "
            "FROM research_items WHERE campaign_id = ? GROUP BY 1",
            (campaign_id,),
        ).fetchall()
    }
    coverage_counts = {
        row["comment_coverage_status"]: row["n"]
        for row in conn.execute(
            "SELECT comment_coverage_status, COUNT(*) AS n FROM research_items "
            "WHERE campaign_id = ? GROUP BY 1",
            (campaign_id,),
        ).fetchall()
    }
    comment_stats = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN comment_level = 1 THEN 1 ELSE 0 END) AS top_level, "
        "SUM(CASE WHEN comment_level > 1 THEN 1 ELSE 0 END) AS nested "
        "FROM research_comments WHERE research_item_id IN "
        "(SELECT item_id FROM research_items WHERE campaign_id = ?)",
        (campaign_id,),
    ).fetchone()

    candidate_states = repo.candidate_state_counts(campaign_id=campaign_id)
    query_stats = conn.execute(
        "SELECT COUNT(*) AS queries, COALESCE(SUM(candidates_found), 0) AS found, "
        "COALESCE(SUM(duplicates), 0) AS duplicates, COALESCE(SUM(accepted), 0) AS accepted, "
        "COALESCE(AVG(duration_ms), 0) AS avg_ms FROM engine_query_runs WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()

    phase_metrics = {
        row["phase"]: {
            "count": row["n"],
            "avg_ms": round(float(row["avg_ms"] or 0), 1),
            "max_ms": int(row["max_ms"] or 0),
        }
        for row in conn.execute(
            "SELECT phase, COUNT(*) AS n, AVG(duration_ms) AS avg_ms, MAX(duration_ms) AS max_ms "
            "FROM engine_metrics GROUP BY phase ORDER BY phase"
        ).fetchall()
    }
    error_counts = {
        row["error_type"] or "none": row["n"]
        for row in conn.execute(
            "SELECT error_type, COUNT(*) AS n FROM engine_candidates "
            "WHERE campaign_id = ? AND error_type IS NOT NULL GROUP BY 1 ORDER BY n DESC",
            (campaign_id,),
        ).fetchall()
    }

    runs = _rows(
        conn,
        "SELECT engine_run_id, started_at, finished_at, stop_reason, articles_added, "
        "comments_added, target_xiaohongshu, target_zhihu FROM engine_runs "
        "WHERE campaign_id = ? ORDER BY started_at",
        (campaign_id,),
    )
    run_detail: dict[str, Any] | None = None
    if engine_run_id:
        row = conn.execute(
            "SELECT COUNT(*) AS accepted FROM engine_candidates WHERE engine_run_id = ? "
            "AND state IN ('accepted', 'completed')",
            (engine_run_id,),
        ).fetchone()
        run_detail = {"engine_run_id": engine_run_id, "accepted_candidates": int(row["accepted"])}

    total_articles = sum(platform_counts.values())
    total_seconds = 0.0
    for entry in runs:
        if entry["started_at"] and entry["finished_at"]:
            total_seconds += _seconds_between(entry["started_at"], entry["finished_at"])

    report: dict[str, Any] = {
        "campaign": {
            "campaign_id": campaign_id,
            "name": campaign["name"],
            "status": campaign["status"],
            "target_total": int(campaign["target_total"]),
            "actual_total": total_articles,
            "stored_actual_total": int(campaign["actual_total"]),
            "target_xiaohongshu": int(campaign["target_xiaohongshu"]),
            "target_zhihu": int(campaign["target_zhihu"]),
        },
        "articles": {
            "by_platform": platform_counts,
            "total": total_articles,
            "by_dimension": dimension_counts,
            "by_cohort": cohort_counts,
            "by_coverage": coverage_counts,
        },
        "comments": {
            "total": int(comment_stats["total"] or 0),
            "top_level": int(comment_stats["top_level"] or 0),
            "nested": int(comment_stats["nested"] or 0),
        },
        "quality": {
            "candidate_states": candidate_states,
            "errors": error_counts,
            "queries": {
                "total": int(query_stats["queries"]),
                "candidates_found": int(query_stats["found"]),
                "duplicates": int(query_stats["duplicates"]),
                "accepted": int(query_stats["accepted"]),
                "avg_ms": round(float(query_stats["avg_ms"] or 0), 1),
                "duplicate_rate": round(
                    int(query_stats["duplicates"]) / max(int(query_stats["found"]), 1), 3
                ),
            },
            "phase_metrics": phase_metrics,
        },
        "runs": runs,
        "run_detail": run_detail,
        "performance": {
            "engine_seconds": round(total_seconds, 1),
            "articles_per_hour": round(
                sum(int(entry["articles_added"]) for entry in runs) / max(total_seconds / 3600, 0.001),
                1,
            ),
            "seconds_per_article": round(
                total_seconds / max(sum(int(entry["articles_added"]) for entry in runs), 1), 1
            ),
        },
    }
    if verify:
        report["artifacts"] = verify_artifacts(settings, repo)
    return report


def _seconds_between(start: str, end: str) -> float:
    from datetime import datetime

    try:
        left = datetime.fromisoformat(start.replace("Z", "+00:00"))
        right = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max((right - left).total_seconds(), 0.0)
    except ValueError:
        return 0.0


def render_report_markdown(report: dict[str, Any]) -> str:
    campaign = report["campaign"]
    articles = report["articles"]
    comments = report["comments"]
    quality = report["quality"]
    performance = report["performance"]
    artifacts = report.get("artifacts")

    lines = [
        "# 就业情报 V6 采集报告",
        "",
        f"- Campaign：`{campaign['campaign_id']}`",
        f"- 状态：{campaign['status']}",
        f"- 进度：{campaign['actual_total']} / {campaign['target_total']}",
        "",
        "## 文章",
        "",
        f"- 合计：{articles['total']}",
    ]
    for platform, count in sorted(articles["by_platform"].items()):
        lines.append(f"- {platform}：{count}")
    lines += ["", "### 主题分布", ""]
    for dimension, count in sorted(articles["by_dimension"].items(), key=lambda item: -item[1]):
        lines.append(f"- {dimension}：{count}")
    lines += ["", "### 届别分布", ""]
    for cohort, count in sorted(articles["by_cohort"].items()):
        lines.append(f"- {cohort}：{count}")
    lines += ["", "### 评论覆盖", ""]
    for status, count in sorted(articles["by_coverage"].items()):
        lines.append(f"- {status}：{count}")

    lines += [
        "",
        "## 评论",
        "",
        f"- 合计：{comments['total']}",
        f"- 一级评论：{comments['top_level']}",
        f"- 楼中楼：{comments['nested']}",
        "",
        "## 执行质量",
        "",
        "### 候选状态",
        "",
    ]
    for state, count in sorted(quality["candidate_states"].items()):
        lines.append(f"- {state}：{count}")
    lines += ["", "### 错误分类", ""]
    if quality["errors"]:
        for error_type, count in quality["errors"].items():
            lines.append(f"- {error_type}：{count}")
    else:
        lines.append("- 无")
    queries = quality["queries"]
    lines += [
        "",
        "### 关键词执行",
        "",
        f"- 查询次数：{queries['total']}",
        f"- 候选总数：{queries['candidates_found']}",
        f"- 重复数：{queries['duplicates']}（重复率 {queries['duplicate_rate']:.1%}）",
        f"- 采纳数：{queries['accepted']}",
        f"- 平均搜索耗时：{queries['avg_ms']} ms",
        "",
        "## 性能",
        "",
        f"- 引擎运行总时长：{performance['engine_seconds']} 秒",
        f"- 每小时新增文章：{performance['articles_per_hour']}",
        f"- 平均每篇耗时：{performance['seconds_per_article']} 秒",
        "",
        "### 分阶段耗时",
        "",
        "| 阶段 | 次数 | 平均 (ms) | 最大 (ms) |",
        "|---|---:|---:|---:|",
    ]
    for phase, metrics in sorted(quality["phase_metrics"].items()):
        lines.append(f"| {phase} | {metrics['count']} | {metrics['avg_ms']} | {metrics['max_ms']} |")

    if artifacts:
        lines += [
            "",
            "## 档案校验",
            "",
            f"- 校验产物：{artifacts['checked']}",
            f"- 缺失：{artifacts['missing_count']}",
            f"- 哈希不一致：{artifacts['mismatched_count']}",
        ]

    lines += ["", "## 运行记录", "", "| engine_run_id | 开始 | 结束 | 停止原因 | 新增 | 评论 |", "|---|---|---|---|---:|---:|"]
    for entry in report["runs"]:
        lines.append(
            f"| {entry['engine_run_id']} | {entry['started_at']} | {entry['finished_at'] or '未结束'} | "
            f"{entry['stop_reason'] or '-'} | {entry['articles_added']} | {entry['comments_added']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], json_path, markdown_path) -> None:  # noqa: ANN001
    from pathlib import Path

    json_target = Path(json_path)
    md_target = Path(markdown_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_target.write_text(render_report_markdown(report), encoding="utf-8", newline="")
