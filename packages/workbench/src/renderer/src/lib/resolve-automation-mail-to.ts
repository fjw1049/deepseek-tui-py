/** Read default automation recipient from config.toml ``[automation]``. */

import { readTomlString } from '@shared/toml-section'

export async function resolveAutomationMailTo(): Promise<string | null> {
  if (typeof window.dsGui === 'undefined' || typeof window.dsGui.getDeepseekConfigFile !== 'function') {
    return null
  }
  try {
    const file = await window.dsGui.getDeepseekConfigFile()
    const content = file.content ?? ''
    const mailTo = readTomlString(content, 'mail_to', { section: 'automation' })
    if (mailTo) return mailTo
    return readTomlString(content, 'to_addr', { section: 'automation.email' })
  } catch {
    return null
  }
}
