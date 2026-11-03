// @vitest-environment happy-dom
import { act, createElement, useMemo } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { preloadPetThumbnails, usePetThumbnails } from './pet-thumbnails'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const host = document.createElement('div')
let root = createRoot(host)
function Preview({ names }: { names: string }) {
  const slugs = useMemo(() => names.split(','), [names])
  return createElement('div', null, JSON.stringify(usePetThumbnails(slugs)))
}
afterEach(async () => {
  await act(async () => root.unmount())
  root = createRoot(host)
  vi.unstubAllGlobals()
})

it('publishes ready images without waiting for slow ones and survives list changes', async () => {
  const finish = new Map<string, (value: Record<string, string>) => void>()
  const resolve = vi.fn((slugs: string[]) => new Promise<Record<string, string>>(done => finish.set(slugs[0], done)))
  vi.stubGlobal('dsGui', { resolvePetThumbnails: resolve })
  await act(async () => preloadPetThumbnails(['fast', 'slow']))
  await act(async () => root.render(createElement(Preview, { names: 'fast,slow' })))
  await act(async () => root.render(createElement(Preview, { names: 'slow,fast' })))
  expect(resolve).toHaveBeenCalledTimes(2)
  await act(async () => finish.get('fast')!({ fast: 'image-fast' }))
  expect(host.textContent).toContain('image-fast')
  expect(host.textContent).not.toContain('image-slow')
  await act(async () => finish.get('slow')!({ slow: 'image-slow' }))
  expect(host.textContent).toContain('image-slow')
})

it('retries failed images on a later request instead of caching failure', async () => {
  const resolve = vi.fn().mockResolvedValueOnce({ retry: null }).mockResolvedValueOnce({ retry: 'image-retry' })
  vi.stubGlobal('dsGui', { resolvePetThumbnails: resolve })
  await act(async () => root.render(createElement(Preview, { names: 'retry' })))
  await act(async () => preloadPetThumbnails(['retry']))
  expect(resolve).toHaveBeenCalledTimes(2)
  expect(host.textContent).toContain('image-retry')
})
