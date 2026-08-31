import { describe, expect, it } from 'vitest'
import { normalizeChangeReviewRequest } from './change-review'

describe('normalizeChangeReviewRequest', () => {
  it('defaults to the current working tree', () => {
    expect(normalizeChangeReviewRequest(undefined)).toEqual({
      context: 'working-tree',
      turnId: undefined,
      path: undefined,
      workspaceRoot: undefined
    })
  })

  it('keeps a valid context and trims navigation context', () => {
    expect(
      normalizeChangeReviewRequest({
        context: 'last-turn',
        turnId: ' turn-1 ',
        path: ' src/a.ts ',
        workspaceRoot: ' /repo '
      })
    ).toEqual({
      context: 'last-turn',
      turnId: 'turn-1',
      path: 'src/a.ts',
      workspaceRoot: '/repo'
    })
  })
})
