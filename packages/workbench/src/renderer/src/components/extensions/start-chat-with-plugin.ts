import { useChatStore } from '../../store/chat-store'

let entering = false

/** Select the same composer chip as the chat picker; no message is sent. */
export async function usePluginNow(name: string): Promise<void> {
  if (entering) return
  entering = true
  try {
    if (useChatStore.getState().runtimeConnection !== 'ready') {
      await useChatStore.getState().probeRuntime('background')
    }
    const threadId = await useChatStore.getState().createThread({ forceNew: true, chats: true })
    if (!threadId) return
    useChatStore.setState({ pendingPluginSelection: name, route: 'chat' })
  } finally { entering = false }
}
