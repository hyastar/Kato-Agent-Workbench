"""性能埋点、聚合与 A/B 门槛的离线测试。"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from scripts.employment.perf import (
    EventWriter,
    PerfEvent,
    Stopwatch,
    adoption_gate,
    compare_summaries,
    load_events,
    percentile,
    summarize,
)


def _events_for(backend: str, scale: float = 1.0) -> list[dict]:
    rows = []
    specs = [
        ("case_a", "xiaohongshu", 1000 * scale, 5, 10, 20, "complete"),
        ("case_b", "zhihu", 2000 * scale, 10, 20, 0, "partial"),
        ("case_c", "xiaohongshu", 3000 * scale, 15, 30, 10, "complete"),
    ]
    for case_id, platform, wall, calls, top, replies, coverage in specs:
        rows.append(
            PerfEvent(
                run_id="run",
                experiment_id="exp",
                case_id=case_id,
                backend=backend,
                platform=platform,
                phase="navigation",
                wall_ms=wall * 0.5,
                browser_tool_calls=calls,
            ).as_dict()
        )
        rows.append(
            PerfEvent(
                run_id="run",
                experiment_id="exp",
                case_id=case_id,
                backend=backend,
                platform=platform,
                phase="total",
                wall_ms=wall,
                browser_tool_calls=0,
                top_level_count=top,
                reply_count=replies,
                coverage_status=coverage,
            ).as_dict()
        )
    return rows


class PerfMetricTests(unittest.TestCase):
    def test_stopwatch_uses_monotonic_clock(self) -> None:
        watch = Stopwatch()
        time.sleep(0.01)
        elapsed = watch.stop()
        self.assertGreaterEqual(elapsed, 5)

    def test_event_writer_roundtrip(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "events.jsonl"
        writer = EventWriter(path)
        writer.write(
            PerfEvent(
                run_id="r",
                experiment_id="e",
                case_id="c",
                backend="mcp_baseline",
                platform="zhihu",
                phase="total",
                wall_ms=12.5,
            )
        )
        rows = load_events(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["wall_ms"], 12.5)
        json.loads(path.read_text(encoding="utf-8"))

    def test_percentile(self) -> None:
        self.assertEqual(percentile([], 50), None)
        self.assertEqual(percentile([1, 2, 3, 4], 50), 2)
        self.assertEqual(percentile([1, 2, 3, 4], 95), 4)

    def test_summary(self) -> None:
        summary = summarize(_events_for("mcp_baseline"))
        self.assertEqual(summary["cases"], 3)
        self.assertEqual(summary["total_wall_ms"], 6000)
        self.assertEqual(summary["mean_ms"], 2000)
        self.assertEqual(summary["p50_ms"], 2000)
        self.assertEqual(summary["p95_ms"], 3000)
        self.assertEqual(summary["browser_tool_calls"], 30)
        self.assertEqual(summary["top_level_count"], 60)
        self.assertEqual(summary["reply_count"], 30)
        self.assertEqual(summary["coverage"]["complete"], 2)
        self.assertAlmostEqual(summary["articles_per_hour"], 1800, places=3)

    def test_compare_and_gate(self) -> None:
        baseline = summarize(_events_for("mcp_baseline", 1.0))
        optimized = summarize(_events_for("mcp_batch", 0.5))
        comparison = compare_summaries(baseline, optimized)
        self.assertEqual(comparison["speedup"], 2.0)
        gate = adoption_gate(baseline, optimized)
        self.assertTrue(gate["passed"], gate["reasons"])

    def test_gate_rejects_quality_regression(self) -> None:
        baseline = summarize(_events_for("mcp_baseline", 1.0))
        optimized_events = _events_for("mcp_batch", 0.5)
        for row in optimized_events:
            if row["phase"] == "total" and row["case_id"] == "case_a":
                row["coverage_status"] = "partial"
        optimized = summarize(optimized_events)
        gate = adoption_gate(baseline, optimized)
        self.assertFalse(gate["passed"])
        self.assertTrue(any("覆盖" in reason for reason in gate["reasons"]))


if __name__ == "__main__":
    unittest.main()
