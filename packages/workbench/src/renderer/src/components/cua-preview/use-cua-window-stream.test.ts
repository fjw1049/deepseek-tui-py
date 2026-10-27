// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useCuaWindowStream, type CuaWindowStreamState } from './use-cua-window-stream'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: ReturnType<typeof createRoot>
let host: HTMLDivElement
let state: CuaWindowStreamState
let frame: (() => void) | undefined
let stops: Record<string, ReturnType<typeof vi.fn>>
let failA: boolean
const canvasRef = { current: null as HTMLCanvasElement | null }
function Probe({ appId, enabled = true }: { appId: string | null; enabled?: boolean }) {
  state = useCuaWindowStream({ canvasRef, appId, revision: 1, enabled })
  return null
}
const render = (appId: string | null, enabled = true) => act(async () => {
  root.render(createElement(Probe, { appId, enabled }))
})
beforeEach(() => {
  failA = false
  frame = undefined
  stops = {}
  host = document.createElement('div')
  root = createRoot(host)
  canvasRef.current = document.createElement('canvas')
  vi.spyOn(canvasRef.current, 'getContext').mockReturnValue({ drawImage: vi.fn(), clearRect: vi.fn() } as unknown as CanvasRenderingContext2D)
  vi.spyOn(performance, 'now').mockReturnValue(1000)
  const create = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation((tag, options) => {
    const element = create(tag, options)
    if (tag === 'video') {
      Object.defineProperties(element, {
        videoWidth: { value: 800 }, videoHeight: { value: 600 },
        srcObject: { value: null, writable: true },
        play: { value: vi.fn(async () => {}) },
        requestVideoFrameCallback: { value: (callback: () => void) => { frame = callback; return 1 } }
      })
    }
    return element
  })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    platform: 'darwin', resolveCuaPreviewWindow: vi.fn(async (id: string) => ({
      status: 'ok', sourceId: id, appName: id, icon: `icon-${id}`
    }))
  } })
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async (constraints) => {
    const id = constraints.video.mandatory.chromeMediaSourceId as string
    if (id === 'A' && failA) throw new Error('capture failed')
    const stop = stops[id] = vi.fn()
    const track = { stop, addEventListener: vi.fn() }
    return { getTracks: () => [track], getVideoTracks: () => [track] }
  }) } })
})
afterEach(async () => {
  await act(async () => root.unmount())
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('releases the live frame when the target changes to a browser', async () => {
  await render('A')
  await act(async () => frame!())
  expect(state.hasFrame).toBe(true)
  await render(null)
  expect(stops.A).toHaveBeenCalledOnce()
  expect(state).toMatchObject({ hasFrame: false, appName: null, icon: null })
})

it('keeps the final frame when the task stops on the same app', async () => {
  await render('A')
  await act(async () => frame!())
  await render('A', false)
  expect(stops.A).toHaveBeenCalledOnce()
  expect(state).toMatchObject({ hasFrame: true, appName: 'A' })
})

it('stops B before falling back for a previously failed A window', async () => {
  failA = true
  await render('A')
  await render('B')
  await act(async () => frame!())
  await render('A')
  expect(stops.B).toHaveBeenCalledOnce()
  expect(state).toMatchObject({ status: 'failed', hasFrame: false, appName: 'A' })
  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(2)
})

it('retries a failed capture after permission recheck without replaying a desktop action', async () => {
  failA = true
  await render('A')
  expect(state.status).toBe('failed')
  failA = false
  await act(async () => window.dispatchEvent(new Event('cua-permission-recheck')))
  await act(async () => frame!())
  expect(state.hasFrame).toBe(true)
  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(2)
})


it('stops and clears a live window when the same app becomes ambiguous', async () => {
  await render('A')
  await act(async () => frame!())
  expect(state.hasFrame).toBe(true)
  vi.mocked(window.dsGui.resolveCuaPreviewWindow).mockResolvedValue({ status: 'ambiguous', appName: 'A' })
  await act(async () => window.dispatchEvent(new Event('cua-permission-recheck')))
  expect(stops.A).toHaveBeenCalledOnce()
  expect(state).toMatchObject({ status: 'ambiguous', hasFrame: false })
  expect(canvasRef.current!.getContext('2d')!.clearRect).toHaveBeenCalled()
  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1)
})


it('does not erase a task screenshot when no live window was captured', async () => {
  vi.mocked(window.dsGui.resolveCuaPreviewWindow).mockResolvedValue({ status: 'ambiguous', appName: 'A' })
  await render('A')
  expect(canvasRef.current!.getContext('2d')!.clearRect).not.toHaveBeenCalled()
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
})

it('recovers when a window appears after the initial recheck', async () => {
  vi.useFakeTimers()
  const lookup = vi.mocked(window.dsGui.resolveCuaPreviewWindow)
  lookup.mockResolvedValue({ status: 'no-window' })
  await render('A')
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  expect(lookup).toHaveBeenCalledTimes(2)
  lookup.mockResolvedValue({ status: 'ok', sourceId: 'A' })
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  await act(async () => frame!())
  expect(state).toMatchObject({ status: 'ok', hasFrame: true })
  await act(async () => { await vi.advanceTimersByTimeAsync(4500) })
  expect(lookup).toHaveBeenCalledTimes(3)
})

it('cancels missing-window rechecks when the preview stops', async () => {
  vi.useFakeTimers()
  const lookup = vi.mocked(window.dsGui.resolveCuaPreviewWindow)
  lookup.mockResolvedValue({ status: 'no-window' })
  await render('A')
  await render('A', false)
  await act(async () => { await vi.advanceTimersByTimeAsync(4500) })
  expect(lookup).toHaveBeenCalledOnce()
})

it('allows manual recovery after a lookup error', async () => {
  vi.mocked(window.dsGui.resolveCuaPreviewWindow).mockRejectedValueOnce(new Error('IPC failed'))
  await render('A')
  expect(state.status).toBe('lookup-failed')
  await act(async () => window.dispatchEvent(new Event('cua-preview-recheck')))
  await act(async () => frame!())
  expect(state).toMatchObject({ status: 'ok', hasFrame: true })
})
