import { memo } from 'react'
import {
  languageFromPath,
  SharedCodeBlock,
  titleFromPath
} from '../../SharedCodeBlock'
import { ToolBody, ToolEmptyState } from '../primitives'
import type { ToolRenderContext } from '../render-context'

/**
 * Renderer for read-only inspection tools (read_file / fetch_url / web_search).
 * File contents use the shared code card (path header + copy/download/fullscreen).
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
        return (
          <ToolBody>
            <span className="text-[12px] text-ds-faint">⠋ reading…</span>
          </ToolBody>
        )
      }
      return <ToolEmptyState message="No output" />
    }

    if (context.shortName === 'read_file') {
      const path = context.input.path || context.description
      const language = languageFromPath(path)
      const title = titleFromPath(path) || 'file'
      const downloadName = path?.split(/[\\/]/).pop()
      return (
        <div className="ds-markdown px-2 pb-2 pt-1">
          <SharedCodeBlock
            code={output}
            language={language}
            title={title}
            downloadName={downloadName}
          />
        </div>
      )
    }

    return (
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words px-3 pb-2.5 pt-1 font-mono text-[12px] leading-6 text-ds-ink">
        {output}
      </pre>
    )
  })
}
