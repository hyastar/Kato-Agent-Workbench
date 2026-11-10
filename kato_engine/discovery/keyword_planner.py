"""十维关键词调度。

数据源固定为 `tasks/employment/search_keywords.json`，不硬编码任何默认搜索组。
调度依据是"缺口"，不是顺序：
- 维度缺口 = 该维度目标 - 已采集 - 已入队待处理；
- 缺口最大的维度优先；
- 同维度内取第一个"未执行过"的组合（关键词 × 届别修饰词）。

不得声称某个搜索用了"最新排序"等未实际确认的顺序。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

YEAR_TOKENS: tuple[str, ...] = (
    "2026",
    "2027",
    "2025",
    "2024",
    "26届",
    "27届",
    "25届",
)

DIMENSION_IDS: tuple[str, ...] = (
    "salary",
    "job_search",
    "probation",
    "layoff",
    "home_idle",
    "factory",
    "machinery",
    "it",
    "campus",
    "worklife",
)


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    target: int
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class KeywordLibrary:
    version: str
    campaign: str
    goal: str
    target_total: int
    modifiers: tuple[str, ...]
    dimensions: tuple[Dimension, ...]

    def dimension(self, dimension_id: str) -> Dimension:
        for item in self.dimensions:
            if item.id == dimension_id:
                return item
        raise KeyError(f"未知维度：{dimension_id}")

    def total_dimension_target(self) -> int:
        return sum(item.target for item in self.dimensions)


@dataclass(frozen=True)
class QueryPlan:
    dimension: str
    keyword: str
    combined_query: str
    deficit: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "keyword": self.keyword,
            "combined_query": self.combined_query,
            "deficit": self.deficit,
        }


class KeywordLibraryError(ValueError):
    pass


def load_keyword_library(path: str | Path) -> KeywordLibrary:
    target = Path(path)
    if not target.is_file():
        raise KeywordLibraryError(f"关键词库不存在：{target}")
    payload = json.loads(target.read_text(encoding="utf-8"))

    dimensions_raw = payload.get("dimensions") or []
    if not dimensions_raw:
        raise KeywordLibraryError("关键词库缺少 dimensions")

    modifiers = tuple(str(item).strip() for item in payload.get("modifiers") or [] if str(item).strip())
    dimensions: list[Dimension] = []
    seen: set[str] = set()
    for entry in dimensions_raw:
        dimension_id = str(entry.get("id") or "").strip()
        if not dimension_id:
            raise KeywordLibraryError("维度缺少 id")
        if dimension_id in seen:
            raise KeywordLibraryError(f"维度 id 重复：{dimension_id}")
        seen.add(dimension_id)
        keywords = tuple(
            str(item).strip() for item in entry.get("keywords") or [] if str(item).strip()
        )
        if not keywords:
            raise KeywordLibraryError(f"维度 {dimension_id} 没有关键词")
        dimensions.append(
            Dimension(
                id=dimension_id,
                label=str(entry.get("label") or dimension_id),
                target=int(entry.get("target") or 0),
                keywords=keywords,
            )
        )

    return KeywordLibrary(
        version=str(payload.get("version") or ""),
        campaign=str(payload.get("campaign") or ""),
        goal=str(payload.get("goal") or ""),
        target_total=int(payload.get("target_total") or 0),
        modifiers=modifiers,
        dimensions=tuple(dimensions),
    )


def build_combinations(keyword: str, modifiers: Iterable[str]) -> list[str]:
    """关键词已含年份时直接用；否则依次尝试"修饰词 + 关键词"。"""
    cleaned = keyword.strip()
    if not cleaned:
        return []
    if any(token in cleaned for token in YEAR_TOKENS):
        return [cleaned]
    combos = [f"{modifier} {cleaned}" for modifier in modifiers if modifier.strip()]
    return combos or [cleaned]


class KeywordPlanner:
    """按缺口与执行历史选择下一条查询。"""

    def __init__(
        self,
        library: KeywordLibrary,
        *,
        executed_queries: Iterable[str] = (),
        accepted_by_dimension: Mapping[str, int] | None = None,
        pipeline_by_dimension: Mapping[str, int] | None = None,
        dimension_targets: Mapping[str, int] | None = None,
    ) -> None:
        self.library = library
        self.executed = {query.strip() for query in executed_queries}
        self.accepted = dict(accepted_by_dimension or {})
        self.pipeline = dict(pipeline_by_dimension or {})
        self.targets = dict(dimension_targets or {})

    def target_for(self, dimension: Dimension) -> int:
        return int(self.targets.get(dimension.id, dimension.target))

    def deficit(self, dimension: Dimension) -> int:
        used = self.accepted.get(dimension.id, 0) + self.pipeline.get(dimension.id, 0)
        return self.target_for(dimension) - used

    def ordered_dimensions(self) -> list[Dimension]:
        """按剩余缺口比例降序；同比例时按绝对缺口与原始顺序。"""

        def sort_key(item: Dimension) -> tuple[float, int, int]:
            target = max(self.target_for(item), 1)
            remaining = self.deficit(item)
            ratio = remaining / target
            return (-ratio, -remaining, self.library.dimensions.index(item))

        return sorted(self.library.dimensions, key=sort_key)

    def next_plan(self) -> QueryPlan | None:
        for dimension in self.ordered_dimensions():
            remaining = self.deficit(dimension)
            if remaining <= 0:
                continue
            for keyword in dimension.keywords:
                for combined in build_combinations(keyword, self.library.modifiers):
                    if combined in self.executed:
                        continue
                    return QueryPlan(
                        dimension=dimension.id,
                        keyword=keyword,
                        combined_query=combined,
                        deficit=remaining,
                    )
        return None

    def exhausted_dimensions(self) -> list[str]:
        exhausted: list[str] = []
        for dimension in self.library.dimensions:
            remaining = self.deficit(dimension)
            if remaining <= 0:
                continue
            available = any(
                combined not in self.executed
                for keyword in dimension.keywords
                for combined in build_combinations(keyword, self.library.modifiers)
            )
            if not available:
                exhausted.append(dimension.id)
        return exhausted
