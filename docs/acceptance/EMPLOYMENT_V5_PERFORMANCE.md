# 就业情报 V5 — 浏览器执行性能验收摘要

> 只记录脱敏指标、测试结果与阻塞；不写入真实文章、评论全文、作者信息、Cookie、Profile、Token 或 trace。

## 阶段总览

| 阶段 | 内容 | 状态 | 提交标题 |
|---|---|---|---|
| 1 | 审计、备份、性能协议与埋点 | 完成 | 文档：制定V5浏览器执行与性能验收方案 |
| 2 | V4 真实浏览器基线 | 完成 | 测试：建立就业采集真实浏览器性能基线 |
| 3 | 浏览器执行工具对比 | 完成 | 调研：完成浏览器执行工具兼容性对比 |
| 4 | 优化执行层实现 | 完成 | 优化：实现浏览器批量操作与文章评论提取 |
| 5 | 同样本 A/B 测速 | 完成（12 篇固定样本） | 测试：完成浏览器采集优化前后对照验收 |
| 6 | 后端选择与文档定版 | 完成 | 文档：发布V5性能评测与执行架构规范 |
| 7 | 新 20 篇批次与恢复 | 部分完成（实际新增 1 篇；小红书安全验证阻塞） | 验证：完成V5真实批次采集与断点恢复（部分） |

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

## 阶段 5 — 同样本 A/B 测速

- 日期：2026-11-09
- 样本：固定 12 篇（小红书 8、知乎 4），与基线同一集合；未写生产库。
- 优化后端：一次 `browser_evaluate` 完成“展开 + 提取”，自适应稳定检测 + 最后一次展开；Python 规范化与 50 条规则。
- 结果（12 篇）：
  - 总墙钟：基线 724,390.87 ms → 优化 456,769.22 ms；**speedup 1.586**；
  - 每篇平均：60,365.91 → 38,064.10 ms；p50：51,769.77 → 31,651.83 ms；p95：98,282.48 → 61,153.54 ms；
  - 吞吐：59.64 → 94.58 篇/小时；
  - 浏览器工具调用：152 → 45（12.67 → 3.75 次/篇）；
  - 一级评论：213 = 213（基线按 50 条规则截断）；覆盖 complete 9 / partial 3，与基线一致；
  - 楼中楼：基线 150，优化 151（均为实际采集）。
- 质量修复：无文字/图片评论保留 `[无文字内容]` 占位，避免被误判为丢评论；`select_comments()` 默认不声称 `latest`。
- 门槛：`adoption_gate` 通过（speedup ≥1.3，覆盖率与一级评论不退化）。
- **未执行**：4 篇盲测样本的时间盒未完成；结论仅基于 12 篇固定样本，不外推为通用 SLA。
- 局限：小红书搜索卡片与评论数存在波动；p95 样本量小，仅描述；Token 未测量。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 7 交付表。

## 阶段 6 — 后端选择与文档定版

- 日期：2026-11-09
- 采用后端：`mcp_batch`（Playwright MCP 会话内批量执行）；`mcp_baseline` 保留回退。
- 新增/更新文档：
  - `docs/performance/V5_RESULT.md`：12 篇 A/B 实测、四张表、结论与边界；
  - `AGENTS.md`：已验证重复步骤交给执行层；
  - `README.md`：V5 性能结果与 runner 命令；
  - `docs/ARCHITECTURE_EMPLOYMENT.md`：V5 执行层边界；
  - `docs/platforms/ZHIHU.md`、`docs/platforms/XIAOHONGSHU.md`：已验证批处理动作与选择器；
  - `.gitignore`：trace / test-results / playwright-report。
- 缺陷修复：`select_comments()` 默认不声称 `latest`；无文字评论保留占位；产物 SHA 与文件字节一致。
- 测试：`python -m unittest discover -v` → **88 个测试全部通过**。
- 未执行：4 篇盲测；未宣称 1000 篇吞吐、Token 节省或长期后台 Worker。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 7 交付表。

## 阶段 7 — 新批次真实采集与恢复（部分完成）

- 日期：2026-11-09
- 运行：`20261109T090541Z-8d6d`；批次 `v5-xhs-8`、`v5-zhihu-4`；Campaign `employment-2026-2027-1000-20261109`。
- 目标：新增 8 篇小红书（原建议 20 篇），小红书受阻后补跑 4 篇知乎。
- 实际新增 **5 篇唯一文章**：
  - 小红书 1 篇（新华书店 2026 秋招）：一级评论 5、楼中楼 0，页面显示 6，覆盖 `partial`；
  - 知乎 4 篇：1 篇 2 条一级评论（complete），3 篇页面未显示/未加载评论（`not_available`）；
  - Campaign 从 20 增至 **25/1000**。
- 小红书失败与阻塞：
  - 7 篇因搜索结果标题/卡片波动未能定位，未进入详情；
  - 重试时返回“安全验证”页面，**立即停止该平台操作，未绕过验证**；
  - 未继续重试，未使用代理、指纹或隐藏接口。
- 恢复验证：对已完成小红书文章重新导入 5 条一级评论 → `inserted=0`、`existing=5`，文章/评论总数不变；checkpoint 已写入 `runs/20261109T090541Z-8d6d/checkpoints/`。
- 数据核对：SQLite `user_version=3`；`research_items=27`；`research_comments=372`（一级 218、楼中楼 154）；`research_artifacts=61`；`integrity_check=ok`；外键违规 0；测试 88 个通过。
- 未完成：8 篇小红书目标仅完成 1 篇；20 篇新批次、4 篇盲测均未执行；3 篇知乎评论不可用。
- 下一步：由用户在可见 Chrome 完成小红书安全验证后，再从失败 ID 清单继续；不扩大访问范围、不提高频率。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 7 交付表。

## 交付表（阶段 1–7）

| 阶段 | 提交标题 | 本地完整 SHA | 远端完整 SHA | 一致 |
|---|---|---|---|---|
| 1 | 文档：制定V5浏览器执行与性能验收方案 | `04168f1223720ba0eb5191db019ec6fd277e162f` | 同左 | 是 |
| 2 | 测试：建立就业采集真实浏览器性能基线 | `60be52bc45adf8d07ce9d3edef62c86cc8d35cbe` | 同左 | 是 |
| 3 | 调研：完成浏览器执行工具兼容性对比 | `31d01d8b865655f4ad357b410a15b1f82d334575` | 同左 | 是 |
| 4 | 优化：实现浏览器批量操作与文章评论提取 | `024750aefce722a10eac4a37274d74e8157a4dda` | 同左 | 是 |
| 5 | 测试：完成浏览器采集优化前后对照验收 | `7318e0bcdfb44e1c4f26fa22adbd5910d24bcf97` | 同左 | 是 |
| 6 | 文档：发布V5性能评测与执行架构规范 | `4e637d550d441e4e8b7d6549169089e162dda4bb` | 同左 | 是 |
| 7 | 验证：完成V5真实批次采集与断点恢复（部分） | 本次提交 | 推送后核对 | 见最终汇报 |
