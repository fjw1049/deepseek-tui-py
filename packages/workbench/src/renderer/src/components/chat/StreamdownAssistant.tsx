import type { ComponentPropsWithRef, MouseEvent, ReactElement } from 'react'
import { Streamdown, defaultRehypePlugins, type AnimateOptions, type StreamdownProps } from 'streamdown'
import remarkGfm from 'remark-gfm'
import { harden } from 'rehype-harden'
import 'streamdown/styles.css'
import {
  parseFileReferenceHref,
  parseMarkdownFileReferenceHref,
  rehypeFileReferences
} from '../../lib/file-references'
import { StreamdownCode, StreamdownInlineCode } from './StreamdownCode'
import { FileChip } from './FileChip'

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
  // Parse disclosures, then sanitize HTML before generating trusted file links.
  defaultRehypePlugins.raw,
  defaultRehypePlugins.sanitize,
  rehypeFileReferences,
  [
    harden,
    {
      allowedLinkPrefixes: ['*'],
      // Chat path linkify emits deepseek-file://…; without this, harden
      // replaces those anchors with plain text + a "[blocked]" suffix.
      allowedProtocols: ['deepseek-file:']
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
  inlineCode: StreamdownInlineCode,
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
  const generatedFileReference = className?.split(/\s+/).includes('ds-file-reference-link') === true
  const fileTarget = generatedFileReference
    ? parseFileReferenceHref(href)
    : parseMarkdownFileReferenceHref(href)
  const authoredFileReference = className?.split(/\s+/).includes('ds-file-reference-authored') === true
  const cleanClassName = className?.replace(/\bds-file-reference-(?:link|authored)\b/g, '').trim()
  const isExternal = href ? /^(https?:|mailto:)/i.test(href) : false

  if (fileTarget) {
    return (
      <FileChip
        path={fileTarget.path}
        line={fileTarget.line}
        column={fileTarget.column}
        label={generatedFileReference && !authoredFileReference ? undefined : children}
        className={cleanClassName}
      />
    )
  }

  if (!isExternal) {
    return <span className={cleanClassName}>{children}</span>
  }

  const handleClick = (event: MouseEvent<HTMLAnchorElement>): void => {
    if (href && typeof window.dsGui?.openExternal === 'function') {
      event.preventDefault()
      void window.dsGui.openExternal(href)
    }
  }

  return (
    <a href={href} title={title} className={cleanClassName} onClick={handleClick}>
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
      controls={{ table: true }}
      remarkPlugins={[remarkGfm]}
      rehypePlugins={rehypePlugins}
      components={components}
    >
      {text}
    </Streamdown>
  )
}
