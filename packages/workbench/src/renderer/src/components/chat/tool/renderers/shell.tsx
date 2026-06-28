import { memo } from 'react'
import { cn } from '../cn'
import type { ToolRenderContext } from '../render-context'

/**
 * Renderer for shell/command tools. `renderWhenPending` is true so streaming
 * stdout shows live while the command runs (the ToolCard host also auto-opens
 * running shells). On completion the output stays until the user collapses.
 */
export const ShellRenderer = {
  renderWhenPending: true,
  fullBleed: true,
  Output: memo(function ShellOutput({
    context
  }: {
    context: ToolRenderContext
  }): React.JSX.Element | null {
    const output = context.output
    const isRunning = context.state === 'running'
    if (!output && !isRunning) return null

    return (
      <div
        className={cn(
          'overflow-auto bg-ds-subtle/60 px-3 py-2 font-mono text-[12px] leading-[1.55]',
          isRunning ? 'max-h-80' : 'max-h-72'
        )}
      >
        {output ? (
          <pre className="whitespace-pre-wrap break-words text-ds-ink">{output}</pre>
        ) : isRunning ? (
          <span className="text-ds-faint">⠋ running…</span>
        ) : null}
      </div>
    )
  }),

  Footer: memo(function ShellFooter({
    context
  }: {
    context: ToolRenderContext
  }): React.JSX.Element | null {
    const meta = context.meta
    if (typeof meta !== 'object' || meta === null) return null
    const parts: string[] = []
    const exitCode = meta.exit_code
    if (typeof exitCode === 'number') {
      parts.push(`exit ${exitCode}`)
    }
    const durationMs = meta.duration_ms
    if (typeof durationMs === 'number') {
      parts.push(formatDuration(durationMs))
    }
    if (parts.length === 0) return null
    return (
      <div className="flex items-center gap-2 px-3 pb-2 text-[11px] tabular-nums text-ds-faint">
        {parts.join(' · ')}
      </div>
    )
  })
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m${s}s`
}
