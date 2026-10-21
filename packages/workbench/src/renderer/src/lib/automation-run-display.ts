import type { AutomationRecord, AutomationRunRecord } from './automation-runtime-client'

type Translate = (key: string) => string

function automationHasDelivery(automation: AutomationRecord | undefined): boolean {
  const mode = automation?.delivery?.mode?.trim()
  if (!mode) return false
  return mode !== 'none' && mode !== 'silent'
}

function isTerminalRunStatus(status: string): boolean {
  const normalized = status.toLowerCase()
  return (
    normalized === 'completed' ||
    normalized === 'succeeded' ||
    normalized === 'success' ||
    normalized === 'failed' ||
    normalized === 'error' ||
    normalized === 'canceled'
  )
}

/** Human-readable delivery column for run history tables. */
export function formatRunDeliveryStatus(
  run: AutomationRunRecord,
  automation: AutomationRecord | undefined,
  t: Translate
): string {
  if (!automationHasDelivery(automation)) {
    return t('automationRunDeliveryNotConfigured')
  }

  if (!isTerminalRunStatus(run.status)) {
    return '—'
  }

  const deliveryFailed =
    Boolean(run.delivery_error) || (run.error?.toLowerCase().includes('delivery failed') ?? false)
  if (deliveryFailed) {
    return t('automationRunDeliveryFailed')
  }

  if (run.delivery_done === true) {
    return t('automationRunDelivered')
  }

  if (run.delivery_done === false) {
    return t('automationRunNotDelivered')
  }

  return '—'
}

/** A delivery failure does not establish whether execution succeeded. */
export function formatRunStatus(run: AutomationRunRecord, t: Translate): string {
  if (run.status === 'failed' && (run.delivery_error || /delivery failed/i.test(run.error || ''))) {
    return t('automationDeliveryIssue')
  }
  const labels: Record<string, string> = {
    completed: 'automationCompleted', succeeded: 'automationCompleted', success: 'automationCompleted',
    failed: 'automationRunFailed', error: 'automationRunFailed', running: 'automationRunRunning',
    queued: 'automationRunQueued', canceled: 'automationRunCanceled'
  }
  return labels[run.status] ? t(labels[run.status]) : run.status
}
