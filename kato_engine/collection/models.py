"""与浏览器实现无关的数据模型。

V6.1 起浏览器由 ZCode 内置 Browser Use 持有；Python 只接收**结构化结果**，
因此这里不再引用任何 Playwright 类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchHit:
    """搜索结果条目。`canonical_url` 已去跟踪参数。"""

    title: str
    canonical_url: str
    raw_index: int = 0
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class SearchOutcome:
    platform: str
    query: str
    page_title: str
    raw_count: int
    hits: list[SearchHit]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "query": self.query,
            "page_title": self.page_title,
            "raw_count": self.raw_count,
            "hits": [
                {"title": hit.title, "canonical_url": hit.canonical_url, "raw_index": hit.raw_index}
                for hit in self.hits
            ],
            "notes": list(self.notes),
        }


@dataclass
class CommentNode:
    content: str
    platform_comment_id: str | None = None
    like_count: int | None = None
    published_time_displayed: str | None = None
    reply_count_displayed: int | None = None
    level: int = 1
    children: list["CommentNode"] = field(default_factory=list)

    def total(self) -> int:
        return 1 + sum(child.total() for child in self.children)

    def to_payload(self, sort_basis: str = "visible_order") -> dict[str, Any]:
        return {
            "platform_comment_id": self.platform_comment_id,
            "content": self.content,
            "like_count": self.like_count,
            "published_time_displayed": self.published_time_displayed,
            "reply_count_displayed": self.reply_count_displayed,
            "sort_basis": sort_basis,
            "children": [child.to_payload(sort_basis) for child in self.children],
        }


@dataclass
class CommentBundle:
    nodes: list[CommentNode]
    displayed_total: int | None = None
    displayed_top_level: int | None = None
    displayed_replies: int | None = None
    sort_basis: str = "visible_order"
    notes: list[str] = field(default_factory=list)

    @property
    def top_level(self) -> int:
        return len(self.nodes)

    @property
    def replies(self) -> int:
        return sum(node.total() - 1 for node in self.nodes)


@dataclass
class ArticleData:
    platform: str
    canonical_url: str
    title: str
    body_text: str = ""
    published_text: str | None = None
    published_at: str | None = None
    city: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def body_length(self) -> int:
        return len(self.body_text)
