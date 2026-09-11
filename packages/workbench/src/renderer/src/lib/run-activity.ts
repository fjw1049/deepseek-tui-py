import type { StepFlowItem } from '../components/chat/StepFlow'

export type RunActivityGroup = {
  id: string
  narration: StepFlowItem | null
  actions: StepFlowItem[]
}

/** A model update and its following actions form one readable unit. */
export function groupRunActivity(items: StepFlowItem[]): RunActivityGroup[] {
  const groups: RunActivityGroup[] = []
  for (const item of items) {
    if (item.variant === 'narration') {
      groups.push({ id: item.id, narration: item, actions: [] })
    } else {
      // Lifecycle chrome is already shown in the pinned header. Keep errors/results.
      if (!item.toolName && !item.variant && !item.output && item.status !== 'failed') continue
      let group = groups[groups.length - 1]
      if (!group) {
        group = { id: item.id, narration: null, actions: [] }
        groups.push(group)
      }
      group.actions.push(item)
    }
  }
  return groups
}

export function runActionCount(items: StepFlowItem[]): number {
  return items.reduce((count, item) => count + (item.toolName || item.variant === 'batch' ? item.batchCount ?? 1 : 0), 0)
}

/** Only shorten the preview; original input/output stays available in the disclosure. */
export function compactRunTarget(value: string): string {
  const text = value.trim()
  if (!text) return ''
  const url = text.match(/https?:\/\/[^\s"<>]+/)?.[0]
  if (url) {
    try {
      return new URL(url).hostname.replace(/^www\./, '')
    } catch { /* Fall back to a plain-text preview. */ }
  }
  const path = text.replace(/\\/g, '/')
  if (!/\s/.test(path) && path.includes('/')) {
    return path.split('/').filter(Boolean).slice(-2).join('/')
  }
  return text.replace(/\s+/g, ' ')
}

export function runActionTargets(item: StepFlowItem): string {
  const targets = item.batchEntries?.map((entry) => entry.target) ?? [item.detail || '']
  const unique = [...new Set(targets.map(compactRunTarget).filter(Boolean))]
  return unique.slice(0, 2).join(' · ')
}

export function isRunActive(status: string | undefined): boolean {
  return status === 'running' || status === 'pending' || status === 'queued'
}

export function runStatusKey(status: string | undefined): string {
  if (status === 'running') return 'contextRailTaskStatusRunning'
  if (status === 'completed' || status === 'ok') return 'contextRailTaskStatusCompleted'
  if (status === 'failed') return 'contextRailTaskStatusFailed'
  if (status === 'timed_out') return 'contextRailTaskStatusTimedOut'
  if (status === 'canceled' || status === 'cancelled') return 'contextRailTaskStatusCanceled'
  return 'contextRailTaskStatusQueued'
}

/** Keep filesystem boilerplate in the assignment, not the navigation title. */
export function runDisplayTitle(value: string): string {
  const firstLine = value.trim().split(/\n/)[0] || value
  return firstLine.replace(/\s*[（(](?:根目录|工作目录|工作区|workspace|root)\s*[：:].*$/i, '').trim()
}
