/** Persist channel setup panel open/closed across route switches within the session. */

const STORAGE_KEY = 'deepseekgui.channels.panel'

type ChannelPanelState = {
  feishu: boolean
  email: boolean
  wecom: boolean
}

function readState(): ChannelPanelState {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return { feishu: false, email: false, wecom: false }
    const parsed = JSON.parse(raw) as Partial<ChannelPanelState>
    return {
      feishu: Boolean(parsed.feishu),
      email: Boolean(parsed.email),
      wecom: Boolean(parsed.wecom)
    }
  } catch {
    return { feishu: false, email: false, wecom: false }
  }
}

export function loadChannelPanelState(): ChannelPanelState {
  return readState()
}

export function saveChannelPanelState(state: ChannelPanelState): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    /* ignore quota / private mode */
  }
}
