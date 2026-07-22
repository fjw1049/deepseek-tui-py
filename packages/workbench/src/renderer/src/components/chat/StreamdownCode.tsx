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
import {
  findFileReferences,
  type FileReferenceTarget
} from '../../lib/file-references'
import { useValidatedFileReference } from '../../lib/file-reference-validation'
import { openWorkspacePathInEditor } from '../../lib/open-workspace-path'
import { useThreadFilesystemRoot } from '../../lib/use-thread-filesystem-root'
import { previewWorkspaceFile } from '../../lib/workspace-file-preview'
import { SharedCodeBlock } from './SharedCodeBlock'
import { StructureBlock } from './StructureBlock'
import { StreamdownMermaidBlock } from './StreamdownMermaidBlock'
import { looksLikeStructureTree } from './structure-tree'

const LANGUAGE_REGEX = /language-([^\s]+)/

type CodeProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
  node?: Element | undefined
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
  text,
  target,
  className
}: {
  text: string
  target: FileReferenceTarget
  className?: string
}): ReactNode {
  const workspaceRoot = useThreadFilesystemRoot()
  const validation = useValidatedFileReference(target, workspaceRoot || undefined)

  if (validation.status !== 'valid') {
    return (
      <code
        className={className ? `ds-code-inline ${className}` : 'ds-code-inline'}
        data-streamdown="inline-code"
      >
        {text}
      </code>
    )
  }

  const resolvedTarget = { ...target, path: validation.path }

  const handlePreview = (): void => {
    previewWorkspaceFile({
      ...resolvedTarget,
      workspaceRoot: workspaceRoot || undefined
    })
  }

  const handleOpenEditor = (): void => {
    void openWorkspacePathInEditor(resolvedTarget, workspaceRoot || undefined).then((result) => {
      if (!result.ok) {
        void window.dsGui?.logError?.('editor-open', 'Failed to open inline file reference', {
          message: result.message,
          target: resolvedTarget
        })
      }
    })
  }

  return (
    <button
      type="button"
      className={`ds-code-inline ds-file-reference-code ${className ?? ''}`.trim()}
      data-streamdown="inline-code"
      title={target.line ? `${target.path}:${target.line}` : target.path}
      onClick={handlePreview}
      onDoubleClick={handleOpenEditor}
    >
      {text}
    </button>
  )
}

function CodeBlock({
  code,
  language
}: {
  code: string
  language: string
}): ReactNode {
  const { isAnimating } = useContext(StreamdownContext)
  if (looksLikeStructureTree(code, language)) {
    return <StructureBlock content={code} actionsDisabled={isAnimating} />
  }
  return (
    <SharedCodeBlock
      code={code}
      language={language}
      deferHighlightWhileBusy
      actionsDisabled={isAnimating}
    />
  )
}

function CodeComponent({ node, className, children, ...props }: CodeProps) {
  const inline = node?.position?.start?.line === node?.position?.end?.line

  if (inline) {
    const text = extractText(children)
    const fileReference = inlineFileReference(text)
    if (fileReference) {
      return (
        <InlineFileReferenceCode
          text={fileReference.text}
          target={fileReference.target}
          className={className}
        />
      )
    }

    return (
      <code
        className={className ? `ds-code-inline ${className}` : 'ds-code-inline'}
        data-streamdown="inline-code"
        {...props}
      >
        {children}
      </code>
    )
  }

  const match = className?.match(LANGUAGE_REGEX)
  const language = match?.[1] ?? ''
  const code = extractText(children)

  if (language.trim().toLowerCase() === 'mermaid') {
    return <StreamdownMermaidBlock chart={code} />
  }

  return <CodeBlock code={code} language={language} />
}

const MemoCode = memo(CodeComponent, (prev, next) => {
  return prev.className === next.className && sameNodePosition(prev.node, next.node)
})

MemoCode.displayName = 'StreamdownCode'

export { MemoCode as StreamdownCode }
