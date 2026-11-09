"""按文章聚合耗时、工具调用、覆盖率与吞吐。"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from scripts.employment.perf.metrics import load_events


def percentile(values: Iterable[float], p: float) -> float | None:
    """最近秩百分位；空序列返回 None。"""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if p <= 0:
        return ordered[0]
    if p >= 100:
        return ordered[-1]
    import math

    rank = math.ceil(p / 100 * len(ordered)) - 1
    return ordered[max(0, min(rank, len(ordered) - 1))]


def _case_total(events: list[dict[str, Any]]) -> float:
    total_events = [event for event in events if event.get("phase") == "total"]
    if total_events:
        return float(sum(event.get("wall_ms") or 0 for event in total_events))
    return float(
        sum(event.get("wall_ms") or 0 for event in events if event.get("phase") != "total")
    )


def per_case(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(event.get("case_id", "unknown"), []).append(event)

    rows: list[dict[str, Any]] = []
    for case_id, case_events in grouped.items():
        status = "failed" if any(event.get("status") == "failed" for event in case_events) else "ok"
        coverage = next(
            (
                event.get("coverage_status")
                for event in reversed(case_events)
                if event.get("coverage_status")
            ),
            None,
        )
        rows.append(
            {
                "case_id": case_id,
                "backend": case_events[0].get("backend"),
                "platform": case_events[0].get("platform"),
                "wall_ms": round(_case_total(case_events), 3),
                "browser_tool_calls": sum(int(e.get("browser_tool_calls") or 0) for e in case_events),
                "browser_round_trips": sum(
                    int(e.get("browser_round_trips") or 0) for e in case_events
                ),
                "snapshots_count": sum(int(e.get("snapshots_count") or 0) for e in case_events),
                "top_level_count": max(
                    (int(e.get("top_level_count") or 0) for e in case_events), default=0
                ),
                "reply_count": max((int(e.get("reply_count") or 0) for e in case_events), default=0),
                "coverage_status": coverage,
                "status": status,
            }
        )
    return sorted(rows, key=lambda row: row["case_id"])


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    rows = per_case(events)
    wall = [row["wall_ms"] for row in rows]
    total_wall = sum(wall)
    total_seconds = total_wall / 1000 if total_wall else 0
    coverage = Counter(row["coverage_status"] for row in rows if row["coverage_status"])
    return {
        "cases": len(rows),
        "total_wall_ms": round(total_wall, 3),
        "mean_ms": round(total_wall / len(rows), 3) if rows else None,
        "p50_ms": percentile(wall, 50),
        "p95_ms": percentile(wall, 95),
        "articles_per_hour": round(len(rows) / (total_seconds / 3600), 3)
        if total_seconds
        else None,
        "success_rate": round(
            sum(1 for row in rows if row["status"] == "ok") / len(rows), 4
        )
        if rows
        else None,
        "browser_tool_calls": sum(row["browser_tool_calls"] for row in rows),
        "browser_round_trips": sum(row["browser_round_trips"] for row in rows),
        "snapshots_count": sum(row["snapshots_count"] for row in rows),
        "top_level_count": sum(row["top_level_count"] for row in rows),
        "reply_count": sum(row["reply_count"] for row in rows),
        "coverage": dict(coverage),
        "cases_detail": rows,
    }


def summarize_file(path: str) -> dict[str, Any]:
    return summarize(load_events(path))
