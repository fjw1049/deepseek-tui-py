/** WeCom (企业微信) group robot webhook helpers shared by UI and tests. */

export const WECOM_WEBHOOK_BASE = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send'

const WECOM_KEY_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Extract webhook key from a full URL or bare UUID key. */
export function parseWecomWebhookKey(input: string): string | null {
  const raw = input.trim()
  if (!raw) return null

  if (WECOM_KEY_PATTERN.test(raw)) return raw

  try {
    const url = new URL(raw)
    if (!url.hostname.includes('qyapi.weixin.qq.com')) return null
    if (!url.pathname.endsWith('/webhook/send')) return null
    const key = url.searchParams.get('key')?.trim() ?? ''
    return WECOM_KEY_PATTERN.test(key) ? key : null
  } catch {
    return null
  }
}

export function isWecomWebhookConfigured(webhookKey: string | null | undefined): boolean {
  return Boolean(parseWecomWebhookKey(webhookKey ?? ''))
}

export function buildWecomWebhookUrl(webhookKey: string): string {
  const key = parseWecomWebhookKey(webhookKey)
  if (!key) throw new Error('invalid_wecom_webhook_key')
  return `${WECOM_WEBHOOK_BASE}?key=${key}`
}
