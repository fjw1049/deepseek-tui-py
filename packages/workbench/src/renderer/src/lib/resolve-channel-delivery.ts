import type { CreateAutomationInput } from './automation-runtime-client'
import { resolveAutomationFeishuChatId } from './resolve-automation-feishu-chat-id'
import { resolveAutomationMailTo } from './resolve-automation-mail-to'
import { loadWecomChannelState } from './resolve-automation-wecom-config'

export type ChannelDeliveryState = {
  feishuDefault: string
  emailDefault: string
  feishuChannelReady: boolean
  wecomChannelReady: boolean
  emailChannelReady: boolean
}

type Translate = (key: string, options?: Record<string, unknown>) => string

export async function loadChannelDeliveryState(): Promise<ChannelDeliveryState> {
  const [feishuFile, feishuChat, mail, emailSecret, wecomState] = await Promise.all([
    window.dsGui.getFeishuConfig(),
    resolveAutomationFeishuChatId(),
    resolveAutomationMailTo(),
    window.dsGui.getEmailSecretStatus(),
    loadWecomChannelState()
  ])
  const chatId = feishuChat?.trim() || feishuFile.config.chatId?.trim() || ''
  const mailTo = mail?.trim() ?? ''
  return {
    feishuDefault: chatId,
    emailDefault: mailTo,
    feishuChannelReady: Boolean(
      feishuFile.config.appId?.trim() && feishuFile.config.appSecret?.trim() && chatId
    ),
    wecomChannelReady: wecomState.configured,
    emailChannelReady: Boolean(mailTo && emailSecret.passwordConfigured)
  }
}

/** Default delivery payload from message-channel bindings (Feishu → WeCom → email). */
export function resolveDefaultDeliveryFromChannels(
  state: ChannelDeliveryState
): CreateAutomationInput['delivery'] | undefined {
  if (state.feishuChannelReady && state.feishuDefault.trim()) {
    return {
      mode: 'feishu',
      to: state.feishuDefault.trim(),
      best_effort: false
    }
  }
  if (state.wecomChannelReady) {
    return {
      mode: 'wecom',
      best_effort: false
    }
  }
  if (state.emailChannelReady && state.emailDefault.trim()) {
    return {
      mode: 'email',
      to: state.emailDefault.trim(),
      best_effort: false
    }
  }
  return undefined
}

/** Hint for template cards: where results will be sent when enabled. */
export function templateDeliveryCardHint(
  state: ChannelDeliveryState | null,
  t: Translate
): string {
  if (!state) return t('automationDeliveryUnsetShort')
  const delivery = resolveDefaultDeliveryFromChannels(state)
  if (!delivery) return t('automationTemplateDeliveryUnset')
  if (delivery.mode === 'feishu') return t('automationTemplateDeliveryFeishu')
  if (delivery.mode === 'wecom') return t('automationTemplateDeliveryWecom')
  return t('automationTemplateDeliveryEmail')
}
