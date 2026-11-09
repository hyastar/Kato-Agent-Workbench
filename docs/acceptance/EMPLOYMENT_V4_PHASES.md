# 就业情报 V4 — 阶段验收摘要

> 只记录脱敏状态、测试结果、数量与阻塞；不写入文章正文、评论全文、作者信息、Cookie、Profile 或数据库内容。

## 阶段总览

| 阶段 | 内容 | 状态 | 提交标题 |
|---|---|---|---|
| 1 | 项目审计与架构设计 | 完成 | 文档：完成就业情报模块化架构与数据模型设计 |
| 2 | Python 模块化重构 | 完成 | 重构：拆分研究数据处理与存储模块 |
| 3 | SQLite V3 与文件档案 | 完成 | 数据库：新增评论层级与就业采集批次管理 |
| 4 | 浏览器工作流与 20 篇试采集 | 完成（评论覆盖部分完整） | 测试：完成就业文章与评论采集小规模验收 |
| 5 | 1000 篇真实采集 | 部分完成（实际 20/1000） | 采集：完成首批就业文章评论与楼中楼入库 |
| 6 | 分析、报告与最终验收 | 完成 | 报告：完成 2026 届与 2027 届就业情报分析 |

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

## 阶段 4 — 浏览器工作流与 20 篇试采集

- 日期：2026-11-09
- 运行：`20261109T053116Z-edbf`（本地 `runs/`，未提交 Git）；Campaign `employment-2026-2027-1000-20261109`。
- 浏览器手册：新增 `docs/platforms/ZHIHU.md`、`docs/platforms/XIAOHONGSHU.md`。
- 真实采集：
  - 小红书 16 篇、知乎 4 篇，共 20 篇唯一文章；2026 届 8、2027 届 12。
  - 全部通过 Playwright MCP 操作真实 Chrome；登录沿用用户已完成的会话，本轮未出现新的登录/验证码。
- 评论：
  - 一级评论 211 条、楼中楼 154 条，合计 365 条；
  - 覆盖：complete 9 篇、partial 8 篇、not_available 3 篇；
  - 小红书超过 50 条一级评论的笔记按高赞 30 + 默认可见顺序末段 20 选择，记录“无官方排序控件”限制；
  - 知乎评论 DOM 无稳定对象 ID，按可见顺序采集一级评论，未区分楼中楼层级。
- 档案：文章 Markdown 20 份、评论 Markdown 20 份、索引 6 份；SHA 已写入 `research_artifacts`。
- 幂等与恢复：重复执行知乎导入后，文章仍 22 条（含历史 2 条）、评论仍 365 条，未重复插入；checkpoint 已写入本地 `runs/`。
- 测试：`python -m unittest discover -v` → 70 个测试全部通过（代码未变更）。
- 未完成：Campaign 1000 篇尚未批量执行；6 篇评论 partial 与 3 篇 not_available 需补采。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 6 交付表。

## 阶段 5 — 1000 篇真实采集（部分完成）

- 日期：2026-11-09
- Campaign：`employment-2026-2027-1000-20261109`（目标 1000；小红书 800、知乎 200；2026 届 400、2027 届 600）。
- 实际：**20 篇唯一文章**（小红书 16、知乎 4；2026 届 8、2027 届 12）。
  - 复用历史 10 篇（6 小红书 + 4 知乎）并补采评论；
  - 新增 10 篇小红书。
- 评论：一级 211、楼中楼 154，合计 365；覆盖 complete 9、partial 8、not_available 3。
- 档案：文章 Markdown 20、评论 Markdown 20、平台/届别索引 6、报告 5；SHA 写入 `research_artifacts`。
- Campaign 状态：`partial`，`actual_total=20`。
- 未完成：800/200 的批量配额未达成；原因是个位到十位级别的逐篇评论展开需要真实浏览器交互，本轮时间不足以完成 1000 篇。**未用重复、演示或搜索结果数量充数。**
- 恢复：Campaign、批次、checkpoint 与 SQLite 状态已保留，后续可从 `pilot-xhs-16` / `pilot-zhihu-4` 之后继续新批次。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 6 交付表。

## 阶段 6 — 分析、报告与最终验收

- 日期：2026-11-09
- 报告：
  - `data/employment/reports/campaigns/employment-2026-2027-1000-20261109.md`；
  - 小红书、知乎平台报告；
  - 2026 届、2027 届报告；
  - 索引：两个平台各 all / 2026 / 2027，共 6 份；
  - 报告均由 `scripts.employment.report` 生成，SHA 写入 `research_artifacts`。
- 最终核对：
  - SQLite `user_version=3`；`research_items=22`（Campaign 内 20 + 历史 2）；`research_comments=365`（一级 211、楼中楼 154）；
  - Campaign 状态 `partial`，`actual_total=20`；批次 `pilot-xhs-16=partial`、`pilot-zhihu-4=completed`；
  - `PRAGMA integrity_check=ok`，外键违规 0；
  - 51 个产物文件存在且 SHA-256 与数据库一致（修复了 Windows 换行导致的历史不一致）；
  - `python -m unittest discover` → 73 个测试全部通过；
  - `python -m scripts.doctor` → PASS=9 WARN=0 FAIL=0。
- Git 安全：`data/employment/` 已加入 `.gitignore`；未提交 SQLite、`runs/`、`workspace/`、Profile、Cookie 或 `.env`；忽略目录仅 `.gitkeep` 被跟踪。
- 结论：开发、模块化、V3 数据模型、浏览器试采集、评论入库、Markdown 档案与分析报告均完成；1000 篇配额实际完成 20 篇，如实标记 `partial`。

## 交付表（阶段 1–6）

| 阶段 | 提交标题 | 本地 SHA | 远端 SHA | 一致 |
|---|---|---|---|---|
| 1 | 文档：完成就业情报模块化架构与数据模型设计 | `93f9526d5ea7520acaaaadd9bb759a7f5a3166d8` | 同左 | 是 |
| 2 | 重构：拆分研究数据处理与存储模块 | `620c75469ac60139d478dec7a39ed9b573dd9864` | 同左 | 是 |
| 3 | 数据库：新增评论层级与就业采集批次管理 | `56787f773729bf23d7e7ff17827f4fe607b863fd` | 同左 | 是 |
| 4 | 测试：完成就业文章与评论采集小规模验收 | `f03754863e459b8cb9a5370d1ce2199bf3dd1ef1` | 同左 | 是 |
| 5 | 采集：完成首批就业文章评论与楼中楼入库 | `c294ce47dff0a2553d2cf7efb5c6b42003f65c17` | 同左 | 是 |
| 6 | 报告：完成 2026 届与 2027 届就业情报分析 | 本次提交 | 推送后核对 | 见最终汇报 |
