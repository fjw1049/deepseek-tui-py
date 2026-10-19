import { readFileSync } from 'fs'
import { describe, expect, it, vi } from 'vitest'
import { localizeDevBrowserScreenshotError } from './dev-browser-screenshot-errors'

describe('localizeDevBrowserScreenshotError', () => {
  const t = vi.fn((key: string) => {
    const labels: Record<string, string> = {
      browserScreenshotNotReady: '页面尚未就绪',
      browserScreenshotTimeout: '截图超时',
      browserScreenshotFailed: '无法复制截图'
    }
    return labels[key] ?? key
  })

  it('maps known server messages to locale keys', () => {
    expect(localizeDevBrowserScreenshotError('Browser tab is not ready.', t)).toBe('页面尚未就绪')
    expect(localizeDevBrowserScreenshotError('Screenshot timed out.', t)).toBe('截图超时')
  })

  it('falls back to the raw message for unknown errors', () => {
    expect(localizeDevBrowserScreenshotError('Custom failure detail.', t)).toBe(
      'Custom failure detail.'
    )
  })
})

it('names only messages both locales define', () => {
  const source = readFileSync(new URL('./dev-browser-screenshot-errors.ts', import.meta.url), 'utf8')
  const keys = [...new Set(source.match(/browserScreenshot[A-Za-z]+/g))]
  for (const locale of ['zh', 'en']) {
    const messages = JSON.parse(readFileSync(new URL(`../locales/${locale}/common.json`, import.meta.url), 'utf8')) as Record<string, string>
    expect(keys.filter(key => !messages[key]), locale).toEqual([])
  }
})
