import { memo } from 'react'
import { DiffView } from '../../../DiffView'
import { looksLikeUnifiedDiff, countDiffStats } from '../../../../lib/diff-stats'
import {
  languageFromPath,
  SharedCodeBlock,
  titleFromPath
} from '../../SharedCodeBlock'
import { ToolBody, ToolErrorState } from '../primitives'
import type { ToolRenderContext } from '../render-context'

/**
 * Renderer for file mutation tools (write_file / edit_file / apply_patch).
 * Inline unified-diff when the output looks like a patch; otherwise a plain
 * error banner or truncated text fallback. Uses the existing `DiffView`.
 */
export const FileEditRenderer = {
  fullBleed: true,
  Output: memo(function FileEditOutput({
    context
  }: {
    context: ToolRenderContext
  }): React.JSX.Element | null {
    if (context.state === 'error' && context.errorText) {
      return (
        <ToolBody>
          <ToolErrorState message={context.errorText} />
        </ToolBody>
      )
    }
    const output = context.output
    if (!output) return null
    if (!looksLikeUnifiedDiff(output)) {
      const path = context.input.path || context.description
      const language = languageFromPath(path)
      const title = titleFromPath(path) || language || 'text'
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
    return <DiffView patch={output} filePath={context.input.path} maxHeight={440} />
  }),

  Footer: memo(function FileEditFooter({
    context
  }: {
    context: ToolRenderContext
  }): React.JSX.Element | null {
    const stats = context.diffStats ?? countDiffStats(context.output)
    if (!stats) return null
    return (
      <div className="flex items-center gap-1.5 px-3 pb-2 text-[11px] tabular-nums text-ds-faint">
        <span className="text-ds-diff-added">+{stats.added}</span>
        <span className="text-ds-faint/50">·</span>
        <span className="text-ds-diff-removed">-{stats.removed}</span>
      </div>
    )
  })
}
