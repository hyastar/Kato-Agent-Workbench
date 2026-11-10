# V6 引擎运维手册

面向操作者（用户与宿主 Agent）。设计说明见 `V6_ARCHITECTURE.md`，审计结论见 `V6_AUDIT.md`。

---

## 1. 运行前检查

```bash
conda activate Kato-Agent-Workbench
python -c "import sys, playwright; print(sys.version)"
python -m kato_engine.cli browser-check
```

`browser-check` 会真实启动 Chrome、执行 DOM 提取并关闭。输出 `ok: true` 才算通过。

### Profile 被占用

```
error_type: profile_in_use
message: 浏览器 Profile 正被占用…（PID: 1234）
```

处理：关闭 ZCode/Codex 的 Playwright MCP 浏览器窗口，或关闭残留的 Chrome 窗口。
**不要**删除 `.kato-playwright-profile`（会丢失登录态），也不要让引擎改用临时 Profile——临时 Profile 没有登录态，会立刻卡在登录页。

被强杀的引擎可能留下 Chrome 子进程。确认 PID 的命令：

```powershell
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  Where-Object { $_.CommandLine -like '*kato-playwright-profile*' -and $_.CommandLine -notlike '*--type=*' } |
  Select-Object ProcessId
```

---

## 2. 运行采集

```bash
python -m kato_engine.cli campaign-run --add-xhs 160 --add-zhihu 40
```

- `--add-*` 是**本轮新增**篇数，引擎会换算成 Campaign 绝对目标（当前数 + 新增）。
- 不指定 `--max-articles` 时会一直跑到目标、队列耗尽或触发停止条件。
- 每 20 篇写一次 checkpoint，但**不会**停下来等指令。
- 日志为 JSON Lines，写在 `runs/<engine-run-id>/` 之外的重定向文件里（建议自行 `2> runs/<run>/engine.log`）。

### 停止条件

| stop_reason | 含义 | 处理 |
|---|---|---|
| `targets_reached` | 平台目标已达成 | 正常结束 |
| `max_articles_reached` | 达到 `--max-articles` | 验收用 |
| `all_platforms_paused` | 两个平台都被暂停 | 检查登录/验证码/限流 |
| `consecutive_failures_N` | 连续失败达到上限 | 检查页面结构或网络 |
| `no_candidates_left` | 队列为空且关键词耗尽 | 扩充关键词库 |
| `interrupted` | 收到 Ctrl+C | 重新执行即续跑 |

---

## 3. 人工验证后的恢复

遇到登录/验证码/设备确认时，引擎会把候选标记为 `blocked` 并暂停该平台。用户在可见 Chrome 中完成验证后：

```bash
python -m kato_engine.cli requeue --platform xiaohongshu
python -m kato_engine.cli campaign-run --add-xhs 0 --add-zhihu 0   # 或直接续跑原命令
```

`requeue` 只把 `blocked` 放回 `queued`，不伪造成功状态。

---

## 4. 观察与校验

```bash
# 队列与分布
python -m kato_engine.cli queue-stats

# Markdown 哈希对账
python -m kato_engine.cli verify-artifacts

# 完整报告（JSON + Markdown）
python -m kato_engine.cli report --out runs/<run-id>/report.json
```

直接查库：

```sql
SELECT state, COUNT(*) FROM engine_candidates GROUP BY state;
SELECT platform, COUNT(*) FROM research_items WHERE campaign_id = '...' GROUP BY platform;
SELECT comment_level, COUNT(*) FROM research_comments GROUP BY comment_level;
```

---

## 5. 数据库迁移

首次运行会自动迁移到最新版本，并在 `data/catalog/backups/` 留备份。迁移前后会校验：

- `PRAGMA integrity_check = ok`
- `foreign_key_check` 无违规
- 历史表行数不减少

任何一项失败都会中止并抛出异常，不会半途删除旧库。已应用的 `db/migrations/NNN_*.sql` 不得修改，结构变化请新增文件。

---

## 6. 常见异常

| 现象 | 原因 | 处理 |
|---|---|---|
| `selector_error` 连续出现 | 平台页面结构变化 | 先更新 `docs/platforms/*.md` 与选择器，再继续 |
| 候选反复 `retryable_failed` | 搜索结果已重排 | 引擎会重试 3 次后 `rejected`；属于正常损耗 |
| `empty_content` | 图文笔记正文过短 | 记为 `rejected`，人工抽查确认 |
| `not_available` 覆盖 | 页面未显示评论总数或无评论 | 保留文章、如实标记，不补造 |
| 报告与实际不一致 | 报告读的是库；`research_campaigns.actual_total` 只在运行结束时刷新 | 以 `report` 输出的 `articles.total` 为准 |

---

## 7. 安全边界

- 只访问任务文档白名单内的站点。
- 不绕过验证码、登录限制、付费墙或风控；不更换账号、不切代理、不做指纹伪装。
- 不保存评论作者昵称、头像、用户 ID、主页、位置；时间与地区在抽取阶段就被剥离。
- Cookie、Profile、SQLite、Markdown 档案、`runs/` 不入 Git。
