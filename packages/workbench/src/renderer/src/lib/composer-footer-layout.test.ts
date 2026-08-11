import { describe, expect, it } from 'vitest'
import {
  composerFooterPlanForWidth,
  composerFooterTierForWidth
} from './composer-footer-layout'

describe('composerFooterPlanForWidth', () => {
  it('keeps labels on typical chat widths and folds only when tight', () => {
    expect(composerFooterTierForWidth(640)).toBe(0)
    expect(composerFooterPlanForWidth(640).showModelLabel).toBe(true)
    expect(composerFooterPlanForWidth(640).showContextMeter).toBe(true)

    expect(composerFooterTierForWidth(480)).toBe(1)
    expect(composerFooterPlanForWidth(480).showModelLabel).toBe(true)
    expect(composerFooterPlanForWidth(480).showContextMeter).toBe(false)

    expect(composerFooterTierForWidth(340)).toBe(2)
    expect(composerFooterPlanForWidth(340).showModelLabel).toBe(false)
    expect(composerFooterPlanForWidth(340).showApprovalLabel).toBe(true)
  })
})
