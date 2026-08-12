/**
 * Empty-stage workspace tray (project | Local | branch).
 *
 * Hide from the right so the bar never stacks / clips:
 *   1. branch chevron
 *   2. branch label (icon only)
 *   3. entire branch (+ sep)
 *   4. local label (icon only)
 *   5. entire local (+ sep)
 *   6. project chevron
 * Project chip always stays (label truncates).
 */

export type WorkspaceContextBarTier = 0 | 1 | 2 | 3 | 4 | 5 | 6

export type WorkspaceContextBarPlan = {
  showBranch: boolean
  showBranchLabel: boolean
  showBranchChevron: boolean
  showLocal: boolean
  showLocalLabel: boolean
  showProjectChevron: boolean
}

const BP = {
  hideBranchChevron: 360,
  hideBranchLabel: 310,
  hideBranch: 270,
  hideLocalLabel: 220,
  hideLocal: 180,
  hideProjectChevron: 150
} as const

export function workspaceContextBarTierForWidth(
  width: number | null
): WorkspaceContextBarTier {
  if (width == null || !Number.isFinite(width)) return 0
  if (width < BP.hideProjectChevron) return 6
  if (width < BP.hideLocal) return 5
  if (width < BP.hideLocalLabel) return 4
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
    showLocalLabel: tier < 4,
    showLocal: tier < 5,
    showProjectChevron: tier < 6
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
    4: BP.hideLocalLabel - 1,
    5: BP.hideLocal - 1,
    6: BP.hideProjectChevron - 1
  }
  return workspaceContextBarPlanForWidth(sample[tier])
}
