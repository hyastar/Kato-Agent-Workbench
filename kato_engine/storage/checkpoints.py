"""检查点：记录"下一条候选是谁"以及平台进度。

写盘位置：`runs/<engine-run-id>/checkpoint.json`（runs/ 不入 Git）。
恢复时以数据库状态为准，checkpoint 用于快速核对与人工排查。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts import db

from kato_engine.config.settings import Settings


@dataclass
class Checkpoint:
    engine_run_id: str
    campaign_id: str
    saved_at: str
    state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_run_id": self.engine_run_id,
            "campaign_id": self.campaign_id,
            "saved_at": self.saved_at,
            **self.state,
        }


def checkpoint_path(settings: Settings, engine_run_id: str) -> Path:
    return settings.runs_dir / engine_run_id / "checkpoint.json"


def write_checkpoint(
    settings: Settings,
    engine_run_id: str,
    campaign_id: str,
    state: dict[str, Any],
) -> Path:
    path = checkpoint_path(settings, engine_run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine_run_id": engine_run_id,
        "campaign_id": campaign_id,
        "saved_at": db.utc_now(),
        **state,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_checkpoint(path: str | Path) -> dict[str, Any] | None:
    target = Path(path)
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))
