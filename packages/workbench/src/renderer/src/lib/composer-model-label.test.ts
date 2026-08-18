import { describe, expect, it } from 'vitest'
import { filterComposerModelOptions } from './composer-model-label'

describe('filterComposerModelOptions', () => {
  it('does not keep default DeepSeek ids when the pick list is empty', () => {
    expect(filterComposerModelOptions('', [])).toEqual([])
  })

  it('only shows models from the configured pick list', () => {
    expect(filterComposerModelOptions('', ['kimi/kimi-k3', 'glm/glm-4'])).toEqual([
      'glm/glm-4',
      'kimi/kimi-k3'
    ])
  })

  it('pins default DeepSeek ids only when they appear in the pick list', () => {
    expect(
      filterComposerModelOptions('deepseek-v4-flash', ['kimi/kimi-k3', 'deepseek-v4-flash'])
    ).toEqual(['deepseek-v4-flash', 'kimi/kimi-k3'])
  })
})
