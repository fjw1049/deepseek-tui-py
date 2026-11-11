export type MermaidRuntime = {
  initialize: (config: Record<string, unknown>) => void
  render: (id: string, chart: string) => Promise<{ svg: string }>
}

let loadPromise: Promise<MermaidRuntime> | null = null

export function loadMermaid(): Promise<MermaidRuntime> {
  // Build the ESM entry against our locked sanitizers; the prebuilt UMD script
  // embeds older dependency copies that package-lock updates cannot replace.
  if (!loadPromise) loadPromise = import('mermaid').then((module) => module.default).catch((error) => {
    loadPromise = null
    throw error
  })
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
