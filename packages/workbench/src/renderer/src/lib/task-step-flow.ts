import type { TaskTimelineEntry } from '../hooks/use-thread-tasks'
import {
  lifecycleToStepStatus,
  type StepFlowItem
} from '../components/chat/StepFlow'
import { collapseStepFlowProbes } from './step-flow-collapse'
import { buildStepIntent } from './step-intent'

/** Split a backend run-log line `name · arg — reason` into its parts. */
export function parseToolSummary(
  summary: string,
  failed: boolean
): { name: string; arg: string; reason: string } {
  let main = summary
  let reason = ''
  if (failed) {
    const dash = summary.indexOf(' — ')
    if (dash >= 0) {
      main = summary.slice(0, dash)
      reason = summary.slice(dash + 3)
    }
  }
  const dot = main.indexOf(' · ')
  const name = dot >= 0 ? main.slice(0, dot) : main
  const arg = dot >= 0 ? main.slice(dot + 3) : ''
  return { name: name.trim(), arg: arg.trim(), reason: reason.trim() }
}

/** Map durable-task timeline → StepFlow rail (intent title + target detail). */
export function timelineToFlowItems(timeline: TaskTimelineEntry[]): StepFlowItem[] {
  let toolIndex = 0
  const mapped = timeline.map((entry, idx) => {
    const kind = entry.kind
    if (kind === 'tool' || kind === 'tool_error') {
      toolIndex += 1
      const failed = kind === 'tool_error'
      const { name, arg, reason } = parseToolSummary(entry.summary, failed)
      const toolName = name || 'tool'
      const intent = buildStepIntent({
        toolName,
        primaryArg: arg || null
      })
      const input = arg || entry.summary
      const output = entry.detail?.trim() || reason || null
      return {
        id: `task-step-${idx}`,
        status: failed ? 'failed' : 'ok',
        label: intent.title,
        detail: intent.detail || undefined,
        meta: entry.timestamp
          ? entry.timestamp
          : toolIndex > 0
            ? `step ${toolIndex}`
            : undefined,
        input,
        output,
        toolName
      } satisfies StepFlowItem
    }
    if (kind === 'text') {
      return {
        id: `task-step-${idx}`,
        status: 'info',
        label: entry.summary.slice(0, 80) || 'narration',
        meta: entry.timestamp ?? undefined,
        output: entry.detail?.trim() || entry.summary,
        variant: 'narration' as const
      } satisfies StepFlowItem
    }
    const status = lifecycleToStepStatus(kind)
    const glyph =
      status === 'running'
        ? '●'
        : status === 'completed' || status === 'ok'
          ? '✓'
          : status === 'failed'
            ? '✗'
            : status === 'queued' || status === 'pending'
              ? '○'
              : '·'
    return {
      id: `task-step-${idx}`,
      status,
      label: `${glyph} ${kind}${entry.summary ? ` · ${entry.summary.slice(0, 60)}` : ''}`,
      meta: entry.timestamp ?? undefined,
      output:
        entry.detail?.trim() ||
        (entry.summary && entry.summary !== kind ? entry.summary : null)
    } satisfies StepFlowItem
  })
  return collapseStepFlowProbes(mapped)
}
