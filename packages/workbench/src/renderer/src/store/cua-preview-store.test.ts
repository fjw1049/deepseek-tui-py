import { beforeEach, expect, it } from 'vitest'
import type { ToolEventPayload } from '../agent/types'
import {
  cuaCallResult,
  cuaEventFromMailbox,
  dismissEndedCuaPreview,
  hideCuaPreviewForTask,
  markCuaPreviewLive,
  noteCuaCallFinished,
  noteCuaCallStarted,
  noteCuaTurnEnded,
  phaseOnCallStart,
  showCuaPreview,
  restoreCuaPreview,
  useCuaPreviewStore
} from './cua-preview-store'

beforeEach(() => useCuaPreviewStore.setState({ sessions: {}, floating: {} }))

const session = (threadId = 'thread') => useCuaPreviewStore.getState().sessions[threadId]

function started(title?: string): ToolEventPayload {
  return { itemId: 'start', summary: 'cua_js', status: 'running', toolName: 'cua_js',
    meta: title ? { tool_input: { title } } : undefined }
}

function finished(meta: Record<string, unknown>, itemId = 'item-1'): ToolEventPayload {
  return { itemId, summary: 'cua_js: ok', status: 'success', meta: { tool_name: 'cua_js', ...meta } }
}

const shot = (assetId: string, kind = 'cua') => ({ asset_id: assetId, source: { kind } })

it('arms on a live computer-use start only', () => {
  noteCuaCallStarted('thread', null, started())
  noteCuaCallStarted('thread', 'turn', { ...started(), toolName: 'browser_use' })
  noteCuaCallStarted('thread', 'turn', { ...started(), status: 'success' })
  expect(session()).toBeUndefined()
  noteCuaCallStarted('thread', 'turn', started('Open TextEdit'))
  expect(session()).toMatchObject({ phase: 'armed', turnId: 'turn', label: 'Open TextEdit', appId: null })
})

it('follows the app and screenshot each finished call reports', () => {
  noteCuaCallStarted('thread', 'turn', started())
  const revision = session()!.revision
  noteCuaCallFinished('thread', finished({
    cua_surface: { kind: 'app', app_id: 'com.apple.TextEdit' },
    images: [shot('a'.repeat(64)), shot('b'.repeat(64), 'user')],
    tool_input: { title: 'Type the note' }
  }))
  expect(session()).toMatchObject({
    surface: 'app', appId: 'com.apple.TextEdit', label: 'Type the note',
    still: { itemId: 'item-1', assetId: 'a'.repeat(64) }
  })
  // A call that touched nothing keeps the target; the stream still re-checks the window.
  noteCuaCallFinished('thread', finished({}, 'item-2'))
  expect(session()).toMatchObject({ appId: 'com.apple.TextEdit', still: { itemId: 'item-1' } })
  expect(session()!.revision).toBe(revision + 2)
  noteCuaCallFinished('thread', finished({ cua_surface: { kind: 'browser' } }, 'item-3'))
  expect(session()).toMatchObject({ surface: 'browser', appId: null })
})

it('ignores other tools and malformed metadata', () => {
  expect(cuaCallResult(finished({ tool_name: 'browser_use' }))).toBeNull()
  expect(cuaCallResult({ ...finished({}), status: 'running' })).toBeNull()
  expect(cuaCallResult(finished({ cua_surface: { kind: 'desktop', app_id: 'x' }, images: 'no' })))
    .toEqual({ surface: null, appId: null, still: null, label: null })
})

it('a dismissed card stays closed for its task and returns with the next one', () => {
  noteCuaCallStarted('thread', 'turn-1', started())
  markCuaPreviewLive('thread')
  expect(session()!.phase).toBe('live')
  hideCuaPreviewForTask('thread')
  noteCuaCallStarted('thread', 'turn-1', started())
  expect(session()!.phase).toBe('hidden-for-task')
  noteCuaCallStarted('thread', 'turn-2', started())
  expect(session()).toMatchObject({ phase: 'armed', turnId: 'turn-2', still: null })
  expect(phaseOnCallStart('live', true)).toBe('live')
})

it('a finished turn ends the card, which then drops until the next call', () => {
  noteCuaTurnEnded('thread')
  expect(session()).toBeUndefined()
  noteCuaCallStarted('thread', 'turn', started())
  noteCuaTurnEnded('thread')
  expect(session()!.phase).toBe('ended')
  // Late results of the ended turn do not revive it.
  noteCuaCallFinished('thread', finished({ cua_surface: { kind: 'app', app_id: 'x' } }))
  expect(session()!.appId).toBeNull()
  dismissEndedCuaPreview('thread')
  expect(session()).toBeUndefined()
})

it('keeps threads independent', () => {
  noteCuaCallStarted('a', 'turn-a', started())
  noteCuaCallStarted('b', 'turn-b', started())
  hideCuaPreviewForTask('a')
  expect(session('a')!.phase).toBe('hidden-for-task')
  expect(session('b')!.phase).toBe('armed')
})

it('a card dismissed for the task ends closed instead of showing done', () => {
  noteCuaCallStarted('thread', 'turn', started())
  hideCuaPreviewForTask('thread')
  noteCuaTurnEnded('thread')
  expect(session()).toBeUndefined()
})

it('sub-agent computer-use steps drive the parent thread card', () => {
  const step = { agent_id: 'child', step: 2, tool_call_id: 'call-9', tool_name: 'cua_js' }
  const start = cuaEventFromMailbox({ ...step, kind: 'tool_call_started' })!
  noteCuaCallStarted('thread', 'turn', start)
  noteCuaCallFinished('thread', cuaEventFromMailbox({
    ...step, kind: 'tool_call_completed', ok: true,
    cua_surface: { kind: 'app', app_id: 'com.apple.Notes' }
  })!)
  expect(session()).toMatchObject({ phase: 'armed', surface: 'app', appId: 'com.apple.Notes', still: null })
  expect(cuaEventFromMailbox({ ...step, tool_name: 'read_file', kind: 'tool_call_completed' })).toBeNull()
  expect(cuaEventFromMailbox({ ...step, kind: 'progress' })).toBeNull()
})


it('drops a previous surface screenshot and rejects late results from old turns', () => {
  noteCuaCallStarted('thread', 'turn', started())
  noteCuaCallFinished('thread', finished({ cua_surface: { kind: 'app', app_id: 'A' }, images: [shot('a')] }))
  expect(session()!.still).not.toBeNull()
  noteCuaCallFinished('thread', finished({ cua_surface: { kind: 'app', app_id: 'B' } }))
  expect(session()!.still).toBeNull()
  noteCuaCallStarted('thread', 'new-turn', started())
  noteCuaCallFinished('thread', { ...finished({ cua_surface: { kind: 'app', app_id: 'old' } }), turnId: 'turn' })
  expect(session()!.appId).toBeNull()
})

it('allows reopening a hidden preview without restarting its turn', () => {
  noteCuaCallStarted('thread', 'turn', started())
  hideCuaPreviewForTask('thread')
  showCuaPreview('thread')
  expect(session()).toMatchObject({ phase: 'live', turnId: 'turn' })
})

it('keeps the known stop or failure outcome across completion polling', () => {
  noteCuaCallStarted('thread', 'turn', started())
  noteCuaTurnEnded('thread', 'stopped')
  noteCuaTurnEnded('thread')
  expect(session()!.outcome).toBe('stopped')
  noteCuaCallStarted('thread', 'next', started())
  noteCuaTurnEnded('thread', 'failed')
  expect(session()!.outcome).toBe('failed')
})


it('restores a new manual turn instead of keeping the previous ended preview', () => {
  noteCuaCallStarted('thread', 'old', started())
  noteCuaTurnEnded('thread')
  restoreCuaPreview('thread', { used: true, active: true, turn_id: 'manual' })
  expect(session()).toMatchObject({ phase: 'armed', turnId: 'manual', still: null })
  expect(session()!.outcome).toBeUndefined()
  hideCuaPreviewForTask('thread')
  restoreCuaPreview('thread', { used: true, active: true, turn_id: 'manual' })
  expect(session()!.phase).toBe('hidden-for-task')
})
