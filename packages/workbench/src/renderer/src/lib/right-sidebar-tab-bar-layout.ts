/**
 * Right-sidebar tab strip (editor | changes | terminal | preview).
 *
 * Hide from the left only when chips are about to collide — not eagerly:
 *   1. editor label (icon only)
 *   2. changes label
 *   3. terminal label
 *   4. preview label
 *   5. inactive editor tab
 *   6. inactive changes tab
 *   7. inactive terminal tab
 *   8. inactive preview tab
 * Active tab always stays; its label drops with the left→right ladder.
 *
 * Four labeled CJK pills need ~250px; four icon-only pills ~120px.
 * Breakpoints sit just under those natural widths.
 */

import type { RightSidebarTab } from './right-sidebar-state'

export const RIGHT_SIDEBAR_TAB_ORDER: readonly RightSidebarTab[] = [
  'editor',
  'changes',
  'terminal',
  'preview'
] as const

export type RightSidebarTabBarTier = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8

export type RightSidebarTabBarPlan = {
  visibleTabs: RightSidebarTab[]
  showLabel: Record<RightSidebarTab, boolean>
}

/** Tab-row clientWidth breakpoints (px) — exclusive upper bound for each tier. */
const BP = {
  hideEditorLabel: 268,
  hideChangesLabel: 248,
  hideTerminalLabel: 228,
  hidePreviewLabel: 208,
  hideEditorTab: 148,
  hideChangesTab: 122,
  hideTerminalTab: 98,
  hidePreviewTab: 78
} as const

export function rightSidebarTabBarTierForWidth(
  width: number | null
): RightSidebarTabBarTier {
  if (width == null || !Number.isFinite(width)) return 0
  if (width < BP.hidePreviewTab) return 8
  if (width < BP.hideTerminalTab) return 7
  if (width < BP.hideChangesTab) return 6
  if (width < BP.hideEditorTab) return 5
  if (width < BP.hidePreviewLabel) return 4
  if (width < BP.hideTerminalLabel) return 3
  if (width < BP.hideChangesLabel) return 2
  if (width < BP.hideEditorLabel) return 1
  return 0
}

export function rightSidebarTabBarPlanForWidth(
  width: number | null,
  activeTab: RightSidebarTab
): RightSidebarTabBarPlan {
  const tier = rightSidebarTabBarTierForWidth(width)
  const labelCutoff = Math.min(tier, 4)
  const tabHideCutoff = tier >= 5 ? Math.min(tier - 4, 4) : 0

  const showLabel = {
    editor: labelCutoff < 1,
    changes: labelCutoff < 2,
    terminal: labelCutoff < 3,
    preview: labelCutoff < 4
  } satisfies Record<RightSidebarTab, boolean>

  const visibleTabs = RIGHT_SIDEBAR_TAB_ORDER.filter((tab, index) => {
    if (tab === activeTab) return true
    return index >= tabHideCutoff
  })

  // Guarantee active is present even if order somehow diverges.
  if (!visibleTabs.includes(activeTab)) {
    visibleTabs.unshift(activeTab)
  }

  return { visibleTabs, showLabel }
}

/** Sample width inside each tier — for tests. */
export function rightSidebarTabBarPlanForTier(
  tier: RightSidebarTabBarTier,
  activeTab: RightSidebarTab
): RightSidebarTabBarPlan {
  const sample: Record<RightSidebarTabBarTier, number> = {
    0: BP.hideEditorLabel,
    1: BP.hideEditorLabel - 1,
    2: BP.hideChangesLabel - 1,
    3: BP.hideTerminalLabel - 1,
    4: BP.hidePreviewLabel - 1,
    5: BP.hideEditorTab - 1,
    6: BP.hideChangesTab - 1,
    7: BP.hideTerminalTab - 1,
    8: BP.hidePreviewTab - 1
  }
  return rightSidebarTabBarPlanForWidth(sample[tier], activeTab)
}
