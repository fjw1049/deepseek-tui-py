import { describe, expect, it } from 'vitest'
import {
  workspaceContextBarPlanForTier,
  workspaceContextBarPlanForWidth,
  workspaceContextBarTierForWidth
} from './workspace-context-bar-layout'

describe('workspaceContextBarPlanForWidth', () => {
  it('keeps everything when wide or unknown', () => {
    expect(workspaceContextBarPlanForWidth(null)).toMatchObject({
      showBranch: true,
      showBranchLabel: true,
      showEnv: true
    })
    expect(workspaceContextBarPlanForWidth(400)).toMatchObject({
      showBranch: true,
      showBranchLabel: true,
      showEnv: true
    })
  })

  it('hides from the right as width shrinks', () => {
    expect(workspaceContextBarTierForWidth(300)).toBe(1)
    expect(workspaceContextBarPlanForWidth(300)).toMatchObject({
      showBranchLabel: false,
      showBranch: true
    })

    expect(workspaceContextBarPlanForWidth(200)).toMatchObject({
      showBranch: false,
      showEnv: true
    })

    expect(workspaceContextBarPlanForWidth(180)).toMatchObject({
      showBranch: false,
      showEnv: false
    })
  })

  it('tier helper matches width ladder', () => {
    for (const tier of [0, 1, 2, 3] as const) {
      expect(workspaceContextBarPlanForTier(tier)).toEqual(
        workspaceContextBarPlanForWidth([310, 309, 219, 189][tier])
      )
    }
  })
})
