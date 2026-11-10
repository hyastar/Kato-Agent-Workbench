"""可观察性：日志、指标与报告。"""

from __future__ import annotations

from .logging import configure_logging, get_logger
from .reporting import build_report, render_report_markdown, write_report

__all__ = [
    "build_report",
    "configure_logging",
    "get_logger",
    "render_report_markdown",
    "write_report",
]
