import { memo } from 'react'
import { ToolBody, ToolEmptyState } from '../primitives'
import type { ToolRenderContext } from '../render-context'

/**
 * Renderer for read-only inspection tools (read_file / list_dir / grep_files /
 * search_files / glob_file_search / fetch_url / web_search). Collapsed by
 * default; on expand shows the raw output capped at a scroll height. These
 * tools rarely need bespoke visualisation — a clean scrollable text panel is
 * enough and keeps the timeline calm.
 */
export const ReadRenderer = {
  Output: memo(function ReadOutput({
    context
  }: {
    context: ToolRenderContext
  }): React.JSX.Element | null {
    const output = context.output
    if (!output || !output.trim()) {
      if (context.state === 'running') {
        return <ToolBody><span className="text-[12px] text-ds-faint">⠋ reading…</span></ToolBody>
      }
      return <ToolEmptyState message="No output" />
    }
    return (
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words px-3 pb-2.5 pt-1 font-mono text-[12px] leading-6 text-ds-ink">
        {output}
      </pre>
    )
  })
}
