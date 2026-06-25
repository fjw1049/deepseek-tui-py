/** Read/write WeCom webhook config from config.toml `[automation.wecom]`. */

import { readTomlString, upsertTomlSections } from '@shared/toml-section'
import { isWecomWebhookConfigured, parseWecomWebhookKey } from '@shared/wecom-channel'

export type WecomChannelConfig = {
  webhookKey: string
}

export const EMPTY_WECOM_CONFIG: WecomChannelConfig = { webhookKey: '' }

export function parseWecomConfig(content: string): WecomChannelConfig {
  const raw = readTomlString(content, 'webhook_key', { section: 'automation.wecom' }) ?? ''
  const webhookKey = parseWecomWebhookKey(raw) ?? raw.trim()
  return { webhookKey }
}

export function isWecomChannelConfigured(
  config: WecomChannelConfig | string
): boolean {
  const webhookKey = typeof config === 'string' ? parseWecomConfig(config).webhookKey : config.webhookKey
  return isWecomWebhookConfigured(webhookKey)
}

export async function loadWecomChannelState(): Promise<{
  configured: boolean
  config: WecomChannelConfig
}> {
  if (typeof window.dsGui.getWecomConfig === 'function') {
    const result = await window.dsGui.getWecomConfig()
    return {
      configured: result.configured,
      config: result.config
    }
  }

  const configFile = await window.dsGui.getDeepseekConfigFile()
  const config = parseWecomConfig(configFile.content ?? '')
  return {
    configured: isWecomChannelConfigured(config),
    config
  }
}

export async function saveWecomWebhookKey(input: string): Promise<void> {
  const key = parseWecomWebhookKey(input)
  if (!key) throw new Error('invalid_wecom_webhook_key')

  if (typeof window.dsGui.setWecomConfig === 'function') {
    await window.dsGui.setWecomConfig({ webhookKey: key })
    return
  }

  const configFile = await window.dsGui.getDeepseekConfigFile()
  const updated = upsertTomlSections(configFile.content ?? '', {
    'automation.wecom': { webhook_key: key }
  })
  await window.dsGui.setDeepseekConfigFile(updated)
}
