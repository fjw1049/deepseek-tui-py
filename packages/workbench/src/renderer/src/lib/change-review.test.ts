import { describe, expect, it } from 'vitest'
import { normalizeChangeReviewRequest } from './change-review'

describe('normalizeChangeReviewRequest', () => {
  it('defaults to the current task scope', () => {
    expect(normalizeChangeReviewRequest(undefined)).toEqual({
      scope: 'thread',
      turnId: undefined,
      path: undefined
    })
  })

  it('keeps a valid scope and trims navigation context', () => {
    expect(
      normalizeChangeReviewRequest({ scope: 'turn', turnId: ' turn-1 ', path: ' src/a.ts ' })
    ).toEqual({ scope: 'turn', turnId: 'turn-1', path: 'src/a.ts' })
  })
})
