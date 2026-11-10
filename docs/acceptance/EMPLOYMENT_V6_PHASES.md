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

