# V6.1 架构：ZCode 内置 Browser Use 执行层

日期：2026-11-10
状态：正式架构（替代 V6 的独立 Chrome + Python Playwright 执行层）

---

## 1. 为什么切换

V6 让 Python 自己启动 Chrome 并持有会话，带来两个无法接受的问题：

1. **浏览器所有权与桌面冲突**：Chromium 在导航/新建标签页时会激活 Windows 窗口，Python 又无法可靠地把前台焦点交还给用户正在使用的 VS Code / Obsidian；
2. **凭据与登录态分叉**：独立 Profile 里的登录态与用户实际使用 ZCode 时的浏览器会话是两套。

V6.1 的决定：**浏览器会话由 ZCode 持有，Python 只处理调度与数据。**

---

## 2. 职责边界

| 层 | 持有 | 负责 |
|---|---|---|
| ZCode 内置 Browser Use | 浏览器会话、标签页、登录态 | 搜索、进入详情、滚动、展开评论、执行页面脚本、返回结构化结果 |
| ZCode Agent | 任务编排 | 取任务、调用内置浏览器、判断异常、人工接管、提交结果 |
| `kato_engine/`（Python） | SQLite、Markdown、队列 | 关键词调度、候选去重、结果校验、分类、入库、导出、Checkpoint、统计 |

Python **不**启动 Chrome、**不**连接 CDP、**不**调用 Windows 焦点接口、**不**假设自己拥有浏览器对象。

---

## 3. 任务 / 结果契约

### 3.1 生成任务

```bash
python -m kato_engine.agent.cli next-batch --run <run_id> --size 4
```

输出 `task.json`（`runs/<run_id>/tasks/task-NNN.json`）：

```json
{
  "run_id": "er_...",
  "campaign_id": "employment-2026-2027-1000-20261109",
  "platform": "xiaohongshu",
  "query": "26届 到手工资",
  "dimension": "salary",
  "keyword": "到手工资",
  "combined_query": "26届 到手工资",
  "search_url": "https://www.xiaohongshu.com/search_result?keyword=...",
  "size": 4,
  "targets": [{"candidate_id": "cd_...", "canonical_url": "...", "note_id": "..."}],
  "scripts": {"search": "<JS>", "scroll": "<JS>", "extract": "<JS>"},
  "selectors": {"expand": ".show-more"},
  "workflow_js": "async ({ tab, task }) => { ... }",
  "task_path": "runs/<run_id>/tasks/task-001.json"
}
```

- `targets` 非空：继续处理队列里同一查询下的候选（已认领，`attempts+1`）；
- `targets` 为空：本批先搜索，再取前 `size` 条结果。

### 3.2 执行

ZCode 在一个标签页里执行 `workflow_js`：

1. `goto(search_url)`，等待 `domcontentloaded`；
2. 执行 `scripts.search` 得到卡片列表（含 `note_id`、标题、href、canonical_url）；
3. 逐条：打开详情 → 滚动评论区 → 少量点击展开 → 执行 `scripts.extract`；
4. 返回 `{platform, query, search, articles[], blocked?}`，写入 `batch.json`。

工作流是**确定性代码**，Agent 不需要对每个按钮单独推理。

### 3.3 提交结果

```bash
python -m kato_engine.agent.cli submit-batch \
  --run <run_id> --task runs/<run_id>/tasks/task-001.json --file runs/<run_id>/batch-001.json
```

入库顺序：

1. 搜索结果全部入队（未处理的候选留给下一批）；
2. 逐篇：认领候选 → 相关性校验 → 分类 → 文章入库 → 评论树 → Markdown → 候选 `completed`；
3. 记录关键词执行（原始数、重复数、打开数、采纳数、失败原因）；
4. 返回剩余量、队列状态与逐篇结果。

---

## 4. 状态机（沿用 V6）

```text
discovered → queued → processing → accepted → completed
                    ↘ retryable_failed / blocked / rejected
```

- 认领时 `attempts+1` 并写租约；`max_attempts` 用尽后拒绝；
- 登录/验证码/限流 → `blocked`，本批停止，等待用户在内置浏览器完成后 `requeue`；
- 内容不相关/正文过短 → `rejected`；
- 其它异常 → `retryable_failed`，下一批可重试。

---

## 5. 登录与人工接管

1. `workflow_js` 检测到登录墙或跳转 `/website-login`，返回 `blocked`;
2. Python 把候选标 `blocked` 并停止该平台；
3. ZCode 告知用户"请在浏览器面板完成登录"，**不代填、不弹窗、不绕过**；
4. 用户完成后执行 `python -m kato_engine.cli requeue --platform xiaohongshu`，继续采集。

---

## 6. 恢复语义

- 浏览器生命周期依附 ZCode：ZCode 关闭即会话结束，**不声称后台仍在采集**；
- 进度保存在 SQLite（候选状态、文章、评论）与 `runs/<run_id>/checkpoint.json`；
- 重新开始只需再次 `next-batch`；租约过期的 `processing` 会由 `recover_expired_leases` 或 `claim_candidate` 重新可用。

---

## 7. 已删除的旧实现

| 文件 | 原因 |
|---|---|
| `kato_engine/browser/manager.py` | 自行启动 Chrome、Profile 占用检测 |
| `kato_engine/browser/session.py` | 持有 Playwright 上下文 |
| `kato_engine/browser/focus.py` | Windows 焦点与 `WS_EX_NOACTIVATE` 操作 |
| `kato_engine/browser/navigation.py` / `interaction.py` | Playwright 导航/点击/滚动 |
| `kato_engine/platforms/*` | 依赖 `Page` 的平台适配器 |
| `kato_engine/core/engine.py` | Python 浏览器任务循环 |

保留并复用：URL 规范化与去重、关键词调度、候选队列与状态机、评论 50 条规则、分类、SQLite 仓储、Markdown 导出、Checkpoint、报告、错误分类。

---

## 8. 不变量

- 已采集的 128 篇与 2647 条评论全部保留，不重建、不重复计算；
- 文章按 `(platform, canonical_url)` 幂等，评论按层级/父级/内容哈希去重；
- 不保存评论作者昵称、头像、用户 ID、主页、位置；时间中的地区在抽取阶段剥离；
- `xsec_token` 只存在于任务与页面导航中，不入库；
- 不绕过登录、验证码、限流或访问控制。
