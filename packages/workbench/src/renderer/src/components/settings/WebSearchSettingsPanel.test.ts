import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { defaultWebSearchSettings, type AppSettingsV1 } from '@shared/app-settings'
import { WebSearchSettingsPanel } from './WebSearchSettingsPanel'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

describe('WebSearchSettingsPanel', () => {
  it('renders sortable providers without extra controls or explanations', () => {
    const webSearch = defaultWebSearchSettings()
    const html = renderToStaticMarkup(createElement(WebSearchSettingsPanel, {
      form: { webSearch } as AppSettingsV1, onUpdate: vi.fn()
    }))
    expect(html).toContain('webSearchProviderDeepseek')
    expect(html).not.toContain('webSearchDeepseekKeyHint')
    expect(html).not.toContain('webFetchProvider')
    expect(html.match(/type="password"/g)).toHaveLength(3)
    expect(html.match(/role="switch"/g)).toHaveLength(3)
  })
})
