import { useEffect, useState } from 'react'
import { highlightCodeHtml } from './highlight-client'

const cache = new Map<string, string[]>()
let size = 0

export function useCodeHighlights(code: string, language: string): string[] | null {
  const key = language + '\0' + code
  const [result, setResult] = useState<{ key: string; lines: string[] } | null>(null)
  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    if (!code || language === 'plaintext' || cache.has(key)) return
    void highlightCodeHtml(code, language, controller.signal).then((html) => {
      if (cancelled) return
      // Shiki emits one line wrapper per source line. Extract strings without
      // building an off-screen DOM for the entire file on the UI thread.
      const body = /<code[^>]*>([\s\S]*)<\/code>/.exec(html)?.[1] ?? ''
      const lines = body.split('\n').map(line => line.replace(/^<span class="line">/, '').replace(/<\/span>$/, ''))
      const cost = key.length + lines.reduce((sum, line) => sum + line.length, 0)
      if (cost <= 4_000_000 && !cache.has(key)) {
        cache.set(key, lines)
        size += cost
        while (size > 4_000_000) {
          const oldest = cache.keys().next().value!
          size -= oldest.length + cache.get(oldest)!.reduce((sum, line) => sum + line.length, 0)
          cache.delete(oldest)
        }
      }
      setResult({ key, lines })
    }).catch(() => {
      if (!cancelled) setResult({ key, lines: code.split('\n').map(line => line.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')) })
    })
    return () => { cancelled = true; controller.abort() }
  }, [code, language, key])
  return cache.get(key) ?? (result?.key === key ? result.lines : null)
}
