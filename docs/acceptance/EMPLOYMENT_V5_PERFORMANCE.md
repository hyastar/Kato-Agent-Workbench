# 就业情报 V5 — 浏览器执行性能验收摘要

> 只记录脱敏指标、测试结果与阻塞；不写入真实文章、评论全文、作者信息、Cookie、Profile、Token 或 trace。

## 阶段总览

| 阶段 | 内容 | 状态 | 提交标题 |
|---|---|---|---|
| 1 | 审计、备份、性能协议与埋点 | 完成 | 文档：制定V5浏览器执行与性能验收方案 |
| 2 | V4 真实浏览器基线 | 完成 | 测试：建立就业采集真实浏览器性能基线 |
| 3 | 浏览器执行工具对比 | 完成 | 调研：完成浏览器执行工具兼容性对比 |
| 4 | 优化执行层实现 | 完成 | 优化：实现浏览器批量操作与文章评论提取 |
| 5 | 同样本 A/B 测速 | 未开始 | 测试：完成浏览器采集优化前后对照验收 |
| 6 | 后端选择与文档定版 | 未开始 | 文档：发布V5性能评测与执行架构规范 |
| 7 | 新 20 篇批次与恢复 | 未开始 | 验证：完成V5真实批次采集与断点恢复 |

## 阶段 1 — 审计、备份、性能协议与埋点

- 日期：2026-11-09
- Git 审计：`main` 与 `origin/main` 均为 `3d8a057`；工作区干净，未 reset/clean。
- 数据库审计（变更前）：
  - `user_version=3`，`integrity_check=ok`，外键违规 0；
  - `datasets=5`、`research_items=22`、`research_comments=365`（一级 211、楼中楼 154）、`research_artifacts=51`；
  - Campaign `employment-2026-2027-1000-20261109`：`partial`，`actual_total=20`。
- 备份：SQLite Online Backup API 生成于本地忽略目录；466,944 字节，SHA-256 `5895efeed44db8a6400d5ea476ddcf2c52186d9e6e54abd82ac43ddf87019c0d`。
- 新增性能模块 `scripts/employment/perf/`：
  - `metrics.py`：`perf_counter_ns` 单调时钟、结构化事件、JSONL 追加与 fsync；
  - `aggregate.py`：逐篇聚合、mean/p50/p95、吞吐、成功率、覆盖计数；
  - `compare.py`：A/B 速度与质量门槛；
  - `cli.py`：`summary` / `compare` 命令。
- 修复 V4 缺陷：`select_comments()` 默认不再把采集顺序倒序当作“最新”；仅 `latest_verified=True` 时才标 `high_likes_then_latest`，否则标 `high_likes`，并新增测试。
- 文档：`docs/performance/BENCHMARK_PROTOCOL.md`、`docs/performance/BASELINE_ASSUMPTIONS.md`。
- 测试：`python -m unittest discover -v` → **80 个测试全部通过**（原 73 + 新增 7）。
- 未访问外部平台；未修改 Campaign 或历史数据。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 7 交付表。

## 阶段 2 — V4 真实浏览器性能基线

- 日期：2026-11-09
- perf run：`20261109T081734Z-071a`（本地 `runs/`，不提交 Git）。
- 样本：固定 12 篇（小红书 8、知乎 4），覆盖评论少/多、楼中楼较多、加载不完整等情况；未新增 Campaign 文章。
- 方式：V4 Playwright MCP 逐步操作（导航 → 快照 → 点击 → 多轮展开 → DOM 解析），不写生产数据库。
- 结果：
  - 12/12 成功；首次 `xhs_07` 因搜索结果波动未找到卡片，精确标题重试成功；
  - 总端到端 724,390.87 ms；平均 60,365.91 ms；p50 51,769.77 ms；p95 98,282.48 ms（样本 12，仅描述）；
  - 59.64 有效文章/小时；浏览器工具调用 152（12.67/篇）；快照 11 次；Token 未测量；
  - 一级评论 247（未按 50 截断的完整加载测量）、楼中楼 150；覆盖 complete 9 / partial 3。
- 数据质量：评论树、脱敏、页面显示/实际计数均按 V4 规则记录；未写生产库，未重复计入 Campaign。
- 局限：未做冷/热缓存重复；小红书评论数与搜索卡片位置有波动；p95 仅描述。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 7 交付表。

## 阶段 3 — 浏览器执行工具对比

- 日期：2026-11-09
- 候选：
  - A：现有 Playwright MCP 0.0.84 逐步操作（已实测基线）；
  - B：Playwright MCP 会话内合并确定性步骤（`browser_evaluate` 一次完成滚动/展开/提取）；
  - C：Tencent BrowserSkill（`bsk` CLI + daemon + Chrome/Edge 扩展）；
  - D：vercel-labs agent-browser（Rust CLI + daemon + CDP）；
  - E：Browser4（仅架构调查）。
- 本机状态：`bsk` 与 `agent-browser` 均未安装；未修改系统环境，未安装扩展或 daemon。
- 官方资料核对：Playwright MCP 支持持久化 Profile、`--snapshot-mode`、`--extension`；BrowserSkill 需要 CLI/daemon/扩展，Windows x64 支持；agent-browser 支持 CDP attach 与紧凑 snapshot，但为独立 daemon/session。
- 评分合计：A=41、B=46、C=29、D=28（1–5 分制，详见 `docs/performance/BROWSER_BACKEND_EVALUATION.md`）。
- 决策：本轮采用 **B（Playwright MCP 会话内批量执行）**；A 回退；C/D 因未安装、未实测及浏览器所有权/扩展/daemon 成本排除；E 不采用。
- 未声明 BrowserSkill/agent-browser 的任何性能或覆盖优势。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 7 交付表。

## 阶段 4 — 优化执行层实现

- 日期：2026-11-09
- 新增 `scripts/employment/browser/`：
  - `contracts.py`：`ArticleTask` / `ArticleResult` / `CommentNode` / 可解释错误；
  - `actions.py`：经审查的小红书、知乎“展开 + 提取”单次页面动作片段；
  - `extraction.py`：payload 规范化、50 条一级评论选择、楼中楼计数、覆盖判定、联系方式脱敏；
  - `runner.py`：`normalize` / `status` CLI 与 checkpoint 写入，不联网。
- 执行边界：浏览器动作仍由宿主 Agent 通过 Playwright MCP 完成；Python 只处理已返回的 payload，不新增 HTTP 爬虫、不持有浏览器会话。
- 质量约束：默认 `latest_verified=False`，无排序证据时标 `high_likes`；一级评论 ≤50；楼中楼独立计数；空评论/作者字段不入库。
- 测试：`python -m unittest discover -v` → **87 个测试全部通过**（新增 7 个浏览器层测试）。
- 未访问平台；未修改 Campaign/历史数据。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 7 交付表。
