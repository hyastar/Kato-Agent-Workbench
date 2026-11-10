"""候选发现：关键词调度、候选队列、去重与相关性。"""

from __future__ import annotations

from .candidate_queue import CandidateQueue
from kato_engine.collection.models import SearchHit
from .deduplication import canonical_url
from .keyword_planner import (
    Dimension,
    KeywordLibrary,
    KeywordPlanner,
    QueryPlan,
    load_keyword_library,
)

__all__ = [
    "CandidateQueue",
    "Dimension",
    "KeywordLibrary",
    "KeywordPlanner",
    "QueryPlan",
    "SearchHit",
    "canonical_url",
    "load_keyword_library",
]
