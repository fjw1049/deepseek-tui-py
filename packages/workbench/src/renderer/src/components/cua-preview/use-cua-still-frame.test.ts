// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useCuaStillFrame, type CuaStillState } from './use-cua-still-frame'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const CURRENT = '/v1/threads/t/cua/frame'
const frame = { ok: true, body: JSON.stringify({ data: btoa('jpeg'), mime_type: 'image/jpeg' }) }
const missing = { ok: false, body: '' }
let root: ReturnType<typeof createRoot>
let state: CuaStillState
let request: ReturnType<typeof vi.fn>
let draw: ReturnType<typeof vi.fn>
const canvasRef = { current: null as HTMLCanvasElement | null }
function Probe(props: { refresh: number; currentPath: string | null; still: { itemId: string; assetId: string } | null }) {
  state = useCuaStillFrame({ canvasRef, enabled: true, ...props })
  return null
}
const render = (props: Parameters<typeof Probe>[0]) => act(async () => root.render(createElement(Probe, props)))

beforeEach(() => {
  root = createRoot(document.createElement('div'))
  draw = vi.fn()
  canvasRef.current = document.createElement('canvas')
  vi.spyOn(canvasRef.current, 'getContext').mockReturnValue({ drawImage: draw } as unknown as CanvasRenderingContext2D)
  vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 800, height: 600, close: vi.fn() })))
  request = vi.fn(async () => frame)
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request } })
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals() })

it('takes a fresh frame after every step', async () => {
  await render({ refresh: 1, currentPath: CURRENT, still: null })
  expect(state).toEqual({ status: 'ready', frameSize: { width: 800, height: 600 } })
  await render({ refresh: 2, currentPath: CURRENT, still: null })
  expect(request.mock.calls.map(call => call[0])).toEqual([CURRENT, CURRENT])
  expect(draw).toHaveBeenCalledTimes(2)
})

it('falls back to the recorded screenshot when the runtime has no frame', async () => {
  request.mockImplementation(async (path: string) => path === CURRENT ? missing : frame)
  await render({ refresh: 1, currentPath: CURRENT, still: { itemId: 'i', assetId: 'a' } })
  expect(request.mock.calls.at(-1)?.[0]).toBe('/v1/cua/frames/i/a')
  expect(state.status).toBe('ready')
})

it('treats no frame between calls as nothing to show, not a failure', async () => {
  request.mockResolvedValue(missing)
  await render({ refresh: 1, currentPath: CURRENT, still: null })
  expect(state).toEqual({ status: 'idle', frameSize: null })
})

it('keeps the shown frame when the next one is not available', async () => {
  await render({ refresh: 1, currentPath: CURRENT, still: null })
  request.mockResolvedValue(missing)
  await render({ refresh: 2, currentPath: CURRENT, still: null })
  expect(state).toEqual({ status: 'ready', frameSize: { width: 800, height: 600 } })
  expect(draw).toHaveBeenCalledOnce()
})
