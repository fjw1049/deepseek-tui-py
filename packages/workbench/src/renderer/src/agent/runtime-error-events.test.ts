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

it('stops reconnecting and asks the owner to reload when replay is unavailable', async () => {
  const controller = new AbortController()
  let emit!: (event: SseEventPayload) => void
  const startSse = vi.fn(async (_thread: string, _seq: number, streamId: string) => {
    emit({ streamId, data: { thread_id: 'thread', since_seq: 7, reason: 'legacy_truncated_payload', event: 'stream.resync_required' } })
    return { streamId }
  })
  const sink: ThreadEventSink = {
    onSeq: vi.fn(), onDeltas: vi.fn(), onUserMessage: vi.fn(), onTool: vi.fn(),
    onApproval: vi.fn(), onUserInput: vi.fn(), onUserInputStatus: vi.fn(), onError: vi.fn(),
    onTurnComplete: vi.fn(), onResyncRequired: vi.fn()
  }
  vi.stubGlobal('dsGui', {
    onSseEvent: (handler: typeof emit) => { emit = handler; return () => {} },
    onSseEnd: () => () => {}, onSseError: () => () => {}, stopSse: async () => true, startSse
  })
  // Resolves on its own: the loop must not reconnect to the same gap.
  await new DeepseekRuntimeProvider().subscribeThreadEvents('thread', 7, sink, controller.signal)
  expect(startSse).toHaveBeenCalledTimes(1)
  expect(sink.onResyncRequired).toHaveBeenCalledTimes(1)
  expect(sink.onError).not.toHaveBeenCalled()
})

it('restores full automation reports and their source instead of the truncated summary', async () => {
  const metadata = { source: 'automation_result', run_id: 'run_1' }
  vi.stubGlobal('dsGui', { runtimeRequest: async () => ({ ok: true, body: JSON.stringify({
    thread: { id: 'thread', status: 'idle' }, latest_seq: 2, turns: [],
    items: [{ id: 'report', kind: 'status', summary: '[Daily] truncated...', detail: '[Daily] ## Full report', metadata }]
  }) }) })
  const detail = await new DeepseekRuntimeProvider().getThreadDetail('thread')
  expect(detail.blocks).toContainEqual(expect.objectContaining({ text: '[Daily] ## Full report', automation: metadata }))
})

it('preserves automation metadata for live report delivery', async () => {
  const controller = new AbortController()
  let emit!: (event: SseEventPayload) => void
  const metadata = { source: 'automation_result', run_id: 'run_1' }
  const sink: ThreadEventSink = {
    onSeq: vi.fn(), onDeltas: vi.fn(), onUserMessage: vi.fn(), onTool: vi.fn(),
    onApproval: vi.fn(), onUserInput: vi.fn(), onUserInputStatus: vi.fn(), onError: vi.fn(),
    onSystemStatus: vi.fn(), onTurnComplete: vi.fn(() => controller.abort())
  }
  vi.stubGlobal('dsGui', {
    onSseEvent: (handler: typeof emit) => { emit = handler; return () => {} },
    onSseEnd: () => () => {}, onSseError: () => () => {}, stopSse: async () => true,
    startSse: async (_thread: string, _seq: number, streamId: string) => {
      emit({ streamId, data: { event: 'item.completed', payload: { item: { id: 'report', kind: 'status', detail: '## Full report', metadata } } } })
      emit({ streamId, data: { event: 'turn.completed', payload: { turn: { id: 'turn', thread_id: 'thread', status: 'completed' } } } })
      return { streamId }
    }
  })
  await new DeepseekRuntimeProvider().subscribeThreadEvents('thread', 0, sink, controller.signal)
  expect(sink.onSystemStatus).toHaveBeenCalledWith('## Full report', 'report', undefined, metadata)
})
