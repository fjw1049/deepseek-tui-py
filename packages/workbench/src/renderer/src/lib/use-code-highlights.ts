import { useEffect, useState } from 'react'

/** Share the existing escaped, dual-theme Shiki output without chat card chrome. */
export function useCodeHighlights(code: string, language: string): string[] | null {
  const [result, setResult] = useState<{ code: string; language: string; lines: string[] } | null>(null)
  useEffect(() => {
    let cancelled = false
    if (!code || language === 'plaintext') return
    void import('../components/chat/SharedCodeBlock')
      .then(({ highlightCodeHtml }) => highlightCodeHtml(code, language))
      .then((html) => {
        if (cancelled) return
        const doc = new DOMParser().parseFromString(html, 'text/html')
        const lines = Array.from(doc.querySelectorAll('pre > code > .line'), (line) => line.innerHTML)
        setResult({ code, language, lines })
      })
      .catch(() => { /* Plain source remains readable if the highlight chunk cannot load. */ })
    return () => { cancelled = true }
  }, [code, language])
  return result?.code === code && result.language === language ? result.lines : null
}
