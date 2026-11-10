"""采集层：文章、评论、层级与分类。"""

from __future__ import annotations

from .article import Collected, collect_article
from .classification import Classification, classify
from .comments import Selection, select_comment_nodes

__all__ = [
    "Classification",
    "Collected",
    "Selection",
    "classify",
    "collect_article",
    "select_comment_nodes",
]
