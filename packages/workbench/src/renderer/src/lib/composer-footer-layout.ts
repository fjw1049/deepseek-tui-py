/**
 * Progressive footer degradation — same ladder for main chat and IDE rail.
 *
 * Hide / compact only when controls are about to collide — not eagerly.
 *
 * Order as width shrinks:
 *   1. active mode / plugin labels → icon only
 *   2. context meter
 *   3. approval label → icon only
 *   4. model reasoning effort tier
 *   5. approval control entirely (the hand) — before model name
 *   6. entire model picker
 *   7. voice
 *   8. plus menu
 *   9. send (last)
 */

export type ComposerFooterTier = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8

export type ComposerFooterPlan = {
  showContextMeter: boolean
  /** Entire approval / permissions control (hand). */
  showApproval: boolean
  showApprovalLabel: boolean
  showModeLabel: boolean
  showPluginLabel: boolean
  /** Model name on the pill (when the picker itself is still shown). */
  showModelLabel: boolean
  /** Effort tier text on the pill (Light / High / Ultra…). */
  showEffortTier: boolean
  /** Entire model / reasoning selector. */
  showModel: boolean
  showVoice: boolean
  showPlus: boolean
  showSend: boolean
}

export type ComposerFooterLayoutOptions = {
  /**
   * IDE rail uses denser (smaller) controls, so the same clientWidth still has
   * room — shift every breakpoint down and only strip chrome near collision.
   */
  dense?: boolean
  /** Optional badges currently rendered in the left cluster. */
  hasMode?: boolean
  hasPlugin?: boolean
}

type Breakpoints = {
  hideMeter: number
  iconOnly: number
  hideEffort: number
  hideApproval: number
  hideModel: number
  hideVoice: number
  hidePlus: number
  hideSend: number
}

/** Main chat — roomy 36px controls. */
const CHAT_BP: Breakpoints = {
  hideMeter: 500,
  iconOnly: 420,
  hideEffort: 340,
  hideApproval: 280,
  hideModel: 250,
  hideVoice: 210,
  hidePlus: 170,
  hideSend: 130
}

/**
 * IDE dense — 28px controls + padded rail. Footer clientWidth is already
 * smaller than the rail; keep the hand until it is truly about to collide.
 */
const DENSE_BP: Breakpoints = {
  hideMeter: 400,
  iconOnly: 340,
  hideEffort: 290,
  hideApproval: 230,
  hideModel: 200,
  hideVoice: 170,
  hidePlus: 145,
  hideSend: 120
}

const OPTIONAL_LABEL_SPACE = {
  chat: { mode: 72, plugin: 144 },
  dense: { mode: 56, plugin: 112 }
} as const

function breakpointsFor(options?: ComposerFooterLayoutOptions): Breakpoints {
  return options?.dense ? DENSE_BP : CHAT_BP
}

function hasRoomForOptionalLabels(
  width: number | null,
  options?: ComposerFooterLayoutOptions
): boolean {
  if (!options?.hasMode && !options?.hasPlugin) return true
  if (width == null || !Number.isFinite(width)) return false

  const bp = breakpointsFor(options)
  const space = options?.dense ? OPTIONAL_LABEL_SPACE.dense : OPTIONAL_LABEL_SPACE.chat
  const reservedLabelWidth =
    (options?.hasMode ? space.mode : 0) + (options?.hasPlugin ? space.plugin : 0)
  return width >= bp.hideMeter + reservedLabelWidth
}

export function composerFooterTierForWidth(
  width: number | null,
  options?: ComposerFooterLayoutOptions
): ComposerFooterTier {
  if (width == null || !Number.isFinite(width)) return 0
  const bp = breakpointsFor(options)
  if (width < bp.hideSend) return 8
  if (width < bp.hidePlus) return 7
  if (width < bp.hideVoice) return 6
  if (width < bp.hideModel) return 5
  if (width < bp.hideApproval) return 4
  if (width < bp.hideEffort) return 3
  if (width < bp.iconOnly) return 2
  if (width < bp.hideMeter) return 1
  return 0
}

export function composerFooterPlanForWidth(
  width: number | null,
  options?: ComposerFooterLayoutOptions
): ComposerFooterPlan {
  const tier = composerFooterTierForWidth(width, options)
  const showOptionalLabels = tier < 2 && hasRoomForOptionalLabels(width, options)
  return {
    showContextMeter: tier < 1,
    showApprovalLabel: tier < 2,
    showModeLabel: tier < 2 && (!options?.hasMode || showOptionalLabels),
    showPluginLabel: tier < 2 && (!options?.hasPlugin || showOptionalLabels),
    showEffortTier: tier < 3,
    // Hand goes away before the model name / picker — but only when cramped.
    showApproval: tier < 4,
    showModelLabel: tier < 5,
    showModel: tier < 5,
    showVoice: tier < 6,
    showPlus: tier < 7,
    showSend: tier < 8
  }
}

/** Sample width inside each tier — for tests / callers that only have a tier. */
export function composerFooterPlanForTier(
  tier: ComposerFooterTier,
  options?: ComposerFooterLayoutOptions
): ComposerFooterPlan {
  const bp = breakpointsFor(options)
  const sample: Record<ComposerFooterTier, number> = {
    0: bp.hideMeter,
    1: bp.hideMeter - 1,
    2: bp.iconOnly - 1,
    3: bp.hideEffort - 1,
    4: bp.hideApproval - 1,
    5: bp.hideModel - 1,
    6: bp.hideVoice - 1,
    7: bp.hidePlus - 1,
    8: bp.hideSend - 1
  }
  return composerFooterPlanForWidth(sample[tier], options)
}
