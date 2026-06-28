import { memo, type ReactNode } from 'react'
import { ToolEmptyState } from '../primitives'
import type { ToolRenderContext } from '../render-context'

/**
 * Renderer for line-oriented inspection tools (grep / search_files /
 * glob_file_search / list_dir). The deepseek runtime delivers tool output as a
 * single plain-text blob, not a structured payload — so unlike Tanzo's typed
 * grep renderer we parse line-by-line. Still a big step up from a raw `<pre>`:
 * each result becomes an aligned, hover-highlightable row, and when the tool
 * had a search pattern we mark the matched substring so the eye lands on it.
 */

const MAX_ROWS = 400

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function HighlightedLine({
  text,
  pattern
}: {
  text: string
  pattern?: string
}): React.JSX.Element {
  if (!pattern || !text) return <>{text || ' '}</>
  let re: RegExp
  try {
    re = new RegExp(escapeRegExp(pattern), 'gi')
  } catch {
    return <>{text}</>
  }
  const parts: ReactNode[] = []
  let last = 0
  let count = 0
  for (let m = re.exec(text); m !== null && count < 30; m = re.exec(text)) {
    if (m[0] === '') {
      re.lastIndex += 1
      continue
    }
    if (m.index > last) parts.push(text.slice(last, m.index))
    parts.push(
      <mark
        key={`${m.index}-${count}`}
        className="rounded-sm bg-amber-400/25 px-0.5 text-ds-ink"
      >
        {m[0]}
      </mark>
    )
    last = m.index + m[0].length
    count += 1
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

export const ListRenderer = {
  fullBleed: true,
  Output: memo(function ListOutput({
    context
  }: {
    context: ToolRenderContext
  }): React.JSX.Element | null {
    const output = context.output
    if (!output || !output.trim()) {
      if (context.state === 'running') {
        return <div className="px-3 py-2 text-[12px] text-ds-faint">⠋ searching…</div>
      }
      return <ToolEmptyState message="No results" />
    }

    const lines = output.replace(/\n+$/, '').split('\n')
    const rows = lines.slice(0, MAX_ROWS)
    const hidden = lines.length - rows.length
    const pattern = context.input.pattern

    return (
      <div className="max-h-72 overflow-auto bg-ds-subtle/50 py-1 font-mono text-[12px] leading-[1.55]">
        <ul>
          {rows.map((line, index) => (
            <li
              key={index}
              className="flex gap-2 px-3 py-0.5 transition hover:bg-ds-hover/40"
            >
              <span className="w-7 shrink-0 select-none text-right tabular-nums text-ds-faint/70">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 whitespace-pre-wrap break-all text-ds-ink/90">
                <HighlightedLine text={line} pattern={pattern} />
              </span>
            </li>
          ))}
        </ul>
        {hidden > 0 ? (
          <p className="px-3 py-1 text-[11px] text-ds-faint">+{hidden} more lines</p>
        ) : null}
      </div>
    )
  })
}
