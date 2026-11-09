# V5 浏览器采集性能测试协议

本协议规定 V4 基线、V5 优化方案的测量方法、样本设计、质量门槛与报告格式。所有结论必须来自本机实测；无数据时写“未测量”。

## 1. 测量单位

一个采集单位是 **真实详情页 + 一级评论 + 选中一级评论下的可访问楼中楼 + 入库 + Markdown 导出**。只打开搜索结果卡片不算完成。

## 2. 计时方法

- 耗时使用 `time.perf_counter_ns()`（Python）或 `performance.now()`（Node），基于本机单调时钟。
- UTC 时间仅用于事件关联，不用于计算耗时。
- 避免重复计入子阶段：每个阶段单独记 `phase` 事件，另有 `phase=total` 的端到端事件；汇总优先使用 `total`。
- 无法观测的 Agent 推理时间与 Token 记 `null`，不估算。

## 3. 指标字段

| 字段 | 含义 |
|---|---|
| `run_id` / `experiment_id` / `case_id` | 实验与样本身份 |
| `backend` | `mcp_baseline` / `mcp_batch` / 其他候选 |
| `platform` / `article_id` | 平台与内部 ID |
| `started_at` / `finished_at` | UTC 时间 |
| `wall_ms` | 阶段或端到端墙钟耗时 |
| `browser_tool_calls` | 浏览器工具调用次数 |
| `browser_round_trips` | Agent ↔ 浏览器往返次数 |
| `navigation_ms` / `page_ready_ms` | 导航与页面稳定等待 |
| `article_extract_ms` | 正文/字段读取 |
| `comment_expand_ms` / `reply_expand_ms` | 一级评论加载与楼中楼展开 |
| `dom_extract_ms` | DOM 批量读取 |
| `normalize_ms` / `db_ms` / `markdown_ms` | Python 处理、入库、产物 |
| `top_level_count` / `reply_count` | 实际入库数量 |
| `coverage_status` | complete / partial / blocked / not_available |
| `status` / `error_type` | 成功或失败 |
| `prompt_tokens` / `completion_tokens` | 无真实指标时 `null` |
| `bytes_returned` / `snapshots_count` | 响应体与快照次数 |
| `profile_mode` / `browser_version` | 浏览器环境 |

## 4. 样本设计

固定样本 12 篇：小红书 8、知乎 4，优先从既有 20 篇已登记文章中选择，覆盖：

- 一级评论少于 50；
- 一级评论超过 50；
- 楼中楼明显较多；
- 评论未完整加载/动态更新；
- 知乎问题/回答/专栏（按实际存在情况）。

另预留 4 篇“盲测样本”，不参与选择器或流程调参。固定样本重复访问只用于性能复测，不增加 Campaign 唯一文章计数。

样本清单保存为 `runs/<run-id>/perf/sample_manifest.json`，不保存 token 或凭据。

## 5. 基线执行（stage ②）

- 使用 V4 原有方式：逐次导航、快照、点击、滚动、展开、读取；不提前批量编排。
- 结果写入独立 benchmark namespace 或数据库副本，禁止污染生产 Campaign 计数。
- 至少 1 轮完整基线；时间允许时对 4 篇做重复测量，记录冷/热缓存。
- 记录真实开始/结束时间、工具调用、快照次数、文章/评论数量与错误。

## 6. 优化执行（stage ④/⑤）

- 同一登录 Profile、同一页面与同样 50 条一级评论/楼中楼规则。
- 已确定的重复步骤合并到一次浏览器执行单元（点击 → 等待 → 展开 → 提取）。
- 正常路径返回紧凑 JSON；只有探索和错误诊断才读详细快照。
- 每篇保存 checkpoint；失败标记 `partial` / `blocked`，不伪装 `complete`。

## 7. 质量不变量与门槛

1. 文章字段、一级评论、可访问楼中楼、评论树、脱敏、SHA 与完整性不得低于基线；差异逐篇说明。
2. 一级评论 ≤50；楼中楼不计入 50。
3. 无可靠“最新排序”证据时，只能标 `visible_order` 或 `high_likes`，不得写 `latest`。
4. 页面显示数与实际采集数分别记录。
5. `PRAGMA integrity_check=ok`，外键违规 0。
6. 最低采纳门槛：端到端总耗时下降 ≥30%（speedup ≥1.3）或有效文章吞吐提升 ≥1.5 倍；未达门槛不强切方案。

## 8. 报告表

- 表 A：速度与成本（文章数、总耗时、均值、p50、p95、每小时文章、工具调用、快照/字节、Token）。
- 表 B：按环节耗时（导航、等待、正文、一级评论、楼中楼、DOM、Python、Markdown）。
- 表 C：内容质量与覆盖（标题、摘要、一级/楼中楼、父子关系、页面显示/实际、覆盖状态、去重与脱敏）。
- 表 D：可靠性（成功率、遇阻率、超时、恢复、人工接管、错误类型）。

## 9. 产物与 Git

- 本地：`runs/<run-id>/perf/events.jsonl`、`baseline_summary.json`、`perf_comparison.json`、逐篇数据。
- Git：仅脱敏汇总与协议文档；不提交真实文章、评论、SQLite、Profile、Cookie、Token、trace、快照。
- 样本量小时 p95 仅作描述，不用于 SLA。
