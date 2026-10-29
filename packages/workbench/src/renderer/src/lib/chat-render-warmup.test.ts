// @vitest-environment happy-dom
import { expect, it, vi } from 'vitest'
import { scheduleChatRenderWarmup } from './chat-render-warmup'
const highlight = vi.hoisted(() => vi.fn().mockResolvedValue('html'))
vi.mock('../components/chat/StreamdownAssistant', () => ({}))
vi.mock('../components/chat/SharedCodeBlock', () => ({ highlightCodeHtml: highlight }))
it('cancels idle preparation before it starts', () => {
  let callback = () => {}
  const cancel = vi.fn()
  vi.stubGlobal('requestIdleCallback', (fn: () => void) => { callback = fn; return 7 })
  vi.stubGlobal('cancelIdleCallback', cancel)
  try {
    const dispose = scheduleChatRenderWarmup()
    dispose()
    callback()
    expect(cancel).toHaveBeenCalledWith(7)
    expect(highlight).not.toHaveBeenCalled()
  } finally { vi.unstubAllGlobals() }
})
it('warms common languages in separate idle slots', async () => {
  const callbacks: Array<() => void> = []
  vi.stubGlobal('requestIdleCallback', (fn: () => void) => { callbacks.push(fn); return callbacks.length })
  vi.stubGlobal('cancelIdleCallback', vi.fn())
  const dispose = scheduleChatRenderWarmup()
  try {
    callbacks.shift()!()
    await vi.waitFor(() => expect(callbacks).toHaveLength(1))
    callbacks.shift()!()
    await vi.waitFor(() => expect(highlight).toHaveBeenCalledWith('const value = 1', 'typescript'))
    await vi.waitFor(() => expect(callbacks).toHaveLength(1))
    callbacks.shift()!()
    expect(highlight).toHaveBeenCalledWith('{"ready": true}', 'json')
  } finally { dispose(); vi.unstubAllGlobals() }
})
it('contains preparation failures and stops remaining optional work', async () => {
  const callbacks: Array<() => void> = []
  vi.stubGlobal('requestIdleCallback', (fn: () => void) => { callbacks.push(fn); return callbacks.length })
  vi.stubGlobal('cancelIdleCallback', vi.fn())
  highlight.mockClear()
  highlight.mockRejectedValueOnce(new Error('optional preparation failed'))
  const dispose = scheduleChatRenderWarmup()
  try {
    callbacks.shift()!()
    await vi.waitFor(() => expect(callbacks).toHaveLength(1))
    callbacks.shift()!()
    await vi.waitFor(() => expect(highlight).toHaveBeenCalledOnce())
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(callbacks).toHaveLength(0)
  } finally { dispose(); vi.unstubAllGlobals() }
})
