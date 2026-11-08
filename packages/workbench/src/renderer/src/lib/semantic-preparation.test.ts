import { expect, it, vi } from 'vitest'
import type { editor } from 'monaco-editor'
const state = vi.hoisted(() => ({ workers: [] as { onmessage: ((event: { data: Uint32Array }) => void) | null; postMessage: ReturnType<typeof vi.fn>; terminate: ReturnType<typeof vi.fn> }[] }))
vi.mock('monaco-editor', () => ({ languages: {} }))
vi.mock('./semantic-tokens.worker?worker', () => ({ default: class {
  onmessage = null
  onerror = null
  postMessage = vi.fn()
  terminate = vi.fn()
  constructor() { state.workers.push(this) }
} }))
import { prepareSemanticTokens, cancelSemanticPreparation } from './monaco-lexical-semantic-tokens'

it('shares prepared versions, reuses workers, and cancels stale computations', async () => {
  vi.useFakeTimers()
  let version = 1
  const lifecycle = () => ({ dispose: vi.fn() })
  const model = {
    isDisposed: () => false, getLanguageId: () => 'typescript', getVersionId: () => version,
    getValue: () => 'const value = f()', onWillDispose: lifecycle,
    onDidChangeAttached: lifecycle, isAttachedToEditor: () => true
  } as unknown as editor.ITextModel
  const first = prepareSemanticTokens(model)
  expect(prepareSemanticTokens(model)).toBe(first)
  state.workers[0].onmessage!({ data: new Uint32Array([0, 1, 2, 0, 0]) })
  expect((await first)?.data.length).toBe(5)
  version++
  const second = prepareSemanticTokens(model)
  expect(state.workers).toHaveLength(1)
  expect(state.workers[0].postMessage).toHaveBeenCalledTimes(2)
  cancelSemanticPreparation(model)
  expect(await second).toBeNull()
  expect(state.workers[0].terminate).toHaveBeenCalledTimes(1)
  const third = prepareSemanticTokens(model)
  version++
  state.workers[1].onmessage!({ data: new Uint32Array([0, 1, 2, 0, 0]) })
  expect(await third).toBeNull()
  vi.runAllTimers()
  vi.useRealTimers()
})
