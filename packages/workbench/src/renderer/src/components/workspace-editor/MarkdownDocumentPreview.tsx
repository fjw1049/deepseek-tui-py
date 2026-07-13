import type { ReactElement } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type Props = {
  content: string
}

/** Scrollable rendered markdown for workspace file reading (non-edit) mode. */
export function MarkdownDocumentPreview({ content }: Props): ReactElement {
  const body = content.trim() ? content : '\u00a0'

  return (
    <div className="ds-markdown-doc-shell min-h-0 flex-1 overflow-y-auto">
      <article className="ds-markdown-doc-page">
        <div className="ds-markdown ds-markdown--document">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
        </div>
      </article>
    </div>
  )
}
