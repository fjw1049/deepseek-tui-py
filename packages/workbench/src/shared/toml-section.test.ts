import { describe, expect, it } from 'vitest'
import { upsertTomlSections } from './toml-section'

describe('upsertTomlSections', () => {
  it('writes typed values into nested sections', () => {
    const next = upsertTomlSections(
      '[memory]\nenabled = false\nmode = "manual"\n',
      {
        memory: {
          enabled: true,
          mode: 'hybrid'
        },
        'memory.smart': {
          enabled: true,
          recall_limit: 8,
          recall_score_threshold: 0.3,
          capture_enabled: false
        }
      }
    )

    expect(next).toContain('[memory]')
    expect(next).toContain('enabled = true')
    expect(next).toContain('mode = "hybrid"')
    expect(next).toContain('[memory.smart]')
    expect(next).toContain('recall_limit = 8')
    expect(next).toContain('recall_score_threshold = 0.3')
    expect(next).toContain('capture_enabled = false')
  })
})
