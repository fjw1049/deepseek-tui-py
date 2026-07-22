import { describe, expect, it } from 'vitest'
import { modelIconMatchText, resolveProviderIconBrand } from './provider-icon-match'

describe('resolveProviderIconBrand', () => {
  it('does not treat endpoint name zhipu as the model brand', () => {
    expect(
      resolveProviderIconBrand({
        providerId: 'zhipu',
        id: 'zhipu::kimi-k2.7-code',
        label: 'zhipu/kimi-k2.7-code'
      })
    ).toBe('kimi')

    expect(
      resolveProviderIconBrand({
        providerId: 'zhipu',
        id: 'zhipu::minimax-m3',
        label: 'zhipu/minimax-m3'
      })
    ).toBe('minimax')

    expect(
      resolveProviderIconBrand({
        providerId: 'zhipu',
        id: 'zhipu::deepseek-v4-flash',
        label: 'zhipu/deepseek-v4-flash'
      })
    ).toBe('deepseek')

    expect(
      resolveProviderIconBrand({
        providerId: 'zhipu',
        id: 'zhipu::doubao-seed-2.0-code',
        label: 'zhipu/doubao-seed-2.0-code'
      })
    ).toBe('doubao')
  })

  it('still maps real GLM model ids under a zhipu endpoint', () => {
    expect(
      resolveProviderIconBrand({
        providerId: 'zhipu',
        id: 'zhipu::glm-5.2',
        label: 'zhipu/glm-5.2'
      })
    ).toBe('glm')
  })

  it('matches model tokens only in modelIconMatchText', () => {
    expect(
      modelIconMatchText({
        id: 'zhipu::kimi-k2.7-code',
        label: 'zhipu/kimi-k2.7-code'
      })
    ).toBe('kimi-k2.7-code kimi-k2.7-code')
  })
})
