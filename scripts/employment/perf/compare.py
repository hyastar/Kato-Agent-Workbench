"""A/B 比较与采纳门槛。

门槛是评价条件，不是保证；样本量小时只描述观察结果。
"""

from __future__ import annotations

from typing import Any


def compare_summaries(
    baseline: dict[str, Any], optimized: dict[str, Any]
) -> dict[str, Any]:
    baseline_wall = baseline.get("total_wall_ms") or 0
    optimized_wall = optimized.get("total_wall_ms") or 0
    speedup = round(baseline_wall / optimized_wall, 3) if optimized_wall else None
    return {
        "baseline_cases": baseline.get("cases"),
        "optimized_cases": optimized.get("cases"),
        "baseline_total_wall_ms": baseline_wall,
        "optimized_total_wall_ms": optimized_wall,
        "speedup": speedup,
        "baseline_mean_ms": baseline.get("mean_ms"),
        "optimized_mean_ms": optimized.get("mean_ms"),
        "baseline_p50_ms": baseline.get("p50_ms"),
        "optimized_p50_ms": optimized.get("p50_ms"),
        "baseline_p95_ms": baseline.get("p95_ms"),
        "optimized_p95_ms": optimized.get("p95_ms"),
        "baseline_articles_per_hour": baseline.get("articles_per_hour"),
        "optimized_articles_per_hour": optimized.get("articles_per_hour"),
        "baseline_tool_calls": baseline.get("browser_tool_calls"),
        "optimized_tool_calls": optimized.get("browser_tool_calls"),
    }


def adoption_gate(
    baseline: dict[str, Any],
    optimized: dict[str, Any],
    *,
    required_speedup: float = 1.3,
) -> dict[str, Any]:
    """检查是否达到最低采纳门槛（速度 + 质量不退化）。"""
    reasons: list[str] = []
    comparison = compare_summaries(baseline, optimized)

    if baseline.get("cases") != optimized.get("cases"):
        reasons.append(
            f"样本数不同：baseline={baseline.get('cases')} optimized={optimized.get('cases')}"
        )
    if (optimized.get("success_rate") or 0) < (baseline.get("success_rate") or 0):
        reasons.append("优化方案成功率低于基线")
    baseline_complete = (baseline.get("coverage") or {}).get("complete", 0)
    optimized_complete = (optimized.get("coverage") or {}).get("complete", 0)
    if optimized_complete < baseline_complete:
        reasons.append(
            f"评论完整覆盖数下降：baseline={baseline_complete} optimized={optimized_complete}"
        )
    baseline_top = baseline.get("top_level_count") or 0
    optimized_top = optimized.get("top_level_count") or 0
    if baseline_top and optimized_top < baseline_top * 0.95:
        reasons.append(
            f"一级评论数量下降超过 5%：baseline={baseline_top} optimized={optimized_top}"
        )
    speedup = comparison.get("speedup")
    if speedup is None or speedup < required_speedup:
        reasons.append(f"速度未达门槛：speedup={speedup} < {required_speedup}")

    return {
        "passed": not reasons,
        "required_speedup": required_speedup,
        "comparison": comparison,
        "reasons": reasons,
    }
