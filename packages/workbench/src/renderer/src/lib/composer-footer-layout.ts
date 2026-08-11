/**
 * Progressive footer degradation for narrow chat composers.
 *
 * Never hide send / voice — those stay in a shrink-0 action cluster.
 * Meter, model name, approval/mode/plugin labels may compact.
 */

export type ComposerFooterTier = 0 | 1 | 2

export type ComposerFooterPlan = {
  showContextMeter: boolean
  /** Model pill shows provider icon + effort; name only when room. */
  showModelLabel: boolean
  showApprovalLabel: boolean
  showModeLabel: boolean
  showPluginLabel: boolean
}

/** Breakpoints (footer clientWidth). Wider → richer chrome. */
const TIER1_HIDE_METER = 520
const TIER2_FOLD_LABELS = 360

export function composerFooterTierForWidth(width: number | null): ComposerFooterTier {
  if (width == null || !Number.isFinite(width)) return 0
  if (width < TIER2_FOLD_LABELS) return 2
  if (width < TIER1_HIDE_METER) return 1
  return 0
}

export function composerFooterPlanForWidth(width: number | null): ComposerFooterPlan {
  const tier = composerFooterTierForWidth(width)
  return {
    showContextMeter: tier < 1,
    showModelLabel: tier < 2,
    // Keep approval text even in the tightest tier — short label fills the
    // empty flex gap next to the bolt better than icon-only chrome.
    showApprovalLabel: true,
    showModeLabel: tier < 2,
    showPluginLabel: tier < 2
  }
}

export function composerFooterPlanForTier(tier: ComposerFooterTier): ComposerFooterPlan {
  return composerFooterPlanForWidth(
    tier === 0 ? TIER1_HIDE_METER : tier === 1 ? TIER1_HIDE_METER - 1 : TIER2_FOLD_LABELS - 1
  )
}
