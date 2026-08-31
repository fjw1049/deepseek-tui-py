export type RewindResendConfirmAction = 'conversation_only' | 'restore_code'

/** A preview needs an explicit choice whenever code restore may be incomplete. */
export function rewindPreviewNeedsConfirmation(
  files: readonly string[],
  missingRoots: readonly string[],
  noCheckpoint: number
): boolean {
  return files.length > 0 || missingRoots.length > 0 || noCheckpoint > 0
}

/** Preview availability changes the explanation, never the user's two safe choices. */
export function rewindResendConfirmModel(previewFailed: boolean): {
  body: 'preview' | 'preview_failed'
  actions: readonly RewindResendConfirmAction[]
} {
  return {
    body: previewFailed ? 'preview_failed' : 'preview',
    actions: ['conversation_only', 'restore_code']
  }
}
