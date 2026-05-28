/** Default Feishu delivery target from config.toml ``[automation]`` / ``[automation.feishu]``. */

import type { FeishuConfigV1 } from '@shared/ds-gui-api'
import { readTomlString } from '@shared/toml-section'

async function readFeishuChatIdFromToml(): Promise<string | null> {
  if (typeof window.dsGui === 'undefined' || typeof window.dsGui.getDeepseekConfigFile !== 'function') {
    return null
  }
  try {
    const file = await window.dsGui.getDeepseekConfigFile()
    const content = file.content ?? ''
    return (
      readTomlString(content, 'feishu_chat_id', { section: 'automation' }) ??
      readTomlString(content, 'chat_id', { section: 'automation.feishu' })
    )
  } catch {
    return null
  }
}

async function readFeishuChatIdFromFeishuConfig(): Promise<string | null> {
  if (typeof window.dsGui === 'undefined' || typeof window.dsGui.getFeishuConfig !== 'function') {
    return null
  }
  try {
    const file = await window.dsGui.getFeishuConfig()
    const chatId = (file.config as FeishuConfigV1 | undefined)?.chatId?.trim()
    return chatId || null
  } catch {
    return null
  }
}

export async function resolveAutomationFeishuChatId(): Promise<string | null> {
  return (await readFeishuChatIdFromFeishuConfig()) ?? (await readFeishuChatIdFromToml())
}
