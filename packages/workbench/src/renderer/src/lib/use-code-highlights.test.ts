// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useCodeHighlights } from './use-code-highlights'

const { highlight } = vi.hoisted(() => ({ highlight: vi.fn() }))
vi.mock('../components/chat/SharedCodeBlock', () => ({ highlightCodeHtml: highlight }))

function Probe({ code, language = 'typescript' }: { code: string; language?: string }) {
  const lines = useCodeHighlights(code, language)
  return createElement('div', null, lines ? lines.join('\n') : `plain:${code}`)
}

let host: HTMLDivElement
let root: ReturnType<typeof createRoot>
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  highlight.mockReset()
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
})

it('does not show an old file when its highlight finishes after a newer file', async () => {
  let finishOld!: (html: string) => void
  highlight.mockImplementationOnce(() => new Promise<string>((resolve) => { finishOld = resolve }))
  await act(async () => { root.render(createElement(Probe, { code: 'old' })) })
  highlight.mockResolvedValueOnce('<pre><code><span class="line">new</span></code></pre>')
  await act(async () => { root.render(createElement(Probe, { code: 'new' })) })
  expect(host.textContent).toBe('new')
  await act(async () => { finishOld('<pre><code><span class="line">old</span></code></pre>') })
  expect(host.textContent).toBe('new')
})

it('keeps escaped markup and line boundaries from the highlighter', async () => {
  highlight.mockResolvedValue('<pre><code><span class="line">&lt;img src=x&gt;</span>\n<span class="line">second</span></code></pre>')
  await act(async () => { root.render(createElement(Probe, { code: '<img src=x>\nsecond' })) })
  expect(host.textContent).toBe('&lt;img src=x&gt;\nsecond')
  expect(host.querySelector('img')).toBeNull()
})

it('leaves plain text readable without loading a grammar', async () => {
  await act(async () => { root.render(createElement(Probe, { code: 'plain document', language: 'plaintext' })) })
  expect(highlight).not.toHaveBeenCalled()
  expect(host.textContent).toBe('plain:plain document')
})
