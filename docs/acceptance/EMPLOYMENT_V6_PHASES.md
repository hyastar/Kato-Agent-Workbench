# 就业情报 V6 阶段验收记录

记录 V6 架构重建各阶段的**脱敏**验收结果：只包含测试结论、真实执行证据摘要与阻塞说明，不包含平台正文、评论内容、账号信息或完整采集数据。

---

## 阶段 1：架构审计与 V6 设计（2026-11-10）

| 项 | 结果 |
|---|---|
| 审计对象 | `scripts/employment/browser/`（5 文件 486 行）、SQLite 12 表、Markdown 95 文件、Conda 环境 |
| 核心发现 | 旧 `runner.py` 不拥有浏览器、只规范化 MCP payload；无候选状态机；`cohort`/`employment_topic` 全为 NULL |
| 数据基线 | 文章 43（Campaign 41 + 历史 2）、评论 728（一级 325 / 楼中楼 403）、Campaign 41/1000 |
| 环境 | Python 3.12.16；审计前无 playwright，本轮安装 1.65.0；Chrome 156.0.8078.81 |
| 产出 | `docs/v6/V6_AUDIT.md`、`docs/v6/V6_ARCHITECTURE.md`；AGENTS.md/README/environment.yml 边界更新 |
| 回归测试 | 95 passed（未改动业务代码） |
| Git | `67a9151c6defcc5087fc1009e9890199b95d838d`，与 `origin/main` 一致 |

---

## 阶段 2：浏览器会话管理（2026-11-10）

| 验收项 | 证据 | 结果 |
|---|---|---|
| 启动真实 Chrome | `channel=chrome`，User-Agent `Chrome/156.0.0.0` | PASS |
| 持久化 Profile | `D:\Code\Github\Code\.kato-playwright-profile`（仓库外） | PASS |
| 健康检查 | `evaluate("1+1")==2`、`page_count=1`、URL 可读 | PASS |
| DOM 提取 | 本地探针页：标题 1、一级评论 2、楼中楼 2 | PASS |
| 关闭释放 | `running=false`，无残留浏览器进程占用 | PASS |
| Profile 占用检测 | 同 Profile 二次启动 → `profile_in_use`，报告主进程 PID | PASS |
| 断线恢复 | `taskkill` 杀掉 Chrome 主进程 → `ensure()` 重建会话，`restarts=1` | PASS |
| 离线测试 | 新增 15 个用例，全套 110 passed | PASS |

### 说明

- 真实页面导航（暂存内容）使用本地探针页完成，未访问外部站点；外网页面验证安排在阶段 4/7。
- `launch_persistent_context` 使用本机 Chrome，不下载 Chromium；未做任何指纹伪装或反检测处理。
- 未把 Cookie、Profile 写入仓库；`.gitignore` 已覆盖。

---

## 阶段 3：关键词调度与持久化候选队列（2026-11-10）

| 验收项 | 证据 | 结果 |
|---|---|---|
| 十维关键词加载 | `plan` 输出 `library_dimensions=10`、`library_keywords=100` | PASS |
| 缺口优先调度 | 全部维度缺额时优先 `salary`（目标 160），而非硬编码秋招 | PASS |
| 跳过已执行查询 | V5 的 `2026 工资` 等 7–8 条查询被识别为已执行 | PASS |
| 组合去重 | 同一候选带不同 `xsec_token` 只入队一次 | PASS |
| 候选持久化 | `engine_candidates` 落库，重启后可继续（临时库用例） | PASS |
| 租约与恢复 | 二次领取返回 None；过期租约退回 queued 并累计 attempts | PASS |
| 幂等 | 重复入队不新增行；重复启动不重复迁移 | PASS |
| 迁移安全 | 真实库 4→5，自动备份；文章 43、评论 728、产物 93 前后一致 | PASS |
| 测试 | 新增 26 个用例，全套 136 passed | PASS |

### 迁移记录

- 备份：`data/catalog/backups/workbench.sqlite3.20261110T030345412685Z.bak`
- `integrity_check=ok`，`foreign_key_check` 0 条，`user_version=5`
- 新增表：`engine_candidates`、`engine_query_runs`、`engine_runs`、`engine_metrics`；`research_artifacts` 增加 `bytes`/`updated_at`

---

## 阶段 4：平台适配器（真实页面，2026-11-10）

| 验收项 | 小红书 | 知乎 |
|---|---|---|
| 搜索解析 | 22 张卡片 → 3 条可用候选（`data-note-id`） | 19 条结果 → 3 条答案链接 |
| 详情进入 | 点击 `a.title`，URL 自动带 token，入库去 token | 点击结果，兼容新标签页 |
| 正文 | `.note-content .desc` 746 字 | `.QuestionRichText` / `.RichText` |
| 页面评论总数 | `共 54 条评论` | 回答操作区 `N 条评论` |
| 一级评论 | 36 条（全部） | 30 条（>50 规则截断前） |
| 楼中楼 | 18 条，多层 | 18 条，按缩进 207/241px 判定父子 |
| 分类 | salary / 2026 / 互联网 | salary / campus 命中 |

- 采集时间清洗：小红书 `05-24河北` → `05-24`；知乎 `发布于2025-09-11 15:14・湖北` → `2025-09-11 15:14`，**不保存位置**。
- 未做全局文本去重；知乎评论无稳定 ID，父子关系由缩进恢复。
- 新增 18 个离线用例；全套 160 passed。

---

## 阶段 5：存储与生命周期（2026-11-10）

| 验收项 | 结果 |
|---|---|
| 历史档案哈希 | 82 个产物（41 篇 × 2）与数据库记录一致 |
| 幂等入库 | 同文重复入库不新增 item/comment，Markdown 不重写 |
| 采集时间 | 重复采集保留首次时间，档案可复现 |
| 评论树 | 一级 50 + 楼中楼 175 正确挂接，父引用完整 |
| checkpoint | `runs/<engine-run-id>/checkpoint.json` 原子写入 |
| 新增产物校验 | `verify-artifacts` 90 个产物全部匹配 |

---

## 阶段 6：连续 Campaign Engine（2026-11-10）

| 验收项 | 结果 |
|---|---|
| 真实采集 | 搜索 → 详情 → 评论 → 入库 → Markdown 全链路走通 |
| 单篇耗时 | 小红书 17–35s，知乎 17s |
| 断点续跑 | 重启后从 `engine_candidates` 继续，`searches=0` 直接复用队列 |
| 失败分类 | 选择器失败重试 3 次后 `rejected`；未分类异常记 `retryable_failed` |
| 平台暂停 | 登录/验证码/限流映射为 `blocked` 并停止该平台 |
| 连续失败保护 | `--max-failures` 达到即停止，避免空转 |
| 恢复缺陷修复 | 旧候选因结果页重排失效 → 改为"新入队优先 + go_back 复用结果页" |

---

## 阶段 7：端到端验收（2026-11-10）

| 验收项 | 证据 | 结果 |
|---|---|---|
| 浏览器启动 | Chrome 156 + 持久 Profile，健康检查通过 | PASS |
| 关键词加载 | 10 维 / 100 关键词，查询按维度缺口选取 | PASS |
| 候选发现 | 单次搜索入队 20 条，跨 query 去重 | PASS |
| 详情与评论 | 真实页面采集，覆盖状态 complete/partial/not_available 均可出现 | PASS |
| 入库与导出 | SQLite + Markdown + 哈希登记 | PASS |
| 主动停止 | `max_articles_reached` 正常退出并写 checkpoint | PASS |
| 中断恢复 | 进程中断后候选状态保留，下一次运行继续 | PASS |
| 档案校验 | `verify-artifacts` 90/90 匹配 | PASS |

### 阶段 4–7 期间的真实缺陷与修复

1. `page.evaluate` 传入 Locator 导致序列化失败 → 改用 `eval_on_selector_all`。
2. 搜索结果重排导致队列里的旧卡片点不到 → 新入队优先 + 结果页懒加载滚动 + `go_back` 复用。
3. 小红书详情有时在新标签页打开 → 检测新页并切换。
4. 分类维度名与数据库枚举不一致（`it`/`worklife` vs `computer`/`work_life`）→ 对齐。
5. `search_limit` 误挂在 Settings 上 → 改为从 `EngineOptions` 读取。


