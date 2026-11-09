"""浏览器执行层的数据契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArticleTask:
    case_id: str
    platform: str
    cohort: str = "unknown"
    recruitment_stage: str = "unknown"
    topic: str = "other"
    company: str | None = None
    url: str | None = None
    keyword: str | None = None
    title_fragment: str | None = None
    comment_limit: int = 50


@dataclass
class CommentNode:
    platform_comment_id: str | None
    content: str
    like_count: int | None = None
    published_time_displayed: str | None = None
    comment_level: int = 1
    sort_basis: str = "visible_order"
    children: list["CommentNode"] = field(default_factory=list)


@dataclass
class ArticleResult:
    task: ArticleTask
    title: str
    url: str
    backend: str = "mcp_batch"
    displayed_total: int | None = None
    collected_top_level: int = 0
    collected_replies: int = 0
    coverage_status: str = "not_available"
    sort_basis: str = "visible_order"
    reason: str | None = None
    comments: list[CommentNode] = field(default_factory=list)
    status: str = "ok"
    error_type: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "case_id": self.task.case_id,
            "platform": self.task.platform,
            "title": self.title,
            "url": self.url,
            "backend": self.backend,
            "displayed_total": self.displayed_total,
            "collected_top_level": self.collected_top_level,
            "collected_replies": self.collected_replies,
            "coverage_status": self.coverage_status,
            "sort_basis": self.sort_basis,
            "status": self.status,
            "error_type": self.error_type,
        }


class BrowserExecutionError(RuntimeError):
    """页面结构或交互失败；调用方应记录并停止该条。"""

    def __init__(self, message: str, error_type: str = "browser_error") -> None:
        super().__init__(message)
        self.error_type = error_type
