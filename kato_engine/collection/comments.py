"""一级评论 50 条规则与覆盖判定。

规则复用 V4 已验证实现（`scripts.employment.validate.select_comments`）：
- 总数 ≤ 50：按可见顺序全取；
- 总数 > 50：高赞前 30，再按可见顺序补足 50；
- 未核实"最新排序"时不声称使用最新排序（`latest_verified=False`）。

楼中楼不计入 50 条，但随所选一级评论整棵保留。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scripts.employment.validate import select_comments

from kato_engine.platforms.base import CommentBundle, CommentNode


@dataclass
class Selection:
    nodes: list[CommentNode]
    sort_basis: str
    coverage_status: str
    reason: str | None
    displayed_total: int | None
    displayed_top_level: int | None
    displayed_replies: int | None
    capped: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def collected_top_level(self) -> int:
        return len(self.nodes)

    @property
    def collected_replies(self) -> int:
        return sum(node.total() - 1 for node in self.nodes)

    def stats(self) -> dict[str, Any]:
        return {
            "displayed_total": self.displayed_total,
            "displayed_top_level": self.displayed_top_level,
            "collected_top_level": self.collected_top_level,
            "displayed_replies": self.displayed_replies,
            "collected_replies": self.collected_replies,
            "coverage_status": self.coverage_status,
            "sort_basis": self.sort_basis,
        }


def select_comment_nodes(
    bundle: CommentBundle,
    *,
    limit: int = 50,
    latest_verified: bool = False,
) -> Selection:
    candidates: list[dict[str, Any]] = []
    for index, node in enumerate(bundle.nodes):
        candidates.append(
            {
                "id": node.platform_comment_id or f"idx-{index}",
                "like_count": node.like_count,
                "order": index,
                "node": node,
            }
        )

    total_displayed = bundle.displayed_total
    selected, basis = select_comments(
        candidates,
        int(total_displayed) if total_displayed is not None else len(candidates),
        limit=limit,
        latest_verified=latest_verified,
    )
    nodes = [row["node"] for row in selected]
    top_level = len(nodes)
    replies = sum(node.total() - 1 for node in nodes)
    capped = len(candidates) > limit

    if total_displayed is None:
        coverage = "not_available" if top_level + replies == 0 else "partial"
    elif capped or top_level + replies < int(total_displayed):
        coverage = "partial"
    else:
        coverage = "complete"

    reason = None
    if capped:
        reason = (
            "页面未提供可核实的最新排序；按高赞选择并用可见顺序补足 50 条，"
            "其余一级评论未采集。"
            if not latest_verified
            else "按高赞 30 + 最新 20 选择，其余一级评论未采集。"
        )
    elif coverage == "partial":
        reason = (
            "页面未显示评论总数；已按可见顺序采集，无法确认完整性。"
            if total_displayed is None
            else "页面显示评论数大于实际可采集数；部分回复未展开或未加载。"
        )
    elif coverage == "not_available":
        reason = "页面未显示评论数，且未加载到评论。"

    return Selection(
        nodes=nodes,
        sort_basis=basis,
        coverage_status=coverage,
        reason=reason,
        displayed_total=total_displayed,
        displayed_top_level=bundle.displayed_top_level,
        displayed_replies=bundle.displayed_replies,
        capped=capped,
        notes=list(bundle.notes),
    )
