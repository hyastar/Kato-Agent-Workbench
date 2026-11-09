# 就业情报模块化架构与数据模型（V4 设计）

本文件描述就业情报工作流在 V4 中的模块边界、SQLite V3 模型、文件档案结构、Campaign/Batch 状态和评论采集规则。实现按阶段增量落地，不推倒现有 Roboflow 与 V2 数据。

## 1. 定位与分工

- 宿主 Agent（ZCode / Codex）：理解任务、规划、操作 Playwright MCP、处理异常、请求人工登录。
- Playwright MCP：操控真实 Chrome，完成搜索、点击、滚动、详情读取、评论展开与排序切换。
- Python：只做确定性工作——标准化、去重、校验、SQLite 读写、Markdown 生成、统计与报告。
- SQLite：结构化索引、关系、批次与产物元信息。
- Markdown：可读的文章档案、评论档案、索引与报告。

不新增独立 Agent 引擎、浏览器爬虫、前端或重型依赖。

## 2. Python 模块边界

实现位置：`scripts/employment/`（包），原 `scripts/research_catalog.py` 保留为兼容 CLI。

| 模块 | 职责 |
|---|---|
| `models.py` | 文章、评论、Campaign、Batch、Artifact 的数据类与枚举 |
| `normalize.py` | URL、时间、平台、届别、招聘阶段、主题标准化 |
| `deduplicate.py` | 文章与评论去重键；无平台评论 ID 时的组合键 |
| `validate.py` | 字段、枚举、父子关系、计数、脱敏与文件完整性检查 |
| `repository.py` | SQLite 事务与 CRUD；复用 `scripts/db.py` 的连接与迁移 |
| `artifacts.py` | 产物路径、SHA-256、产物索引 |
| `markdown_export.py` | 文章 Markdown、评论 Markdown、平台/届别索引 |
| `analytics.py` | 统计与评论观点聚合 |
| `campaign.py` | Campaign 生命周期 |
| `batch.py` | 批次进度、checkpoint、恢复 |
| `report.py` | 平台、届别与综合报告 |

约束：

- 浏览器操作不进入 Python；Python 不联网。
- 所有写库使用参数化 SQL 与事务。
- 旧 CLI 参数保持兼容，新增能力以子命令或参数扩展。

## 3. SQLite V3 模型

新增迁移 `003_employment_comments_and_batches.sql`，不修改 `001` / `002`。

### 3.1 `research_comments`

| 字段 | 说明 |
|---|---|
| `comment_id` | 本地主键 |
| `research_item_id` | FK → `research_items.item_id` |
| `platform_comment_id` | 页面可见评论对象 ID，可空 |
| `parent_comment_id` | 直接父评论内部 ID，一级评论为空 |
| `root_comment_id` | 所属一级评论内部 ID，一级评论为自身 |
| `comment_level` | 1 = 一级评论；≥2 = 楼中楼 |
| `content` | 清理与脱敏后的文本 |
| `content_hash` | 内容指纹 |
| `like_count` | 可见点赞数，可空 |
| `reply_count_displayed` | 页面显示回复数，可空 |
| `published_at` | 可确认的绝对时间，可空 |
| `published_time_displayed` | 页面相对时间原文，可空 |
| `collected_at` | 采集时间 |
| `collection_order` | 本次采集顺序 |
| `sort_basis` | `high_likes` / `latest` / `visible_order` |
| `redaction_status` | 脱敏状态 |
| `created_at` | 创建时间 |

去重：优先 `(research_item_id, platform_comment_id)`；缺失时使用 `(research_item_id, parent_comment_id, content_hash, comment_level, published_time_displayed)`。不同父评论下的相同文本不合并。

禁止字段：作者昵称、作者 ID、主页、头像、简介、地理位置、联系方式。

### 3.2 `research_campaigns`

`campaign_id`、`name`、`status`、`target_total`、`target_xiaohongshu`、`target_zhihu`、`target_2026`、`target_2027`、`actual_total`、`created_at`、`started_at`、`finished_at`、`notes`。

### 3.3 `research_batches`

`batch_id`、`campaign_id`、`platform`、`cohort`、`keyword`、`target_articles`、`discovered`、`succeeded`、`failed`、`top_level_comments`、`nested_replies`、`status`、`checkpoint_path`、`started_at`、`finished_at`、`error_summary`。

状态：`pending` / `running` / `partial` / `completed` / `blocked` / `failed`。

### 3.4 `research_artifacts`

`artifact_id`、`research_item_id`、`artifact_type`（`post_markdown` / `comments_markdown` / `index` / `report`）、`relative_path`、`sha256`、`generated_at`、`status`。

### 3.5 文章统计字段

通过扩展 `research_items`（新列）或独立统计表表达：

- 页面显示评论总数、一级评论总数；
- 实际采集一级评论数；
- 页面显示回复总数、实际采集楼中楼数；
- 评论覆盖状态与排序策略；
- 文章/评论 Markdown 路径；
- Campaign / Batch 关联。

评论正文不写入 `research_items`。

### 3.6 核验状态扩展

在保留 V2 值的基础上支持：`unverified`、`partially_verified`、`verified`、`contradicted`、`expired`。

## 4. 文件档案结构

```text
data/employment/
├── xiaohongshu/{posts,comments,indexes}/
├── zhihu/{posts,comments,indexes}/
├── reports/{campaigns,cohorts,platforms}/
└── manifests/
runs/<run-id>/{task_snapshot.md,progress.md,results.json,checkpoints/}
```

命名使用内部稳定 ID：

- `data/employment/<platform>/posts/<item_id>.md`
- `data/employment/<platform>/comments/<item_id>.comments.md`
- 索引：`data/employment/<platform>/indexes/all.md`、`2026.md`、`2027.md`

文章 Markdown 以元信息、结构化事实、自写摘要为主，不复制整篇正文。评论 Markdown 只含评论文本、点赞、时间、层级与覆盖统计，不含作者身份信息。

## 5. 评论采集规则

1. 每篇最多 **50 条一级评论**；楼中楼不计入 50。
2. 一级评论 ≤50：采集全部可访问一级评论。
3. >50：高赞前 30 + 最新前 20，去重补足；无排序选项时按可见顺序并记录限制。
4. 每条选中一级评论下尽可能展开全部可访问楼中楼，继续展开子回复，保留父子层级。
5. 分别记录页面显示数、实际采集数、排序方式、覆盖状态与未采集原因。
6. 中断时保存 checkpoint，线程标记 `partial`。

覆盖状态：`complete` / `partial` / `blocked` / `not_available`。

## 6. Campaign / Batch / 恢复

- Campaign：`employment-2026-2027-1000-20261109`，目标 小红书 800、知乎 200；2026 届 400、2027 届 600。
- 每批约 20 篇；每批完成搜索、文章、评论、入库、Markdown、索引、进度与 checkpoint。
- 至少每 5 篇保存一次 checkpoint；长任务可每篇保存。
- 恢复时先查 SQLite 与 checkpoint，已完成文章/评论不重复采集。
- 失败类型区分：登录要求、验证要求、限流、页面加载失败、详情不可用、评论不可用、回复展开失败、浏览器断开、校验失败、重复、未知。

## 7. 不变量

- 文章数、评论数分别统计；评论不计入文章目标。
- `verified` 必须有证据 URL 与核验时间；UGC 不得升级为官方事实。
- 不伪造时间、点赞数、评论总数、排序方式或核验状态。
- 作者身份字段与联系方式不入库。
- 采集数据、SQLite、Markdown 档案、Profile、Cookie、Token 不提交 Git。
- Roboflow 工作流与历史数据保持可用。
