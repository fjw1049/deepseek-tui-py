// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PetSprite } from './PetSprite'

let root: ReturnType<typeof createRoot>
let host: HTMLDivElement
const frame = (): string => host.querySelector<HTMLElement>('.pet-sprite')!.style.backgroundPosition

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.spyOn(Math, 'random').mockReturnValue(0)
  host = document.createElement('div')
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('plays a one-shot from its first frame and holds the last one', async () => {
  await act(async () => root.render(createElement(PetSprite, { src: 'x', stateId: 'waving' })))
  expect(frame()).toBe('0px -624px')
  await act(async () => vi.advanceTimersByTimeAsync(140))
  expect(frame()).toBe('-192px -624px')
  await act(async () => vi.advanceTimersByTimeAsync(5000))
  expect(frame()).toBe('-576px -624px')
})

it('replays the same state from frame 0 when the play key changes', async () => {
  await act(async () => root.render(createElement(PetSprite, { src: 'x', stateId: 'jumping', playKey: 1 })))
  await act(async () => vi.advanceTimersByTimeAsync(300))
  expect(frame()).not.toBe('0px -832px')
  await act(async () => root.render(createElement(PetSprite, { src: 'x', stateId: 'jumping', playKey: 2 })))
  expect(frame()).toBe('0px -832px')
})

it('rests on the first idle frame between cycles', async () => {
  await act(async () => root.render(createElement(PetSprite, { src: 'x', stateId: 'idle' })))
  await act(async () => vi.advanceTimersByTimeAsync(2400 + 279))
  expect(frame()).toBe('0px 0px')
  await act(async () => vi.advanceTimersByTimeAsync(1))
  expect(frame()).toBe('-192px 0px')
})

it('holds still while paused', async () => {
  await act(async () => root.render(createElement(PetSprite, { src: 'x', stateId: 'running', motionPaused: true })))
  await act(async () => vi.advanceTimersByTimeAsync(5000))
  expect(frame()).toBe('0px -1456px')
})
