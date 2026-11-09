# 就业情报 V4 — 阶段验收摘要

> 只记录脱敏状态、测试结果、数量与阻塞；不写入文章正文、评论全文、作者信息、Cookie、Profile 或数据库内容。

## 阶段总览

| 阶段 | 内容 | 状态 | 提交标题 |
|---|---|---|---|
| 1 | 项目审计与架构设计 | 完成 | 文档：完成就业情报模块化架构与数据模型设计 |
| 2 | Python 模块化重构 | 完成 | 重构：拆分研究数据处理与存储模块 |
| 3 | SQLite V3 与文件档案 | 完成 | 数据库：新增评论层级与就业采集批次管理 |
| 4 | 浏览器工作流与 20 篇试采集 | 未开始 | 测试：完成就业文章与评论采集小规模验收 |
| 5 | 1000 篇真实采集 | 未开始 | 采集：完成就业文章评论与楼中楼入库 |
| 6 | 分析、报告与最终验收 | 未开始 | 报告：完成 2026 届与 2027 届就业情报分析 |

## 阶段 1 — 项目审计与架构设计

- 日期：2026-11-09
- Git 审计：`main` 与 `origin/main` 均为 `c8d8bbd`，工作区干净；未做 reset/clean。
- 数据库审计（迁移前）：
  - `user_version=2`，`integrity_check=ok`，外键违规 0；
  - 表：`tasks`、`runs`、`datasets`、`run_datasets`、`research_items`、`run_research_items`；
  - 数量：`tasks=2`、`runs=2`、`datasets=5`、`run_datasets=5`、`research_items=12`、`run_research_items=12`。
- 备份：使用 SQLite Online Backup API 生成于本地忽略目录 `data/catalog/backups/`；备份文件 118,784 字节，SHA-256 `e34f5dfea7b3bded35def4cb6edceb94a84e7a13c1fe0d550ee7d4b2fc7623c3`，备份完整性检查通过。
- 设计交付：
  - `docs/ARCHITECTURE_EMPLOYMENT.md`：模块边界、SQLite V3 表、文件档案结构、Campaign/Batch/checkpoint、评论规则与不变量；
  - `tasks/employment/CURRENT_TASK.md`：1000 篇目标、平台/届别配额、关键词、评论规则、输出与验收；
  - `AGENTS.md`：新增长期 Campaign 规范。
- 未改代码、未改旧迁移、未访问外部站点、未修改历史 12 条记录。
- 测试：本阶段为文档与审计；阶段 2 起补充模块测试。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 6 交付表。

## 阶段 2 — Python 模块化重构

- 日期：2026-11-09
- 新增包：`scripts/employment/`
  - `models.py`：平台/主题/届别/核验/排序/覆盖状态与数据结构；
  - `normalize.py`：URL、文本、ISO-8601、相对时间与联系方式脱敏；
  - `deduplicate.py`：文章身份与评论去重键（无平台 ID 时使用父评论 + 内容指纹 + 层级 + 相对时间）；
  - `validate.py`：文章/评论字段校验、`verified` 证据约束、评论树校验、50 条一级评论选择算法；
  - `repository.py`：复用 V2 的 `research_items` 写入与关联；
  - `artifacts.py`：产物路径、写入与 SHA-256；
  - `markdown_export.py`：文章、评论、索引 Markdown；评论档案拒绝作者身份字段；
  - `analytics.py`：文章/评论/覆盖统计。
- 兼容性：`scripts/research_catalog.py` 未改参数与行为；Roboflow 与旧测试保持通过。
- 测试：`python -m unittest discover -v` → **62 个测试全部通过**（新增 19 个；原 43 个全部保留）。
- 数据库：未修改 schema，未写入真实数据。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 6 交付表。

## 阶段 3 — SQLite V3 与文件档案

- 日期：2026-11-09
- 迁移：新增 `003_employment_comments_and_batches.sql`（未修改 001/002）。
  - 重建 `research_items` 以扩展核验状态并加入评论统计/档案/Campaign 字段；
  - 新增 `research_comments`、`research_campaigns`、`research_batches`、`research_artifacts`；
  - 迁移期间临时关闭外键，迁移后执行 `foreign_key_check`。
- 真实库升级：`user_version 2 -> 3`；迁移前自动备份（118,784 字节，SHA-256 `e34f5dfea7b3bded35def4cb6edceb94a84e7a13c1fe0d550ee7d4b2fc7623c3`）。
- 历史数据：`datasets=5`、`runs=2`、`research_items=12`、`run_research_items=12` 全部保留；`integrity_check=ok`，外键违规 0。
- 新增能力：
  - `repository.import_comment_thread`：父子/根评论层级、幂等导入、无平台 ID 时组合去重、作者字段拒绝；
  - `repository.update_article_stats`、Campaign/Batch/Artifact CRUD；
  - `exporter.export_article_artifacts`：文章与评论 Markdown、SHA 登记、回写路径；
  - `exporter.export_platform_index`：平台 all / 2026 / 2027 索引。
- 测试：`python -m unittest discover -v` → **70 个测试全部通过**（新增 8 个 V3/评论/导出测试）。
- 未访问外部站点，未写入真实评论数据。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 6 交付表。
