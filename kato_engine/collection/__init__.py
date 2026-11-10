"""采集层：文章、评论、层级与分类。"""

from __future__ import annotations

from .article import Collected, build_summary
from .classification import Classification, classify
from .comments import Selection, select_comment_nodes
from .models import ArticleData, CommentBundle, CommentNode, SearchHit, SearchOutcome

__all__ = [
    "ArticleData",
    "Classification",
    "Collected",
    "CommentBundle",
    "CommentNode",
    "SearchHit",
    "SearchOutcome",
    "Selection",
    "build_summary",
    "classify",
    "select_comment_nodes",
]
