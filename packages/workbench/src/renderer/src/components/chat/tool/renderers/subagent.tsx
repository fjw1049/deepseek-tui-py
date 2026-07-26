import { memo } from 'react'
import { Bot } from 'lucide-react'
import { humanizeAgentType } from '../../../../lib/agent-type-label'
import { ToolStatusIndicator } from '../primitives'
import type { ToolRenderContext } from '../render-context'

/**
 * Lightweight renderer for sub-agent orchestration tools. The current runtime
 * exposes a single action-dispatched `agent` tool (action: spawn/result/
 * cancel/list/send_input/wait) plus `agent_resume`; the legacy agent_* names
 * (agent_spawn / agent_wait / …) are still handled for replayed history.
 *
 * Intentionally far simpler than the durable-task UI: these calls are just
 * orchestration markers, so a single calm row — Bot icon · label · agent
 * descriptor · status — is enough. The rich live progress lives in the
 * mailbox-driven `SubagentSummaryPanel`; when that panel is present these tool
 * blocks are hidden upstream, so this renderer only shows in the degraded case
 * where no mailbox cards exist (e.g. fast subagents or replayed history).
 */

const WAIT_MODE_LABELS: Record<string, string> = {
  all: '全部',
  any: '任一',
  first: '最先'
}

/** Per-action labels for the merged `agent` tool (mirror the legacy names). */
const ACTION_LABELS: Record<string, string> = {
  spawn: '派生子代理',
  result: '获取子代理结果',
  cancel: '取消子代理',
  list: '子代理列表',
  send_input: '发送子代理输入',
  wait: '等待子代理'
}

function readToolInput(context: ToolRenderContext): Record<string, unknown> {
  const raw = context.meta?.tool_input
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : {}
}

function readString(input: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = input[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return undefined
}

function agentDescriptor(context: ToolRenderContext): string {
  const input = readToolInput(context)
  const action = readString(input, 'action')?.toLowerCase()
  const isWait = context.toolName.includes('wait') || action === 'wait'

  if (isWait) {
    const mode = readString(input, 'wait_mode', 'mode')
    return mode ? (WAIT_MODE_LABELS[mode.toLowerCase()] ?? mode) : context.description
  }

  const type = readString(input, 'type', 'agent_type')
  const nickname = readString(input, 'nickname')
  const parts = [type ? humanizeAgentType(type) : undefined, nickname].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : context.description
}

/** Label for the header: per-action for the merged `agent` tool, else mapped. */
function subagentLabel(context: ToolRenderContext): string {
  const action = readString(readToolInput(context), 'action')?.toLowerCase()
  return (action && ACTION_LABELS[action]) || context.label || context.shortName
}

export const SubagentRenderer = {
  Header: memo(function SubagentHeader({
    context
  }: {
    context: ToolRenderContext
  }): React.JSX.Element {
    const descriptor = agentDescriptor(context)
    return (
      <div className="flex w-full items-center gap-2">
        <Bot
          className="h-3.5 w-3.5 shrink-0 text-violet-500/80 dark:text-violet-300/80"
          strokeWidth={1.8}
          aria-hidden
        />
        <span className="shrink-0 font-mono text-[0.6875rem] font-medium text-ds-muted">
          {subagentLabel(context)}
        </span>
        {descriptor ? (
          <span
            className="min-w-0 flex-1 truncate text-[13px] text-ds-faint"
            title={descriptor}
          >
            {descriptor}
          </span>
        ) : (
          <span className="flex-1" />
        )}
        <ToolStatusIndicator state={context.state} />
      </div>
    )
  })
}
