import { describe, expect, it } from 'vitest'
import { FileStack } from 'lucide-react'
import { pluginDisplayTitle, pluginVisual } from './plugin-presentation'

describe('document-process identity', () => {
  it('maps the installed plugin ID to its document identity and usage instructions', () => {
    const visual = pluginVisual('document-process')
    expect(visual.icon).toBe(FileStack)
    expect(pluginDisplayTitle('document-process', 'zh')).toBe('文档处理')
    expect(pluginDisplayTitle('document-process', 'en')).toBe('Document Processing')
    expect(visual.detail.zh).toContain('@plugin:document-process')
    expect(visual.detail.en).not.toContain('@plugin:document-skills')
  })
})
