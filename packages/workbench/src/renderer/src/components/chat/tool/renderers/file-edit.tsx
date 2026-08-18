import { memo } from 'react'
import { LoaderCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { DiffView } from '../../../DiffView'
import { looksLikeUnifiedDiff } from '../../../../lib/diff-stats'
import { languageFromPath, titleFromPath } from '../../code-language'
import { SharedCodeBlock } from '../../SharedCodeBlock'
import { ToolBody, ToolErrorState } from '../primitives'
import type { ToolRenderContext } from '../render-context'

/**
 * Renderer for file mutation tools (write_file / edit_file / apply_patch).
 * The ToolCard host auto-opens this while the write is running and collapses
 * it on success; Output is the expandable patch / file body.
 */
export const FileEditRenderer = {
  fullBleed: true,
  renderWhenPending: true,
  Output: memo(function FileEditOutput({
    context
  }: {
    context: ToolRenderContext
  }): React.JSX.Element | null {
    const { t } = useTranslation('common')
    if (context.state === 'error' && context.errorText) {
      return (
        <ToolBody>
          <ToolErrorState message={context.errorText} />
        </ToolBody>
      )
    }
    const output = context.output
    const running = context.state === 'running'
    if (!output) {
      if (!running) return null
      return (
        <div className="flex items-center gap-2 px-3 py-2 text-[12px] text-ds-muted">
          <LoaderCircle className="size-3.5 shrink-0 animate-spin" strokeWidth={2} />
          {t('fileDiffApplying')}
        </div>
      )
    }
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
    return (
      <DiffView
        patch={output}
        filePath={context.input.path}
        maxHeight={220}
        follow={running}
        showHeader={false}
      />
    )
  })
}
