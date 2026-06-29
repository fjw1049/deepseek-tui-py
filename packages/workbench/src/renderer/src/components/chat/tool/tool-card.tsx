import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef } from 'react'
import type { LucideIcon } from 'lucide-react'
import { FileEdit, Search, Terminal, Wrench } from 'lucide-react'
import { cn } from './cn'
import { buildToolRenderContext, isPendingState, type ToolRenderContext } from './render-context'
import { resolveToolRenderer } from './registry'
import { useDisclosure } from '../model/use-disclosure'
import { ToolBody, ToolCopyButton, ToolErrorState, ToolHeaderRow } from './primitives'
import type { ToolBlock } from '../../../agent/types'

export interface ToolCardProps {
  block: ToolBlock
  className?: string
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
  if (isFileChange) return FileEdit
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

function isSuccessfulShell(ctx: ToolRenderContext): boolean {
  const meta = ctx.meta
  if (typeof meta !== 'object' || meta === null) return true
  const reason = meta.reason
  if (reason === 'error' || reason === 'timeout' || reason === 'abort' || reason === 'closed') {
    return false
  }
  const status = meta.status
  if (status === 'running' || status === 'failed' || status === 'stopped') return false
  if (status === 'exited') return meta.exit_code === 0
  const code = meta.exit_code
  if (typeof code === 'number') return code === 0
  return true
}

/**
 * Tool-card host. Builds a normalised render context from a `ToolBlock`,
 * resolves a renderer from the registry, and renders Header + (optional)
 * Output/Footer inside a collapsible shell. Expand state is persisted via
 * `useDisclosure` so it survives remounts.
 *
 * Auto-open/close rules (mirror Tanzo tool-card.tsx):
 *  - running shell → auto-open (so the user sees streaming stdout live)
 *  - shell that exited 0 → auto-close (success collapses, noise recedes)
 *  - any failure stays open
 * User interaction overrides auto behaviour.
 */
export const ToolCard = memo(function ToolCard({
  block,
  className
}: ToolCardProps): React.JSX.Element | null {
  const ctx = useMemo(() => buildToolRenderContext(block), [block])
  const disclosureKey = `tool:${ctx.toolCallId}`
  const [storedOpen, setDisclosureOpen, hasStoredOpen] = useDisclosure(
    disclosureKey,
    ctx.state === 'error'
  )
  const autoOpenedRef = useRef(false)
  const userInteractedRef = useRef(false)

  const isShell = SHELL_TOOL_NAMES.has(ctx.toolName) || ctx.isCommand
  const shouldAutoOpen = isShell && ctx.state === 'running'
  const shouldAutoClose = isShell && ctx.state === 'success' && isSuccessfulShell(ctx)

  const setUserOpen = useCallback(
    (next: boolean) => {
      userInteractedRef.current = true
      setDisclosureOpen(next)
    },
    [setDisclosureOpen]
  )

  useEffect(() => {
    if (!shouldAutoOpen || hasStoredOpen || userInteractedRef.current) return
    autoOpenedRef.current = true
    setDisclosureOpen(true)
  }, [hasStoredOpen, setDisclosureOpen, shouldAutoOpen])

  useEffect(() => {
    if (!shouldAutoClose || !autoOpenedRef.current || userInteractedRef.current) return
    autoOpenedRef.current = false
    setDisclosureOpen(false)
  }, [setDisclosureOpen, shouldAutoClose])

  const renderer = resolveToolRenderer(ctx)
  const HeaderComp = renderer?.Header ?? null
  const OutputComp = renderer?.Output ?? null
  const FooterComp = renderer?.Footer ?? null

  const hasOutput = ctx.output !== undefined && ctx.output.trim().length > 0
  const canExpand = hasOutput || Boolean(renderer?.Output) || ctx.state === 'running'
  const renderOutput =
    ctx.errorText !== undefined ||
    hasOutput ||
    Boolean(renderer?.renderWhenPending) ||
    !isPendingState(ctx.state)

  const open = canExpand && (ctx.state === 'running' ? true : storedOpen)
  const Icon = pickIcon(ctx.toolName, ctx.isFileChange, ctx.isCommand)

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
      label={ctx.label || ctx.shortName}
      title={ctx.description || undefined}
      state={ctx.state}
      expanded={open}
      canExpand={canExpand}
    />
  )

  const handleToggle = useCallback(() => {
    if (!canExpand || ctx.state === 'running') return
    setUserOpen(!open)
  }, [canExpand, ctx.state, open, setUserOpen])

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
    tabIndex: canExpand && ctx.state !== 'running' ? 0 : undefined,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (canExpand && ctx.state !== 'running' && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault()
        handleToggle()
      }
    }
  }

  // Lightweight row: a quiet line on the work-process rail.
  if (!isHeavy) {
    return (
      <div id={`block-${block.id}`} className="group">
        <div
          className={cn(
            'flex items-center rounded-md px-1.5 py-1 -mx-1',
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
        'group overflow-hidden rounded-[14px] border',
        ctx.state === 'error'
          ? 'border-red-300/70 bg-red-500/5 dark:border-red-800/40 dark:bg-red-950/20'
          : ctx.state === 'running'
            ? 'border-amber-300/60 bg-amber-500/5 dark:border-amber-800/40 dark:bg-amber-950/15'
            : 'border-ds-border bg-ds-card/60',
        className
      )}
    >
      <div
        className={cn(
          'flex items-center px-3 py-2',
          canExpand && ctx.state !== 'running' ? 'cursor-pointer hover:bg-ds-hover/40' : ''
        )}
        {...interactionProps}
      >
        {headerElement}
      </div>
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
