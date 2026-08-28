// @vitest-environment happy-dom

/** Workbench runtime client helpers — user-input parsing regressions. */

import { describe, expect, it, vi } from 'vitest'

import { DeepseekRuntimeProvider } from './deepseek-runtime'

// Mirror the production helper so we can lock the contract without exporting it.
function readUserInputQuestions(value: unknown) {
  if (!value) return null
  const rawQuestions = Array.isArray(value)
    ? value
    : typeof value === 'object'
      ? (value as Record<string, unknown>).questions
      : null
  if (!Array.isArray(rawQuestions) || rawQuestions.length === 0) return null
  const questions = []
  for (const rawQuestion of rawQuestions) {
    if (!rawQuestion || typeof rawQuestion !== 'object') return null
    const q = rawQuestion as Record<string, unknown>
    const rawOptions = q.options
    if (!Array.isArray(rawOptions) || rawOptions.length === 0) return null
    const options = rawOptions
      .map((rawOption) => {
        if (!rawOption || typeof rawOption !== 'object') return null
        const opt = rawOption as Record<string, unknown>
        const label = typeof opt.label === 'string' ? opt.label.trim() : ''
        const description = typeof opt.description === 'string' ? opt.description.trim() : ''
        if (!label) return null
        return { label, description: description || label }
      })
      .filter(Boolean)
    const header = typeof q.header === 'string' ? q.header.trim() : ''
    const id = typeof q.id === 'string' ? q.id.trim() : ''
    const question = typeof q.question === 'string' ? q.question.trim() : ''
    if (!header || !id || !question || options.length === 0) return null
    questions.push({ header, id, question, options })
  }
  return questions
}

describe('readUserInputQuestions', () => {
  const sample = [
    {
      header: 'Pick',
      id: 'q1',
      question: 'Continue?',
      options: [{ label: 'Yes', description: 'Option A' }]
    }
  ]

  it('accepts bare question arrays from pending API / SSE', () => {
    expect(readUserInputQuestions(sample)).toEqual([
      {
        header: 'Pick',
        id: 'q1',
        question: 'Continue?',
        options: [{ label: 'Yes', description: 'Option A' }]
      }
    ])
  })

  it('accepts wrapped tool.input objects', () => {
    expect(readUserInputQuestions({ questions: sample })).toHaveLength(1)
  })

  it('falls back description to label when empty', () => {
    const bare = [
      {
        header: 'Pick',
        id: 'q1',
        question: 'Continue?',
        options: [{ label: 'Yes', description: '' }]
      }
    ]
    expect(readUserInputQuestions(bare)?.[0]?.options[0]?.description).toBe('Yes')
  })
})

describe('thread creation title', () => {
  it('sends the query-derived title in the atomic create request', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      body: JSON.stringify({
        id: 'thr_query',
        title: '修复会话标题',
        created_at: '2026-08-28T10:00:00Z',
        updated_at: '2026-08-28T10:00:00Z',
        model: 'deepseek-chat',
        mode: 'agent',
        workspace: '/project'
      })
    })
    Object.defineProperty(window, 'dsGui', {
      configurable: true,
      value: {
        getSettings: vi.fn().mockResolvedValue({
          deepseek: { approvalPolicy: 'never' }
        }),
        runtimeRequest
      }
    })

    await new DeepseekRuntimeProvider().createThread({
      workspace: '/project',
      title: '修复会话标题'
    })

    expect(runtimeRequest).toHaveBeenCalledTimes(1)
    expect(runtimeRequest).toHaveBeenCalledWith(
      '/v1/threads',
      'POST',
      expect.stringContaining('"title":"修复会话标题"')
    )
  })
})

describe('rewind result compatibility', () => {
  it('reads the additive rewind_result while preserving the old thread envelope', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      body: JSON.stringify({
        id: 'thr_1',
        title: 'Thread',
        rewind_result: {
          restore_files: true,
          restored_files: ['src/a.ts'],
          merged_files: ['src/b.ts'],
          conflicted_files: ['src/c.ts'],
          skipped_files: ['asset.bin'],
          missing_roots: ['/gone/worktree']
        }
      })
    })
    Object.defineProperty(window, 'dsGui', {
      configurable: true,
      value: { runtimeRequest }
    })

    const result = await new DeepseekRuntimeProvider().rewindThread(
      'thr_1',
      'item_1',
      true
    )

    expect(result).toEqual({
      restoreFiles: true,
      restoredFiles: ['src/a.ts'],
      mergedFiles: ['src/b.ts'],
      conflictedFiles: ['src/c.ts'],
      skippedFiles: ['asset.bin'],
      missingRoots: ['/gone/worktree']
    })
  })

  it('accepts an older runtime response without rewind_result', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      body: JSON.stringify({ id: 'thr_legacy', title: 'Legacy thread' })
    })
    Object.defineProperty(window, 'dsGui', {
      configurable: true,
      value: { runtimeRequest }
    })

    await expect(
      new DeepseekRuntimeProvider().rewindThread('thr_legacy', 'item_1', true)
    ).resolves.toBeNull()
  })
})

describe('thread deletion safety', () => {
  it('only opts into discarding unpublished worktree code explicitly', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({ ok: true, body: '' })
    Object.defineProperty(window, 'dsGui', {
      configurable: true,
      value: { runtimeRequest }
    })
    const provider = new DeepseekRuntimeProvider()

    await provider.deleteThread('thr_safe')
    await provider.deleteThread('thr_forced', { discardUnpublished: true })

    expect(runtimeRequest).toHaveBeenNthCalledWith(
      1,
      '/v1/threads/thr_safe',
      'DELETE'
    )
    expect(runtimeRequest).toHaveBeenNthCalledWith(
      2,
      '/v1/threads/thr_forced?discard_unpublished=true',
      'DELETE'
    )
  })
})

describe('isolated draft apply result', () => {
  it('preserves queued state instead of treating HTTP 202 as applied', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      body: JSON.stringify({
        status: 'queued',
        blocking_thread_id: 'thr_busy',
        thread: {
          id: 'thr_draft',
          created_at: '2026-08-28T00:00:00Z',
          updated_at: '2026-08-28T00:01:00Z',
          model: 'deepseek-chat',
          mode: 'agent',
          workspace: '/repo',
          env_mode: 'worktree',
          worktree_path: '/managed/thr_draft',
          publish_pending: true,
          publish_request_action: 'apply',
          publish_waiting_on: 'thr_busy',
          publish_blocked: false,
          publish_conflicts: []
        }
      })
    })
    Object.defineProperty(window, 'dsGui', {
      configurable: true,
      value: { runtimeRequest }
    })

    const result = await new DeepseekRuntimeProvider().resolvePublishConflicts(
      'thr_draft',
      'apply'
    )

    expect(result.status).toBe('queued')
    expect(result.blockingThreadId).toBe('thr_busy')
    expect(result.thread).toMatchObject({
      envMode: 'worktree',
      publishPending: true,
      publishRequestAction: 'apply',
      publishWaitingOn: 'thr_busy'
    })
  })
})
