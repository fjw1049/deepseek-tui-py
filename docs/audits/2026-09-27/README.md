# src/deepseek_tui 系统化审核索引

历史基线：2026-09-27 工作区，204 个 Python 源文件、约 8.7 万行。2026-09-28 当前工作区含未提交改动及新增辅助模块，共 210 个 Python 源文件。非 Python 提示词、内置 Skill 等资源随所属调用链审查。

按业务体系分篇，每篇给出优点、问题位置、触发条件、证据等级、方案比较和验收建议。当前第 01—17 体系的首轮核心审核已交付（第 06 篇分上下篇）；第 01—17 体系均有修复/局部优化记录，本轮按用户要求结束。下方清单覆盖当前 210 个 Python 源文件；这不是分支测试覆盖率，也不表示所有建议均已实施。剩余工作及范围说明见 [进度台账](progress.md)。

[01 · 自动化任务审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/01-automation.md)

[02 · 权限、审批与沙箱审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/02-permissions.md)

[03 · Hook 生命周期与执行机制审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/03-hooks.md)

[04 · 持久化 Task 与恢复机制审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/04-durable-tasks.md)

[00 · 前四篇修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/00-implemented-fixes.md)

[05 · 子 Agent 与协作机制审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/05-subagents.md)

[05 · 子 Agent 修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/05-implemented-fixes.md)

[06 · Engine 与工具调度审核（上篇）](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-engine.md)

[06 · Engine 调度修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-implemented-fixes.md)

[06 · 上下文预算、压缩与提示词审核及优化（下篇）](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-context.md)

[06 · 上下文第二轮优化记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-context-followup.md)

[07 · Goal 模式、目标队列与完成判定审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/07-goal.md)

[07 · Goal 优化实施记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/07-implemented-fixes.md)

[08 · 状态、上下文持久化与媒体审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/08-state-media.md)

[08 · 状态与媒体修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/08-implemented-fixes.md)

[09 · 模型客户端与流式协议审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/09-client-streaming.md)

[09 · 模型客户端修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/09-implemented-fixes.md)

[10 · MCP 连接、工具发现与调用生命周期审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/10-mcp.md)

[10 · MCP 修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/10-implemented-fixes.md)

[11 · 插件、Skill 与 LSP 审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/11-plugins-skills-lsp.md)

[11 · 插件、Skill 与 LSP 修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/11-implemented-fixes.md)

[12 · 工作区、Git 与变更记录审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/12-workspace-git.md)

[12 · 工作区修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/12-implemented-fixes.md)

[13 · HTTP 服务、会话、线程与事件流审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/13-server-threads.md)

[13 · HTTP 服务与线程修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/13-implemented-fixes.md)

[14 · 协议、事件模型与展示归约审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/14-protocol-presentation.md)

[14 · 协议与展示修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/14-implemented-fixes.md)

[15 · TUI 生命周期与交互审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/15-tui.md)

[15 · TUI 修复记录](15-implemented-fixes.md)

[16 · 内置工具审核](16-builtin-tools.md) · [修复记录](16-implemented-fixes.md)

[17 · 配置、CLI 与基础设施审核](17-config-cli.md) · [修复与收尾记录](17-implemented-fixes.md)

本轮已收尾：第十七篇修复完成；累计回归 1448 项通过，最终凭据补丁定向回归 143 项通过（两批有重叠）。历史保留项详见进度台账，不继续开启新审核。

## 覆盖台账

| 体系 | Python文件数 | 状态 |
|---|---:|---|
| 01 自动化任务 | 5 | 核心审核完成；见01-automation.md |
| 02 权限、审批与沙箱 | 9 | 核心审核完成；见02-permissions.md |
| 03 Hook生命周期 | 1 | 核心审核完成；见03-hooks.md |
| 04 持久化Task与恢复 | 9 | 核心审核完成；见04-durable-tasks.md |
| 05 子Agent与协作 | 10 + 新增 store | 核心审核与修复完成；见05-subagents.md、05-implemented-fixes.md |
| 06 Engine与工具调度 | 24 | 上下篇核心审核与局部修复完成；持久化账单、协议、插件及 UI 边界见对应后续体系 |
| 07 Goal模式 | 9 + 新增 workspace | 核心审核与局部优化完成；07-implemented-fixes.md 说明语义验收等剩余边界 |
| 08 状态、上下文与媒体 | 6 | 核心审核与已复现缺陷修复完成；见08-implemented-fixes.md 的剩余边界 |
| 09 模型客户端与流式协议 | 12 | 核心审核与修复完成；见09-implemented-fixes.md 的局部修复边界与已知旧测试失败 |
| 10 MCP连接与工具发现 | 10 | 核心审核与 M01–M08 修复完成；见10-implemented-fixes.md 的剩余边界 |
| 11 插件、Skill与LSP | 19 | 核心审核与边界修复完成；见11-implemented-fixes.md |
| 12 工作区、Git与变更记录 | 10 | 核心审核与边界修复完成；见12-implemented-fixes.md |
| 13 HTTP服务、会话与线程 | 27 + 新增 lifecycle | 核心审核与本轮修复完成；剩余边界见13-implemented-fixes.md |
| 14 协议与展示模型 | 8 | 核心审核及局部修复完成；见14-implemented-fixes.md |
| 15 TUI与交互 | 16 + 新增 lifecycle | 核心审核及局部修复完成；见15-implemented-fixes.md |
| 16 内置工具 | 16 + 新增 output_capture、plan_state | N01—N11 最小修复完成；389 项扩展回归通过，保留边界见16-implemented-fixes.md |
| 17 配置、CLI与基础设施 | 14 | 核心审核及最小修复完成；见17-implemented-fixes.md |

## 01 自动化任务

核心审核完成；见01-automation.md

- [automation/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/__init__.py)
- [automation/delivery.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/delivery.py)
- [automation/inbox.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/inbox.py)
- [automation/pipeline.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/pipeline.py)
- [tools/automation.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py)

## 02 权限、审批与沙箱

核心审核完成；见02-permissions.md。关联调用链的权限部分已追踪，不代表关联体系整体审核完成。

- [policy/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/__init__.py)
- [policy/command_safety.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/command_safety.py)
- [policy/env_filter.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/env_filter.py)
- [policy/exec_policy.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/exec_policy.py)
- [policy/network.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/network.py)
- [policy/sandbox.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/sandbox.py)
- [server/approval.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/approval.py)
- [tools/approval.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/approval.py)
- [utils/network_escalation.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/utils/network_escalation.py)

## 03 Hook生命周期

核心审核完成；见03-hooks.md。已追踪关联入口与协议适配，不代表插件、Engine、子Agent整体审核完成。

- [integrations/hooks.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py)

## 04 持久化Task与恢复

核心审核完成；见04-durable-tasks.md。已追踪引擎执行器与检查点，不代表Engine整体审核完成。

- [tools/durable_transcript.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/durable_transcript.py)
- [tools/run_conversation.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/run_conversation.py)
- [tools/task/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/__init__.py)
- [tools/task/helpers.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/helpers.py)
- [tools/task/manager.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/manager.py)
- [tools/task/models.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/models.py)
- [tools/task/resume.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/resume.py)
- [tools/task/store.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/store.py)
- [tools/task/tools.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/tools.py)

## 05 子Agent与协作

核心审核完成；见05-subagents.md（历史问题基线）。本次实施见05-implemented-fixes.md，新增 store.py，原有10文件盘点不回写成历史已存在。

- [tools/subagent/store.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/store.py)

- [tools/subagent/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/__init__.py)
- [tools/subagent/agent.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/agent.py)
- [tools/subagent/completion.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/completion.py)
- [tools/subagent/handoff_ledger.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/handoff_ledger.py)
- [tools/subagent/loop.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py)
- [tools/subagent/mailbox.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/mailbox.py)
- [tools/subagent/manager.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py)
- [tools/subagent/structured_output.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/structured_output.py)
- [tools/subagent/tools.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/tools.py)
- [tools/subagent/types.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/types.py)

## 06 Engine与工具调度

上下篇已交付：06-engine.md 保留调度问题的历史基线，06-implemented-fixes.md 记录 E01—E08 修复；06-context.md 覆盖上下文预算、压缩、提示词7文件及相关调用链，记录 C01—C08 局部修复与剩余建议。验证见06-validation.json；跨模块追踪不代表状态、协议、插件或 UI 体系已完成审核。

- [engine/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/__init__.py)
- [engine/capacity.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/capacity.py)
- [engine/completion_requirement.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/completion_requirement.py)
- [engine/context.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context.py)
- [engine/context_pressure.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context_pressure.py)
- [engine/cycle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/cycle.py)
- [engine/dispatch.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/dispatch.py)
- [engine/events.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/events.py)
- [engine/handle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/handle.py)
- [engine/orchestrator/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/__init__.py)
- [engine/orchestrator/core.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py)
- [engine/orchestrator/helpers.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/helpers.py)
- [engine/orchestrator/lifecycle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/lifecycle.py)
- [engine/orchestrator/maintenance.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/maintenance.py)
- [engine/orchestrator/tooling.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py)
- [engine/prefix_probe.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/prefix_probe.py)
- [engine/prompts.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/prompts.py)
- [engine/reminders.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/reminders.py)
- [engine/tool_dedup.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/tool_dedup.py)
- [engine/tools.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/tools.py)
- [engine/turn.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/turn.py)
- [engine/usage_ledger.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/usage_ledger.py)
- [tools/registry.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/registry.py)
- [tools/runtime.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/runtime.py)

## 07 Goal模式

核心审核与局部优化完成，见07-goal.md、07-implemented-fixes.md；新增 workspace.py 随证据时效调用链审核。

- [goal/workspace.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/workspace.py)
- [goal/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/__init__.py)
- [goal/commands.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/commands.py)
- [goal/injection.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/injection.py)
- [goal/persist.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/persist.py)
- [goal/queue.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/queue.py)
- [goal/service.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py)
- [goal/state.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/state.py)
- [goal/tools.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/tools.py)
- [goal/types.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/types.py)

## 08 状态、上下文与媒体

核心审核与修复完成；原基线见08-state-media.md，实施与剩余边界见08-implemented-fixes.md。Server 存储事务另属后续体系。

- [media.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/media.py)
- [state/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/__init__.py)
- [state/context.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/context.py)
- [state/paste_file.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/paste_file.py)
- [state/secrets.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/secrets.py)
- [state/session.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/session.py)

## 09 模型客户端与流式协议

核心审核与修复完成；原问题见09-client-streaming.md，实施和边界见09-implemented-fixes.md。

- [client/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/__init__.py)
- [client/anthropic.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/anthropic.py)
- [client/base.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/base.py)
- [client/chat_messages.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/chat_messages.py)
- [client/deepseek.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/deepseek.py)
- [client/factory.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/factory.py)
- [client/media.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/media.py)
- [client/normalize.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/normalize.py)
- [client/pricing.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/pricing.py)
- [client/rate_limit.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/rate_limit.py)
- [client/sanitize.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/sanitize.py)
- [client/streaming.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/streaming.py)

## 10 MCP连接与工具发现

核心审核与 M01–M08 局部修复完成；见10-implemented-fixes.md 的剩余边界。

- [mcp/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/__init__.py)
- [mcp/actions.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/actions.py)
- [mcp/client.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/client.py)
- [mcp/config.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/config.py)
- [mcp/execute.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/execute.py)
- [mcp/manager.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/manager.py)
- [mcp/schema_hints.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/schema_hints.py)
- [mcp/store.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/store.py)
- [mcp/transport.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/transport.py)
- [tools/mcp.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/mcp.py)

## 11 插件、Skill与LSP

核心审核与边界修复完成；见11-plugins-skills-lsp.md、11-implemented-fixes.md。

- [integrations/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/__init__.py)
- [integrations/lsp.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/lsp.py)
- [integrations/plugin_compat.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugin_compat.py)
- [integrations/plugins.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugins.py)
- [integrations/skills.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/skills.py)
- [plugins/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/__init__.py)
- [plugins/adapters/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/__init__.py)
- [plugins/adapters/bare_skill.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/bare_skill.py)
- [plugins/adapters/claude.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/claude.py)
- [plugins/adapters/common.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/common.py)
- [plugins/adapters/registry.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/registry.py)
- [plugins/fetch.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/fetch.py)
- [plugins/grants.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/grants.py)
- [plugins/host.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/host.py)
- [plugins/identity.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/identity.py)
- [plugins/model.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/model.py)
- [plugins/runtime.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/runtime.py)
- [plugins/source.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/source.py)
- [plugins/store.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/store.py)

## 12 工作区、Git与变更记录

核心审核与边界修复完成；见12-workspace-git.md、12-implemented-fixes.md。

- [workspace/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/__init__.py)
- [workspace/diff_synth.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/diff_synth.py)
- [workspace/execution.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/execution.py)
- [workspace/git_reconcile.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/git_reconcile.py)
- [workspace/managed_worktree.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/managed_worktree.py)
- [workspace/mutation_ledger.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/mutation_ledger.py)
- [workspace/project_lease.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/project_lease.py)
- [workspace/shell_mutation_watch.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/shell_mutation_watch.py)
- [workspace/shell_write_guard.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/shell_write_guard.py)
- [workspace/turn_checkpoints.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/turn_checkpoints.py)

## 13 HTTP服务、会话与线程

核心路径审核与本轮修复完成；历史证据见13-server-threads.md，实施与剩余边界见13-implemented-fixes.md。新增 server/lifecycle.py 承担取消时的任务收拢。

- [server/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/__init__.py)
- [server/agent_segments.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/agent_segments.py)
- [server/app.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/app.py)
- [server/lifecycle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/lifecycle.py)
- [server/auth.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/auth.py)
- [server/data_bundle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/data_bundle.py)
- [server/data_inventory.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/data_inventory.py)
- [server/metrics.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/metrics.py)
- [server/phase_bridge.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/phase_bridge.py)
- [server/routes.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/routes.py)
- [server/runtime.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/runtime.py)
- [server/session_snapshot.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/session_snapshot.py)
- [server/sessions.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/sessions.py)
- [server/share_routes.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/share_routes.py)
- [server/share_service.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/share_service.py)
- [server/threads/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/__init__.py)
- [server/threads/broadcast.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/broadcast.py)
- [server/threads/errors.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/errors.py)
- [server/threads/items.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/items.py)
- [server/threads/manager.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py)
- [server/threads/models.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/models.py)
- [server/threads/rewind_audit.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/rewind_audit.py)
- [server/threads/soft_resume.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/soft_resume.py)
- [server/threads/store.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/store.py)
- [server/threads/titles.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/titles.py)
- [server/threads/usage.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/usage.py)
- [server/workbench_usage_ledger.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/workbench_usage_ledger.py)

## 14 协议与展示模型

审核与 P01–P07 修复完成；见14-protocol-presentation.md、14-implemented-fixes.md。8个模块逐个给出建议，修复后新增37项测试，并保留前后性能证据。

- [presentation/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/__init__.py)
- [presentation/models.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/models.py)
- [presentation/reducer.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/reducer.py)
- [presentation/semantics.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/semantics.py)
- [protocol/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/__init__.py)
- [protocol/events.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/events.py)
- [protocol/messages.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/messages.py)
- [protocol/responses.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/responses.py)

## 15 TUI与交互

核心路径审核及最小修复完成；见 [原审核](15-tui.md)、[修复记录](15-implemented-fixes.md)、[验证记录](15-fixes-validation.json)。T01—T12 已处理，308 项扩展回归通过。完整 rewind、增量过滤等保留边界详见修复记录。

- [tui/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/__init__.py)
- [tui/app.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py)
- [tui/lifecycle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/lifecycle.py)
- [tui/cards.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/cards.py)
- [tui/commands.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/commands.py)
- [tui/dialogs.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/dialogs.py)
- [tui/input.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/input.py)
- [tui/notifications.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/notifications.py)
- [tui/onboarding.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/onboarding.py)
- [tui/plan.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/plan.py)
- [tui/sanitize.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/sanitize.py)
- [tui/session_restore.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/session_restore.py)
- [tui/sidebar.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/sidebar.py)
- [tui/status.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/status.py)
- [tui/tool_cell.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/tool_cell.py)
- [tui/tool_classify.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/tool_classify.py)
- [tui/transcript.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/transcript.py)

## 16 内置工具

核心路径审核与 N01—N11 最小修复完成；见 [原审核](16-builtin-tools.md)、[修复记录](16-implemented-fixes.md)、[修复验证](16-fixes-validation.json)。扩展回归 389 项通过。旧探针只保留历史缺陷证据，不能直接作为当前验收。

- [tools/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/__init__.py)
- [tools/encoding.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/encoding.py)
- [tools/file.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/file.py)
- [tools/knowledge.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/knowledge.py)
- [tools/plan_mode.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/plan_mode.py)
- [tools/plan_state.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/plan_state.py)
- [tools/search.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/search.py)
- [tools/shell.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/shell.py)
- [tools/output_capture.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/output_capture.py)
- [tools/todo.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/todo.py)
- [tools/user_input.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/user_input.py)
- [tools/utils/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/utils/__init__.py)
- [tools/utils/edit_diagnostics.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/utils/edit_diagnostics.py)
- [tools/utils/gitignore.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/utils/gitignore.py)
- [tools/utils/path_suggestions.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/utils/path_suggestions.py)
- [tools/utils/sensitive.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/utils/sensitive.py)
- [tools/utils/validation.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/utils/validation.py)
- [tools/web.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/web.py)

## 17 配置、CLI与基础设施

核心审核和 Q01—Q12 最小修复完成；[原审核](17-config-cli.md) 保留历史证据，当前结果见 [修复记录](17-implemented-fixes.md)、[验证记录](17-fixes-validation.json)。本轮结束。

- [__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/__init__.py)
- [__main__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/__main__.py)
- [cli/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/__init__.py)
- [cli/app.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py)
- [config/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/__init__.py)
- [config/image_capabilities.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/image_capabilities.py)
- [config/layout.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/layout.py)
- [config/loader.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/loader.py)
- [config/models.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/models.py)
- [config/paths.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/paths.py)
- [config/providers.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/providers.py)
- [config/routing.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/routing.py)
- [prompts/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/prompts/__init__.py)
- [utils/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/utils/__init__.py)
