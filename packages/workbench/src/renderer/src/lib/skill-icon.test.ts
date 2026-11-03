import { expect, it } from 'vitest'
import { skillIcon } from './skill-icon'

it('keeps a skill icon stable across capitalization and surrounding whitespace', () => {
  expect(skillIcon('humanizer-zh')).toBe(skillIcon(' Humanizer-ZH '))
})

it('varies icons across the visible skill list', () => {
  const names = ['prompt-master', 'slack-gif-creator', 'strategy-comm', 'telesales-qc',
    'webapp-testing', 'xlsx', 'analyze-agent-intervention-data', 'hatch-pet', 'office-documents']
  expect(new Set(names.map(skillIcon)).size).toBeGreaterThanOrEqual(6)
})
