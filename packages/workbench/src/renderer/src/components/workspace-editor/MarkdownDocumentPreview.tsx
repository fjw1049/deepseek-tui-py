import type { ReactElement } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type Props = {
  content: string
}

/** Scrollable rendered markdown for workspace file reading (non-edit) mode. */
export function MarkdownDocumentPreview({ content }: Props): ReactElement {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-ds-sidebar px-5 py-4">
      <div className="ds-markdown mx-auto max-w-[52rem] text-[14px] leading-7 text-ds-ink">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    </div>
  )
}
