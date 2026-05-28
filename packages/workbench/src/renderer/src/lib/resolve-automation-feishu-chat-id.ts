/** Default Feishu delivery target from config.toml ``[automation]`` / ``[automation.feishu]``. */

import { readTomlString } from '@shared/toml-section'

export async function resolveAutomationFeishuChatId(): Promise<string | null> {
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
