function escapeHtml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

export function renderFallbackHtml(code: string): string {
  const lines = code.split('\n')
  return `<pre class="shiki shiki-themes"><code>${lines
    .map((line) => `<span class="line">${escapeHtml(line)}</span>`)
    .join('\n')}</code></pre>`
}

