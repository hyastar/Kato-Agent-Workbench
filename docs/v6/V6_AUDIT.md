# V6 架构审计报告

审计时间：2026-11-10
审计对象：V4 → V5.2 的就业情报执行层、SQLite 模型、Markdown 档案、运行环境与迁移风险
结论：**执行层不是"写得不好"，而是从未存在**。V6 必须新建执行系统，不是在 `runner.py` 外面再包一层循环。

---

## 1. 执行层审计

### 1.1 现状盘点

| 路径 | 行数 | 实际职责 | 是否拥有浏览器 |
|---|---:|---|---|
| `scripts/employment/browser/runner.py` | 134 | 规范化 MCP 返回的 payload、写 checkpoint、入队搜索结果 | 否 |
| `scripts/employment/browser/actions.py` | 179 | 生成注入浏览器的 JS 动作片段（字符串常量） | 否 |
| `scripts/employment/browser/extraction.py` | 141 | 把 payload 转成 `ArticleResult`、50 条规则、覆盖判定 | 否 |
| `scripts/employment/browser/discovery.py` | 85 | 搜索结果 JSON → 候选队列 JSON（内存/文件） | 否 |
| `scripts/employment/browser/contracts.py` | 73 | dataclass 与 `BrowserExecutionError` | 否 |

`runner.py` 的模块 docstring 原文：*"浏览器动作由宿主 Agent 通过 Playwright MCP 完成；本模块只处理已返回的 payload…不发起任何网络请求。"*

### 1.2 机制性缺口

1. **没有会话所有权**：浏览器由 ZCode 的 MCP 驱动进程创建，生命周期不由本项目控制；MCP 进程退出或空闲回收后，任何"循环"都失去执行能力。
2. **没有任务循环**：批次推进靠 Agent 每篇文章手动调用一次工具；`20 篇一批`是人工边界，不是引擎状态机。
3. **没有候选状态机**：候选只以 JSON 列表在内存/磁盘短暂存在，重启即丢；数据库无一列记录 `discovered → queued → processing → accepted/…`。
4. **关键词调度是空壳**：V5.2 已建 `tasks/employment/search_keywords.json`（10 维）与 `research_search_queries` 表，但没有任何代码按配额选择"仍缺样本的主题 + 未执行关键词"；实际执行仍出现过硬编码"2026届 秋招"。
5. **检查点粒度错误**：checkpoint 只记录单篇文章结果，不记录"下一条候选是谁"；恢复时无法自动续跑。
6. **覆盖率不可解释**：`not_available=11 / partial=11 / complete=21`，但没有失败原因字段，无法区分"无评论区"与"选择器失效"。

### 1.3 结论

旧 `scripts/employment/browser/` 只能作为**协议参考**（50 条规则、覆盖判定、选择器经验），不能作为 V6 的运行时。V6 验收通过后整目录废弃。

---

## 2. 数据资产审计

### 2.1 数据库现状（`data/catalog/workbench.sqlite3`，782 KB）

| 表 | 行数 | 说明 |
|---|---:|---|
| `research_items` | 43 | 41 篇属 Campaign，2 篇为更早历史记录（`campaign_id IS NULL`） |
| `research_comments` | 728 | 一级 325 + 楼中楼 403 |
| `research_campaigns` | 1 | `employment-2026-2027-1000-20261109`，`actual_total=41` |
| `research_search_queries` | 10 | 5 维 × 2 平台，每平台仅执行 1 个关键词 |
| `research_keyword_candidates` | 0 | 建表但从未使用 |
| `research_artifacts` | 93 | Markdown 侧车元信息 |
| `research_batches` | 5 | V4/V5 批次 |
| `research_campaigns.actual_total` | 41 | 与 `research_items` 43 的差额来自 2 篇非 Campaign 记录，**不是**计数错误 |

### 2.2 数据质量缺口

- `cohort`、`employment_topic`、`graduation_cohort`、`industry` 等全部为 `NULL`：十维分类与届别判定**从未写入**，即使 V5.2 已加列。
- 无 `status` / `attempts` / `last_error` 一族字段；失败文章无法与"未采集"区分。
- `displayed_comments_total` 存在但部分为 `NULL`，覆盖状态无法复算。
- 41 篇全部有 `post_markdown_path` 且文件存在（实测 41/41），SHA 未入表，需在阶段 5 建立 `sha256` 一致性校验。
- `canonical_url` 唯一索引 `ux_research_items_identity(platform, canonical_url)` 已存在，跨关键词去重可复用它作为最终判据。

### 2.3 Markdown 档案

- 结构：`data/employment/<platform>/{posts,comments,indexes}/`，共 95 个 `.md`。
- 无内容哈希清单，无法判断"文件被手工改过"还是"导出器升级后过期"。

### 2.4 结论

数据可以完整保留；V6 只需**新增**候选队列表、搜索查询扩展字段与 Markdown 哈希表，不需要重建已有表。

---

## 3. 环境审计

| 项 | 实测结果 | 影响 |
|---|---|---|
| Conda 环境 | `Kato-Agent-Workbench`，Python 3.12.16 | 可用 |
| `playwright` | 审计前缺失；本轮安装 1.65.0（含 greenlet 3.5.6） | V6 依赖已满足 |
| Chrome | `C:\Program Files\Google\Chrome\Application\chrome.exe`，版本 156.0.8078.81 | `channel="chrome"` 实测启动/关闭成功，无需下载 Chromium |
| Node / npx | v24.21.0 / 11.19.0 | MCP 仅保留为调试工具 |
| 持久 Profile | `D:\Code\Github\Code\.kato-playwright-profile`，513 MB，含登录态 | **必须独占**；当前被运行中的 Chrome 占用 |
| 测试基线 | `python -m unittest discover -s tests -t .` → 95 passed | 阶段验收以此为回归基线 |
| SQLite | 标准库 | 无需额外依赖 |

### 3.1 浏览器所有权风险（最高优先级）

同一 `--user-data-dir` 不允许两个 Chrome 进程同时使用。当前 ZCode MCP 浏览器可能占用该目录，V6 启动会直接失败（`ProcessSingleton` 锁）。处理方式：

1. V6 启动前做**锁检测**，检测到占用时立即返回明确错误并提示关闭 MCP 浏览器，不允许静默降级为临时 Profile；
2. V6 独占期内，ZCode 不再打开同一 Profile；
3. 引擎退出时通过 `context.close()` 释放锁。

---

## 4. 迁移风险

| 风险 | 影响 | 处置 |
|---|---|---|
| 旧库被 V6 迁移破坏 | 丢失 41 篇/728 评论 | 迁移前 `backup_database()` + `PRAGMA integrity_check`，失败即中止 |
| 修改已应用迁移 | 破坏历史可复现性 | 仅新增 `005_*.sql`，禁止改 001–004 |
| 新旧 schema 语义漂移 | 计数对不上 | 阶段 5 建立字段映射表并逐列核对 |
| 重复插入 | 数量虚高 | 依赖既有唯一索引 + `INSERT ... ON CONFLICT` 幂等测试 |
| Markdown 与库不一致 | 验收不可信 | 新增 `sha256` 记录与校验命令 |
| Profile/Cookie 入库 | 安全事故 | `.gitignore` 已覆盖，V6 路径固定在仓库外 |

---

## 5. 本轮不可改变的业务约束（审计确认）

- Campaign：`employment-2026-2027-1000-20261109`，现 41/1000，本轮 +200 → 241/1000（小红书 +160、知乎 +40）。
- 每篇一级评论 ≤ 50；`>50` 时高赞前 30 + 最新前 20，去重后不足再补；排序不可确认时记录 `visible_order`，不得声称"最新"。
- 选中一级评论下尽可能展开全部可访问楼中楼，楼中楼不计入 50。
- 不保存评论作者昵称、头像、用户 ID、主页、位置或联系方式。
- 不绕过验证码、登录限制、风控；出现即暂停并交回用户。
- 不伪造时间、点赞数、评论总数、排序方式与核验状态。

---

## 6. 审计结论

1. V6 必须自建浏览器会话（`launch_persistent_context`，`channel="chrome"`，Profile 在仓库外）。
2. 必须自建持久化候选队列与状态机，恢复判据是数据库而非内存。
3. 关键词调度必须真正读取 `tasks/employment/search_keywords.json` 的 10 个维度并按缺口配额取词。
4. 存储层只做**增量迁移**，保留全部历史数据，并新增哈希校验与幂等保证。
5. 旧 `scripts/employment/browser/` 在 V6 验收后废弃；业务规则与选择器经验迁入 `kato_engine/platforms/`。
