/**
 * Empty-stage workspace tray (project | branch).
 *
 * Hide from the right so the bar never stacks / clips:
 *   1. branch chevron
 *   2. branch label (icon only)
 *   3. entire branch (+ sep)
 *   4. project chevron
 * Project chip always stays (label truncates).
 */

export type WorkspaceContextBarTier = 0 | 1 | 2 | 3 | 4

export type WorkspaceContextBarPlan = {
  showBranch: boolean
  showBranchLabel: boolean
  showBranchChevron: boolean
  showProjectChevron: boolean
}

const BP = {
  hideBranchChevron: 360,
  hideBranchLabel: 310,
  hideBranch: 220,
  hideProjectChevron: 150
} as const

export function workspaceContextBarTierForWidth(
  width: number | null
): WorkspaceContextBarTier {
  if (width == null || !Number.isFinite(width)) return 0
  if (width < BP.hideProjectChevron) return 4
  if (width < BP.hideBranch) return 3
  if (width < BP.hideBranchLabel) return 2
  if (width < BP.hideBranchChevron) return 1
  return 0
}

export function workspaceContextBarPlanForWidth(
  width: number | null
): WorkspaceContextBarPlan {
  const tier = workspaceContextBarTierForWidth(width)
  return {
    showBranchChevron: tier < 1,
    showBranchLabel: tier < 2,
    showBranch: tier < 3,
    showProjectChevron: tier < 4
  }
}

/** Sample width inside each tier — for tests. */
export function workspaceContextBarPlanForTier(
  tier: WorkspaceContextBarTier
): WorkspaceContextBarPlan {
  const sample: Record<WorkspaceContextBarTier, number> = {
    0: BP.hideBranchChevron,
    1: BP.hideBranchChevron - 1,
    2: BP.hideBranchLabel - 1,
    3: BP.hideBranch - 1,
    4: BP.hideProjectChevron - 1
  }
  return workspaceContextBarPlanForWidth(sample[tier])
}
