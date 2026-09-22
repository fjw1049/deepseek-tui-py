/**
 * Empty-stage workspace tray (project | env | branch).
 *
 * Chevrons are always hidden (each picker passes `hideChevron`).
 * Hide from the right so the bar never stacks / clips:
 *   1. branch label (icon only)
 *   2. entire branch (+ sep)
 *   3. env picker
 * Project chip always stays (label truncates).
 */

export type WorkspaceContextBarTier = 0 | 1 | 2 | 3

export type WorkspaceContextBarPlan = {
  showBranch: boolean
  showBranchLabel: boolean
  showEnv: boolean
}

const BP = {
  hideBranchLabel: 310,
  hideBranch: 220,
  hideEnv: 190
} as const

export function workspaceContextBarTierForWidth(
  width: number | null
): WorkspaceContextBarTier {
  if (width == null || !Number.isFinite(width)) return 0
  if (width < BP.hideEnv) return 3
  if (width < BP.hideBranch) return 2
  if (width < BP.hideBranchLabel) return 1
  return 0
}

export function workspaceContextBarPlanForWidth(
  width: number | null
): WorkspaceContextBarPlan {
  const tier = workspaceContextBarTierForWidth(width)
  return {
    showBranchLabel: tier < 1,
    showBranch: tier < 2,
    showEnv: tier < 3
  }
}

/** Sample width inside each tier — for tests. */
export function workspaceContextBarPlanForTier(
  tier: WorkspaceContextBarTier
): WorkspaceContextBarPlan {
  const sample: Record<WorkspaceContextBarTier, number> = {
    0: BP.hideBranchLabel,
    1: BP.hideBranchLabel - 1,
    2: BP.hideBranch - 1,
    3: BP.hideEnv - 1
  }
  return workspaceContextBarPlanForWidth(sample[tier])
}
