/** Run optional preparation only after the shell has painted. */
export function scheduleChatRenderWarmup(): () => void {
  let cancelled = false
  let cancelPending = (): void => {}
  const idle = (task: () => void): void => {
    if (cancelled) return
    if (typeof window.requestIdleCallback === 'function') {
      const id = window.requestIdleCallback(() => { if (!cancelled) task() })
      cancelPending = () => window.cancelIdleCallback(id)
    } else {
      const id = window.setTimeout(() => { if (!cancelled) task() }, 1000)
      cancelPending = () => window.clearTimeout(id)
    }
  }
  idle(() => {
    void import('../components/chat/StreamdownAssistant').then(() => {
      idle(() => {
        void import('../components/chat/SharedCodeBlock').then(async ({ highlightCodeHtml }) => {
          if (cancelled) return
          await highlightCodeHtml('const value = 1', 'typescript')
          idle(() => { void highlightCodeHtml('{"ready": true}', 'json').catch(() => {}) })
        }).catch(() => {})
      })
    }).catch(() => {})
  })
  return () => { cancelled = true; cancelPending() }
}
