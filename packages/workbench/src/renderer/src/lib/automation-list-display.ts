import type { AutomationRecord } from './automation-runtime-client'

type Translate = (key: string) => string

const DELIVERY_MODE_I18N: Record<string, string> = {
  email: 'automationDeliveryEmailShort',
  feishu: 'automationDeliveryFeishuShort',
  wecom: 'automationDeliveryWecomShort'
}

/** Flatten prompt / summary text for fixed-height list cards (visual clamp in CSS). */
export function automationCardPreview(text: string): string {
  const raw = text.trim()
  if (!raw) return ''
  const firstBlock = (raw.split(/\n\s*\n/)[0] ?? raw).trim()
  return firstBlock.replace(/\s+/g, ' ')
}

function deliveryModeLabel(mode: string, t: Translate): string {
  const key = DELIVERY_MODE_I18N[mode]
  return key ? t(key) : mode
}

function isOpaqueDeliveryTarget(value: string): boolean {
  const trimmed = value.trim()
  if (!trimmed) return false
  if (/^oc_[a-f0-9]{8,}$/i.test(trimmed)) return true
  if (/^ou_[a-f0-9]{8,}$/i.test(trimmed)) return true
  return trimmed.length > 40 && !trimmed.includes('@') && !trimmed.includes(' ')
}

function readableDeliveryTarget(mode: string, to: string | undefined): string | null {
  const target = to?.trim()
  if (!target) return null
  if (mode === 'email') return target
  if (isOpaqueDeliveryTarget(target)) return null
  return target.length > 32 ? `${target.slice(0, 29)}…` : target
}

/** Full delivery string for detail drawer / tooltips. */
export function automationDeliveryDetail(row: AutomationRecord, t: Translate): string {
  const mode = row.delivery?.mode
  if (!mode) return t('automationDeliveryUnsetDetail')
  const label = deliveryModeLabel(mode, t)
  const target = row.delivery?.to?.trim()
  if (mode === 'feishu' && target && isOpaqueDeliveryTarget(target)) {
    return t('automationDeliveryFeishuBound')
  }
  if (mode === 'wecom') {
    return t('automationDeliveryWecomBound')
  }
  return target ? `${label} · ${target}` : label
}

/** Compact delivery hint for list cards. */
export function automationDeliveryCardHint(row: AutomationRecord, t: Translate): string {
  const mode = row.delivery?.mode
  if (!mode) return t('automationDeliveryUnsetShort')
  const label = deliveryModeLabel(mode, t)
  const target = readableDeliveryTarget(mode, row.delivery?.to)
  if (mode === 'feishu' && !target && row.delivery?.to?.trim()) {
    return t('automationDeliveryFeishuBound')
  }
  if (mode === 'wecom') {
    return t('automationDeliveryWecomBound')
  }
  return target ? `${label} · ${target}` : label
}
