"""V6.1 ZCode Browser 任务层。

浏览器由 ZCode 内置 Browser Use 持有；本包只定义任务/结果契约、批次规划与入库。
"""

from __future__ import annotations

from .contracts import BatchContractError, BatchResult, BatchTask, BatchTarget
from .ingest import IngestSummary, ingest_batch
from .planner import BatchPlan, plan_batch

__all__ = [
    "BatchContractError",
    "BatchPlan",
    "BatchResult",
    "BatchTarget",
    "BatchTask",
    "IngestSummary",
    "ingest_batch",
    "plan_batch",
]
