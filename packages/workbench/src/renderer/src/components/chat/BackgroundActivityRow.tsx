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
  const action = name === 'agent' ? String(input.action ?? 'spawn')
    : name === 'spawn_agent' || name === 'delegate_to_agent' ? 'spawn' : name.replace(/^[^_]+_/, '')
  const verb = /^(spawn|create|resume)$/.test(action) ? action
    : /^(cancel|stop|delete)$/.test(action) ? 'stop' : 'updated'
  const label = t(`backgroundActivity_${kind}_${verb}`)
  const descriptor = [input.name, input.nickname, input.description, input.prompt]
    .find((value): value is string => typeof value === 'string' && !!value.trim())
    ?.replace(/\s+/g, ' ').trim()
  const Icon = agent ? Bot : scheduled ? CalendarClock : ListTodo
  // Same row grid as neighbouring tool rows so icon, label, and descriptor columns line up.
  return (
    <div className="ds-tool-row flex items-center rounded-md" role="status">
      <div className="ds-tool-header-row flex w-full min-w-0 items-center">
        <span className="ds-tool-header-row__lead min-w-0 flex-1">
          <Icon className="ds-tool-header-row__icon shrink-0 text-ds-faint" strokeWidth={1.8} aria-hidden />
          <span className="ds-tool-header-row__label shrink-0 text-ds-muted">{label}</span>
          {descriptor ? (
            <span className="ds-tool-header-row__title ds-tool-header-row__main min-w-0 truncate text-ds-faint" title={descriptor}>
              {descriptor}
            </span>
          ) : null}
        </span>
      </div>
    </div>
  )
}
