"""浏览器执行性能测量（V5）。"""

from scripts.employment.perf.aggregate import per_case, percentile, summarize
from scripts.employment.perf.compare import adoption_gate, compare_summaries
from scripts.employment.perf.metrics import (
    EventWriter,
    PerfEvent,
    Stopwatch,
    load_events,
    now_ns,
    utc_now,
)

__all__ = [
    "EventWriter",
    "PerfEvent",
    "Stopwatch",
    "adoption_gate",
    "compare_summaries",
    "load_events",
    "now_ns",
    "per_case",
    "percentile",
    "summarize",
    "utc_now",
]
