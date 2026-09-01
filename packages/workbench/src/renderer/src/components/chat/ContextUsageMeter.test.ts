// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ContextUsageMeter } from './ContextUsageMeter'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => {
      if (key === 'contextUsageIdle') return 'context —'
      if (key === 'contextUsageLabel') {
        return `context ${values?.used} / ${values?.max} (${values?.percent}%)`
      }
      return key
    }
  })
}))

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

function renderMeter(
  root: Root,
  props: {
    hasActiveThread: boolean
    threadId?: string | null
  }
): void {
  root.render(
    createElement(ContextUsageMeter, {
      blocks: [],
      model: 'deepseek-chat',
      ...props
    })
  )
}

describe('ContextUsageMeter', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('shows the estimated system baseline before a thread exists', async () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => renderMeter(root, { hasActiveThread: false }))

    const button = container.querySelector('button')
    expect(button?.disabled).toBe(false)
    expect(button?.getAttribute('aria-label')).toBe('context 8.4k / 1.0M (1%)')
    expect(button?.querySelectorAll('circle')).toHaveLength(2)

    await act(async () => root.unmount())
  })

  it('keeps every non-zero category visible at very low usage', async () => {
    ;(window as unknown as { dsGui: unknown }).dsGui = {
      runtimeRequest: vi.fn().mockResolvedValue({
        ok: true,
        body: JSON.stringify({
          system_prompt: 600,
          tool_definitions: 7800,
          tools: 7801,
          mcp: 1,
          skills: 1,
          rules: 1,
          conversation: 1,
          total: 8404,
          window: 1_000_000,
          free: 991_596
        })
      })
    }

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      renderMeter(root, { hasActiveThread: true, threadId: 'thread-a' })
    })
    await vi.waitFor(() => {
      expect(container.querySelector('button')?.getAttribute('aria-label')).toBe(
        'context 8.4k / 1.0M (1%)'
      )
    })

    await act(async () => {
      container.querySelector('button')?.click()
    })

    const segmentGroup = document.body.querySelector<HTMLElement>(
      '.ds-context-usage-bar__segments'
    )
    const segments = document.body.querySelectorAll<HTMLElement>(
      '.ds-context-usage-bar__segment'
    )
    expect(segmentGroup?.style.minWidth).toBe('17px')
    expect(segments).toHaveLength(6)
    expect(Array.from(segments).every((segment) => segment.style.minWidth === '2px')).toBe(true)

    await act(async () => root.unmount())
  })

  it('does not retain another thread breakdown when the next request fails', async () => {
    const runtimeRequest = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        body: JSON.stringify({
          system_prompt: 20_000,
          tools: 20_000,
          conversation: 60_000,
          total: 100_000,
          window: 1_000_000,
          free: 900_000
        })
      })
      .mockResolvedValueOnce({ ok: false, body: '' })
    ;(window as unknown as { dsGui: unknown }).dsGui = { runtimeRequest }

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      renderMeter(root, { hasActiveThread: true, threadId: 'thread-a' })
    })
    await vi.waitFor(() => {
      expect(container.querySelector('button')?.getAttribute('aria-label')).toBe(
        'context 100.0k / 1.0M (10%)'
      )
    })

    await act(async () => {
      renderMeter(root, { hasActiveThread: true, threadId: 'thread-b' })
    })
    await vi.waitFor(() => {
      expect(container.querySelector('button')?.getAttribute('aria-label')).toBe(
        'context 8.4k / 1.0M (1%)'
      )
    })

    await act(async () => root.unmount())
  })
})
