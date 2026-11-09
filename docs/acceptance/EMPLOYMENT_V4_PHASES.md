# 就业情报 V4 — 阶段验收摘要

> 只记录脱敏状态、测试结果、数量与阻塞；不写入文章正文、评论全文、作者信息、Cookie、Profile 或数据库内容。

## 阶段总览

| 阶段 | 内容 | 状态 | 提交标题 |
|---|---|---|---|
| 1 | 项目审计与架构设计 | 完成 | 文档：完成就业情报模块化架构与数据模型设计 |
| 2 | Python 模块化重构 | 未开始 | 重构：拆分研究数据处理与存储模块 |
| 3 | SQLite V3 与文件档案 | 未开始 | 数据库：新增评论层级与就业采集批次管理 |
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
