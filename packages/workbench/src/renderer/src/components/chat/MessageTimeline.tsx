import type { ReactElement, RefObject } from 'react'
import type { LucideIcon } from 'lucide-react'
import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  FileEdit,
  FileText,
  FolderOpen,
  GitFork,
  Loader2,
  PencilLine,
  Search,
  Terminal,
  Wrench,
  X
} from 'lucide-react'
import { TaskSuggestionHero, TaskSuggestionOfflineHero } from './TaskSuggestionHero'
import type {
  ChatBlock,
  RuntimeConnectionStatus,
  ToolBlock,
  UserInputAnswer,
  UserInputQuestion
} from '../../agent/types'
import {
  countDiffStats,
  extractDiffFilePath,
  formatFilePathForDisplay,
  looksLikeUnifiedDiff,
  sumDiffStats
} from '../../lib/diff-stats'
import { useDeferredRender } from '../../hooks/use-deferred-render'
import { useChatStore } from '../../store/chat-store'
import { getProvider } from '../../agent/registry'
import { DiffView } from '../DiffView'
import { ApprovalBubble } from './ApprovalBubble'
import { EvolutionBubble } from './EvolutionBubble'
import { ElevationBubble } from './ElevationBubble'
import { InlineTodoBlock } from './InlineTodoBlock'
import { WorkflowBlock } from './WorkflowBlock'
import {
  ToolCard,
  registerToolRenderers,
  buildToolRenderContext,
  humanizeToolName,
  SHELL_TOOL_NAMES
} from './tool'
import { ToolCopyButton } from './tool/primitives'

// Register the built-in tool renderers once at module load. Idempotent: the
// registry overwrites prior entries, so re-imports are safe.
registerToolRenderers()
import {
  buildTodoEventsForTurn,
  buildTodoSessionForTurn,
  isTodoToolBlock,
  type TodoTurnEvent,
  type TodoTurnSession
} from '../../lib/extract-todos-from-blocks'
import { sanitizeReasoningPlaceholders } from '../../lib/reasoning-text'

const LazyStreamdownAssistant = lazy(() =>
  import('./StreamdownAssistant').then((module) => ({ default: module.StreamdownAssistant }))
)

type Props = {
  blocks: ChatBlock[]
  liveReasoning: string
  live: string
  activeThreadId: string | null
  runtimeConnection: RuntimeConnectionStatus
  onRetryConnection: () => void
  onOpenSettings: () => void
  onOpenDiagnostics: () => void
  onSelectSuggestion?: (prompt: string) => void
  devPreviewCard?: ReactElement | null
  stageCentered?: boolean
  useChatStageWidth?: boolean
  withOperationColumn?: boolean
}

type Turn = {
  user?: Extract<ChatBlock, { kind: 'user' }>
  blocks: ChatBlock[]
}

const COPY_FEEDBACK_RESET_MS = 1600
const TURN_PAGE_SIZE = 18
const AUTO_COLLAPSE_THRESHOLD = 24
const TOP_LOAD_TRIGGER_PX = 120

type AssistantMarkdownProps = {
  text: string
  streaming: boolean
  className?: string
}

/**
 * Above this many characters a single Markdown block is parsed/rendered behind a
 * "show full" toggle. A multi-MB payload in one node can lock up the render
 * thread (the parser + the resulting DOM are both O(n)); collapsing by default
 * keeps the timeline responsive while leaving the full text one click away.
 * Live streams are never truncated — they are bounded by the model's output and
 * the user is actively watching them grow.
 */
const INLINE_MARKDOWN_MAX_CHARS = 80_000

function useBoundedText(
  text: string,
  streaming: boolean
): { shown: string; overLimit: boolean; expanded: boolean; remaining: number; toggle: () => void } {
  const [expanded, setExpanded] = useState(false)
  const overLimit = !streaming && text.length > INLINE_MARKDOWN_MAX_CHARS
  const shown = overLimit && !expanded ? text.slice(0, INLINE_MARKDOWN_MAX_CHARS) : text
  const toggle = useCallback(() => setExpanded((v) => !v), [])
  return {
    shown,
    overLimit,
    expanded,
    remaining: Math.max(0, text.length - INLINE_MARKDOWN_MAX_CHARS),
    toggle
  }
}

function ShowFullToggle({
  expanded,
  remaining,
  onToggle
}: {
  expanded: boolean
  remaining: number
  onToggle: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <button
      type="button"
      onClick={onToggle}
      className="mt-1 w-fit rounded-md border border-ds-border-muted bg-ds-card/90 px-2 py-0.5 text-[11px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
    >
      {expanded ? t('inlineTextCollapse') : t('inlineTextShowFull', { count: remaining })}
    </button>
  )
}

function AssistantMarkdown({
  text,
  streaming,
  className
}: AssistantMarkdownProps): ReactElement {
  const { shown, overLimit, expanded, remaining, toggle } = useBoundedText(text, streaming)
  return (
    <>
      <Suspense
        fallback={
          <div className={className}>
            {shown}
          </div>
        }
      >
        <LazyStreamdownAssistant text={shown} streaming={streaming} className={className} />
      </Suspense>
      {overLimit ? (
        <ShowFullToggle expanded={expanded} remaining={remaining} onToggle={toggle} />
      ) : null}
    </>
  )
}

function BoundedReasoningMarkdown({ text }: { text: string }): ReactElement {
  const { shown, overLimit, expanded, remaining, toggle } = useBoundedText(text, false)
  return (
    <>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{shown}</ReactMarkdown>
      {overLimit ? (
        <ShowFullToggle expanded={expanded} remaining={remaining} onToggle={toggle} />
      ) : null}
    </>
  )
}

export function MessageTimeline({
  blocks,
  liveReasoning,
  live,
  activeThreadId,
  runtimeConnection,
  onRetryConnection,
  onOpenSettings,
  onOpenDiagnostics,
  onSelectSuggestion,
  devPreviewCard,
  stageCentered = false,
  useChatStageWidth = true,
  withOperationColumn = false
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const chooseWorkspace = useChatStore((s) => s.chooseWorkspace)
  const busy = useChatStore((s) => s.busy)
  const currentTurnUserId = useChatStore((s) => s.currentTurnUserId)
  const turnStartedAtByUserId = useChatStore((s) => s.turnStartedAtByUserId)
  const turnDurationByUserId = useChatStore((s) => s.turnDurationByUserId)
  const turnReasoningFirstAtByUserId = useChatStore((s) => s.turnReasoningFirstAtByUserId)
  const turnReasoningLastAtByUserId = useChatStore((s) => s.turnReasoningLastAtByUserId)
  const scrollToBlockId = useChatStore((s) => s.scrollToBlockId)
  const clearScrollTarget = useChatStore((s) => s.clearScrollTarget)
  const hasContent = blocks.length > 0 || live || liveReasoning
  const endRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const pendingPrependRef = useRef<{ scrollHeight: number; scrollTop: number } | null>(null)
  const prependInFlightRef = useRef(false)
  const scrollFrameRef = useRef<number | null>(null)
  const turns = useMemo(() => groupTurns(blocks), [blocks])
  const shouldCollapseHistory = turns.length > AUTO_COLLAPSE_THRESHOLD
  const [visibleTurnCount, setVisibleTurnCount] = useState(() =>
    shouldCollapseHistory ? TURN_PAGE_SIZE : turns.length
  )
  const hiddenTurnCount = Math.max(0, turns.length - visibleTurnCount)
  const visibleTurns = useMemo(
    () => (hiddenTurnCount > 0 ? turns.slice(hiddenTurnCount) : turns),
    [hiddenTurnCount, turns]
  )

  const loadEarlierTurns = useCallback((): void => {
    if (hiddenTurnCount === 0 || prependInFlightRef.current) return
    const el = containerRef.current
    if (el) {
      pendingPrependRef.current = {
        scrollHeight: el.scrollHeight,
        scrollTop: el.scrollTop
      }
    }
    prependInFlightRef.current = true
    setVisibleTurnCount((count) => Math.min(turns.length, count + TURN_PAGE_SIZE))
  }, [hiddenTurnCount, turns.length])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onScroll = (): void => {
      const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      stickToBottomRef.current = distanceToBottom < 96
      if (hiddenTurnCount > 0 && el.scrollTop <= TOP_LOAD_TRIGGER_PX) {
        loadEarlierTurns()
      }
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [hiddenTurnCount, loadEarlierTurns])

  useEffect(() => {
    if (!stickToBottomRef.current) return
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null
      endRef.current?.scrollIntoView({
        behavior: live || liveReasoning ? 'auto' : 'smooth',
        block: 'end'
      })
    })
  }, [blocks, live, liveReasoning])

  useEffect(() => {
    stickToBottomRef.current = true
    pendingPrependRef.current = null
    prependInFlightRef.current = false
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
      scrollFrameRef.current = null
    }
    endRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' })
  }, [activeThreadId])

  useEffect(() => {
    if (!currentTurnUserId) return
    stickToBottomRef.current = true
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null
      endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    })
  }, [currentTurnUserId])

  useEffect(() => {
    if (!scrollToBlockId) return
    const target = document.getElementById(`block-${scrollToBlockId}`)
    if (target) {
      stickToBottomRef.current = false
      target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    clearScrollTarget()
  }, [clearScrollTarget, scrollToBlockId])

  useEffect(
    () => () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current)
      }
    },
    []
  )

  useEffect(() => {
    setVisibleTurnCount(shouldCollapseHistory ? TURN_PAGE_SIZE : turns.length)
  }, [activeThreadId, shouldCollapseHistory, turns.length])

  useEffect(() => {
    if (!busy) return
    setVisibleTurnCount((count) => Math.max(count, turns.length))
  }, [busy, turns.length])

  useEffect(() => {
    const snapshot = pendingPrependRef.current
    const el = containerRef.current
    if (!snapshot || !el) return

    pendingPrependRef.current = null
    prependInFlightRef.current = false

    requestAnimationFrame(() => {
      const addedHeight = el.scrollHeight - snapshot.scrollHeight
      el.scrollTop = snapshot.scrollTop + Math.max(0, addedHeight)
    })
  }, [visibleTurnCount])

  useEffect(() => {
    const el = containerRef.current
    if (!el || hiddenTurnCount === 0 || prependInFlightRef.current) return
    if (el.scrollHeight <= el.clientHeight + TOP_LOAD_TRIGGER_PX) {
      loadEarlierTurns()
    }
  }, [hiddenTurnCount, loadEarlierTurns, visibleTurnCount])

  const showEmptyHeroOnly =
    (!activeThreadId || (activeThreadId && !hasContent)) && hiddenTurnCount === 0

  return (
    <div
      ref={containerRef}
      className={`ds-no-drag flex min-w-0 flex-col overflow-x-hidden ${
        stageCentered && showEmptyHeroOnly
          ? 'shrink-0 overflow-visible'
          : 'min-h-0 flex-1 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden'
      }`}
    >
      <div
        className={`flex w-full min-w-0 flex-col gap-6 ${
          useChatStageWidth ? 'ds-chat-stage px-3 sm:px-4' : 'max-w-none px-0'
        } ${showEmptyHeroOnly ? 'pb-0 pt-0' : withOperationColumn ? 'ds-timeline-with-operation pb-4' : 'pb-4 pt-2'}`}
      >
        {!activeThreadId && (
          <EmptyHero
            ready={runtimeConnection === 'ready'}
            hasWorkspace={!!workspaceRoot}
            onPickWorkspace={() => void chooseWorkspace()}
            onRetry={onRetryConnection}
            onOpenSettings={onOpenSettings}
            onOpenDiagnostics={onOpenDiagnostics}
            onSelectSuggestion={onSelectSuggestion}
          />
        )}

        {activeThreadId && !hasContent && (
          <EmptyHero
            ready={runtimeConnection === 'ready'}
            hasWorkspace={!!workspaceRoot}
            onPickWorkspace={() => void chooseWorkspace()}
            onRetry={onRetryConnection}
            onOpenSettings={onOpenSettings}
            onOpenDiagnostics={onOpenDiagnostics}
            onSelectSuggestion={onSelectSuggestion}
          />
        )}

        {hiddenTurnCount > 0 ? (
          <div className="flex items-center justify-center">
            <button
              type="button"
              onClick={loadEarlierTurns}
              className="ds-chip rounded-full px-4 py-2 text-[13px] font-medium text-ds-muted transition hover:text-ds-ink"
            >
              {t('timelineShowEarlierTurns', { count: Math.min(hiddenTurnCount, TURN_PAGE_SIZE) })}
            </button>
          </div>
        ) : null}

        {visibleTurns.map((turn, index) => {
          const userId = turn.user?.id
          const isLive = !!(userId && currentTurnUserId === userId)
          const startedAt = userId ? turnStartedAtByUserId[userId] : undefined
          const recordedDuration = userId ? turnDurationByUserId[userId] : undefined
          const liveStartedAt =
            isLive && typeof startedAt === 'number' ? startedAt : undefined
          const durationMs = isLive ? undefined : recordedDuration
          const reasoningFirst = userId ? turnReasoningFirstAtByUserId[userId] : undefined
          const reasoningLast = userId ? turnReasoningLastAtByUserId[userId] : undefined
          const reasoningDurationMs =
            typeof reasoningFirst === 'number' && typeof reasoningLast === 'number'
              ? Math.max(0, reasoningLast - reasoningFirst)
              : undefined
          const turnPending = turnHasPendingRuntimeWork(turn)
          const isLatestTurn = index === visibleTurns.length - 1
          const hasLiveStream = isLatestTurn && !!(liveReasoning.trim() || live.trim())
          return (
            <MemoMessageTurn
              key={userId ?? `turn-${index}`}
              turn={turn}
              isProcessing={(busy && isLatestTurn) || turnPending || hasLiveStream}
              liveReasoning={isLatestTurn ? liveReasoning : ''}
              live={isLatestTurn ? live : ''}
              liveStartedAt={liveStartedAt}
              durationMs={durationMs}
              reasoningDurationMs={reasoningDurationMs}
              devPreviewCard={isLatestTurn ? devPreviewCard : null}
              viewportRef={containerRef}
            />
          )
        })}

        {hiddenTurnCount === 0 && shouldCollapseHistory && turns.length > TURN_PAGE_SIZE && !busy ? (
          <div className="flex items-center justify-center">
            <button
              type="button"
              onClick={() => setVisibleTurnCount(TURN_PAGE_SIZE)}
              className="rounded-full px-3 py-1.5 text-[12.5px] font-medium text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            >
              {t('timelineCollapseEarlierTurns')}
            </button>
          </div>
        ) : null}

        {blocks.length === 0 && (live || liveReasoning) ? (
          <MemoMessageTurn
            turn={{ blocks: [] }}
            isProcessing={busy}
            liveReasoning={liveReasoning}
            live={live}
            devPreviewCard={devPreviewCard}
            viewportRef={containerRef}
            liveStartedAt={
              currentTurnUserId &&
              typeof turnStartedAtByUserId[currentTurnUserId] === 'number'
                ? turnStartedAtByUserId[currentTurnUserId]
                : undefined
            }
            reasoningDurationMs={(() => {
              if (!currentTurnUserId) return undefined
              const first = turnReasoningFirstAtByUserId[currentTurnUserId]
              const last = turnReasoningLastAtByUserId[currentTurnUserId]
              if (typeof first !== 'number' || typeof last !== 'number') return undefined
              return Math.max(0, last - first)
            })()}
          />
        ) : null}
        <div ref={endRef} aria-hidden className="h-px w-full shrink-0" />
      </div>
    </div>
  )
}

function EmptyHero({
  ready,
  hasWorkspace,
  onPickWorkspace,
  onRetry,
  onOpenSettings,
  onOpenDiagnostics,
  onSelectSuggestion
}: {
  ready: boolean
  hasWorkspace: boolean
  onPickWorkspace: () => void
  onRetry: () => void
  onOpenSettings: () => void
  onOpenDiagnostics: () => void
  onSelectSuggestion?: (prompt: string) => void
}): ReactElement {
  const { t } = useTranslation('common')

  if (!ready) {
    return (
      <TaskSuggestionOfflineHero
        onRetry={onRetry}
        onOpenSettings={onOpenSettings}
        onOpenDiagnostics={onOpenDiagnostics}
      />
    )
  }

  if (!hasWorkspace) {
    return (
      <div className="ds-no-drag flex flex-col items-center justify-center px-6 py-24 text-center">
        <FolderOpen className="mb-4 h-8 w-8 text-ds-muted" strokeWidth={1.6} />
        <h1 className="ds-hero-title">{t('selectWorkspace')}</h1>
        <p className="ds-hero-sub mt-3 max-w-sm">{t('emptyHeroSubNoWorkspace')}</p>
        <button
          type="button"
          className="ds-chip mt-5 rounded-full px-5 py-2.5 text-[13px] font-medium text-ds-ink transition hover:text-ds-ink"
          onClick={onPickWorkspace}
        >
          {t('selectWorkspace')}
        </button>
      </div>
    )
  }

  return <TaskSuggestionHero onSelectSuggestion={onSelectSuggestion} />
}

function groupTurns(blocks: ChatBlock[]): Turn[] {
  const turns: Turn[] = []
  let current: Turn | null = null

  for (const block of blocks) {
    // System events (context compaction, turn errors) are not part of any
    // dialogue turn — render them as standalone dividers between turns,
    // otherwise they get embedded inside an adjacent turn (e.g. between a
    // user message and the assistant reply), which reads as an interruption.
    if (block.kind === 'system') {
      if (current) turns.push(current)
      current = null
      turns.push({ blocks: [block] })
      continue
    }
    if (block.kind === 'user') {
      if (current) turns.push(current)
      current = { user: block, blocks: [] }
      continue
    }
    if (!current) current = { blocks: [] }
    current.blocks.push(block)
  }

  if (current) turns.push(current)
  return turns
}

const THINK_TAG_RE = /<think(?:ing)?>([\s\S]*?)(?:<\/(?:think(?:ing)?|redacted_thinking)>|$)/i

export function splitThink(text: string): { think: string; content: string } {
  const tagged = text.match(THINK_TAG_RE)
  if (!tagged) return { think: '', content: sanitizeReasoningPlaceholders(text) }
  return {
    think: sanitizeReasoningPlaceholders(tagged[1]),
    content: sanitizeReasoningPlaceholders(text.replace(THINK_TAG_RE, ''))
  }
}

function blockHasPendingRuntimeWork(block: ChatBlock): boolean {
  if (block.kind === 'tool') return block.status === 'running'
  if (block.kind === 'approval') return block.status === 'pending'
  if (block.kind === 'evolution') return block.status === 'pending'
  if (block.kind === 'user_input') return block.status === 'pending'
  if (block.kind === 'subagent') {
    return block.status === 'pending' || block.status === 'running'
  }
  if (block.kind === 'workflow') return block.status === 'running'
  return false
}

function blockNeedsAttention(block: ChatBlock): boolean {
  if (blockHasPendingRuntimeWork(block)) return true
  if (block.kind === 'tool') return block.status === 'error'
  if (block.kind === 'approval') return block.status === 'error'
  if (block.kind === 'user_input') return block.status === 'error'
  if (block.kind === 'subagent') return block.status === 'failed' || block.status === 'cancelled'
  if (block.kind === 'workflow') return block.status === 'failed' || block.status === 'cancelled'
  return false
}

function isWorkflowBlock(block: ChatBlock): boolean {
  return block.kind === 'workflow'
}

function isProcessBlock(block: ChatBlock): boolean {
  return (
    block.kind === 'reasoning' ||
    block.kind === 'tool' ||
    block.kind === 'workflow' ||
    block.kind === 'approval' ||
    block.kind === 'user_input' ||
    block.kind === 'subagent' ||
    block.kind === 'system'
  )
}

function turnHasPendingRuntimeWork(turn: Turn): boolean {
  return turn.blocks.some(blockHasPendingRuntimeWork)
}

const TURN_EPILOGUE_TOOL_RE = /(?:todo|checklist)_(?:update|write|add|list)$/i
const SUBAGENT_ORCHESTRATION_TOOL_RE =
  /^(?:agent_spawn|spawn_agent|delegate_to_agent|agent_wait|wait|agent_result|agent_list)$/i

function toolNameFromProcessBlock(block: Extract<ChatBlock, { kind: 'tool' }>): string {
  const metaName = typeof block.meta?.tool_name === 'string' ? block.meta.tool_name : undefined
  if (metaName) return metaName
  const summary = block.summary.trim()
  return summary.split(/[:(]/, 1)[0]?.trim() ?? ''
}

export function isSubagentOrchestrationToolName(name: string | undefined): boolean {
  return !!name && SUBAGENT_ORCHESTRATION_TOOL_RE.test(name.trim())
}

function isTurnEpilogueBlock(block: ChatBlock): boolean {
  if (block.kind !== 'tool') return false
  const toolName = toolNameFromProcessBlock(block)
  if (TURN_EPILOGUE_TOOL_RE.test(toolName)) return true
  return TURN_EPILOGUE_TOOL_RE.test(block.summary.trim().split(/[:(]/, 1)[0]?.trim() ?? '')
}

function findTrailingAssistantContentStart(blocks: ChatBlock[]): number {
  let scanEnd = blocks.length
  while (scanEnd > 0 && isTurnEpilogueBlock(blocks[scanEnd - 1]!)) {
    scanEnd -= 1
  }

  let start = scanEnd
  for (let index = scanEnd - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (block.kind !== 'assistant') break

    const split = splitThink(block.text)
    if (!split.content.trim()) break
    start = index
  }

  return start
}

type AssistantContentBlock = Extract<ChatBlock, { kind: 'assistant' }>

function isFinalAnswerAssistantBlock(block: ChatBlock): block is AssistantContentBlock {
  return block.kind === 'assistant' && block.agentSegment === 'final_answer'
}

export function placeAssistantContentBlock(
  block: AssistantContentBlock,
  contentBlock: AssistantContentBlock,
  options: {
    hasExplicitFinalAnswer: boolean
    isProcessing: boolean
    index: number
    trailingAssistantContentStart: number
  },
  nextProcessBlocks: ChatBlock[],
  nextAssistantContentBlocks: AssistantContentBlock[]
): void {
  // Mid-turn model prefaces are the storyline the user follows while tools
  // execute. Keep them in the work trace for finished turns too, so reopening
  // history shows the same throughline the user saw live.
  if (block.agentSegment === 'mid_turn_preface') {
    nextProcessBlocks.push(contentBlock)
    return
  }
  if (options.hasExplicitFinalAnswer) {
    if (block.agentSegment === 'final_answer') {
      nextAssistantContentBlocks.push(contentBlock)
    } else {
      nextProcessBlocks.push(contentBlock)
    }
    return
  }
  if (
    !options.isProcessing &&
    options.index >= options.trailingAssistantContentStart
  ) {
    nextAssistantContentBlocks.push(contentBlock)
  } else {
    nextProcessBlocks.push(contentBlock)
  }
}

export function reasoningDetailTextFromBlocks(blocks: ChatBlock[]): string {
  if (reasoningNarrationFromBlocks(blocks)) return ''
  return blocks
    .filter(
      (block): block is Extract<ChatBlock, { kind: 'reasoning' }> => block.kind === 'reasoning'
    )
    .map((block) => block.text.trim())
    .filter(Boolean)
    .join('\n\n')
}

export function reasoningNarrationFromBlocks(blocks: ChatBlock[]): string {
  for (const block of blocks) {
    if (block.kind === 'reasoning' && block.narration?.trim()) {
      return block.narration.trim()
    }
  }
  return ''
}

export function findFallbackFinalAnswer(
  blocks: ChatBlock[]
): Extract<ChatBlock, { kind: 'assistant' }> | null {
  if (blocks.some(isFinalAnswerAssistantBlock)) return null
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (
      block?.kind === 'assistant' &&
      block.agentSegment !== 'mid_turn_preface' &&
      block.text.trim()
    ) {
      return {
        ...block,
        text: block.text.trim(),
        agentSegment: 'final_answer'
      }
    }
  }
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (block?.kind === 'reasoning' && block.text.trim()) {
      return {
        kind: 'assistant',
        id: block.id,
        createdAt: block.createdAt,
        text: block.text.trim(),
        agentSegment: 'final_answer'
      }
    }
  }
  return null
}

function MessageTurn({
  turn,
  isProcessing,
  liveReasoning,
  live,
  liveStartedAt,
  durationMs,
  reasoningDurationMs,
  devPreviewCard,
  viewportRef
}: {
  turn: Turn
  isProcessing: boolean
  liveReasoning: string
  live: string
  liveStartedAt?: number
  durationMs?: number
  reasoningDurationMs?: number
  devPreviewCard?: ReactElement | null
  viewportRef: RefObject<HTMLDivElement | null>
}): ReactElement {
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const { think: liveThink, content: liveContent } = splitThink(live)
  const liveProcessText = [liveReasoning, liveThink].filter(Boolean).join('\n\n')
  const hasLiveAssistantStream = isProcessing && !!liveContent.trim()
  const [workExpanded, setWorkExpanded] = useState(isProcessing)

  useEffect(() => {
    setWorkExpanded(isProcessing)
  }, [isProcessing])

  const todoSession = useMemo(() => buildTodoSessionForTurn(turn.blocks), [turn.blocks])
  const todoEvents = useMemo(() => buildTodoEventsForTurn(turn.blocks), [turn.blocks])
  const subagentSummary = useMemo(() => buildSubagentSummaryForTurn(turn.blocks), [turn.blocks])

  const { processBlocks, assistantContentBlocks, turnFileChanges, systemBlocks } = useMemo(() => {
    const nextProcessBlocks: ChatBlock[] = []
    const nextSystemBlocks: Array<Extract<ChatBlock, { kind: 'system' }>> = []
    const nextAssistantContentBlocks: Array<Extract<ChatBlock, { kind: 'assistant' }>> = []
    const hasExplicitFinalAnswer = turn.blocks.some(isFinalAnswerAssistantBlock)
    const trailingAssistantContentStart = isProcessing
      ? turn.blocks.length
      : findTrailingAssistantContentStart(turn.blocks)

    for (const [index, block] of turn.blocks.entries()) {
      if (block.kind === 'assistant') {
        const split = splitThink(block.text)
        if (split.think) {
          nextProcessBlocks.push({ kind: 'reasoning', id: `${block.id}-think`, text: split.think })
        }
        if (split.content.trim()) {
          const contentBlock = { ...block, text: split.content }
          placeAssistantContentBlock(
            block,
            contentBlock,
            {
              hasExplicitFinalAnswer,
              isProcessing,
              index,
              trailingAssistantContentStart
            },
            nextProcessBlocks,
            nextAssistantContentBlocks
          )
        }
        continue
      }
      if (block.kind === 'system') {
        nextSystemBlocks.push(block)
        continue
      }
      if (isProcessBlock(block)) {
        nextProcessBlocks.push(block)
      }
    }

    if (liveProcessText.trim()) {
      nextProcessBlocks.push({ kind: 'reasoning', id: 'live-reasoning', text: liveProcessText })
    }

    // The in-flight `agent_message` streams into `liveContent` for BOTH a
    // mid-turn preface and the final answer (deltas carry no item id, and the
    // backend itself only classifies the segment at completion). Stream it live
    // inside the work trace in the small process style. When the segment
    // settles, the store clears `liveAssistant`: a preface persists as a small
    // trace row, and a final answer arrives through `onFinalAnswer` to render as
    // the big bubble below (`showLiveAssistant`).
    if (hasLiveAssistantStream) {
      nextProcessBlocks.push({ kind: 'assistant', id: 'live-assistant', text: liveContent })
    }

    const nextTurnFileChanges = !isProcessing
      ? turn.blocks.flatMap((block): ToolBlock[] => {
          if (
            !(block.kind === 'tool' && block.toolKind === 'file_change' && block.status === 'success')
          ) {
            return []
          }

          const detailText = block.detail?.trim() ?? ''
          if (!looksLikeUnifiedDiff(detailText)) return []

          const resolvedFilePath = formatFilePathForDisplay(
            extractDiffFilePath(detailText, block.filePath),
            workspaceRoot
          )
          if (!resolvedFilePath) return []

          return [{ ...block, filePath: resolvedFilePath }]
        })
      : []

    if (!isProcessing) {
      const fallbackAnswer = findFallbackFinalAnswer(turn.blocks)
      return {
        processBlocks: nextProcessBlocks,
        assistantContentBlocks:
          nextAssistantContentBlocks.length > 0 || !fallbackAnswer
            ? nextAssistantContentBlocks
            : [fallbackAnswer],
        turnFileChanges: nextTurnFileChanges,
        systemBlocks: nextSystemBlocks
      }
    }

    return {
      processBlocks: nextProcessBlocks,
      assistantContentBlocks: nextAssistantContentBlocks,
      turnFileChanges: nextTurnFileChanges,
      systemBlocks: nextSystemBlocks
    }
  }, [turn.blocks, isProcessing, liveProcessText, hasLiveAssistantStream, liveContent, workspaceRoot])

  const showLiveAssistant = !isProcessing && !!liveContent.trim()

  const isSystemOnlyTurn =
    !turn.user &&
    systemBlocks.length > 0 &&
    processBlocks.length === 0 &&
    assistantContentBlocks.length === 0

  const hasProcess = !isSystemOnlyTurn && (isProcessing || processBlocks.length > 0)

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {turn.user ? <MessageBubble block={turn.user} /> : null}

      {isSystemOnlyTurn ? (
        <div className="flex flex-col items-center gap-1 py-1">
          {systemBlocks.map((b) => (
            <div
              key={b.id}
              className="max-w-full rounded-full border border-ds-border-muted bg-ds-card/60 px-3 py-1 text-center text-[12px] text-ds-faint"
            >
              {b.text}
            </div>
          ))}
        </div>
      ) : (
        <>
          {hasProcess ? (
            <div className="flex flex-col gap-1 pb-2">
              <WorkMetaRow
                processing={isProcessing}
                stepCount={processBlocks.length}
                liveStartedAt={liveStartedAt}
                durationMs={durationMs}
                reasoningDurationMs={reasoningDurationMs}
                expanded={workExpanded}
                onToggle={() => setWorkExpanded((value) => !value)}
                activeWorkflowName={processBlocks.find((b): b is ChatBlock & { kind: 'workflow'; workflowName: string } => b.kind === 'workflow' && b.status === 'running')?.workflowName}
                activeActionLabel={activeRunningActionLabel(processBlocks)}
              />
              {workExpanded ? (
                <ProcessStream
                  blocks={processBlocks}
                  processing={isProcessing}
                  todoSession={todoSession}
                  todoEvents={todoEvents}
                  subagentSummary={subagentSummary}
                />
              ) : null}
            </div>
          ) : null}

          {systemBlocks.length > 0 ? (
            <div className="flex flex-col gap-1">
              {systemBlocks.map((b) => (
                <div
                  key={b.id}
                  className="rounded-md border border-ds-border-muted bg-ds-card/60 px-3 py-1.5 text-[12px] text-ds-faint"
                >
                  {b.text}
                </div>
              ))}
            </div>
          ) : null}

          {!workExpanded && todoSession ? (
            <InlineTodoBlock
              session={todoSession}
              active={isProcessing && !todoSession.isComplete}
              className="pb-1"
            />
          ) : null}

          {assistantContentBlocks.map((block) => (
            <MessageBubble key={block.id} block={block} />
          ))}

          {showLiveAssistant ? (
            <MessageBubble block={{ kind: 'assistant', id: 'live-assistant', text: liveContent }} />
          ) : null}

          {!isProcessing && devPreviewCard ? devPreviewCard : null}

          {!isProcessing && turnFileChanges.length > 0 ? (
            <TurnChangeSummary changes={turnFileChanges} viewportRef={viewportRef} />
          ) : null}
        </>
      )}
    </div>
  )
}

const MemoMessageTurn = memo(MessageTurn, (prev, next) => (
  prev.turn === next.turn &&
  prev.isProcessing === next.isProcessing &&
  prev.liveReasoning === next.liveReasoning &&
  prev.live === next.live &&
  prev.liveStartedAt === next.liveStartedAt &&
  prev.durationMs === next.durationMs &&
  prev.reasoningDurationMs === next.reasoningDurationMs &&
  prev.devPreviewCard === next.devPreviewCard &&
  prev.viewportRef === next.viewportRef
))

function TurnChangeSummary({
  changes,
  viewportRef
}: {
  changes: ToolBlock[]
  viewportRef: RefObject<HTMLDivElement | null>
}): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(
    () => changes.find((change) => change.detail?.trim())?.id ?? changes[0]?.id ?? null
  )

  useEffect(() => {
    if (changes.length === 0) {
      setActiveId(null)
      return
    }
    setActiveId((current) => {
      if (current && changes.some((change) => change.id === current)) return current
      return changes.find((change) => change.detail?.trim())?.id ?? changes[0]?.id ?? null
    })
  }, [changes])

  const totals = useMemo(() => sumDiffStats(changes.map((change) => change.detail)), [changes])
  const title = useMemo(
    () =>
      changes.length === 1
        ? t('turnChangeFilesOne')
        : t('turnChangeFilesMany', { count: changes.length }),
    [changes.length, t]
  )
  const { ref: deferredBodyRef, shouldRender: shouldRenderBody } = useDeferredRender<HTMLDivElement>({
    enabled: expanded,
    root: viewportRef
  })

  return (
    <section className="ds-card-strong overflow-hidden rounded-[24px] border border-ds-border shadow-[0_16px_40px_rgba(86,103,136,0.08)]">
      <button
        type="button"
        onClick={() => {
          setExpanded((value) => !value)
          window.dispatchEvent(new CustomEvent('deepseekgui:open-changes-panel'))
        }}
        aria-expanded={expanded}
        className="flex w-full items-center gap-4 px-5 py-4 text-left transition hover:bg-ds-hover/40"
      >
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[16px] bg-ds-card-muted text-ds-muted">
          <FileEdit className="h-5 w-5" strokeWidth={1.85} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[18px] font-semibold tracking-[-0.02em] text-ds-ink">
            {title}
          </span>
          {totals ? (
            <span className="mt-1 block text-[12px] tabular-nums">
              <span className="text-ds-diff-added">+{totals.added}</span>
              <span className="mx-1.5 text-ds-faint">·</span>
              <span className="text-ds-diff-removed">-{totals.removed}</span>
            </span>
          ) : null}
        </span>
        {expanded ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
        )}
      </button>

      {expanded ? (
        <div
          ref={deferredBodyRef}
          className="border-t border-ds-border-muted/70"
          style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 280px' }}
        >
          {shouldRenderBody
            ? changes.map((change) => {
            const stats = countDiffStats(change.detail)
            const open = activeId === change.id
            const primary = change.filePath ?? t('toolActionFile')

            return (
              <div key={change.id} className="border-b border-ds-border-muted/60 last:border-b-0">
                <button
                  type="button"
                  onClick={() => setActiveId(open ? null : change.id)}
                  aria-expanded={open}
                  className={`flex w-full items-start gap-3 px-5 py-3 text-left transition ${
                    open ? 'bg-ds-hover/45' : 'hover:bg-ds-hover/35'
                  }`}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block break-all text-[14px] font-medium text-ds-ink">
                      {primary}
                    </span>
                  </span>
                  {stats ? (
                    <span className="shrink-0 text-[12px] tabular-nums">
                      <span className="text-ds-diff-added">+{stats.added}</span>
                      <span className="ml-1.5 text-ds-diff-removed">-{stats.removed}</span>
                    </span>
                  ) : null}
                  {open ? (
                    <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
                  ) : (
                    <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
                  )}
                </button>

                {open && change.detail ? (
                  <div className="bg-ds-card-muted/45 px-4 pb-4 pt-1">
                    <DiffView
                      patch={change.detail}
                      filePath={change.filePath}
                      maxHeight={440}
                      className="border border-ds-border-muted/70"
                    />
                  </div>
                ) : null}
              </div>
            )
          })
            : null}
        </div>
      ) : null}
    </section>
  )
}

/**
 * Live one-liner for the currently-running tool, e.g. "读取文件 src/foo.ts".
 * Surfaced on the collapsed work-process header so the user knows what the
 * agent is doing right now without expanding the trace (cursor/codex pattern).
 */
function activeRunningActionLabel(blocks: ChatBlock[]): string | undefined {
  // Skip sub-agent orchestration tools (agent_spawn/agent_wait/…): a blocking
  // agent_wait would otherwise hijack the header for minutes. Sub-agent progress
  // is surfaced by the SubagentSummaryPanel instead.
  const running = blocks.find(
    (b): b is ToolBlock =>
      b.kind === 'tool' &&
      b.status === 'running' &&
      !isSubagentOrchestrationToolName(toolNameFromProcessBlock(b))
  )
  if (!running) return undefined
  const ctx = buildToolRenderContext(running)
  const label = [ctx.label || ctx.shortName, ctx.description].filter(Boolean).join(' ').trim()
  if (!label) return undefined
  return label.length > 56 ? `${label.slice(0, 55).trimEnd()}…` : label
}

/** Turn-level work-process summary. It auto-collapses when the turn finishes. */
function WorkMetaRow({
  processing,
  stepCount,
  liveStartedAt,
  durationMs,
  reasoningDurationMs,
  expanded,
  onToggle,
  activeWorkflowName,
  activeActionLabel
}: {
  processing: boolean
  stepCount: number
  liveStartedAt?: number
  durationMs?: number
  reasoningDurationMs?: number
  expanded: boolean
  onToggle: () => void
  activeWorkflowName?: string
  activeActionLabel?: string
}): ReactElement {
  const { t } = useTranslation('common')
  const [tickNow, setTickNow] = useState(() => Date.now())

  useEffect(() => {
    if (!processing || typeof liveStartedAt !== 'number') return
    setTickNow(Date.now())
    const id = window.setInterval(() => setTickNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [processing, liveStartedAt])

  const displayDurationMs =
    processing && typeof liveStartedAt === 'number'
      ? Math.max(0, tickNow - liveStartedAt)
      : durationMs

  const durationText =
    typeof displayDurationMs === 'number' ? formatDuration(displayDurationMs) : undefined
  const liveActionText = processing && !activeWorkflowName ? activeActionLabel : undefined
  const mainLabel = processing
    ? liveActionText
      ? liveActionText
      : durationText
        ? `${t('processing')} ${durationText}`
        : t('processing')
    : durationText
      ? `${t('processed')} ${durationText}`
      : t('processSteps', { count: stepCount })

  const showThoughtSuffix =
    !processing &&
    typeof reasoningDurationMs === 'number' &&
    reasoningDurationMs >= 1000

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      className="group flex w-fit max-w-full items-center gap-1.5 rounded-md py-1 text-left text-[15px] font-medium text-ds-muted transition hover:opacity-85"
    >
      {processing ? (
        <span className="mr-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
          {activeWorkflowName ? (
            <span className="ds-workflow-spinner" />
          ) : (
            <Bot className="h-4 w-4 text-ds-faint ds-work-logo-pulse" strokeWidth={1.75} />
          )}
        </span>
      ) : null}
      <span className={`min-w-0 truncate tabular-nums ${processing ? 'ds-shiny-text' : ''}`}>
        {mainLabel}
      </span>
      {liveActionText && durationText ? (
        <span className="shrink-0 text-ds-faint">· {durationText}</span>
      ) : null}
      {activeWorkflowName ? (
        <span className="ds-workflow-tag">⚡ {activeWorkflowName}</span>
      ) : null}
      {showThoughtSuffix ? (
        <span className="text-ds-faint">
          · {t('thoughtFor', { duration: formatDuration(reasoningDurationMs!) })}
        </span>
      ) : null}
      {expanded ? (
        <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
      ) : (
        <ChevronRight
          className="h-3.5 w-3.5 shrink-0 opacity-40 transition group-hover:opacity-65"
          strokeWidth={1.8}
        />
      )}
    </button>
  )
}

function shouldHideTodoToolBlock(block: ChatBlock, todoSession: TodoTurnSession | null): boolean {
  return !!todoSession && isTodoToolBlock(block) && todoSession.todoBlockIds.includes(block.id)
}

function TodoEventRow({
  event,
  anchorBlockId
}: {
  event: TodoTurnEvent
  anchorBlockId: string
}): ReactElement {
  const { t } = useTranslation('common')
  const jumpToTodos = (): void => {
    document.getElementById(`todo-session-${anchorBlockId}`)?.scrollIntoView({
      behavior: 'smooth',
      block: 'center'
    })
  }

  return (
    <button
      type="button"
      onClick={jumpToTodos}
      className="group flex w-fit max-w-full items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1.5 text-left text-[13.5px] text-emerald-800 transition hover:bg-emerald-500/15 dark:text-emerald-200"
    >
      <Check className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
      <span className="min-w-0 truncate font-medium">
        {t('todoEventCompleted', { item: event.item.content })}
      </span>
      <span className="shrink-0 text-[12.5px] text-emerald-700/75 dark:text-emerald-200/70">
        {t('todoEventViewProgress', { done: event.done, total: event.total })}
      </span>
    </button>
  )
}

type SubagentBlock = Extract<ChatBlock, { kind: 'subagent' }>

type SubagentTurnSummary = {
  anchorBlockId: string
  blockIds: string[]
  blocks: SubagentBlock[]
  total: number
  pending: number
  running: number
  completed: number
  failed: number
  cancelled: number
}

function addSubagentStatus(
  counts: Pick<SubagentTurnSummary, 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'>,
  status: SubagentBlock['status']
): void {
  counts[status] += 1
}

function buildSubagentSummaryForTurn(blocks: ChatBlock[]): SubagentTurnSummary | null {
  const subagentBlocks = blocks.filter(
    (block): block is SubagentBlock => block.kind === 'subagent'
  )
  if (subagentBlocks.length === 0) return null

  const counts = {
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    cancelled: 0
  }
  let total = 0

  for (const block of subagentBlocks) {
    if (block.cardKind === 'fanout' && block.workers && block.workers.length > 0) {
      total += block.workers.length
      for (const worker of block.workers) {
        addSubagentStatus(counts, worker.status)
      }
      continue
    }
    total += 1
    addSubagentStatus(counts, block.status)
  }

  return {
    anchorBlockId: subagentBlocks[0]!.id,
    blockIds: subagentBlocks.map((block) => block.id),
    blocks: subagentBlocks,
    total,
    ...counts
  }
}

function shouldHideSubagentBlock(block: ChatBlock, summary: SubagentTurnSummary | null): boolean {
  return !!summary && block.kind === 'subagent' && summary.blockIds.includes(block.id)
}

function isSubagentSummaryAnchor(block: ChatBlock, summary: SubagentTurnSummary | null): boolean {
  return !!summary && block.kind === 'subagent' && block.id === summary.anchorBlockId
}

function shouldHideSubagentToolBlock(block: ChatBlock, summary: SubagentTurnSummary | null): boolean {
  if (!summary || block.kind !== 'tool' || block.status === 'error') return false
  return isSubagentOrchestrationToolName(toolNameFromProcessBlock(block))
}

function visibleExecutionBlocks(
  blocks: ChatBlock[],
  todoSession: TodoTurnSession | null,
  subagentSummary: SubagentTurnSummary | null
): ChatBlock[] {
  return blocks.filter(
    (block) =>
      !shouldHideTodoToolBlock(block, todoSession) &&
      (!shouldHideSubagentBlock(block, subagentSummary) ||
        isSubagentSummaryAnchor(block, subagentSummary)) &&
      !shouldHideSubagentToolBlock(block, subagentSummary)
  )
}

type ToolProcessBlock = Extract<ChatBlock, { kind: 'tool' }>

/**
 * Whether a process block is a successful read-only probe (read_file, list_dir,
 * grep…) that can be folded into a batch. Mirrors the `!isHeavy` rule in
 * tool-card.tsx: running / error / file mutations / shell commands stay on their
 * own row. Todo and subagent-orchestration tool calls are excluded so their
 * dedicated panels keep working.
 */
function isMergeableProbeBlock(block: ChatBlock): block is ToolProcessBlock {
  if (block.kind !== 'tool') return false
  if (block.status !== 'success') return false
  if (block.toolKind === 'file_change' || block.toolKind === 'command_execution') return false
  const name = toolNameFromProcessBlock(block)
  if (SHELL_TOOL_NAMES.has(name)) return false
  if (isTodoToolBlock(block)) return false
  if (isSubagentOrchestrationToolName(name)) return false
  return true
}

export type RenderRow =
  | { type: 'block'; block: ChatBlock }
  | { type: 'tool_batch'; toolName: string; blocks: ToolProcessBlock[] }

/**
 * Fold the visible execution blocks into render rows, collapsing runs of ≥2
 * consecutive same-name read-only probes into a single `tool_batch`. A run of
 * one stays a plain block row, and any non-mergeable block (or a different tool
 * name) ends the current run.
 */
export function groupProcessRows(visible: ChatBlock[]): RenderRow[] {
  const rows: RenderRow[] = []
  let buffer: ToolProcessBlock[] = []
  let bufferName = ''

  const flush = (): void => {
    if (buffer.length >= 2) {
      rows.push({ type: 'tool_batch', toolName: bufferName, blocks: buffer })
    } else if (buffer.length === 1) {
      rows.push({ type: 'block', block: buffer[0]! })
    }
    buffer = []
    bufferName = ''
  }

  for (const block of visible) {
    if (isMergeableProbeBlock(block)) {
      const name = toolNameFromProcessBlock(block)
      if (buffer.length > 0 && name !== bufferName) flush()
      bufferName = name
      buffer.push(block)
      continue
    }
    flush()
    rows.push({ type: 'block', block })
  }
  flush()
  return rows
}

function SubagentSummaryPanel({ summary }: { summary: SubagentTurnSummary }): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(true)
  const [detailBlock, setDetailBlock] = useState<SubagentBlock | null>(null)
  const active = summary.running > 0 || summary.pending > 0
  const hasFailure = summary.failed > 0
  const countParts = [
    summary.running > 0 ? t('subagentSummaryRunning', { count: summary.running }) : '',
    summary.completed > 0 ? t('subagentSummaryCompleted', { count: summary.completed }) : '',
    summary.failed > 0 ? t('subagentSummaryFailed', { count: summary.failed }) : '',
    summary.cancelled > 0 ? t('subagentSummaryCancelled', { count: summary.cancelled }) : ''
  ].filter(Boolean)

  return (
    <section
      className={[
        'my-2 overflow-hidden rounded-[18px] border shadow-[0_10px_28px_rgba(86,103,136,0.04)]',
        hasFailure
          ? 'border-red-300/70 bg-red-500/10 dark:border-red-800/50'
          : 'border-violet-300/45 bg-violet-500/10 dark:border-violet-800/50'
      ].join(' ')}
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="group flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-ds-hover/35"
      >
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-violet-500/15 text-violet-700 dark:text-violet-300">
          {active ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
          ) : (
            <Bot className="h-3.5 w-3.5" strokeWidth={1.8} />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-[14px] font-semibold text-ds-ink">
              {t('subagentSummaryTitle', { count: summary.total })}
            </span>
            {countParts.length > 0 ? (
              <span
                className={[
                  'text-[13px] text-ds-muted',
                  active && !hasFailure ? 'ds-shiny-text' : ''
                ].join(' ')}
              >
                {countParts.join(' · ')}
              </span>
            ) : null}
          </span>
        </span>
        {expanded ? (
          <ChevronDown className="mt-1 h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
        ) : (
          <ChevronRight
            className="mt-1 h-3.5 w-3.5 shrink-0 opacity-40 transition group-hover:opacity-65"
            strokeWidth={1.8}
          />
        )}
      </button>

      {expanded ? (
        <div className="border-t border-ds-border-muted/60 px-4 py-3">
          <div className="flex flex-col gap-2">
            {summary.blocks.map((block) => (
              <SubagentSummaryRow key={block.id} block={block} onOpen={() => setDetailBlock(block)} />
            ))}
          </div>
        </div>
      ) : null}
      {detailBlock ? (
        <SubagentDetailDialog block={detailBlock} onClose={() => setDetailBlock(null)} />
      ) : null}
    </section>
  )
}

function pickToolBatchIcon(toolName: string): LucideIcon {
  if (toolName === 'list_dir') return FolderOpen
  if (
    toolName === 'grep' ||
    toolName === 'grep_files' ||
    toolName === 'search_files' ||
    toolName === 'glob_file_search' ||
    toolName === 'file_search'
  ) {
    return Search
  }
  if (toolName === 'read_file') return FileText
  return Wrench
}

/**
 * A folded batch of consecutive same-name read-only probes (e.g. "读取文件 · 5
 * 项"). Collapsed by default with neutral styling so the work trace stays calm;
 * expanding reveals each call as its regular lightweight `ToolCard` row.
 */
function ToolBatchPanel({
  toolName,
  blocks
}: {
  toolName: string
  blocks: ToolProcessBlock[]
}): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const Icon = pickToolBatchIcon(toolName)
  const label = humanizeToolName(toolName) || toolName

  return (
    <div className="overflow-hidden rounded-[12px] border border-ds-border-muted/50 bg-ds-card/40">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="group flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition hover:bg-ds-hover/40"
      >
        <Icon className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
        <span className="min-w-0 flex-1 text-[13.5px] leading-6 text-ds-muted">
          {t('toolBatchTitle', { label, count: blocks.length })}
        </span>
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
        ) : (
          <ChevronRight
            className="h-3.5 w-3.5 shrink-0 opacity-40 transition group-hover:opacity-65"
            strokeWidth={1.8}
          />
        )}
      </button>
      {expanded ? (
        <div className="flex flex-col gap-1.5 border-t border-ds-border-muted/40 px-2.5 py-2">
          {blocks.map((block) => (
            <ToolCard key={block.id} block={block} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function SubagentSummaryRow({
  block,
  onOpen
}: {
  block: SubagentBlock
  onOpen: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const statusLabel = subagentStatusLabel(block.status, t)
  const isActive = block.status === 'running' || block.status === 'pending'
  const isTerminal = !isActive
  const statusTone =
    block.status === 'completed'
      ? 'text-emerald-700 dark:text-emerald-300'
      : block.status === 'failed'
        ? 'text-red-700 dark:text-red-300'
        : block.status === 'running'
          ? 'text-amber-800 dark:text-amber-200'
          : 'text-ds-muted'

  return (
    <button
      type="button"
      onClick={onOpen}
      className="group w-full rounded-xl border border-ds-border-muted/70 bg-ds-card/65 px-3 py-2 text-left text-[12.5px] leading-5 transition hover:border-violet-300/70 hover:bg-ds-hover/55"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-semibold text-ds-ink">
          {block.cardKind === 'fanout'
            ? t('subagentFanoutTitle', { kind: block.agentType })
            : t('subagentDelegateTitle', { type: block.agentType })}
        </span>
        {isActive ? (
          <Loader2 className="h-3 w-3 animate-spin text-amber-700 dark:text-amber-200" strokeWidth={2} />
        ) : null}
        <span className={`font-medium ${statusTone}`}>{statusLabel}</span>
        <span className="font-mono text-[11px] text-ds-faint">{block.agentId.slice(0, 10)}</span>
        <span
          className={`ml-auto text-[11px] transition ${
            isTerminal
              ? 'text-violet-600 dark:text-violet-300'
              : 'text-ds-faint opacity-0 group-hover:opacity-100'
          }`}
        >
          {t('subagentDetails')}
        </span>
      </div>
      {block.cardKind === 'fanout' && block.workers && block.workers.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {block.workers.map((worker) => (
            <span
              key={worker.id}
              title={worker.id}
              className={`inline-flex h-6 min-w-6 items-center justify-center rounded-md px-1 font-mono text-[10px] ${
                worker.status === 'completed'
                  ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                  : worker.status === 'failed'
                    ? 'bg-red-500/15 text-red-700 dark:text-red-300'
                    : worker.status === 'running'
                      ? 'bg-amber-500/15 text-amber-800 dark:text-amber-200'
                      : 'bg-ds-hover text-ds-muted'
              }`}
            >
              {worker.id.slice(-2)}
            </span>
          ))}
        </div>
      ) : null}
    </button>
  )
}

function SubagentDetailDialog({
  block,
  onClose
}: {
  block: SubagentBlock
  onClose: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const title =
    block.cardKind === 'fanout'
      ? t('subagentFanoutTitle', { kind: block.agentType })
      : t('subagentDelegateTitle', { type: block.agentType })
  const statusLabel = subagentStatusLabel(block.status, t)
  const resultTitle =
    block.status === 'failed' ? t('subagentFailureReason') : t('subagentFinalResult')
  const resultText = block.summary?.trim() ?? ''
  const hasResult = resultText.length > 0
  const finalText =
    resultText ||
    (block.status === 'running' || block.status === 'pending'
      ? t('subagentDetailNoResultRunning')
      : t('subagentDetailNoResult'))

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (typeof document === 'undefined') return <></>

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/55 px-4 py-6 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className="flex max-h-[82vh] w-full max-w-3xl flex-col overflow-hidden rounded-[22px] border border-ds-border bg-ds-elevated shadow-[0_24px_80px_rgba(15,23,42,0.35)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-start gap-3 border-b border-ds-border-muted/70 bg-ds-elevated px-5 py-4">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-violet-500/15 text-violet-700 dark:text-violet-300">
            <Bot className="h-4 w-4" strokeWidth={1.8} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <h3 className="text-[15px] font-semibold text-ds-ink">{title}</h3>
              <span className="text-[12px] font-medium text-ds-muted">{statusLabel}</span>
            </div>
            <div className="mt-0.5 font-mono text-[11px] text-ds-faint">{block.agentId}</div>
          </div>
          {hasResult ? <ToolCopyButton text={resultText} className="!opacity-100" /> : null}
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-1 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label={t('close')}
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto bg-ds-elevated px-5 py-4">
          <div className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ds-faint">
            {resultTitle}
          </div>
          <div className="ds-markdown mt-2 text-[13.5px] leading-6 text-ds-ink">
            <AssistantMarkdown text={finalText} streaming={false} />
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

/**
 * Chronological work-process stream. Replaces the old phase-grouper: blocks
 * render in the exact order the runtime emitted them, with no client-side
 * regrouping or canned labels.
 *
 * Per-block dispatch:
 *  - tool            → ToolCard (registry-resolved renderer)
 *  - reasoning       → narration line if present (model's own承上启下),
 *                      else collapsed raw reasoning
 *  - assistant       → mid-turn preface shown inline as narration
 *  - approval/elev/etc→ existing Bubble/Block components, never hidden
 *
 * The 4 `shouldHide*` patches are gone: todo/subagent were never wrong-blocked
 * because we no longer group reasoning+tools into phases that misplace them.
 */
function ProcessStream({
  blocks,
  processing,
  todoSession = null,
  todoEvents = [],
  subagentSummary = null
}: {
  blocks: ChatBlock[]
  processing: boolean
  todoSession?: TodoTurnSession | null
  todoEvents?: TodoTurnEvent[]
  subagentSummary?: SubagentTurnSummary | null
}): ReactElement {
  const visible = visibleExecutionBlocks(blocks, todoSession, subagentSummary)
  const rows = groupProcessRows(visible)

  return (
    <div className="ds-process-rail flex flex-col gap-1.5 pt-1">
      {rows.map((row) =>
        row.type === 'tool_batch' ? (
          <ToolBatchPanel
            key={`batch-${row.blocks[0]!.id}`}
            toolName={row.toolName}
            blocks={row.blocks}
          />
        ) : (
          <ProcessStreamEntry
            key={row.block.id}
            block={row.block}
            processing={processing}
            todoSession={todoSession}
            todoEvents={todoEvents}
            subagentSummary={subagentSummary}
          />
        )
      )}
    </div>
  )
}

function ProcessStreamEntry({
  block,
  processing,
  todoSession = null,
  todoEvents = [],
  subagentSummary = null
}: {
  block: ChatBlock
  processing: boolean
  todoSession?: TodoTurnSession | null
  todoEvents?: TodoTurnEvent[]
  subagentSummary?: SubagentTurnSummary | null
}): ReactElement | null {
  // Inline todo card at its anchor block.
  if (todoSession && isTodoToolBlock(block) && block.id === todoSession.anchorBlockId) {
    return (
      <InlineTodoBlock
        session={todoSession}
        active={processing && !todoSession.isComplete}
      />
    )
  }
  // Todo progress chips emitted alongside todo tool calls.
  if (todoSession) {
    const events = todoEvents.filter((event) => event.blockId === block.id)
    if (events.length > 0) {
      return (
        <div className="flex flex-col gap-1">
          {events.map((event) => (
            <TodoEventRow
              key={`${event.blockId}-${event.item.id}`}
              event={event}
              anchorBlockId={todoSession.anchorBlockId}
            />
          ))}
        </div>
      )
    }
  }
  // Hide todo tool blocks once their session is rendered inline above.
  if (todoSession && isTodoToolBlock(block) && todoSession.todoBlockIds.includes(block.id)) {
    return null
  }

  // Subagent summary card replaces the orchestration tool calls around it.
  if (subagentSummary && block.kind === 'subagent' && block.id === subagentSummary.anchorBlockId) {
    return <SubagentSummaryPanel summary={subagentSummary} />
  }
  if (subagentSummary && block.kind === 'subagent' && subagentSummary.blockIds.includes(block.id)) {
    return null
  }
  if (subagentSummary && block.kind === 'tool' && block.status !== 'error' && isSubagentOrchestrationToolName(toolNameFromProcessBlock(block))) {
    return null
  }

  // The actual content blocks.
  if (block.kind === 'tool') {
    return <ToolCard block={block} />
  }
  if (block.kind === 'reasoning') {
    return <ReasoningEntry block={block} processing={processing} />
  }
  if (block.kind === 'assistant') {
    // The model's 承上启下 storyline line written before a tool batch. Render
    // it like the reasoning narration line (Bot + muted text) so it reads as
    // the throughline the user follows while tools execute.
    if (block.agentSegment === 'mid_turn_preface') {
      return (
        <div className="flex items-start gap-1.5 py-0.5">
          <Bot
            className="mt-1 h-3.5 w-3.5 shrink-0 text-ds-faint ds-work-logo-pulse"
            strokeWidth={1.8}
          />
          <p className="text-[13.5px] leading-6 text-ds-muted">{block.text}</p>
        </div>
      )
    }
    // Other assistant content that landed in the work trace (interstitial
    // final-answer segments).
    return (
      <div className="ds-markdown text-[13.5px] leading-6 text-ds-muted">
        <AssistantMarkdown text={block.text} streaming={processing} />
      </div>
    )
  }
  // Data events: route to their dedicated components, never hidden.
  if (block.kind === 'approval') return <ApprovalBubble block={block} />
  if (block.kind === 'elevation') return <ElevationBubble block={block} />
  if (block.kind === 'evolution') return <EvolutionBubble block={block} />
  if (block.kind === 'user_input') return <UserInputBubble block={block} />
  if (block.kind === 'subagent') return <SubagentBubble block={block} />
  if (block.kind === 'workflow') {
    return (
      <WorkflowBlock
        workflowName={block.workflowName}
        status={block.status}
        snapshot={block.snapshot}
      />
    )
  }
  if (block.kind === 'system') {
    return <p className="text-[12px] text-ds-faint">{block.text}</p>
  }
  return null
}

/**
 * A reasoning block. Shows the model's narration line (承上启下) when present;
 * otherwise collapses the raw reasoning trace behind a toggle so the timeline
 * stays calm but the detail remains one click away.
 */
function ReasoningEntry({
  block,
  processing
}: {
  block: Extract<ChatBlock, { kind: 'reasoning' }>
  processing: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const narration = block.narration?.trim()
  const text = block.text.trim()
  const isLive = block.id === 'live-reasoning'

  // Narration is the user-facing line — show it directly, no toggle.
  if (narration) {
    return (
      <div className="flex items-start gap-1.5 py-0.5">
        {isLive || processing ? (
          <Bot className="mt-1 h-3.5 w-3.5 shrink-0 text-ds-faint ds-work-logo-pulse" strokeWidth={1.8} />
        ) : null}
        <p className="text-[13.5px] leading-6 text-ds-muted">{narration}</p>
      </div>
    )
  }

  // No narration: collapsible raw reasoning.
  if (!text) return <></>
  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="group flex w-fit items-center gap-1.5 py-0.5 text-left text-[14px] font-medium text-ds-muted transition hover:opacity-85"
      >
        {isLive || processing ? (
          <Bot className="h-3.5 w-3.5 text-ds-faint ds-work-logo-pulse" strokeWidth={1.8} />
        ) : null}
        <span className={isLive ? 'ds-shiny-text' : ''}>{t('thinkingLabel')}</span>
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-0 transition group-hover:opacity-55" strokeWidth={1.8} />
        )}
      </button>
      {expanded ? (
        <div className="mt-1 border-l-2 border-ds-border-muted/35 pl-3">
          <div className="ds-markdown text-[13.5px] leading-6 text-ds-muted">
            <AssistantMarkdown text={text} streaming={isLive && processing} />
          </div>
        </div>
      ) : null}
    </div>
  )
}

/**
 * Tiny "via <model>" tag rendered above the user message body. Subtle by
 * design — no pill, no ring, just faint text right-aligned at the top of the
 * bubble. Hidden when there's no model selection to surface.
 */
function ModelMetaTag({
  label,
  className = ''
}: {
  label?: string
  className?: string
}): ReactElement | null {
  const { t } = useTranslation('common')
  if (!label) return null
  return (
    <div
      className={`flex min-w-0 text-right ${className}`.trim()}
      title={t('turnModelBadgeTitle', { model: label })}
    >
      <span className="truncate text-[12px] tracking-tight text-ds-faint/85">
        {label}
      </span>
    </div>
  )
}

/**
 * User message bubble with hover affordance to rewind/edit. Click the rewind
 * pill, the bubble flips into a textarea, and Resend submits an edited
 * version of the message — locally truncating subsequent turns and starting
 * a fresh turn on the same thread (see chat-store `rewindAndResend`).
 */
function UserMessageBubble({
  block
}: {
  block: Extract<ChatBlock, { kind: 'user' }>
}): ReactElement {
  const { t } = useTranslation('common')
  const busy = useChatStore((s) => s.busy)
  const rewindAndResend = useChatStore((s) => s.rewindAndResend)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(block.text)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!editing) return
    const el = textareaRef.current
    if (!el) return
    el.focus()
    const len = el.value.length
    el.setSelectionRange(len, len)
    // Auto-size to content
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 360)}px`
  }, [editing])

  const startEdit = (): void => {
    if (busy) return
    setDraft(block.text)
    setEditing(true)
  }

  const cancelEdit = (): void => {
    setDraft(block.text)
    setEditing(false)
  }

  const submit = async (): Promise<void> => {
    const trimmed = draft.trim()
    if (!trimmed || busy) return
    setEditing(false)
    await rewindAndResend(block.id, trimmed)
  }

  if (editing) {
    return (
      <div id={`block-${block.id}`} className="ds-user-message">
        <div className="ds-user-message-bubble ds-user-message-edit-bubble min-w-0">
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              const el = e.currentTarget
              el.style.height = 'auto'
              el.style.height = `${Math.min(el.scrollHeight, 360)}px`
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.preventDefault()
                cancelEdit()
              } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                void submit()
              }
            }}
            rows={2}
            className="ds-user-message-edit-textarea block w-full min-w-0 resize-none break-words bg-transparent text-[15px] font-medium leading-[1.58] text-ds-ink outline-none [overflow-wrap:anywhere]"
          />
          <div className="mt-2 flex items-center justify-end gap-3">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={cancelEdit}
                className="rounded-md px-3 py-1 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
              >
                {t('rewindCancel')}
              </button>
              <button
                type="button"
                onClick={() => void submit()}
                disabled={!draft.trim() || busy}
                className="rounded-md bg-accent px-3 py-1 text-[13px] font-medium text-white shadow-sm transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t('rewindResend')}
              </button>
            </div>
          </div>
        </div>
        <div className="mt-2 flex min-w-0 items-center justify-end">
          <ModelMetaTag label={block.modelLabel} />
        </div>
      </div>
    )
  }

  return (
    <div id={`block-${block.id}`} className="ds-user-message group relative">
      <div className="ds-user-message-bubble min-w-0">
        <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-left">
          {block.text}
        </div>
      </div>
      <div className="mt-2 flex min-w-0 items-center justify-between gap-3 text-ds-faint opacity-90 transition group-hover:opacity-100">
        <ModelMetaTag label={block.modelLabel} className="flex-1 justify-start text-left" />
        <div className="flex items-center justify-end gap-3">
          <CopyFeedbackButton text={block.text} iconOnly />
          <button
            type="button"
            onClick={startEdit}
            disabled={busy}
            title={t('rewindEditMessage')}
            aria-label={t('rewindEditMessage')}
            className="rounded-md p-1 transition hover:bg-ds-hover hover:text-ds-muted disabled:cursor-not-allowed disabled:hover:text-ds-faint"
          >
            <PencilLine className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>
      </div>
    </div>
  )
}

const USER_INPUT_OTHER_LABEL = 'Other'

function CopyFeedbackButton({
  text,
  iconOnly = false
}: {
  text: string
  iconOnly?: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const resetRef = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (resetRef.current !== null) window.clearTimeout(resetRef.current)
    },
    []
  )

  const scheduleReset = (): void => {
    if (resetRef.current !== null) window.clearTimeout(resetRef.current)
    resetRef.current = window.setTimeout(() => {
      setStatus('idle')
      resetRef.current = null
    }, COPY_FEEDBACK_RESET_MS)
  }

  const handleCopy = async (): Promise<void> => {
    try {
      if (!navigator?.clipboard?.writeText) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(text)
      setStatus('success')
    } catch {
      setStatus('error')
    }
    scheduleReset()
  }

  const success = status === 'success'
  const error = status === 'error'
  const label = success ? t('copySuccess') : error ? t('copyFailed') : t('copyMessage')
  const iconClassName = iconOnly ? 'h-4 w-4' : 'h-3.5 w-3.5'

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      title={label}
      aria-label={label}
      className={`flex shrink-0 items-center rounded-md transition ${
        iconOnly
          ? 'gap-0 p-1 hover:bg-ds-hover'
          : 'gap-1 px-1.5 py-0.5 hover:bg-ds-hover'
      } ${
        success
          ? 'text-emerald-500'
          : error
            ? 'text-rose-400'
            : 'text-ds-faint hover:text-ds-muted'
      }`}
    >
      {success ? (
        <Check className={iconClassName} strokeWidth={2} />
      ) : (
        <Copy className={iconClassName} strokeWidth={1.8} />
      )}
      {!iconOnly ? <span>{label}</span> : null}
    </button>
  )
}

/**
 * "Fork from here" — branch a new thread containing the conversation up to and
 * including this message's item. Sits next to the copy button on each user and
 * assistant message footer. Disabled while a turn is running or when no thread
 * is active. The backend truncates the fork at ``through_item_id``.
 */
function ForkFromHereButton({ itemId }: { itemId: string }): ReactElement {
  const { t } = useTranslation('common')
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const forkThread = useChatStore((s) => s.forkThread)
  const busy = useChatStore((s) => s.busy)
  const runtimeConnection = useChatStore((s) => s.runtimeConnection)
  const [pending, setPending] = useState(false)

  const disabled = !activeThreadId || busy || pending || runtimeConnection !== 'ready'

  const handleClick = async (): Promise<void> => {
    if (disabled || !activeThreadId) return
    setPending(true)
    try {
      await forkThread(activeThreadId, itemId)
    } finally {
      setPending(false)
    }
  }

  const label = t('forkFromHere')
  return (
    <button
      type="button"
      onClick={() => void handleClick()}
      disabled={disabled}
      title={label}
      aria-label={label}
      className="flex shrink-0 items-center rounded-md p-1 text-ds-faint transition hover:bg-ds-hover hover:text-ds-muted disabled:cursor-not-allowed disabled:opacity-40"
    >
      {pending ? (
        <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.8} />
      ) : (
        <GitFork className="h-4 w-4" strokeWidth={1.8} />
      )}
    </button>
  )
}

function subagentStatusLabel(
  status: Extract<ChatBlock, { kind: 'subagent' }>['status'],
  t: (key: string) => string
): string {
  switch (status) {
    case 'completed':
      return t('subagentStatusCompleted')
    case 'failed':
      return t('subagentStatusFailed')
    case 'cancelled':
      return t('subagentStatusCancelled')
    case 'running':
      return t('subagentStatusRunning')
    default:
      return t('subagentStatusPending')
  }
}

function SubagentBubble({
  block
}: {
  block: Extract<ChatBlock, { kind: 'subagent' }>
}): ReactElement {
  const { t } = useTranslation('common')
  const title =
    block.cardKind === 'fanout'
      ? t('subagentFanoutTitle', { kind: block.agentType })
      : t('subagentDelegateTitle', { type: block.agentType })
  const statusLabel = subagentStatusLabel(block.status, t)

  return (
    <div className="rounded-[22px] border border-violet-300/50 bg-[linear-gradient(180deg,rgba(139,92,246,0.06),rgba(139,92,246,0.12))] px-4 py-4 text-[13px] leading-6 text-ds-ink shadow-[0_12px_30px_rgba(86,103,136,0.04)] dark:border-violet-800/50">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="font-semibold text-violet-700 dark:text-violet-300">{title}</div>
        <span className="font-mono text-[11px] text-ds-faint">{block.agentId.slice(0, 10)}</span>
      </div>
      <p className="mt-1 text-[12px] text-ds-muted">{statusLabel}</p>
      {block.cardKind === 'fanout' && block.workers && block.workers.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {block.workers.map((worker) => (
            <span
              key={worker.id}
              title={worker.id}
              className={`inline-flex h-6 min-w-6 items-center justify-center rounded-md px-1 font-mono text-[10px] ${
                worker.status === 'completed'
                  ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                  : worker.status === 'failed'
                    ? 'bg-red-500/15 text-red-700 dark:text-red-300'
                    : worker.status === 'running'
                      ? 'bg-amber-500/15 text-amber-800 dark:text-amber-200'
                      : 'bg-ds-hover text-ds-muted'
              }`}
            >
              {worker.id.slice(-2)}
            </span>
          ))}
        </div>
      ) : null}
      {block.summary ? (
        <p className="mt-2 whitespace-pre-wrap text-[13px] text-ds-ink">{block.summary}</p>
      ) : null}
    </div>
  )
}

function UserInputBubble({
  block
}: {
  block: Extract<ChatBlock, { kind: 'user_input' }>
}): ReactElement {
  const { t } = useTranslation('common')
  const resolveUserInput = useChatStore((s) => s.resolveUserInput)
  const [answers, setAnswers] = useState<Record<string, UserInputAnswer>>(() =>
    answersByQuestionId(block.answers)
  )
  const pending = block.status === 'pending'
  const done = block.status !== 'pending'

  useEffect(() => {
    setAnswers(answersByQuestionId(block.answers))
  }, [block.id, block.answers])

  const chooseOption = (question: UserInputQuestion, label: string, value = label): void => {
    setAnswers((prev) => ({
      ...prev,
      [question.id]: { id: question.id, label, value }
    }))
  }

  const canSubmit = block.questions.every((question) => {
    const answer = answers[question.id]
    if (!answer) return false
    if (answer.label === USER_INPUT_OTHER_LABEL) return answer.value.trim().length > 0
    return true
  })

  const submit = (): void => {
    if (!canSubmit || !pending) return
    const ordered = block.questions.map((question) => answers[question.id]).filter(Boolean)
    void resolveUserInput(block.id, { kind: 'submit', answers: ordered })
  }

  const cancel = (): void => {
    if (!pending) return
    void resolveUserInput(block.id, { kind: 'cancel' })
  }

  const statusLabel =
    block.status === 'submitted'
      ? t('userInputSubmitted')
      : block.status === 'cancelled'
        ? t('userInputCancelled')
        : block.status === 'error'
          ? t('userInputFailed')
          : t('userInputPending')

  return (
    <div
      className={`rounded-[22px] border px-4 py-4 text-[13px] leading-6 shadow-[0_12px_30px_rgba(86,103,136,0.04)] ${
        block.status === 'error'
          ? 'border-red-300/80 bg-red-500/10 dark:border-red-800/60 dark:bg-red-950/35'
          : 'border-accent/35 bg-[linear-gradient(180deg,rgba(79,124,255,0.07),rgba(79,124,255,0.11))] text-ds-ink'
      }`}
    >
      <div className="font-semibold text-accent">{t('userInputTitle')}</div>
      <p className="mt-1 text-[12px] text-ds-muted">{statusLabel}</p>

      <div className="mt-3 flex flex-col gap-4">
        {block.questions.map((question, index) => {
          const answer = answers[question.id]
          const otherSelected = answer?.label === USER_INPUT_OTHER_LABEL
          return (
            <div key={question.id} className="rounded-xl border border-ds-border bg-ds-card/60 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ds-muted">
                  {question.header}
                </div>
                <div className="text-[12px] text-ds-faint">
                  {t('userInputQuestionProgress', {
                    current: index + 1,
                    total: block.questions.length
                  })}
                </div>
              </div>
              <p className="mt-1.5 whitespace-pre-wrap text-[14px] font-medium text-ds-ink">
                {question.question}
              </p>
              <div className="mt-3 grid gap-2">
                {question.options.map((option) => {
                  const selected = answer?.label === option.label && answer.value === option.label
                  return (
                    <button
                      key={option.label}
                      type="button"
                      disabled={done}
                      onClick={() => chooseOption(question, option.label)}
                      className={`rounded-lg border px-3 py-2 text-left transition disabled:cursor-default ${
                        selected
                          ? 'border-accent/60 bg-accent/10 text-ds-ink'
                          : 'border-ds-border bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <span className="block text-[13px] font-semibold">{option.label}</span>
                      <span className="mt-0.5 block text-[12px] leading-5 text-ds-faint">
                        {option.description}
                      </span>
                    </button>
                  )
                })}
                <button
                  type="button"
                  disabled={done}
                  onClick={() =>
                    chooseOption(
                      question,
                      USER_INPUT_OTHER_LABEL,
                      answer?.label === USER_INPUT_OTHER_LABEL ? answer.value : ''
                    )
                  }
                  className={`rounded-lg border px-3 py-2 text-left transition disabled:cursor-default ${
                    otherSelected
                      ? 'border-accent/60 bg-accent/10 text-ds-ink'
                      : 'border-ds-border bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                  }`}
                >
                  <span className="block text-[13px] font-semibold">{t('userInputOther')}</span>
                  <span className="mt-0.5 block text-[12px] leading-5 text-ds-faint">
                    {t('userInputOtherDescription')}
                  </span>
                </button>
                {otherSelected ? (
                  <textarea
                    rows={2}
                    disabled={done}
                    value={answer?.value ?? ''}
                    onChange={(e) =>
                      chooseOption(question, USER_INPUT_OTHER_LABEL, e.target.value)
                    }
                    placeholder={t('userInputCustomPlaceholder')}
                    className="min-h-20 resize-y rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[13px] leading-5 text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60 disabled:cursor-default disabled:opacity-80"
                  />
                ) : null}
              </div>
            </div>
          )
        })}
      </div>

      {block.errorMessage ? (
        <p className="mt-3 text-[12px] text-red-700 dark:text-red-300">{block.errorMessage}</p>
      ) : null}

      {block.answers && block.answers.length > 0 && block.status === 'submitted' ? (
        <div className="mt-3 rounded-lg bg-ds-card px-3 py-2 text-[12px] text-ds-muted">
          {block.answers.map((answer) => (
            <div key={answer.id} className="flex gap-2">
              <span className="font-mono text-ds-faint">{answer.id}</span>
              <span className="min-w-0 flex-1 break-words">{answer.value || answer.label}</span>
            </div>
          ))}
        </div>
      ) : null}

      {pending ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!canSubmit}
            className="rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={submit}
          >
            {t('userInputSubmit')}
          </button>
          <button
            type="button"
            className="rounded-lg border border-ds-border bg-ds-card px-3 py-1.5 text-[13px] font-medium text-ds-ink hover:bg-ds-hover"
            onClick={cancel}
          >
            {t('userInputCancel')}
          </button>
        </div>
      ) : null}
    </div>
  )
}

function answersByQuestionId(
  answers: UserInputAnswer[] | undefined
): Record<string, UserInputAnswer> {
  const out: Record<string, UserInputAnswer> = {}
  for (const answer of answers ?? []) {
    out[answer.id] = answer
  }
  return out
}

function formatMessageDateTime(input: string, locale: string): string {
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) return input
  const now = new Date()
  const sameYear = date.getFullYear() === now.getFullYear()
  return new Intl.DateTimeFormat(locale, {
    ...(sameYear ? {} : { year: 'numeric' }),
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

function MessageBubble({ block }: { block: ChatBlock }): ReactElement {
  const { t, i18n } = useTranslation('common')
  if (block.kind === 'user') {
    return <UserMessageBubble block={block} />
  }
  if (block.kind === 'assistant') {
    const streaming = block.id === 'live-assistant'
    const createdAtLabel = block.createdAt
      ? formatMessageDateTime(block.createdAt, i18n.language)
      : null
    return (
      <div id={`block-${block.id}`} className="group/message flex min-w-0 max-w-full flex-col">
        <div className="ds-markdown ds-chat-answer min-w-0 max-w-full text-ds-ink">
          <AssistantMarkdown text={block.text} streaming={streaming} />
        </div>
        {!streaming ? (
          <div className="mt-1 flex min-h-5 min-w-0 items-center justify-between gap-3 text-[11.5px] text-ds-faint opacity-0 transition duration-150 group-hover/message:opacity-100">
            <span className="min-w-0 truncate">{createdAtLabel ?? ''}</span>
            <div className="flex items-center gap-1.5">
              <ForkFromHereButton itemId={block.id} />
              <CopyFeedbackButton text={block.text} iconOnly />
            </div>
          </div>
        ) : null}
      </div>
    )
  }
  if (block.kind === 'reasoning') {
    return (
      <div id={`block-${block.id}`} className="ds-card-soft rounded-[20px] px-4 py-3 text-[13.5px] leading-6 text-ds-muted">
        <div className="ds-markdown">
          <BoundedReasoningMarkdown text={block.text} />
        </div>
      </div>
    )
  }
  if (block.kind === 'tool') {
    return <ToolCard block={block} />
  }
  if (block.kind === 'user_input') {
    return <UserInputBubble block={block} />
  }
  if (block.kind === 'subagent') {
    return <SubagentBubble block={block} />
  }
  if (block.kind === 'workflow') {
    return (
      <WorkflowBlock
        workflowName={block.workflowName}
        status={block.status}
        snapshot={block.snapshot}
      />
    )
  }
  if (block.kind === 'approval') {
    return <ApprovalBubble block={block} />
  }
  if (block.kind === 'evolution') {
    return <EvolutionBubble block={block} />
  }
  if (block.kind === 'elevation') {
    return <ElevationBubble block={block} />
  }
  return (
    <div className="ds-card-soft rounded-[18px] px-3 py-2 text-[13.5px] text-ds-muted">
      {block.text}
    </div>
  )
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m ${s}s`
}
