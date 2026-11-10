"""候选状态机：所有状态迁移必须经过这里。

状态语义见 `docs/v6/V6_ARCHITECTURE.md` 第 4 节。非法迁移直接抛错，
避免"跳步"导致计数与覆盖状态不可解释。
"""

from __future__ import annotations

from typing import Final

CANDIDATE_STATES: Final[tuple[str, ...]] = (
    "discovered",
    "queued",
    "processing",
    "accepted",
    "rejected",
    "retryable_failed",
    "blocked",
    "completed",
    "skipped",
)

TERMINAL_STATES: Final[frozenset[str]] = frozenset({"rejected", "skipped", "completed"})

# 允许的迁移方向。
TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "discovered": frozenset({"queued", "rejected", "skipped"}),
    "queued": frozenset({"processing", "rejected", "skipped", "blocked"}),
    # processing → queued 只出现在租约超时回收时。
    "processing": frozenset({"accepted", "rejected", "retryable_failed", "blocked", "queued"}),
    "accepted": frozenset({"completed", "blocked"}),
    "retryable_failed": frozenset({"queued", "processing", "rejected"}),
    "blocked": frozenset({"queued", "processing", "rejected"}),
    # rejected 表示"本批放弃"，不是永久事实：结果页重排等临时原因
    # 会在后续批次重新遇到同一 URL，允许在未达重试上限时复活。
    "rejected": frozenset({"queued", "processing"}),
    "completed": frozenset(),
    "skipped": frozenset(),
}


class InvalidTransition(RuntimeError):
    def __init__(self, source: str, target: str) -> None:
        super().__init__(f"非法状态迁移：{source} → {target}")
        self.source = source
        self.target = target


def can_transition(source: str, target: str) -> bool:
    if source not in TRANSITIONS:
        return False
    return target in TRANSITIONS[source]


def assert_transition(source: str, target: str) -> None:
    if not can_transition(source, target):
        raise InvalidTransition(source, target)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES
