import { Bot, CalendarClock, ListTodo } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ToolProcessBlock } from './message-timeline-logic'
import { isSubagentOrchestrationToolName, toolNameFromProcessBlock } from './message-timeline-logic'

export function BackgroundActivityRow({ block }: { block: ToolProcessBlock }): React.JSX.Element {
  const { t } = useTranslation('common')
  const name = toolNameFromProcessBlock(block)
  const raw = block.meta?.tool_input
  const input = raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown> : {}
  const agent = isSubagentOrchestrationToolName(name)
  const scheduled = /^(cron|automation)_/.test(name)
  const kind = agent ? 'agent' : scheduled ? 'schedule' : 'task'
  const action = name === 'agent' ? String(input.action ?? 'spawn') : name.replace(/^[^_]+_/, '')
  const verb = /^(spawn|create|resume)$/.test(action) ? action
    : /^(cancel|stop|delete)$/.test(action) ? 'stop' : 'updated'
  const label = t(`backgroundActivity_${kind}_${verb}`)
  const descriptor = [input.name, input.nickname, input.description, input.prompt]
    .find((value): value is string => typeof value === 'string' && !!value.trim())
    ?.replace(/\s+/g, ' ').trim()
  const Icon = agent ? Bot : scheduled ? CalendarClock : ListTodo
  return (
    <div className="flex min-w-0 items-center gap-2 py-1 text-[13px] text-ds-muted" role="status">
      <Icon className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} aria-hidden />
      <span className="shrink-0">{label}</span>
      {descriptor ? <span className="truncate text-ds-faint" title={descriptor}>· {descriptor}</span> : null}
    </div>
  )
}
