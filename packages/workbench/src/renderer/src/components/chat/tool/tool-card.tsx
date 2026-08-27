import { lazy, memo, Suspense, useCallback, useMemo } from 'react'
import type { LucideIcon } from 'lucide-react'
import { FileCode2, Search, Terminal, Wrench } from 'lucide-react'
import { cn } from './cn'
import { buildToolRenderContext, isPendingState } from './render-context'
import { resolveToolRenderer } from './registry'
import { ToolGateBar } from './tool-gate-bar'
import { useDisclosure } from '../model/use-disclosure'
import { ToolBody, ToolCopyButton, ToolErrorState, ToolHeaderRow } from './primitives'
import type { ToolBlock } from '../../../agent/types'
import { findPendingToolGate, hasPendingToolGate } from '../../../lib/tool-gate'
import { useChatStore } from '../../../store/chat-store'
import { prefetchWorkspaceFile } from '../../../lib/workspace-editor-events'

export interface ToolCardProps {
  block: ToolBlock
  className?: string
  /** Open a workspace file in the editor panel (file-mutation / read rows). */
  onOpenWorkspaceFile?: (
    path: string,
    line?: number,
    options?: { review?: boolean }
  ) => void
}

const LazyFullOutput = lazy(() => import('./lazy-full-output'))

export const SHELL_TOOL_NAMES = new Set([
  'exec_shell',
  'exec_shell_wait',
  'exec_shell_interact',
  'run_terminal_cmd'
])

function pickIcon(toolName: string, isFileChange: boolean, isCommand: boolean): LucideIcon {
  if (isCommand || SHELL_TOOL_NAMES.has(toolName)) return Terminal
  if (isFileChange) return FileCode2
  if (
    toolName === 'grep' ||
    toolName === 'grep_files' ||
    toolName === 'search_files' ||
    toolName === 'glob_file_search' ||
    toolName === 'file_search'
  ) {
    return Search
  }
  return Wrench
}

/**
 * Tool-card host. Builds a normalised render context from a `ToolBlock`,
 * resolves a renderer from the registry, and renders Header + (optional)
 * Output/Footer inside a collapsible shell. Expand state is persisted via
 * `useDisclosure` so it survives remounts.
 *
 * Default is collapsed. File mutations auto-open while running (so the live
 * patch is visible) and collapse again on success unless the user toggled
 * the card. An explicit user toggle always wins. Status is a quiet trailing
 * cue ("…" / check / "!") — not a tinted shell — so the work trace stays a
 * calm, consistent list.
 */
export const ToolCard = memo(function ToolCard({
  block,
  className,
  onOpenWorkspaceFile
}: ToolCardProps): React.JSX.Element | null {
  const blocks = useChatStore((s) => s.blocks)
  const gate = useMemo(() => findPendingToolGate(blocks, block), [block, blocks])
  const awaitingGate = hasPendingToolGate(gate)
  const ctx = useMemo(() => {
    const built = buildToolRenderContext(block)
    return awaitingGate ? { ...built, state: 'awaiting_approval' as const } : built
  }, [awaitingGate, block])
  const filePath = ctx.input.path
  const headerLabel = filePath
    ? ctx.label || ctx.shortName
    : ctx.isFileChange
      ? ctx.description || ctx.label || ctx.shortName
      : ctx.label || ctx.shortName
  const headerTitle = filePath || ctx.isFileChange ? undefined : ctx.description || undefined
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const prefetchPath = ctx.input.path
  const handlePrefetch = useCallback((): void => {
    if (prefetchPath && workspaceRoot.trim()) prefetchWorkspaceFile(prefetchPath, workspaceRoot)
  }, [prefetchPath, workspaceRoot])
  const disclosureKey = `tool:${ctx.toolCallId}`
  const [storedOpen, setDisclosureOpen, hasStoredOpen] = useDisclosure(
    disclosureKey,
    false
  )

  const isShell = SHELL_TOOL_NAMES.has(ctx.toolName) || ctx.isCommand

  const setUserOpen = useCallback(
    (next: boolean) => {
      setDisclosureOpen(next)
    },
    [setDisclosureOpen]
  )

  const renderer = resolveToolRenderer(ctx)
  const HeaderComp = renderer?.Header ?? null
  const OutputComp = renderer?.Output ?? null
  const FooterComp = renderer?.Footer ?? null

  const hasOutput = ctx.output !== undefined && ctx.output.trim().length > 0
  const canExpand =
    hasOutput || Boolean(renderer?.Output) || ctx.state === 'running' || awaitingGate
  const renderOutput =
    ctx.errorText !== undefined ||
    hasOutput ||
    Boolean(renderer?.renderWhenPending) ||
    !isPendingState(ctx.state)

  const autoOpenFile = ctx.isFileChange && ctx.state === 'running'
  const open = canExpand && (hasStoredOpen ? storedOpen : autoOpenFile)
  const Icon = pickIcon(ctx.toolName, ctx.isFileChange, ctx.isCommand)

  const readOffset =
    ctx.shortName === 'read_file' && ctx.meta?.tool_input && typeof ctx.meta.tool_input === 'object'
      ? (ctx.meta.tool_input as Record<string, unknown>).offset
      : undefined
  const readLine =
    typeof readOffset === 'number' && Number.isFinite(readOffset) && readOffset >= 1
      ? Math.floor(readOffset)
      : undefined

  // Visual tiering (mirrors cursor/codex): only running / error / file mutations
  // and shell commands earn a full bordered card. A successful read-only probe
  // (read_file, grep, list_dir…) collapses to a single calm row so a turn with
  // a dozen reads reads as one quiet thread instead of a wall of boxes.
  const isHeavy = ctx.state !== 'success' || ctx.isFileChange || ctx.isCommand || isShell

  const headerElement = HeaderComp ? (
    <HeaderComp context={ctx} />
  ) : (
    <ToolHeaderRow
      icon={Icon}
      label={headerLabel}
      title={headerTitle}
      filePath={filePath}
      fileLine={ctx.isFileChange ? ctx.editLine : readLine}
      state={ctx.state}
      expanded={open}
      canExpand={canExpand}
      diffStats={ctx.diffStats}
      onOpenInEditor={
        onOpenWorkspaceFile && ctx.input.path && (ctx.isFileChange || ctx.shortName === 'read_file')
          ? () =>
              onOpenWorkspaceFile(
                ctx.input.path!,
                ctx.isFileChange ? ctx.editLine : readLine,
                ctx.isFileChange ? { review: true } : undefined
              )
          : undefined
      }
    />
  )

  const handleToggle = useCallback(() => {
    if (!canExpand) return
    setUserOpen(!open)
  }, [canExpand, open, setUserOpen])

  const expandedBody = renderOutput ? (
    renderer?.fullBleed && OutputComp ? (
      <>
        <OutputComp context={ctx} />
        {FooterComp ? (
          <ToolBody>
            <FooterComp context={ctx} />
          </ToolBody>
        ) : null}
      </>
    ) : (
      <ToolBody>
        {OutputComp ? (
          <OutputComp context={ctx} />
        ) : ctx.errorText !== undefined ? (
          <ToolErrorState message={ctx.errorText} />
        ) : hasOutput ? (
          ctx.outputTruncated ? (
            <Suspense
              fallback={
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-ds-ink">
                  {ctx.output}
                </pre>
              }
            >
              <LazyFullOutput text={ctx.output!} itemId={block.id} />
            </Suspense>
          ) : (
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-ds-ink">
              {ctx.output}
            </pre>
          )
        ) : null}
        {FooterComp ? <FooterComp context={ctx} /> : null}
      </ToolBody>
    )
  ) : null

  const copyText = ctx.errorText ?? ctx.output
  const copyButton =
    copyText && copyText.trim() ? (
      <ToolCopyButton text={copyText} className="absolute right-1.5 top-1.5 z-10" />
    ) : null

  const interactionProps = {
    onClick: handleToggle,
    role: canExpand ? ('button' as const) : undefined,
    tabIndex: canExpand ? 0 : undefined,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (canExpand && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault()
        handleToggle()
      }
    }
  }

  // Lightweight row: a quiet line on the work-process rail.
  if (!isHeavy) {
    return (
      <div id={`block-${block.id}`} className="group" onMouseEnter={handlePrefetch}>
        <div
          className={cn(
            'ds-tool-row flex items-center rounded-md',
            canExpand ? 'cursor-pointer hover:bg-ds-hover/40' : ''
          )}
          {...interactionProps}
        >
          {headerElement}
        </div>
        {open && expandedBody ? (
          <div
            className="relative mt-1 overflow-hidden rounded-[10px] border border-ds-border-muted/40 bg-ds-card/40"
            style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 160px' }}
          >
            {copyButton}
            {expandedBody}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div
      id={`block-${block.id}`}
      className={cn(
        'ds-tool-card group overflow-hidden rounded-[14px] border border-ds-border bg-ds-card/60',
        awaitingGate ? 'border-amber-500/40' : '',
        className
      )}
      onMouseEnter={handlePrefetch}
    >
      <div
        className={cn(
          'flex items-center px-3 py-2',
          canExpand ? 'cursor-pointer hover:bg-ds-hover/40' : ''
        )}
        {...interactionProps}
      >
        {headerElement}
      </div>
      {awaitingGate ? (
        <ToolGateBar approval={gate.approval} elevation={gate.elevation} />
      ) : null}
      {open ? (
        <div
          className="relative border-t border-ds-border-muted/50"
          style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 180px' }}
        >
          {copyButton}
          {expandedBody}
        </div>
      ) : null}
    </div>
  )
})
