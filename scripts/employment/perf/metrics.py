"""单调时钟、结构化事件与可恢复 JSONL 写入。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PHASES: tuple[str, ...] = (
    "navigation",
    "page_ready",
    "article_extract",
    "comment_expand",
    "reply_expand",
    "dom_extract",
    "normalize",
    "db",
    "markdown",
    "total",
)


def now_ns() -> int:
    """本机单调时钟，仅用于耗时计算。"""
    return time.perf_counter_ns()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Stopwatch:
    """用单调时钟测量一个阶段。"""

    def __init__(self) -> None:
        self._start = now_ns()
        self.wall_ms: float | None = None

    def stop(self) -> float:
        self.wall_ms = (now_ns() - self._start) / 1_000_000
        return self.wall_ms


@dataclass
class PerfEvent:
    run_id: str
    experiment_id: str
    case_id: str
    backend: str
    platform: str
    article_id: str | None = None
    phase: str = "total"
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    wall_ms: float | None = None
    agent_think_ms: float | None = None
    browser_tool_calls: int = 0
    browser_round_trips: int = 0
    navigation_ms: float | None = None
    page_ready_ms: float | None = None
    article_extract_ms: float | None = None
    comment_expand_ms: float | None = None
    reply_expand_ms: float | None = None
    dom_extract_ms: float | None = None
    normalize_ms: float | None = None
    db_ms: float | None = None
    markdown_ms: float | None = None
    top_level_count: int | None = None
    reply_count: int | None = None
    coverage_status: str | None = None
    status: str = "ok"
    error_type: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    bytes_returned: int | None = None
    snapshots_count: int = 0
    profile_mode: str | None = None
    browser_version: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventWriter:
    """追加写 JSONL；每行完整事件，进程中断不影响已写入行。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: PerfEvent) -> None:
        line = json.dumps(event.as_dict(), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def load_events(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
