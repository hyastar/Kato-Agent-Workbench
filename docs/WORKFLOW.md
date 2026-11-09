# 工作流程

本文件描述一次任务从“用户下达指令”到“报告归档”的完整流程，以及失败、中断和重试时的处理约定。

## 0. 何时可以开始

只有用户**明确**要求“执行当前任务”（或等价表述）时才可开始。用户明确点名并授权 `tasks/` 下的某个具名任务（例如 `tasks/EMPLOYMENT_2026_2027.md`）时，该文件即为本轮任务定义。

以下行为都**不构成**执行授权：

- 打开仓库、阅读 `AGENTS.md` / `README.md` / 任务文档；
- 讨论架构或修改文档；
- 初始化数据库、运行 `doctor`、跑离线测试；
- 浏览项目目录。

## 1. 开始前的检查

1. 阅读 `AGENTS.md`、本轮任务文档（默认 `tasks/CURRENT_TASK.md`，或用户点名的具名任务）；按需阅读本文件与 `docs/SAFETY.md`。
2. 确认任务文档包含目标、范围、网站白名单、筛选条件、人工确认点和验收标准；缺失时先向用户澄清，不自行补造。
3. 确认运行环境：当前 Python 解释器来自 `Kato-Agent-Workbench` 环境；`python -m scripts.doctor` 无 FAIL。
4. 确认浏览器 MCP 可用；不可用时如实报告，不假装已访问网站。
5. 确认任务涉及的外部站点在文档白名单内。

## 2. 建立运行记录

1. 生成唯一 `run-id`：UTC 时间戳 + 4 位随机十六进制，例如 `20261106T082500Z-a1b2`。同一秒内重试必须换新后缀，绝不覆盖已有目录。
2. 创建 `runs/<run-id>/`。
3. 把本轮任务文档原样复制为 `runs/<run-id>/task_snapshot.md`（不可变快照；具名任务则复制该文件）。
4. 计算快照 SHA-256，写入 SQLite：
   - `tasks` 表登记任务定义（`task_id` 可由 `CURRENT_TASK.md` 相对路径与内容哈希派生，重复内容复用同一条）；
   - `runs` 表登记本次执行，状态先 `pending`，正式开始后改 `running`。
5. 在 `runs/<run-id>/progress.md` 写下开始时间、环境摘要、计划步骤。

## 3. 执行阶段

推荐按阶段推进，每阶段结束更新 `progress.md`：

1. **调研**：通过 Playwright MCP 操控真实 Chrome，在允许范围内使用页面正常的搜索、点击、滚动与详情页导航；记录标题、URL、发布时间（若可见）、类别/规模/许可等字段，不确定字段写“未核实”。
2. **候选整理**：用 `python -m scripts.catalog add` 登记候选（`status=candidate`），关联到本次 run（`action=discovered`）。
3. **人工确认**：向用户展示候选清单与下载体积，等待明确批准。
4. **下载**：经批准后保存到 `data/raw/<source>/<dataset>/<version>/`；记录 `source_url`、许可、获取日期、大小、SHA-256；关联 `action=downloaded`。
5. **校验**：运行 `python -m scripts.validate_dataset <path>`；结构不合格时标记 `failed` 并保留失败原因。
6. **入库与报告**：更新数据集状态与路径，写 `results.json`、`report.md`，把 `runs` 状态改为 `completed` 或 `partial`。

### 3.1 浏览器页面采集规程（情报类任务）

1. 使用 Playwright MCP + 独立持久化 Chrome Profile；先打开平台正常页面，再使用页面可见的搜索框、结果链接、滚动与详情页。
2. 遇到登录、二维码、验证码、设备确认或 Cloudflare 时暂停，请用户在可见浏览器窗口亲自完成；用户确认后继续。
3. 按任务文档的每平台上限采集，不连续翻页；优先打开详情页读取标题、来源 URL、发布时间与有限事实，摘要由 Agent 自己组织。
4. 不调用隐藏或逆向接口，不抓取登录态 API，不批量下载媒体，不采集非任务必需的个人信息。
5. 遇到 403、限流、验证码循环、权限提示等技术性拒绝时停止该平台，记录 `blocked` / `partial` 与现象，继续另一平台；不绕过访问控制。
6. 采集结果用 `python -m scripts.research_catalog add` 入库，重复 URL 幂等去重，并关联本次 `run-id`。

任何阶段需要登录、CAPTCHA、二次验证、付费或超出文档授权范围时，暂停并交回用户；用户确认后继续。

## 4. 运行目录约定

```text
runs/<run-id>/
├── task_snapshot.md   # 执行时的 CURRENT_TASK.md 快照（不修改）
├── progress.md        # 进度、检查点、失败原因、人工确认记录
├── results.json       # 机器可读结果：候选、来源、许可、本地路径、校验结论
└── report.md          # 供人阅读的总结
```

`results.json` 至少包含：

```json
{
  "run_id": "20261106T082500Z-a1b2",
  "task": "收集适合端侧目标检测研究的数据集",
  "status": "partial",
  "started_at": "2026-11-06T08:25:00.000Z",
  "finished_at": "2026-11-06T09:10:00.000Z",
  "datasets": [
    {
      "name": "example-dataset",
      "source": "roboflow",
      "source_url": "https://example.invalid/dataset",
      "version": "v3",
      "license_name": "CC BY 4.0",
      "license_url": "https://example.invalid/license",
      "format": "coco",
      "image_count": 1200,
      "verified": false,
      "local_path": null,
      "sha256": null
    }
  ],
  "verification": [
    {"path": "data/raw/...", "result": "not_downloaded", "message": "等待用户批准"}
  ],
  "notes": []
}
```

`progress.md` 建议包含：开始/结束时间、执行环境、每阶段状态、人工确认记录、失败与重试、未验证项。

## 5. 失败、中断与恢复

- 失败时保留已获得的文件与证据，把 `runs` 状态改为 `failed`（完全失败）或 `partial`（部分完成），写明 `error_message`。
- 浏览器崩溃、网络中断、MCP 断开：先记录现象，再检查 `runs/<run-id>/` 与 `data/` 实际文件，不凭记忆补写。
- 恢复执行时：
  1. 读取旧 `run-id` 的 `progress.md`、`results.json` 和 SQLite 状态；
  2. 核对 `data/` 中实际文件与记录的哈希；
  3. **新建** `run-id` 继续，快照取当前任务文档，并在 `progress.md` 注明“恢复自 `<old-run-id>`”；旧运行只追加恢复说明，不重写历史。
- 同一数据集重复下载前先查 SQLite 与本地文件：数据库有记录不等于文件仍在；文件在但哈希不符时按新版本处理并标记。

## 6. 结束与验收

1. 对照任务文档的“验收标准”逐条核对。
2. 检查 `results.json` 中每条数据集都有可追溯 URL；未核实字段明确标记。
3. 更新 SQLite 的 `datasets.status`、`runs.status`、`finished_at`、`report_path`。
4. 写 `report.md`：完成了什么、未完成什么、哪些步骤未经验证、用户下一步要做什么。
5. 向用户报告：完成 / 部分完成 / 受阻，以及具体原因。

## 7. 临时文件

- 一次性探索脚本、日志、中间产物放 `workspace/`，可随时清空。
- 不使用 `data/` 或 `runs/` 存放临时文件。
- 清理 `workspace/` 不影响已登记成果；删除 `data/` 或 `runs/` 中的内容必须由用户明确确认。
