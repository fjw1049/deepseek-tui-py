import { isValidElement, useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Element, Root } from 'hast'
import { useTranslation } from 'react-i18next'
import { useCodeHighlights } from '../../lib/use-code-highlights'
import { markdownLocalTarget } from '../../lib/markdown-local-target'

type Props = {
  content: string
  path: string
  workspaceRoot: string
  fragment?: string
  revealNonce?: number
  onOpenFile: (path: string, fragment: string) => Promise<boolean>
}

function documentHeadingIds() {
  return (tree: Root): void => {
    const seen = new Map<string, number>()
    const text = (node: Element): string => node.children.map((child) =>
      child.type === 'text' ? child.value : child.type === 'element' ? text(child) : ''
    ).join('')
    const visit = (node: Root | Element): void => {
      if (node.type === 'element' && /^h[1-6]$/.test(node.tagName)) {
        const slug = text(node).trim().toLowerCase().replace(/[^\p{L}\p{N}_ -]/gu, '').replace(/\s/g, '-')
        const count = seen.get(slug) ?? 0
        seen.set(slug, count + 1)
        node.properties.id = `doc-${slug}${count ? `-${count}` : ''}`
      }
      for (const child of node.children) if (child.type === 'element') visit(child)
    }
    visit(tree)
  }
}

function DocumentImage({ src = '', alt = '', title, path, workspaceRoot }: {
  src?: string; alt?: string; title?: string; path: string; workspaceRoot: string
}): ReactElement {
  const { t } = useTranslation('common')
  const [resolved, setResolved] = useState<{ source: string; url?: string; error?: boolean }>()
  const target = markdownLocalTarget(src, path, workspaceRoot)
  const localPath = target?.path
  useEffect(() => {
    if (!localPath) return
    let cancelled = false
    void window.dsGui.getWorkspaceHtmlPreviewUrl({ path: localPath, workspaceRoot })
      .then((result) => {
        if (!cancelled) setResolved({ source: src, ...(result.ok ? { url: result.url } : { error: true }) })
      })
      .catch(() => { if (!cancelled) setResolved({ source: src, error: true }) })
    return () => { cancelled = true }
  }, [localPath, src, workspaceRoot])
  const url = localPath ? (resolved?.source === src ? resolved.url : undefined) : src
  if (resolved?.source === src && resolved.error) return <span role="img" aria-label={alt}>{t('workspaceMarkdownImageUnavailable', { name: alt || src })}</span>
  return url ? <img src={url} alt={alt} title={title} loading="lazy" onError={() => setResolved({ source: src, error: true })} /> : <span>{alt}</span>
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
export function MarkdownDocumentPreview({ content, path, workspaceRoot, fragment, revealNonce, onOpenFile }: Props): ReactElement {
  const { t } = useTranslation('common')
  const article = useRef<HTMLElement>(null)
  const [linkError, setLinkError] = useState(false)
  const body = content.trim() ? content : '\u00a0'
  const reveal = (value: string): void => {
    const heading = Array.from(article.current?.querySelectorAll('[id]') ?? []).find((node) => node.id === `doc-${value}`)
    heading?.scrollIntoView({ block: 'start' })
  }
  useEffect(() => {
    if (fragment) reveal(fragment)
    setLinkError(false)
  }, [fragment, revealNonce, content, path])

  return (
    <div className="ds-markdown-doc-shell min-h-0 flex-1 overflow-y-auto">
      <article ref={article} className="ds-markdown-doc-page">
        {linkError ? <p role="alert">{t('workspaceMarkdownLinkUnavailable')}</p> : null}
        <div className="ds-markdown ds-markdown--document">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[documentHeadingIds]} components={{
            pre: DocumentCodeBlock,
            img: ({ src, alt, title }) => <DocumentImage key={`${path}:${src}`} src={src} alt={alt} title={title} path={path} workspaceRoot={workspaceRoot} />,
            a: ({ href, children }) => <a href={href} onClick={(event) => {
              event.preventDefault()
              if (!href) return
              setLinkError(false)
              const target = markdownLocalTarget(href, path, workspaceRoot)
              if (href.startsWith('#') && target) { reveal(target.fragment); return }
              if (target) {
                void onOpenFile(target.path, target.fragment).then((ok) => { if (!ok) setLinkError(true) }).catch(() => setLinkError(true))
              } else if (/^(https?:|mailto:)/i.test(href)) {
                void window.dsGui.openExternal(href).catch(() => setLinkError(true))
              }
            }}>{children}</a>
          }}>{body}</ReactMarkdown>
        </div>
      </article>
    </div>
  )
}
