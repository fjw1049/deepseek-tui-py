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
      showLocal: true,
      showProjectChevron: true
    })
    expect(workspaceContextBarPlanForWidth(400)).toMatchObject({
      showBranch: true,
      showBranchLabel: true,
      showBranchChevron: true,
      showLocal: true,
      showLocalLabel: true,
      showProjectChevron: true
    })
  })

  it('hides from the right as width shrinks', () => {
    expect(workspaceContextBarTierForWidth(350)).toBe(1)
    expect(workspaceContextBarPlanForWidth(350)).toMatchObject({
      showBranchChevron: false,
      showBranchLabel: true,
      showBranch: true
    })

    expect(workspaceContextBarPlanForWidth(300)).toMatchObject({
      showBranchLabel: false,
      showBranch: true,
      showLocal: true
    })

    expect(workspaceContextBarPlanForWidth(260)).toMatchObject({
      showBranch: false,
      showLocal: true,
      showLocalLabel: true
    })

    expect(workspaceContextBarPlanForWidth(200)).toMatchObject({
      showBranch: false,
      showLocalLabel: false,
      showLocal: true
    })

    expect(workspaceContextBarPlanForWidth(170)).toMatchObject({
      showLocal: false,
      showProjectChevron: true
    })

    expect(workspaceContextBarPlanForWidth(140)).toMatchObject({
      showLocal: false,
      showProjectChevron: false
    })
  })

  it('tier helper matches width ladder', () => {
    for (const tier of [0, 1, 2, 3, 4, 5, 6] as const) {
      expect(workspaceContextBarPlanForTier(tier)).toEqual(
        workspaceContextBarPlanForWidth(
          [360, 359, 309, 269, 219, 179, 149][tier]
        )
      )
    }
  })
})
