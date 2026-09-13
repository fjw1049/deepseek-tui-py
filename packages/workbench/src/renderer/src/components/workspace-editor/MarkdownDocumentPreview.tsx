import { isValidElement, type ReactElement, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useCodeHighlights } from '../../lib/use-code-highlights'

type Props = {
  content: string
}

function DocumentCodeBlock({ children }: { children?: ReactNode }): ReactElement {
  const codeElement = isValidElement<{ children?: ReactNode; className?: string }>(children) ? children : null
  const code = typeof codeElement?.props.children === 'string' ? codeElement.props.children : ''
  const language = /language-([^\s]+)/.exec(codeElement?.props.className ?? '')?.[1] ?? 'plaintext'
  const lines = useCodeHighlights(code.replace(/\n$/, ''), language)
  return (
    <pre className="ds-document-code"><code>{lines ? lines.map((html, i) => (
      <span key={i}><span className="ds-syntax-line" dangerouslySetInnerHTML={{ __html: html }} />{i < lines.length - 1 ? '\n' : ''}</span>
    )) : codeElement ? code : children}</code></pre>
  )
}

/** Scrollable rendered markdown for workspace file reading (non-edit) mode. */
export function MarkdownDocumentPreview({ content }: Props): ReactElement {
  const body = content.trim() ? content : '\u00a0'

  return (
    <div className="ds-markdown-doc-shell min-h-0 flex-1 overflow-y-auto">
      <article className="ds-markdown-doc-page">
        <div className="ds-markdown ds-markdown--document">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ pre: DocumentCodeBlock }}>{body}</ReactMarkdown>
        </div>
      </article>
    </div>
  )
}
