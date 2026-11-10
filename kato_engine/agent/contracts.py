"""ZCode Browser 任务与结果契约。

浏览器由 ZCode 内置 Browser Use 持有；Python 不启动、不连接、不假设拥有浏览器。
双方只通过 JSON 文件交换：
- Python 产出 `task.json`（查询、搜索 URL、要打开的候选、要执行的脚本）；
- ZCode 执行后写出 `batch.json`（搜索结果 + 每篇文章的结构化结果）；
- Python 读取 `batch.json` 校验、分类、入库。

任何字段缺失都按失败处理，不做猜测性补全。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kato_engine.agent.scripts import task_scripts, task_selectors, WORKFLOW_JS
from kato_engine.discovery.deduplication import canonical_url as normalize_platform_url


class BatchContractError(ValueError):
    """batch.json 不符合契约。"""


@dataclass
class BatchTarget:
    candidate_id: str | None
    canonical_url: str | None
    note_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "canonical_url": self.canonical_url,
            "note_id": self.note_id,
        }


@dataclass
class BatchTask:
    run_id: str
    campaign_id: str
    platform: str
    query: str
    dimension: str
    keyword: str
    combined_query: str
    search_url: str
    size: int
    targets: list[BatchTarget] = field(default_factory=list)
    exclude_urls: list[str] = field(default_factory=list)
    task_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "campaign_id": self.campaign_id,
            "platform": self.platform,
            "query": self.query,
            "dimension": self.dimension,
            "keyword": self.keyword,
            "combined_query": self.combined_query,
            "search_url": self.search_url,
            "size": self.size,
            "targets": [target.to_dict() for target in self.targets],
            "exclude_urls": self.exclude_urls,
            "scripts": task_scripts(self.platform),
            "selectors": task_selectors(self.platform),
            "workflow_js": WORKFLOW_JS,
            "task_path": self.task_path,
        }

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.task_path = str(target)
        return target


@dataclass
class ArticleExtraction:
    ok: bool
    candidate_id: str | None = None
    canonical_url: str | None = None
    title: str = ""
    body: str = ""
    published_text: str | None = None
    displayed_total: int | None = None
    comments_nested: list[dict[str, Any]] = field(default_factory=list)
    comments_flat: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error_type: str | None = None
    message: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any], platform: str) -> "ArticleExtraction":
        ok = bool(payload.get("ok"))
        raw_url = payload.get("url") or payload.get("canonical_url")
        canonical = None
        if raw_url:
            try:
                canonical = normalize_platform_url(platform, str(raw_url))
            except ValueError:
                canonical = None
        if ok and not canonical:
            return cls(
                ok=False,
                error_type="invalid_url",
                message=f"无法识别的 URL：{raw_url!r}",
            )
        title = str(payload.get("title") or "").strip()
        if ok and not title:
            return cls(ok=False, canonical_url=canonical, error_type="empty_content", message="标题为空")
        displayed = payload.get("displayed_total")
        try:
            displayed_total = int(displayed) if displayed is not None else None
        except (TypeError, ValueError):
            displayed_total = None
        return cls(
            ok=ok,
            candidate_id=(str(payload.get("candidate_id")) if payload.get("candidate_id") else None),
            canonical_url=canonical,
            title=title,
            body=str(payload.get("body") or ""),
            published_text=(str(payload.get("published_text")).strip() or None)
            if payload.get("published_text")
            else None,
            displayed_total=displayed_total,
            comments_nested=list(payload.get("comments") or []),
            comments_flat=list(payload.get("comments_flat") or []),
            notes=[str(item) for item in payload.get("notes") or []],
            error_type=payload.get("error_type"),
            message=payload.get("message"),
        )


@dataclass
class BatchResult:
    run_id: str
    platform: str
    query: str
    search: dict[str, Any]
    articles: list[ArticleExtraction]
    blocked: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path, *, platform: str, run_id: str, query: str) -> "BatchResult":
        target = Path(path)
        if not target.is_file():
            raise BatchContractError(f"batch 文件不存在：{target}")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BatchContractError(f"batch 文件不是合法 JSON：{exc}") from exc
        if not isinstance(payload, dict):
            raise BatchContractError("batch 文件顶层必须是对象")

        batch_platform = str(payload.get("platform") or platform)
        if batch_platform != platform:
            raise BatchContractError(f"平台不一致：任务 {platform}，结果 {batch_platform}")

        search = payload.get("search")
        if search is not None and not isinstance(search, dict):
            raise BatchContractError("search 必须是对象")
        raw_articles = payload.get("articles") or []
        if not isinstance(raw_articles, list):
            raise BatchContractError("articles 必须是数组")

        articles: list[ArticleExtraction] = []
        for item in raw_articles:
            if not isinstance(item, dict):
                raise BatchContractError("articles 元素必须是对象")
            articles.append(ArticleExtraction.from_dict(item, platform))

        blocked = payload.get("blocked")
        if blocked is not None and not isinstance(blocked, dict):
            raise BatchContractError("blocked 必须是对象")

        return cls(
            run_id=str(payload.get("run_id") or run_id),
            platform=batch_platform,
            query=str(payload.get("query") or query),
            search=search or {},
            articles=articles,
            blocked=blocked,
            notes=[str(item) for item in payload.get("notes") or []],
        )

    def search_hits(self) -> list[tuple[str, str, int]]:
        """返回 (title, canonical_url, index)；无法识别的 URL 跳过并计数在 stats 中。"""
        hits: list[tuple[str, str, int]] = []
        for card in self.search.get("cards") or []:
            raw = card.get("canonical_url") or card.get("href")
            canonical = None
            if raw:
                try:
                    canonical = normalize_platform_url(self.platform, str(raw))
                except ValueError:
                    canonical = None
            if canonical is None and self.platform == "xiaohongshu" and card.get("note_id"):
                # 搜索卡片 href 形如 /search_result/<id>?xsec_token=...，无法直接规范化，
                # 但 note_id 是稳定的笔记标识。
                canonical = f"https://www.xiaohongshu.com/explore/{card['note_id']}"
            if canonical is None:
                continue
            hits.append(
                (
                    str(card.get("title") or "").strip(),
                    canonical,
                    int(card.get("index") or 0),
                )
            )
        return hits
