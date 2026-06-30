import mermaidScriptUrl from 'mermaid/dist/mermaid.min.js?url'

export type MermaidRuntime = {
  initialize: (config: Record<string, unknown>) => void
  render: (id: string, chart: string) => Promise<{ svg: string }>
}

declare global {
  interface Window {
    mermaid?: MermaidRuntime
  }
}

let loadPromise: Promise<MermaidRuntime> | null = null

function loadMermaidScript(): Promise<MermaidRuntime> {
  if (window.mermaid) return Promise.resolve(window.mermaid)

  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-ds-mermaid="1"]')
    if (existing) {
      existing.addEventListener('load', () => {
        if (window.mermaid) resolve(window.mermaid)
        else reject(new Error('Mermaid script loaded but window.mermaid is missing.'))
      })
      existing.addEventListener('error', () => reject(new Error('Failed to load Mermaid script.')))
      if (window.mermaid) resolve(window.mermaid)
      return
    }

    const script = document.createElement('script')
    script.src = mermaidScriptUrl
    script.async = true
    script.dataset.dsMermaid = '1'
    script.onload = () => {
      if (window.mermaid) resolve(window.mermaid)
      else reject(new Error('Mermaid script loaded but window.mermaid is missing.'))
    }
    script.onerror = () => reject(new Error('Failed to load Mermaid script.'))
    document.head.appendChild(script)
  })
}

export function loadMermaid(): Promise<MermaidRuntime> {
  if (!loadPromise) loadPromise = loadMermaidScript()
  return loadPromise
}

export function getMermaidTheme(): 'dark' | 'default' {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default'
}

export function initMermaid(mermaid: MermaidRuntime, theme: 'dark' | 'default'): void {
  mermaid.initialize({
    startOnLoad: false,
    theme,
    securityLevel: 'strict',
    fontFamily: 'var(--font-mono), ui-monospace, monospace',
    suppressErrorRendering: true
  })
}
