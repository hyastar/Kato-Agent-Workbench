"""核心层：状态机、调度与执行循环。"""

from __future__ import annotations

from .state_machine import (
    CANDIDATE_STATES,
    InvalidTransition,
    assert_transition,
    can_transition,
    is_terminal,
)

__all__ = [
    "CANDIDATE_STATES",
    "InvalidTransition",
    "assert_transition",
    "can_transition",
    "is_terminal",
]
