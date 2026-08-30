import { describe, expect, it } from 'vitest'
import {
  composerFooterPlanForWidth,
  composerFooterTierForWidth
} from './composer-footer-layout'

describe('composerFooterPlanForWidth', () => {
  it('keeps full chrome on wide footers', () => {
    expect(composerFooterTierForWidth(640)).toBe(0)
    const plan = composerFooterPlanForWidth(640)
    expect(plan.showContextMeter).toBe(true)
    expect(plan.showApproval).toBe(true)
    expect(plan.showApprovalLabel).toBe(true)
    expect(plan.showEffortTier).toBe(true)
    expect(plan.showModel).toBe(true)
  })

  it('hides context meter before folding approval text', () => {
    expect(composerFooterTierForWidth(460)).toBe(1)
    const plan = composerFooterPlanForWidth(460)
    expect(plan.showContextMeter).toBe(false)
    expect(plan.showApproval).toBe(true)
    expect(plan.showApprovalLabel).toBe(true)
  })

  it('folds active mode and plugin labels before core controls collide', () => {
    const pressured = composerFooterPlanForWidth(640, {
      hasMode: true,
      hasPlugin: true
    })
    expect(pressured.showModeLabel).toBe(false)
    expect(pressured.showPluginLabel).toBe(false)
    expect(pressured.showContextMeter).toBe(true)
    expect(pressured.showApprovalLabel).toBe(true)
    expect(pressured.showModelLabel).toBe(true)
    expect(pressured.showSend).toBe(true)

    const wide = composerFooterPlanForWidth(800, {
      hasMode: true,
      hasPlugin: true
    })
    expect(wide.showModeLabel).toBe(true)
    expect(wide.showPluginLabel).toBe(true)
  })

  it('keeps the approval hand until near collision in chat', () => {
    // Still roomy enough — hand stays (was wrongly gone at 350 before).
    expect(composerFooterPlanForWidth(330).showApproval).toBe(true)
    expect(composerFooterPlanForWidth(330).showEffortTier).toBe(false)

    expect(composerFooterPlanForWidth(270).showApproval).toBe(false)
    expect(composerFooterPlanForWidth(270).showModel).toBe(true)
  })

  it('IDE dense keeps the hand at typical rail footer widths', () => {
    // ~360–400px is common once rail padding is subtracted — hand must stay.
    const plan = composerFooterPlanForWidth(360, { dense: true })
    expect(plan.showApproval).toBe(true)
    expect(plan.showModel).toBe(true)
    expect(plan.showEffortTier).toBe(true)

    // Label folds only when denser still; hand itself waits for near-collision.
    expect(composerFooterPlanForWidth(320, { dense: true }).showApprovalLabel).toBe(false)
    expect(composerFooterPlanForWidth(320, { dense: true }).showApproval).toBe(true)

    expect(composerFooterPlanForWidth(220, { dense: true }).showApproval).toBe(false)
    expect(composerFooterPlanForWidth(220, { dense: true }).showModel).toBe(true)
  })

  it('removes model before voice, plus, and send', () => {
    expect(composerFooterPlanForWidth(240).showModel).toBe(false)
    expect(composerFooterPlanForWidth(240).showVoice).toBe(true)

    expect(composerFooterPlanForWidth(200).showVoice).toBe(false)
    expect(composerFooterPlanForWidth(200).showPlus).toBe(true)

    expect(composerFooterPlanForWidth(160).showPlus).toBe(false)
    expect(composerFooterPlanForWidth(160).showSend).toBe(true)

    expect(composerFooterPlanForWidth(120).showSend).toBe(false)
  })
})
