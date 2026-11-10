"""执行生命周期：把一次采集结果原子地落成数据库记录与 Markdown 档案。

顺序（任一步失败都不把候选标成 completed）：
1. 文章幂等入库（唯一索引 platform + canonical_url）；
2. 挂到 Campaign；
3. 写入内容分类；
4. 写入评论统计；
5. 导入评论树（父子关系由仓储递归恢复）；
6. 导出 Markdown 并登记哈希；
7. 候选 accepted → completed。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kato_engine.collection.article import Collected, build_summary
from kato_engine.observability.logging import get_logger
from kato_engine.storage.markdown import ExportResult, export_article
from kato_engine.storage.repository import EngineRepository

_LOGGER = get_logger("kato.lifecycle")


@dataclass
class PersistResult:
    item_id: str
    created: bool
    comments_inserted: int
    comments_existing: int
    export: ExportResult
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "created": self.created,
            "comments_inserted": self.comments_inserted,
            "comments_existing": self.comments_existing,
            "export": self.export.to_dict(),
            "stats": self.stats,
        }


class ArticleService:
    def __init__(self, repo: EngineRepository) -> None:
        self.repo = repo
        self.settings = repo.settings

    def persist(
        self,
        collected: Collected,
        *,
        campaign_id: str,
        candidate_id: str,
    ) -> PersistResult:
        classification = collected.classification
        summary = build_summary(collected.article) or None

        existing = self.repo.find_item(collected.article.platform, collected.canonical_url)
        payload = {
            "platform": collected.article.platform,
            "canonical_url": collected.canonical_url,
            "title": collected.article.title,
            "summary": summary,
            "source_type": "ugc",
            "topic": classification.legacy_topic,
            "cohort": classification.cohort,
            "recruitment_stage": classification.recruitment_stage,
            "published_at": collected.article.published_at,
        }
        if existing is not None:
            # 重复采集保留首次采集时间，保证 Markdown 档案稳定可复现。
            payload["collected_at"] = existing["collected_at"]

        item_id, created = self.repo.save_article(payload)
        self.repo.attach_article(item_id, campaign_id=campaign_id)
        self.repo.set_classification(item_id, **classification.to_db_fields())
        self.repo.set_aux_classification(item_id, **classification.to_aux_fields())

        selection = collected.selection
        stats = selection.stats()
        stats["reason"] = selection.reason
        self.repo.update_stats(item_id, stats)

        node_payloads = [
            node.to_payload(selection.sort_basis) for node in selection.nodes
        ]
        comment_counts = self.repo.import_comments(item_id, node_payloads)

        item_row = self.repo.get_item(item_id)
        if item_row is None:
            raise KeyError(f"文章入库后读取失败：{item_id}")
        item = dict(item_row)
        comment_rows = [dict(row) for row in self.repo.item_comments(item_id)]
        # 渲染时空值显示为"未记录"，而不是字面的 None。
        render_stats = {key: value for key, value in stats.items() if value is not None}
        render_stats["coverage_status"] = stats["coverage_status"]
        render_stats["collected_top_level"] = stats["collected_top_level"]
        render_stats["collected_replies"] = stats["collected_replies"]
        export = export_article(self.settings, item, comment_rows, render_stats)

        self.repo.set_markdown_paths(
            item_id, post_path=export.post_path, comments_path=export.comments_path
        )
        self.repo.upsert_artifact(
            item_id=item_id,
            artifact_type="post_markdown",
            relative_path=export.post_path or "",
            sha256=export.post_sha or "",
        )
        self.repo.upsert_artifact(
            item_id=item_id,
            artifact_type="comments_markdown",
            relative_path=export.comments_path or "",
            sha256=export.comments_sha or "",
        )

        state = self.repo.candidate_state(candidate_id)
        if state == "completed":
            # 重复入库（重跑/恢复）不再推进状态，避免非法迁移。
            pass
        elif state == "accepted":
            self.repo.mark_completed(candidate_id, item_id)
        else:
            self.repo.mark_accepted(candidate_id, item_id)
            self.repo.mark_completed(candidate_id, item_id)

        _LOGGER.info(
            "文章入库完成：%s 新建=%s 一级=%s 楼中楼=%s 覆盖=%s",
            item_id,
            created,
            selection.collected_top_level,
            selection.collected_replies,
            selection.coverage_status,
        )
        return PersistResult(
            item_id=item_id,
            created=created,
            comments_inserted=int(comment_counts.get("inserted", 0)),
            comments_existing=int(comment_counts.get("existing", 0)),
            export=export,
            stats=stats,
        )
