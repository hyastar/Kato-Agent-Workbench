# 就业情报 V5 — 浏览器执行性能验收摘要

> 只记录脱敏指标、测试结果与阻塞；不写入真实文章、评论全文、作者信息、Cookie、Profile、Token 或 trace。

## 阶段总览

| 阶段 | 内容 | 状态 | 提交标题 |
|---|---|---|---|
| 1 | 审计、备份、性能协议与埋点 | 完成 | 文档：制定V5浏览器执行与性能验收方案 |
| 2 | V4 真实浏览器基线 | 未开始 | 测试：建立就业采集真实浏览器性能基线 |
| 3 | 浏览器执行工具对比 | 未开始 | 调研：完成浏览器执行工具兼容性对比 |
| 4 | 优化执行层实现 | 未开始 | 优化：实现浏览器批量操作与文章评论提取 |
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
