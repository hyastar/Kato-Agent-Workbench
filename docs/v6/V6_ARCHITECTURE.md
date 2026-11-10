> **状态：已被 V6.1 取代（2026-11-10）。**
> 浏览器执行层从"Python 拥有 Chrome 会话"改为"ZCode 内置 Browser Use 持有会话"。
> 现行架构见 `docs/v6/V6_1_ZCODE_BROWSER.md`；本文保留为 V6 设计与审计依据。

# Kato Collection Engine V6 架构

版本：6.0
日期：2026-11-10
前置阅读：`docs/v6/V6_AUDIT.md`（审计结论）、`docs/ARCHITECTURE_EMPLOYMENT.md`（V4 业务模型）

---

## 1. 定位

V6 是一个**独立运行、可连续工作、可断点恢复**的浏览器采集引擎。它自己拥有 Chrome、自己驱动任务循环、自己写入 SQLite 与 Markdown。

分工：

| 层 | 角色 | 职责 |
|---|---|---|
| ZCode | 开发与监督 | 架构决策、编码、测试验收、复杂异常判定；不再逐篇操作浏览器 |
| `kato_engine/`（V6） | 执行 | 会话管理、关键词调度、候选队列、页面采集、落库、导出、恢复 |
| `scripts/`（保留） | 离线工具 | 初始化、校验、报告、历史数据维护 |
| SQLite / Markdown | 事实层 | 结构化索引 + 人类可读档案 |

本轮正式废除"Python 只能做确定性离线操作"的限制：浏览器自动化、调度与采集由 Python 承担。

---

## 2. 目录与依赖方向

```text
kato_engine/
├── config/          settings.py, loader.py      # 路径、平台开关、配额、限速
├── core/            engine.py, scheduler.py, lifecycle.py, state_machine.py
├── browser/         manager.py, session.py, navigation.py, interaction.py, errors.py
├── platforms/       base.py, xiaohongshu.py, zhihu.py
├── discovery/       keyword_planner.py, candidate_queue.py, deduplication.py
├── collection/      article.py, comments.py, thread_tree.py, classification.py
├── storage/         repository.py, migrations.py, markdown.py, checkpoints.py
├── observability/   metrics.py, logging.py, reporting.py
└── cli.py
```

依赖方向（只允许单向）：

```text
cli → core → (platforms, discovery, collection) → (browser, storage, config)
platforms → browser, collection.models
storage → config
observability 被所有层调用，不反向依赖
```

`scripts/` 不导入 `kato_engine`；`kato_engine` 可以只读复用 `scripts/db.py` 的迁移与幂等函数，但**不**调用 `scripts/employment/browser/*`。

---

## 3. 会话所有权模型

- 唯一所有者：`BrowserManager`。进程内单例，持有 `Playwright → BrowserContext → Page`。
- 启动方式：`chromium.launch_persistent_context(user_data_dir=<repo 外的 Profile>, channel="chrome", headless=False)`。
- 登录态：复用 `D:\Code\Github\Code\.kato-playwright-profile`（路径由 `config/settings.py` 解析为 `<repo>/../.kato-playwright-profile`，可用环境变量 `KATO_BROWSER_PROFILE` 覆盖）。
- 锁检测：启动前检查 `SingletonLock`/`ProcessSingleton` 与 `chrome.exe` 命令行；被占用时抛出 `ProfileInUseError`，**不**自动改用临时 Profile。
- 健康检查：`context.pages` 可枚举 + `page.evaluate("1+1")==2` + 当前 URL 可读；任一失败即视为未连接，禁止进入采集循环。
- 关闭：`context.close()` → `playwright.stop()`，异常路径用 `try/finally` 保证释放。
- 断线：`page.on("close")` / 导航异常 → `PageLostError`，`RecoveryManager` 依据数据库状态决定重开页面或重开会话。

---

## 4. Campaign 状态机

### 4.1 候选状态

```text
discovered ──► queued ──► processing ──► accepted ──► completed
     │            │            │
     │            │            ├─► retryable_failed ──► queued (attempts < max)
     │            │            ├─► blocked        (登录/验证码/403，需人工)
     │            │            └─► rejected       (不相关/无正文/重复内容)
     │            └─► skipped (关键词无效/候选已存在)
     └─► rejected
```

约束：

- 状态迁移只能经 `state_machine.py`，非法迁移抛 `InvalidTransition`。
- `processing` 是**租约**：带 `lease_owner` 与 `lease_until`；进程崩溃后超时租约可被回收为 `queued`。
- `attempts` 上限默认 3；达到上限转 `rejected` 并记录 `last_error`。
- `accepted` 表示已入库且 Markdown 已落盘；`completed` 表示评论覆盖流程走完（含 `partial`/`not_available`）。

### 4.2 Campaign 循环

```text
读取 campaign + 目标配额
  ├─ 平台配额未满？
  │    ├─ 选维度（缺口最大且有关键词未执行）
  │    ├─ 执行搜索 → 候选入队（去重）
  │    └─ 队列空则换关键词，关键词耗尽则换维度
  ├─ 取队首候选（lease）
  ├─ 打开详情 → 判相关 → 采集正文 + 评论
  ├─ 校验 → SQLite 幂等写入 → Markdown 导出 → 记录 SHA
  ├─ checkpoint（候选状态 + 计数 + 耗时）
  └─ 继续下一条（不因 20 篇停止）
```

- 每 20 篇做一次一致性核对（计数、SHA、覆盖率），**不**停下等待指令。
- 人工等待时间单独记账：`blocked` 期间不计入吞吐分母。

---

## 5. 关键词调度

数据源：`tasks/employment/search_keywords.json`（10 维，每维 10 关键词，`modifiers` 提供届别前缀）。

规则：

1. 维度优先级 = `target / campaign_target - 已采集占比`，缺口大的优先。
2. 同维度内按 `keywords` 顺序取**未执行**关键词；同一平台同一关键词只执行一次（`research_search_queries` 唯一性）。
3. 关键词与 modifier 组合成实际查询串（如 `26届 到手工资`），组合级去重。
4. 无效关键词（结果 < 阈值或全为重复）标记 `exhausted`，计入 `notes`，不再重试。
5. 分类**不**依据关键词：入库后由 `collection/classification.py` 按正文内容判定 `employment_topic` / `graduation_cohort` / `employment_status`。

搜索记录字段（新增）：`candidates_found`、`duplicates`、`opened_details`、`accepted`、`failure_reason`、`duration_ms`。

---

## 6. 平台适配器契约

```python
class PlatformAdapter(Protocol):
    name: str
    def search(self, query: str, limit: int) -> list[Candidate]: ...
    def open_detail(self, candidate: Candidate) -> DetailPage: ...
    def is_relevant(self, detail: DetailPage) -> tuple[bool, str]: ...
    def read_article(self, detail: DetailPage) -> ArticleData: ...
    def collect_comments(self, detail: DetailPage, limit: int = 50) -> CommentBundle: ...
```

- 知乎：搜索页 → 问题/专栏页；评论层级按缩进差（一级 ~91px，楼中楼 ~125px），不使用全局文本去重。
- 小红书：搜索页 → 必须点击真实卡片进入（URL 自动带 `xsec_token`），禁止拼接 `/explore/<id>`；层级按 `reply-container` 递归，支持多层。
- 共享：滚动/展开稳定检测（连续 3 轮无增长即停）、50 条规则、作者身份字段**在抽取阶段即丢弃**，不进入内存数据结构。

---

## 7. 存储设计

### 7.1 新增迁移 `005_v6_engine.sql`

| 表 | 用途 | 关键列 |
|---|---|---|
| `engine_candidates` | 持久化候选队列 | `candidate_id` PK, `campaign_id`, `platform`, `canonical_url`, `search_query_id`, `dimension`, `state`, `attempts`, `lease_owner`, `lease_until`, `last_error`, `error_type`, `discovered_at`, `updated_at`；唯一索引 `(platform, canonical_url)` |
| `engine_query_runs` | 关键词执行明细 | `query_run_id` PK, `campaign_id`, `platform`, `dimension`, `keyword`, `combined_query`, `candidates_found`, `duplicates`, `opened_details`, `accepted`, `failure_reason`, `duration_ms`, `executed_at`；唯一索引 `(platform, combined_query)` |
| `engine_runs` | 引擎运行（进程级） | `engine_run_id` PK, `campaign_id`, `started_at`, `finished_at`, `stop_reason`, `articles_added`, `comments_added`, `profile_used` |
| `engine_metrics` | 单篇耗时与失败原因 | `metric_id` PK, `candidate_id`, `phase`, `duration_ms`, `outcome`, `error_type` |
| `research_artifacts`（扩展） | Markdown 哈希 | 新增 `sha256`, `bytes`, `generated_at` 列 |

不变式：

- `engine_candidates.canonical_url` 与 `research_items.canonical_url` 使用同一规范化函数（`scripts/db.normalize_url`）。
- 文章入库仍走既有唯一索引 `ux_research_items_identity`，`ON CONFLICT` 幂等。
- 备份 → `integrity_check` → 迁移 → 再次 `integrity_check` → 计数比对（41 篇 / 728 评论不得变化）。

### 7.2 Markdown

- 路径沿用 `data/employment/<platform>/{posts,comments}/`。
- 导出后计算 SHA-256 写入 `research_artifacts`；`kato_engine storage verify` 可对账。
- 重跑同一篇文章：内容不变则文件不改写（幂等），内容变化则重写并更新哈希。

---

## 8. 错误分类

| 错误 | 类型 | 处理 |
|---|---|---|
| 选择器缺失/结构变化 | `selector_error` | 记录、转 `retryable_failed`，连续 3 次同类型则停止该平台 |
| 页面加载超时 | `timeout` | 重试 1 次后 `retryable_failed` |
| 内容不相关 | `irrelevant` | `rejected`，不重试 |
| 无正文 | `empty_content` | `rejected` |
| 需要登录 | `auth_required` | `blocked`，暂停该平台，请求用户 |
| 验证码/设备确认 | `verification_required` | `blocked`，暂停该平台，请求用户 |
| 403 / 限流 | `rate_limited` | `blocked`，停止该平台本轮，记录时间 |
| 浏览器断开 | `page_lost` | 重开页面；失败 2 次重开会话 |
| Profile 被占用 | `profile_in_use` | 启动阶段中止，提示关闭 MCP 浏览器 |

---

## 9. 可观察性

单篇记录：搜索发现、页面打开、正文提取、一级评论加载、楼中楼展开、SQLite 写入、Markdown 导出、总耗时。

汇总指标：每小时新增唯一文章、每小时评论完整覆盖文章数、详情进入成功率、相关内容命中率、评论覆盖率、重复率、恢复成功率；同时输出"纯执行时长"与"人工等待时长"两个口径。

---

## 10. 阶段与验收

| 阶段 | 交付 | 验收 |
|---|---|---|
| 1 | 审计 + 架构（本文） | 文档评审通过，改动提交 |
| 2 | Browser Manager | 真实启动 Chrome、导航本地页、提取 DOM、关闭；Profile 占用时报错 |
| 3 | 关键词调度 + 候选队列 | 10 维加载、配额选择、跨关键词去重、重启续跑 |
| 4 | 平台适配器 | 真实页面取到正文 + 一级评论 + 楼中楼父子关系 |
| 5 | 存储与生命周期 | 迁移备份/校验通过、41 篇 728 评论不变、幂等重跑不新增 |
| 6 | Campaign Engine | 无人值守从关键词推进到 Markdown，自动进入下一条 |
| 7 | 端到端验收 | 启动/发现/详情/评论/入库/停止/恢复全链路 |
| 8 | 正式采集 200 篇 | 小红书 +160、知乎 +40，真实计数 |
| 9 | 质量与性能报告 | 与 V5 对比，SHA 校验，Git 交付 |

每个阶段：测试 → 中文提交 → `git push origin main` → 核对远端 SHA。

---

## 11. 明确不做

- 不做 Agent 框架、前端、分布式队列、Docker。
- 不调用隐藏/逆向接口，不抓取登录态 API，不使用代理池或指纹伪装。
- 不把 Cookie、Profile、正文、评论内容写入 Git 或普通日志。
- 不自动删除历史数据、`runs/`、数据库。
