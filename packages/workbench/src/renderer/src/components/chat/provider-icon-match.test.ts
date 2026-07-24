import { describe, expect, it } from 'vitest'
import {
  modelIconMatchText,
  modelIconPrefixText,
  resolveProviderIconBrand
} from './provider-icon-match'

describe('resolveProviderIconBrand', () => {
  it('does not treat endpoint name zhipu as the model brand when model identifies another vendor', () => {
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

  it('falls back to label/id prefix when the short model token has no brand', () => {
    expect(
      resolveProviderIconBrand({
        providerId: 'kimi',
        id: 'kimi::k3',
        label: 'kimi/k3'
      })
    ).toBe('kimi')

    expect(
      resolveProviderIconBrand({
        providerId: 'moonshot',
        id: 'moonshot::k3',
        label: 'kimi/k3'
      })
    ).toBe('kimi')
  })

  it('uses endpoint prefix only after the model token fails', () => {
    // Unknown model under a zhipu-named endpoint → prefix fallback to glm.
    expect(
      resolveProviderIconBrand({
        providerId: 'zhipu',
        id: 'zhipu::totally-custom-42',
        label: 'zhipu/totally-custom-42'
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

  it('extracts prefixes for the fallback pass', () => {
    expect(
      modelIconPrefixText({
        id: 'kimi::k3',
        label: 'kimi/k3'
      })
    ).toBe('kimi kimi')
  })
})
