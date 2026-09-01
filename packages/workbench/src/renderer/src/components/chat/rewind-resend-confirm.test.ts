import { describe, expect, it } from 'vitest'

import {
  rewindPreviewNeedsConfirmation,
  rewindResendConfirmModel
} from './rewind-resend-confirm'

describe('rewindPreviewNeedsConfirmation', () => {
  it.each([
    ['no code impact', [], [], 0, false],
    ['affected files', ['src/a.ts'], [], 0, true],
    ['a missing workspace', [], ['/gone/worktree'], 0, true],
    ['a turn without a checkpoint', [], [], 1, true]
  ] as const)(
    'handles %s',
    (_label, files, missingRoots, noCheckpoint, expected) => {
      expect(rewindPreviewNeedsConfirmation(files, missingRoots, noCheckpoint)).toBe(
        expected
      )
    }
  )
})

describe('rewindResendConfirmModel', () => {
  it.each([
    ['preview succeeds', false, 'preview'],
    ['preview fails', true, 'preview_failed']
  ] as const)('keeps both rewind choices when %s', (_label, previewFailed, body) => {
    expect(rewindResendConfirmModel(previewFailed)).toEqual({
      body,
      actions: ['conversation_only', 'restore_code']
    })
  })
})
