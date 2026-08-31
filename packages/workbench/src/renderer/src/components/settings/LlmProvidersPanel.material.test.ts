import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('./LlmProvidersPanel.tsx', import.meta.url), 'utf8')
const stylesheet = readFileSync(new URL('../../index.css', import.meta.url), 'utf8')

describe('LLM provider sheet materials', () => {
  it('uses the shared settings popover for both protocol selectors', () => {
    expect(source.match(/<SettingsSelect\s/g)).toHaveLength(2)
    expect(source).not.toContain('<select')
  })

  it('uses the inset material for every add-model control group', () => {
    expect(
      source.match(
        /className="ds-llm-sheet__add-model ds-llm-sheet__add-model--inset"/g
      )
    ).toHaveLength(3)

    const insetInputRule = stylesheet.match(
      /\.ds-llm-sheet__add-model--inset \.ds-llm-sheet__add-model-input \{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(insetInputRule).toContain('background: transparent;')
  })
})
