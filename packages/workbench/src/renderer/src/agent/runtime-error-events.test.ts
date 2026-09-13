// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import type { SseEventPayload } from '@shared/ds-gui-api'
import type { ThreadEventSink } from './types'
import { DeepseekRuntimeProvider } from './deepseek-runtime'

afterEach(() => vi.unstubAllGlobals())

it('keeps ordinary status informational and marks failed completion as failed', async () => {
  const controller = new AbortController()
  let emit!: (event: SseEventPayload) => void
  const sink: ThreadEventSink = {
    onSeq: vi.fn(), onDeltas: vi.fn(), onUserMessage: vi.fn(), onTool: vi.fn(),
    onApproval: vi.fn(), onUserInput: vi.fn(), onUserInputStatus: vi.fn(), onError: vi.fn(),
    onSystemStatus: vi.fn(), onTurnComplete: vi.fn(() => controller.abort())
  }
  vi.stubGlobal('dsGui', {
    onSseEvent: (handler: typeof emit) => { emit = handler; return () => {} },
    onSseEnd: () => () => {}, onSseError: () => () => {}, stopSse: async () => true,
    startSse: async (_thread: string, _seq: number, streamId: string) => {
      emit({ streamId, data: { event: 'item.completed', payload: { item: { id: 'status', kind: 'status', detail: 'Preparing' } } } })
      emit({ streamId, data: { event: 'turn.completed', payload: { turn: { id: 'turn', thread_id: 'thread', status: 'failed', error: 'Rate limited' } } } })
      return { streamId }
    }
  })
  await new DeepseekRuntimeProvider().subscribeThreadEvents('thread', 0, sink, controller.signal)
  expect(sink.onSystemStatus).toHaveBeenCalledWith('Preparing', 'status')
  expect(sink.onSystemStatus).toHaveBeenCalledWith('Rate limited', 'turn-error-turn', 'error')
  expect(sink.onTurnComplete).toHaveBeenCalledWith(expect.objectContaining({ status: 'failed' }))
})

it('preserves a turn-level failure when the conversation is reloaded', async () => {
  vi.stubGlobal('dsGui', { runtimeRequest: async () => ({ ok: true, body: JSON.stringify({
    thread: { id: 'thread', status: 'idle' }, latest_seq: 2,
    turns: [{ id: 'turn', status: 'failed', error: 'Rate limited' }],
    items: [{ id: 'message', turn_id: 'turn', kind: 'user_message', detail: 'Hello' }]
  }) }) })
  const detail = await new DeepseekRuntimeProvider().getThreadDetail('thread')
  expect(detail.latestTurnOutcome).toBe('failed')
  expect(detail.blocks).toContainEqual(expect.objectContaining({ text: 'Rate limited', severity: 'error' }))
})
