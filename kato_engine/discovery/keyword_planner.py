"""十维关键词调度（V6.2）。

调度分层：
1. **主题多样性**：按"目标 - 已采集 - 队列中"的缺口比例选择维度；
2. **关键词探索/利用**：维度内优先未搜索过的关键词（探索），
   其余按"每次搜索平均新增有效文章"排序（利用），并优先最久未搜索的；
3. **年份/届别多样性**：每个关键词每次只搭配**一个**修饰词，
   按下标轮换，不生成笛卡尔积；关键词自带年份/届别时不再加修饰；
4. **动态关键词**：经人工批准的新词可注入维度，来源单独记录。

不硬编码任何搜索组；数据源固定为 `tasks/employment/search_keywords.json`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

YEAR_TOKENS: tuple[str, ...] = (
    "2023",
    "2024",
    "2025",
    "2026",
    "2027",
    "2028",
    "23届",
    "24届",
    "25届",
    "26届",
    "27届",
    "28届",
)

DIMENSION_IDS: tuple[str, ...] = (
    "salary",
    "job_search",
    "probation",
    "layoff",
    "home_idle",
    "factory",
    "computer",
    "machinery",
    "campus",
    "work_life",
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
    modifier_groups: Mapping[str, tuple[str, ...]] = None  # type: ignore[assignment]
    directions: tuple[Mapping[str, str], ...] = ()
    keyword_meta: Mapping[str, Mapping[str, str]] = None  # type: ignore[assignment]

    def dimension(self, dimension_id: str) -> Dimension:
        for item in self.dimensions:
            if item.id == dimension_id:
                return item
        raise KeyError(f"未知维度：{dimension_id}")

    def total_dimension_target(self) -> int:
        return sum(item.target for item in self.dimensions)

    def base_keyword_total(self) -> int:
        return sum(len(item.keywords) for item in self.dimensions)

    def meta_for(self, keyword: str) -> Mapping[str, str]:
        return (self.keyword_meta or {}).get(keyword, {})


@dataclass(frozen=True)
class KeywordStat:
    searches: int = 0
    found: int = 0
    duplicates: int = 0
    opened: int = 0
    accepted: int = 0
    last_at: str | None = None

    @property
    def new_candidates(self) -> int:
        return max(self.found - self.duplicates, 0)

    @property
    def yield_per_search(self) -> float:
        return self.accepted / self.searches if self.searches else 0.0


@dataclass(frozen=True)
class QueryPlan:
    dimension: str
    keyword: str
    combined_query: str
    deficit: int = 0
    reason: str = "explore"
    modifier: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "keyword": self.keyword,
            "combined_query": self.combined_query,
            "deficit": self.deficit,
            "reason": self.reason,
            "modifier": self.modifier,
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

    modifiers = tuple(
        str(item).strip() for item in payload.get("modifiers") or [] if str(item).strip()
    )
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

    modifier_groups = {
        str(group): tuple(str(item) for item in items)
        for group, items in (payload.get("modifier_groups") or {}).items()
    }
    directions = tuple(payload.get("directions") or ())
    keyword_meta = {
        str(keyword): {str(k): str(v) for k, v in meta.items()}
        for keyword, meta in (payload.get("keyword_meta") or {}).items()
    }

    return KeywordLibrary(
        version=str(payload.get("version") or ""),
        campaign=str(payload.get("campaign") or ""),
        goal=str(payload.get("goal") or ""),
        target_total=int(payload.get("target_total") or 0),
        modifiers=modifiers,
        dimensions=tuple(dimensions),
        modifier_groups=modifier_groups,
        directions=directions,
        keyword_meta=keyword_meta,
    )


def has_year_token(keyword: str) -> bool:
    return any(token in keyword for token in YEAR_TOKENS)


def build_combinations(keyword: str, modifiers: Iterable[str]) -> list[str]:
    """关键词已含年份时直接用；否则生成"修饰词 + 关键词"组合（供测试与全量枚举）。"""
    cleaned = keyword.strip()
    if not cleaned:
        return []
    if has_year_token(cleaned):
        return [cleaned]
    combos = [f"{modifier} {cleaned}" for modifier in modifiers if modifier.strip()]
    return combos or [cleaned]


def _stable_hash(text: str) -> int:
    import hashlib

    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def rotate_modifier(
    keyword: str,
    modifiers: tuple[str, ...],
    attempt: int,
) -> list[str]:
    """按关键词与尝试次数轮换修饰词：每次只尝试一个，命中已执行则顺延。"""
    if not modifiers:
        return [keyword]
    start = (_stable_hash(keyword) + max(attempt, 0)) % len(modifiers)
    ordered = [modifiers[(start + index) % len(modifiers)] for index in range(len(modifiers))]
    return [f"{modifier} {keyword}" for modifier in ordered]


class KeywordPlanner:
    """按缺口、关键词效率与年份多样性选择下一条查询。"""

    def __init__(
        self,
        library: KeywordLibrary,
        *,
        executed_queries: Iterable[str] = (),
        accepted_by_dimension: Mapping[str, int] | None = None,
        pipeline_by_dimension: Mapping[str, int] | None = None,
        dimension_targets: Mapping[str, int] | None = None,
        stats: Mapping[str, KeywordStat] | None = None,
        extra_keywords: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self.library = library
        self.executed = {query.strip() for query in executed_queries}
        self.accepted = dict(accepted_by_dimension or {})
        self.pipeline = dict(pipeline_by_dimension or {})
        self.targets = dict(dimension_targets or {})
        self.stats = dict(stats or {})
        self.extra_keywords = {key: tuple(value) for key, value in (extra_keywords or {}).items()}

    # -- 缺口 -------------------------------------------------------------
    def target_for(self, dimension: Dimension) -> int:
        return int(self.targets.get(dimension.id, dimension.target))

    def deficit(self, dimension: Dimension) -> int:
        used = self.accepted.get(dimension.id, 0) + self.pipeline.get(dimension.id, 0)
        return self.target_for(dimension) - used

    def ordered_dimensions(self) -> list[Dimension]:
        def sort_key(item: Dimension) -> tuple[float, int, int]:
            target = max(self.target_for(item), 1)
            remaining = self.deficit(item)
            return (-remaining / target, -remaining, self.library.dimensions.index(item))

        return sorted(self.library.dimensions, key=sort_key)

    # -- 关键词排序 -------------------------------------------------------
    def keywords_for(self, dimension: Dimension) -> list[str]:
        base = list(dimension.keywords)
        extra = list(self.extra_keywords.get(dimension.id, ()))
        merged = base + [item for item in extra if item not in base]
        return merged

    def stat_for(self, keyword: str) -> KeywordStat:
        return self.stats.get(keyword, KeywordStat())

    def _rank_keywords(self, dimension: Dimension) -> list[tuple[str, str]]:
        """返回 [(keyword, reason)]：先探索未搜索词，再按产出效率利用。"""
        keywords = self.keywords_for(dimension)
        unsearched = [kw for kw in keywords if self.stat_for(kw).searches == 0]
        searched = [kw for kw in keywords if self.stat_for(kw).searches > 0]

        unsearched.sort(key=lambda kw: _stable_hash(f"{dimension.id}:{kw}") % 10_000)
        searched.sort(
            key=lambda kw: (
                -self.stat_for(kw).yield_per_search,
                self.stat_for(kw).last_at or "",
                _stable_hash(kw) % 10_000,
            )
        )
        ranked = [(kw, "explore") for kw in unsearched]
        ranked += [(kw, "exploit") for kw in searched]
        return ranked

    def _plan_for_keyword(
        self, dimension: Dimension, keyword: str, reason: str, deficit: int
    ) -> QueryPlan | None:
        stat = self.stat_for(keyword)
        if has_year_token(keyword):
            if keyword in self.executed:
                return None
            return QueryPlan(
                dimension=dimension.id,
                keyword=keyword,
                combined_query=keyword,
                deficit=deficit,
                reason=reason,
                modifier=None,
            )
        for combined in rotate_modifier(keyword, self.library.modifiers, stat.searches):
            if combined in self.executed:
                continue
            return QueryPlan(
                dimension=dimension.id,
                keyword=keyword,
                combined_query=combined,
                deficit=deficit,
                reason=reason,
                modifier=combined[: -len(keyword)].strip() or None,
            )
        return None

    # -- 入口 -------------------------------------------------------------
    def next_plan(self, *, skip_keywords: set[str] | None = None) -> QueryPlan | None:
        for dimension in self.ordered_dimensions():
            remaining = self.deficit(dimension)
            if remaining <= 0:
                continue
            for keyword, reason in self._rank_keywords(dimension):
                if skip_keywords and keyword in skip_keywords:
                    continue
                plan = self._plan_for_keyword(dimension, keyword, reason, remaining)
                if plan is not None:
                    return plan
        return None

    def next_plans(self, count: int) -> list[QueryPlan]:
        """预览多条计划：同一关键词只出现一次，展示的是关键词多样性。"""
        plans: list[QueryPlan] = []
        skip: set[str] = set()
        for _ in range(max(count, 0)):
            plan = self.next_plan(skip_keywords=skip)
            if plan is None:
                break
            plans.append(plan)
            skip.add(plan.keyword)
            self.executed.add(plan.combined_query)
        return plans

    def exhausted_dimensions(self) -> list[str]:
        exhausted: list[str] = []
        for dimension in self.library.dimensions:
            if self.deficit(dimension) <= 0:
                continue
            if self.next_plan_for_dimension(dimension) is None:
                exhausted.append(dimension.id)
        return exhausted

    def next_plan_for_dimension(self, dimension: Dimension) -> QueryPlan | None:
        remaining = self.deficit(dimension)
        if remaining <= 0:
            return None
        for keyword, reason in self._rank_keywords(dimension):
            plan = self._plan_for_keyword(dimension, keyword, reason, remaining)
            if plan is not None:
                return plan
        return None
