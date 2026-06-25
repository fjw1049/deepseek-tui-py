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

  const deliveryFailed = run.error?.toLowerCase().includes('delivery failed') ?? false
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
