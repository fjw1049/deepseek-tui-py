import type { Element } from 'hast'
import {
  isValidElement,
  memo,
  useContext,
  type DetailedHTMLProps,
  type HTMLAttributes,
  type ReactNode
} from 'react'
import { StreamdownContext } from 'streamdown'
import { parseCodeFenceInfo } from '../../lib/file-chip'
import {
  findFileReferences,
  type FileReferenceTarget
} from '../../lib/file-references'
import { FileChip } from './FileChip'
import { languageFromPath } from './code-language'
import { SharedCodeBlock } from './SharedCodeBlock'
import { StructureBlock } from './StructureBlock'
import { StreamdownMermaidBlock } from './StreamdownMermaidBlock'
import { looksLikeStructureTree } from './structure-tree'

const LANGUAGE_REGEX = /language-([^\s]+)/

type CodeProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
  node?: Element | undefined
  'data-block'?: string | boolean
}

/**
 * Streamdown unwraps `<pre>` and stamps `data-block` on the inner `code`.
 * That flag — not source-map line numbers — is the only safe “this is a fence”
 * signal. Incomplete markdown can give an inline span a multi-line position
 * while still parenting it under `<p>`; treating that as a block emits a
 * `<div>` inside a paragraph and triggers a hydration warning.
 */
export function isStreamdownFencedCode(props: object): boolean {
  return Object.hasOwn(props, 'data-block')
}

type MarkdownPoint = { line?: number; column?: number }
type MarkdownPosition = { start?: MarkdownPoint; end?: MarkdownPoint }
type MarkdownNode = {
  position?: MarkdownPosition
}

function sameNodePosition(prev?: MarkdownNode, next?: MarkdownNode): boolean {
  if (!(prev?.position || next?.position)) return true
  if (!(prev?.position && next?.position)) return false

  const prevStart = prev.position.start
  const nextStart = next.position.start
  const prevEnd = prev.position.end
  const nextEnd = next.position.end

  return (
    prevStart?.line === nextStart?.line &&
    prevStart?.column === nextStart?.column &&
    prevEnd?.line === nextEnd?.line &&
    prevEnd?.column === nextEnd?.column
  )
}

function extractText(node: ReactNode): string {
  if (typeof node === 'string') return node
  if (typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode }
    return extractText(props.children)
  }
  return ''
}

function inlineFileReference(text: string): { text: string; target: FileReferenceTarget } | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const matches = findFileReferences(trimmed)
  const match = matches.length === 1 ? matches[0] : null
  if (!match || match.start !== 0 || match.end !== trimmed.length) return null
  return { text: trimmed, target: match.target }
}

function InlineFileReferenceCode({
  target
}: {
  text: string
  target: FileReferenceTarget
}): ReactNode {
  return <FileChip path={target.path} line={target.line} />
}

function CodeBlock({
  code,
  language,
  filePath,
  lineStart,
  lineEnd
}: {
  code: string
  language: string
  filePath?: string
  lineStart?: number
  lineEnd?: number
}): ReactNode {
  const { isAnimating } = useContext(StreamdownContext)
  if (looksLikeStructureTree(code, language)) {
    return <StructureBlock content={code} actionsDisabled={isAnimating} />
  }
  return (
    <SharedCodeBlock
      code={code}
      language={language}
      filePath={filePath}
      lineStart={lineStart}
      lineEnd={lineEnd}
      deferHighlightWhileBusy
      actionsDisabled={isAnimating}
    />
  )
}

function InlineCodeComponent({
  node: _node,
  className,
  children,
  ...props
}: CodeProps): ReactNode {
  const { 'data-block': _dataBlock, ...rest } = props
  const text = extractText(children)
  const fileReference = inlineFileReference(text)
  if (fileReference) {
    return (
      <InlineFileReferenceCode
        text={fileReference.text}
        target={fileReference.target}
      />
    )
  }

  return (
    <code
      className={className ? `ds-code-inline ${className}` : 'ds-code-inline'}
      data-streamdown="inline-code"
      {...rest}
    >
      {children}
    </code>
  )
}

function FencedCodeComponent({ node: _node, className, children, ...props }: CodeProps): ReactNode {
  if (!isStreamdownFencedCode(props)) {
    return (
      <InlineCodeComponent className={className} {...props}>
        {children}
      </InlineCodeComponent>
    )
  }

  const match = className?.match(LANGUAGE_REGEX)
  const fence = parseCodeFenceInfo(match?.[1] ?? '')
  const language = fence.filePath
    ? languageFromPath(fence.filePath) || fence.language
    : fence.language
  const code = extractText(children)

  if (language.trim().toLowerCase() === 'mermaid') {
    return <StreamdownMermaidBlock chart={code} />
  }

  return (
    <CodeBlock
      code={code}
      language={language}
      filePath={fence.filePath}
      lineStart={fence.lineStart}
      lineEnd={fence.lineEnd}
    />
  )
}

const MemoFencedCode = memo(FencedCodeComponent, (prev, next) => {
  return prev.className === next.className && sameNodePosition(prev.node, next.node)
})

const MemoInlineCode = memo(InlineCodeComponent, (prev, next) => {
  return prev.className === next.className && sameNodePosition(prev.node, next.node)
})

MemoFencedCode.displayName = 'StreamdownCode'
MemoInlineCode.displayName = 'StreamdownInlineCode'

export { MemoFencedCode as StreamdownCode, MemoInlineCode as StreamdownInlineCode }
