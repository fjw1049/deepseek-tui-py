# Workbench on-request 审批 UI 手验清单

> 默认 `approvalPolicy: on-request`（见 `settings-store.ts`）。手验前请确认 Runtime 已连接且**未**设为 `auto` / `never`。

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
| A2 | 卡片显示工具名（如 `write_file` / `apply_patch`）与描述 | 非空白 summary |
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

## 自动化对照

- `pytest tests/contract/test_approvals.py` — Bridge + HTTP + pending list
- `pytest tests/contract/test_turn_approval_integration.py` — `_monitor_turn` + SSE + resolve

## 记录

| 日期 | 环境 | A | B | C | D | 备注 |
|------|------|---|---|---|---|------|
|      |      | ☐ | ☐ | ☐ | ☐ |      |
