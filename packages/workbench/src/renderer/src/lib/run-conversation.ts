import type { ChatBlock, SubagentStepBlock } from '../agent/types'
import type { TaskDetail } from '../hooks/use-thread-tasks'
import { parseToolSummary } from './task-step-flow'

/** Legacy records remain readable without inventing missing structured tool data. */
export function legacyRunConversation({ id, prompt, steps, task, result, live, active }: {
  id: string
  prompt?: string
  steps?: SubagentStepBlock[]
  task?: TaskDetail | null
  result?: string | null
  live?: string | null
  active: boolean
}): { blocks: ChatBlock[]; liveId: string | null } {
  const blocks: ChatBlock[] = []
  const prefix = `run:${id}`
  if (prompt) blocks.push({ kind: 'user', id: `${prefix}:prompt`, text: prompt })
  const narration = (key: string, text: string) => blocks.push({
    kind: 'assistant', id: `${prefix}:${key}`, text, agentSegment: 'mid_turn_preface'
  })
  if (task) {
    task.timeline.forEach((entry, index) => {
      if (entry.kind === 'text') narration(`text:${index}`, entry.detail || entry.summary)
      else if (entry.kind === 'tool' || entry.kind === 'tool_error') {
        const { name } = parseToolSummary(entry.summary, entry.kind === 'tool_error')
        blocks.push({ kind: 'tool', id: `${prefix}:tool:${index}`, summary: entry.summary,
          status: entry.kind === 'tool_error' ? 'error' : 'success', detail: entry.detail ?? undefined,
          meta: { tool_name: name } })
      }
    })
  } else {
    for (const step of steps ?? []) {
      if (step.kind === 'progress') narration(step.id, step.output || step.label)
      if (step.kind === 'tool') {
        let input: Record<string, unknown> | undefined
        try { input = JSON.parse(step.input || '') } catch { /* Older previews may be clipped JSON. */ }
        blocks.push({ kind: 'tool', id: `${prefix}:${step.id}`, summary: `${step.toolName || 'tool'}: ${step.input || ''}`,
          status: step.ok == null ? (active ? 'running' : 'error') : step.ok ? 'success' : 'error',
          detail: step.output ?? undefined, meta: { tool_name: step.toolName, tool_input: input } })
      }
    }
  }
  let liveText = active ? live || '' : ''
  // Legacy streams accumulate across rounds. Remove already-settled narration once.
  for (const block of blocks) {
    if (block.kind === 'assistant' && liveText.startsWith(block.text)) liveText = liveText.slice(block.text.length)
  }
  const terminal = [...(steps ?? [])].reverse().find((step) => step.kind === 'completed' || step.kind === 'failed')
  const finalText = result || terminal?.output
  if (!active && finalText) {
    const last = blocks.at(-1)
    if (last?.kind === 'assistant' && last.text === finalText) last.agentSegment = 'final_answer'
    else blocks.push({ kind: 'assistant', id: `${prefix}:answer`, text: finalText, agentSegment: 'final_answer' })
  }
  const liveId = liveText ? `${prefix}:live` : null
  if (liveId) blocks.push({ kind: 'assistant', id: liveId, text: liveText })
  return { blocks, liveId }
}
