# Workbench on-request 审批 UI 手验清单

> 默认 `approvalPolicy: on-request`（见 `settings-store.ts`）。手验前请确认 Runtime 已连接且**未**设为 `auto` / `never`。
>
> **设计对照**：[`APPROVAL_SYSTEM_DESIGN.md`](./APPROVAL_SYSTEM_DESIGN.md)（v1 基线 + 测试 ID 映射 §11.4）。

## 前置

1. 启动 Runtime（需鉴权时勿加 `--insecure`）：
   ```bash
   cd /path/to/deepseek-tui-py-main
   PYTHONPATH=src .venv/bin/python -m deepseek_tui serve --http --port 7878 --config .deepseek/config.toml
   ```
2. 启动 Workbench：`cd packages/workbench && npm run dev`
3. **Settings → Agents → Approval policy** = `On request`

## 用例 A — 写文件触发审批

| 步骤 | 操作 | 期望 |
|------|------|------|
| A1 | 新建线程，发送：「在当前 workspace 创建 `approval-smoke.txt`，内容为 ok」 | Timeline 出现 **Approval required** 卡片 |
| A2 | 卡片显示工具名（如 `write_file` / `apply_patch`）与描述 | 非空白 summary；**不是**仅 `tool has medium risk level`；可见路径或写入目标（PR-01） |
| A3 | 点击 **Allow** | 卡片变为 allowed；工具继续；最终出现文件变更或成功 tool 行 |
| A4 | 打开 `approval-smoke.txt` | 内容为 `ok` |

## 用例 B — Deny

| 步骤 | 操作 | 期望 |
|------|------|------|
| B1 | 新线程，请求创建 `denied.txt` | 审批卡片出现 |
| B2 | 点击 **Deny** | 状态为 denied；无文件或 tool 失败行 |
| B3 | 可继续发下一条消息 | 线程未卡死 |

## 用例 C — SSE 与设置联动

| 步骤 | 操作 | 期望 |
|------|------|------|
| C1 | 审批卡片显示时打开 DevTools → Network → SSE `/v1/threads/.../events` | 可见 `event: approval.required` |
| C2 | 将 policy 改为 **Auto**，重试写文件 | 无审批卡片（或瞬间 auto-allow） |
| C3 | 改回 **On request** | 恢复 A1 行为 |

## 用例 D — GUI 联调增强（2026-05）

| 步骤 | 操作 | 期望 |
|------|------|------|
| D1 | 触发审批后观察 Composer 上方 | 出现蓝色 **Review** 横幅，点击可滚动到审批卡片 |
| D2 | 审批等待期间切换线程再切回 | 若 turn 仍在运行，审批卡片通过 `GET /v1/approvals/pending` 恢复 |
| D3 | 审批卡片点击 **Approval settings** | 打开 Settings → Agents |
| D4 | Sidebar → **Import TUI session** | 弹出导入对话框，列出 `~/.deepseek/sessions/*.json` |
| D5 | 选择一条 TUI 会话导入 | 创建新线程并加载历史 user/assistant 消息 |

## 用例 E — apply_patch 必须能看懂 diff（实现 A2 后）

| 步骤 | 操作 | 期望 |
|------|------|------|
| E1 | 请求：对已有文件做小改动（或让模型 `apply_patch`） | 审批卡片出现 |
| E2 | 查看预览区 | 可见 **unified diff** 或至少 **受影响文件列表**（PR-02） |
| E3 | Deny | 文件未被意外修改 |

## 用例 F — exec_shell（实现 A2 后）

| 步骤 | 操作 | 期望 |
|------|------|------|
| F1 | 请求：「在当前 workspace 执行 `echo approval-shell-test`」 | 审批卡片 |
| F2 | 卡片 | 可见 **完整 command**；若有 cwd 则显示（PR-03） |
| F3 | 可选：请求含 `rm -rf` 类命令 | 有 **DANGEROUS** 或等价警告（PR-08） |

## 用例 G — fetch_url 必须触发审批（实现 A1 后）

| 步骤 | 操作 | 期望 |
|------|------|------|
| G1 | 启用 `web_search`/`fetch_url` 特性，请求抓取 `https://example.com` | **出现**审批（G-05）；当前未修门控时记为 FAIL |
| G2 | 卡片 | 可见完整 **URL**（PR-04） |

## 用例 H — 子代理（features.subagents=true）

| 步骤 | 操作 | 期望 |
|------|------|------|
| H1 | 请求 spawn 子代理做只读探索（短 prompt） | 审批卡片 |
| H2 | 卡片 | 可见 **prompt/目标** 摘要，非空泛化句（PR-05） |

## 用例 I — Destructive 二次确认（实现 B 后）

| 步骤 | 操作 | 期望 |
|------|------|------|
| I1 | 对 `write_file` 或 `exec_shell` 审批卡 | 第一次点 **Allow** 不提交，UI 提示再确认（P10） |
| I2 | 第二次点 Allow | 工具执行；卡片变 allowed |
| I3 | 点 Deny 或 **取消确认** | 清除 staged 状态（不误批） |
| I4 | 第一次点 Allow 后改点 **Allow for session** | 需再确认一次 session 按钮（不误批） |

## 自动化对照

| 套件 | 覆盖 |
|------|------|
| `pytest tests/contract/test_approvals.py` | Bridge + HTTP + pending（H-01） |
| `pytest tests/contract/test_turn_approval_integration.py` | SSE（I-01, I-02） |
| `pytest tests/test_approval_gate.py` | 门控 G-*、P-*（实现后） |
| `pytest tests/test_approval_presentation.py` | 展示 PR-*（实现后） |

## 记录

| 日期 | 环境 | A | B | C | D | E | F | G | H | I | 备注 |
|------|------|---|---|---|---|---|---|---|---|---|------|
|      |      | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |      |
