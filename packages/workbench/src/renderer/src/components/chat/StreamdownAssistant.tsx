import type { ComponentPropsWithRef, MouseEvent, ReactElement } from 'react'
import { Streamdown, type AnimateOptions, type StreamdownProps } from 'streamdown'
import remarkGfm from 'remark-gfm'
import { harden } from 'rehype-harden'
import 'streamdown/styles.css'
import { parseFileReferenceHref, rehypeFileReferences } from '../../lib/file-references'
import { useValidatedFileReference } from '../../lib/file-reference-validation'
import { openWorkspacePathInEditor } from '../../lib/open-workspace-path'
import { useThreadFilesystemRoot } from '../../lib/use-thread-filesystem-root'
import { previewWorkspaceFile } from '../../lib/workspace-file-preview'
import { StreamdownCode } from './StreamdownCode'

/**
 * Tuned for faster, cleaner streaming:
 * - keep per-character reveal for CJK readability
 * - use a quick fade instead of blur
 * - reduce stagger so chunks don't "crawl" across the screen
 */
const STREAMING_ANIMATED: AnimateOptions = {
  sep: 'char',
  duration: 120,
  stagger: 8,
  easing: 'ease-out',
  animation: 'fadeIn'
}

const rehypePlugins = [
  rehypeFileReferences,
  [
    harden,
    {
      allowedLinkPrefixes: ['*']
    }
  ]
] satisfies StreamdownProps['rehypePlugins']

type StreamdownListProps = ComponentPropsWithRef<'ul'> & { node?: unknown }
type StreamdownOrderedListProps = ComponentPropsWithRef<'ol'> & { node?: unknown }
type StreamdownListItemProps = ComponentPropsWithRef<'li'> & { node?: unknown }

/** Strip Streamdown's default list-inside so wrapped lines align under text. */
function withoutListInside(className: string | undefined): string {
  return (className ?? '').replace(/\blist-inside\b/g, '').trim()
}

function StreamdownUl({ className, children, node: _node, ...props }: StreamdownListProps): ReactElement {
  return (
    <ul {...props} className={['ds-md-list list-outside', withoutListInside(className)].filter(Boolean).join(' ')}>
      {children}
    </ul>
  )
}

function StreamdownOl({
  className,
  children,
  node: _node,
  ...props
}: StreamdownOrderedListProps): ReactElement {
  return (
    <ol {...props} className={['ds-md-list list-outside', withoutListInside(className)].filter(Boolean).join(' ')}>
      {children}
    </ol>
  )
}

function StreamdownLi({
  className,
  children,
  node: _node,
  ...props
}: StreamdownListItemProps): ReactElement {
  return (
    <li {...props} className={['ds-md-list-item', className].filter(Boolean).join(' ')}>
      {children}
    </li>
  )
}

const components = {
  code: StreamdownCode,
  a: StreamdownLink,
  ul: StreamdownUl,
  ol: StreamdownOl,
  li: StreamdownLi
} satisfies StreamdownProps['components']

type StreamdownLinkProps = ComponentPropsWithRef<'a'> & { node?: unknown }

function StreamdownLink({
  href,
  children,
  className,
  title
}: StreamdownLinkProps): ReactElement {
  const workspaceRoot = useThreadFilesystemRoot()
  const fileTarget = parseFileReferenceHref(href)
  const validation = useValidatedFileReference(fileTarget, workspaceRoot || undefined)
  const isExternal = href ? /^(https?:|mailto:)/i.test(href) : false
  const cleanClassName = className?.replace(/\bds-file-reference-link\b/g, '').trim()

  if (fileTarget && validation.status !== 'valid') {
    return (
      <span className={cleanClassName} title={title}>
        {children}
      </span>
    )
  }

  const resolvedFileTarget =
    fileTarget && validation.status === 'valid'
      ? { ...fileTarget, path: validation.path }
      : null

  const handleClick = (event: MouseEvent<HTMLAnchorElement>): void => {
    if (resolvedFileTarget) {
      event.preventDefault()
      previewWorkspaceFile({
        ...resolvedFileTarget,
        workspaceRoot: workspaceRoot || undefined
      })
      return
    }

    if (isExternal && href && typeof window.dsGui?.openExternal === 'function') {
      event.preventDefault()
      void window.dsGui.openExternal(href)
    }
  }

  const handleDoubleClick = (event: MouseEvent<HTMLAnchorElement>): void => {
    if (!resolvedFileTarget) return
    event.preventDefault()
    void openWorkspacePathInEditor(
      resolvedFileTarget,
      workspaceRoot || undefined
    ).then((result) => {
      if (!result.ok) {
        void window.dsGui?.logError?.('editor-open', 'Failed to open file reference', {
          message: result.message,
          target: resolvedFileTarget
        })
      }
    })
  }

  return (
    <a
      href={href}
      title={title}
      className={[
        resolvedFileTarget ? 'ds-file-reference-link' : '',
        cleanClassName
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
    >
      {children}
    </a>
  )
}

const BLOCK_MARKDOWN_REGEX =
  /(^|\n)\s{0,3}(#{1,6}\s|[-+*]\s|\d+\.\s|>\s|```|~~~)|(^|\n)\|.+\|/m

const INLINE_STRUCTURED_MARKDOWN_REGEX =
  /`[^`\n]+`|!\[[^\]]*]\([^)\n]+\)|\[[^\]]+]\([^)\n]+\)/
const MAX_ANIMATED_STREAMING_CHARS = 600

function shouldAnimateStreamingText(text: string): boolean {
  const trimmed = text.trim()
  if (!trimmed) return false
  if (trimmed.length > MAX_ANIMATED_STREAMING_CHARS) return false
  return !(
    BLOCK_MARKDOWN_REGEX.test(trimmed) ||
    INLINE_STRUCTURED_MARKDOWN_REGEX.test(trimmed)
  )
}

type Props = {
  /** Markdown source */
  text: string
  /**
   * When true (live SSE chunking), uses Streamdown `streaming` mode with a
   * fast char-level fade so the output feels responsive without the heavy blur.
   */
  streaming: boolean
  className?: string
}

export function StreamdownAssistant({ text, streaming, className }: Props): ReactElement {
  const animated = streaming && shouldAnimateStreamingText(text) ? STREAMING_ANIMATED : false
  const isAnimating = animated !== false

  return (
    <Streamdown
      className={className}
      mode={streaming ? 'streaming' : 'static'}
      parseIncompleteMarkdown={streaming}
      isAnimating={isAnimating}
      animated={animated}
      remarkPlugins={[remarkGfm]}
      rehypePlugins={rehypePlugins}
      components={components}
    >
      {text}
    </Streamdown>
  )
}
