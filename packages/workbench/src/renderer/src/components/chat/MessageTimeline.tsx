import type { PointerEvent as ReactPointerEvent, ReactElement, RefObject } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  lazy,
  memo,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore
} from 'react'
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
  Globe2,
  Loader2,
  PencilLine,
  Plug,
  Puzzle,
  Search,
  Sparkles,
  Terminal,
  Wand2,
  Wrench,
  X
} from 'lucide-react'
import { isHtmlPreviewPath } from '@shared/html-preview'
import {
  formatHtmlPreviewPathLabel,
  type OpenableTurnResult,
  selectOpenableTurnResults
} from '../../lib/html-preview-detection'
import { TaskSuggestionHero, TaskSuggestionOfflineHero } from './TaskSuggestionHero'
import { SquareGrid } from './SquareGrid'
import type { ChatBlock, RuntimeConnectionStatus, ToolBlock } from '../../agent/types'
import {
  formatFilePathForDisplay,
  resolvePatchStats,
  sumDiffStatsList,
  type DiffStats
} from '../../lib/diff-stats'
import {
  resolveTurnDiffId,
  toolBlocksFromTurnSummary,
  turnSummaryFromSources,
  type TurnDiffSnapshot
} from '../../lib/turn-mutation-view'
import { useDeferredRender } from '../../hooks/use-deferred-render'
import { resumeThreadAgent } from '../../hooks/use-thread-tasks'
import {
  getEmptyHomeLayout,
  getTimestampFormat,
  subscribeAppearance
} from '../../lib/apply-appearance'
import { getProvider } from '../../agent/registry'
import { useChatStore } from '../../store/chat-store'
import { DiffView } from '../DiffView'
import { EvolutionBubble } from './EvolutionBubble'
import { ElevationBubble } from './ElevationBubble'
import { InlineTodoBlock } from './InlineTodoBlock'
import { UserInputBubble } from './UserInputBubble'
import { StepFlow, lifecycleToStepStatus, type StepFlowItem } from './StepFlow'
import { humanizeAgentType } from '../../lib/agent-type-label'
import { subagentListTitle } from '../../lib/extract-subagents-from-blocks'
import { subagentStepsToFlowItems } from '../../lib/subagent-mailbox'
import {
  buildProbeBatchMeta,
  isShellProbeCandidateTool,
  probeComposeSegments
} from '../../lib/step-flow-collapse'
import {
  ToolCard,
  registerToolRenderers,
  buildToolRenderContext,
  humanizeToolName
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
import { parseUserFocusPrefix, composeUserFocusMessage } from '../../lib/user-focus-prefix'
import { FileChip, UserMessageRichText } from './FileChip'
import {
  formatPreviewPickChipLabel,
  formatPreviewPickWireMessage,
  parsePreviewPickWireMessage
} from '../../lib/preview-pick-message'
import { pluginDisplayTitle } from '../extensions/plugin-presentation'
import { QueryTrail } from './QueryTrail'
import { createActiveTrailStore, deriveQueryTrailItems } from './queryTrail.logic'
import { ResizableFullscreenDialog } from './ResizableFullscreenDialog'
import {
  clipMidTurnPrefaceText,
  shouldParseIncompleteAssistantMarkdown,
  countSubagentRailSteps,
  groupProcessRows,
  isInternalSubagentHandoffSystemText,
  isSubagentOrchestrationToolName,
  placeAssistantContentBlock,
  planProcessRenderChunks,
  splitThink,
  toolNameFromProcessBlock,
  trailingThinkingIndicatorId,
  type ProcessWorkSummary,
  type RenderRow,
  type ToolProcessBlock
} from './message-timeline-logic'
import {
  rewindPreviewNeedsConfirmation,
  rewindResendConfirmModel
} from './rewind-resend-confirm'
import { useTailAnchorScroll } from './use-tail-anchor-scroll'

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
  /** Local HTML artifact from this turn — nested under file changes when present. */
  htmlPreviewAction?: { path: string; onOpen: () => void } | null
  /** Open a workspace file in the editor panel (final MD report, etc.). */
  onOpenWorkspaceFile?: (path: string, line?: number) => void
  stageCentered?: boolean
  useChatStageWidth?: boolean
  withOperationColumn?: boolean
  /**
   * IDE chat rail is too narrow for Overview / GitHub cards — always use the
   * simple empty home (hide TaskSuggestionHero) regardless of appearance setting.
   */
  forceSimpleEmptyHome?: boolean
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
  htmlPreviewAction = null,
  onOpenWorkspaceFile,
  stageCentered = false,
  useChatStageWidth = true,
  withOperationColumn = false,
  forceSimpleEmptyHome = false
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const chooseWorkspace = useChatStore((s) => s.chooseWorkspace)
  const busy = useChatStore((s) => s.busy)
  const currentTurnId = useChatStore((s) => s.currentTurnId)
  const lastCompletedTurnId = useChatStore((s) => s.lastCompletedTurnId)
  const turnDiffByTurnId = useChatStore((s) => s.turnDiffByTurnId)
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
  const userScrolledAtRef = useRef(0)
  const pendingPrependRef = useRef<{ scrollHeight: number; scrollTop: number } | null>(null)
  const prependInFlightRef = useRef(false)
  const scrollFrameRef = useRef<number | null>(null)
  const jumpAnimRef = useRef<number | null>(null)
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
    // wheel/touchmove/keydown only fire on genuine user input, never on
    // programmatic scrollTop - so they reliably mark "the user is scrolling
    // right now" for the streaming auto-scroll cooldown.
    const markUserScroll = (): void => {
      userScrolledAtRef.current = performance.now()
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (
        event.key === 'ArrowUp' ||
        event.key === 'ArrowDown' ||
        event.key === 'PageUp' ||
        event.key === 'PageDown' ||
        event.key === 'Home' ||
        event.key === 'End'
      ) {
        markUserScroll()
      }
    }
    el.addEventListener('wheel', markUserScroll, { passive: true })
    el.addEventListener('touchmove', markUserScroll, { passive: true })
    el.addEventListener('keydown', onKeyDown)
    return () => {
      el.removeEventListener('scroll', onScroll)
      el.removeEventListener('wheel', markUserScroll)
      el.removeEventListener('touchmove', markUserScroll)
      el.removeEventListener('keydown', onKeyDown)
    }
  }, [hiddenTurnCount, loadEarlierTurns])

  const { spacerPx: tailAnchorSpacerPx, holdRef: tailAnchorHoldRef } = useTailAnchorScroll({
    containerRef,
    sentUserId: currentTurnUserId,
    threadId: activeThreadId,
    stickToBottomRef,
    userScrolledAtRef
  })

  const pinTimelineToBottom = useCallback((): void => {
    if (tailAnchorHoldRef.current) return
    if (!stickToBottomRef.current) return
    // Back off while the user is actively scrolling so stick-to-bottom
    // doesn't fight their gesture.
    if (performance.now() - userScrolledAtRef.current < 350) return
    const el = containerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [tailAnchorHoldRef])

  // Expanding a collapsed row grows `.ds-timeline-stack`. The resize observer
  // would then pin-to-bottom and yank the row the user just opened off-screen
  // — same bug on the summary header and each child card.
  const releaseStickOnExpandClick = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>): void => {
      const target = event.target
      if (!(target instanceof Element)) return
      if (!target.closest('button, [aria-expanded], summary')) return
      stickToBottomRef.current = false
      tailAnchorHoldRef.current = false
      userScrolledAtRef.current = performance.now()
    },
    [tailAnchorHoldRef]
  )

  // Pin on content resize in the same frame the height changes — waiting for
  // a React effect + rAF left one painted frame at the old scrollTop, which
  // reads as the dialogue "bouncing upward" during streaming / composer growth.
  useLayoutEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const stack = el.querySelector('.ds-timeline-stack')
    if (!stack) return
    const ro = new ResizeObserver(() => {
      pinTimelineToBottom()
    })
    ro.observe(stack)
    return () => ro.disconnect()
  }, [pinTimelineToBottom])

  useLayoutEffect(() => {
    pinTimelineToBottom()
  }, [blocks, live, liveReasoning, pinTimelineToBottom])

  useEffect(() => {
    stickToBottomRef.current = true
    pendingPrependRef.current = null
    prependInFlightRef.current = false
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
      scrollFrameRef.current = null
    }
    // Container-scoped jump (not scrollIntoView) to avoid repositioning
    // scrollable ancestors on thread switch.
    const el = containerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [activeThreadId])

  useLayoutEffect(() => {
    if (!currentTurnUserId) return
    // Tail-anchor owns the send scroll: pin the user bubble to the top instead
    // of jumping to the document bottom.
    stickToBottomRef.current = false
  }, [currentTurnUserId])

  useEffect(() => {
    if (!scrollToBlockId) return
    const target = document.getElementById(`block-${scrollToBlockId}`)
    const container = containerRef.current
    if (target && container) {
      stickToBottomRef.current = false
      tailAnchorHoldRef.current = false
      // Land the query near the top (≈20% from the top, like synara's
      // viewPosition:0.2) rather than centred, and drive the scroll manually
      // with an ease-out rAF so the animation is consistent and not at the
      // mercy of scrollIntoView's multi-ancestor easing.
      if (jumpAnimRef.current !== null) {
        cancelAnimationFrame(jumpAnimRef.current)
        jumpAnimRef.current = null
      }
      // Rects are in zoomed (visual) px while scrollTop is unzoomed content px —
      // divide the rect delta by the UI scale before mixing the two spaces.
      const uiScale =
        parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')
        ) || 1
      const targetTop =
        (target.getBoundingClientRect().top - container.getBoundingClientRect().top) / uiScale +
        container.scrollTop
      const viewH = container.clientHeight
      const goal = Math.max(0, targetTop - viewH * 0.2)
      let start = container.scrollTop
      // The timeline isn't virtualized, so a long animated scroll paints every
      // intermediate region (janky on heavy threads). Teleport to within one
      // viewport of the goal and animate only that last stretch — the cost is
      // bounded no matter how far the jump is (synara gets this for free from
      // its virtualized scrollToIndex).
      const maxAnimated = viewH
      if (Math.abs(goal - start) > maxAnimated) {
        start = goal > start ? goal - maxAnimated : goal + maxAnimated
        container.scrollTop = start
      }
      const distance = goal - start
      const duration = 280
      const startTime = performance.now()
      const easeOut = (t: number): number => 1 - Math.pow(1 - t, 3)
      const step = (now: number): void => {
        const t = Math.min(1, (now - startTime) / duration)
        container.scrollTop = start + distance * easeOut(t)
        if (t < 1) {
          jumpAnimRef.current = requestAnimationFrame(step)
        } else {
          jumpAnimRef.current = null
        }
      }
      jumpAnimRef.current = requestAnimationFrame(step)
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

  const trailItems = useMemo(() => deriveQueryTrailItems(blocks), [blocks])
  // Trail highlights live in an external store (not React state) so scroll-spy
  // can update the rail without re-rendering this heavy timeline. Created once.
  const activeTrailStoreRef = useRef<ReturnType<typeof createActiveTrailStore> | null>(null)
  if (activeTrailStoreRef.current === null) {
    activeTrailStoreRef.current = createActiveTrailStore()
  }
  // Cached block positions in scroll-content space (top = offset from content
  // origin; refresh only on layout/items change — never per scroll frame).
  const blockCacheRef = useRef<Map<string, { top: number; height: number }>>(new Map())
  // Viewport height cache so the scroll hot path never reads clientHeight
  // (which forces layout while streaming keeps styles dirty).
  const viewportHeightRef = useRef(0)

  // Track reading highlights off the transcript's own scroll:
  //  - currentId : the last query bubble at or above the viewport top (the turn
  //    you're reading, even when the user bubble scrolled above a long reply).
  //  - visibleIds: every query bubble intersecting the viewport (brightened).
  // Block rects are cached once per layout change; the scroll hot path reads
  // only `scrollTop`/`clientHeight` (no getBoundingClientRect) and writes to the
  // external store, so the timeline never re-renders on scroll.
  const refreshBlockCache = useCallback(() => {
    const el = containerRef.current
    if (!el || trailItems.length === 0) {
      blockCacheRef.current = new Map()
      return
    }
    const containerRect = el.getBoundingClientRect()
    const scrollTop = el.scrollTop
    const map = new Map<string, { top: number; height: number }>()
    for (const item of trailItems) {
      const node = document.getElementById(`block-${item.id}`)
      if (!node) continue
      const r = node.getBoundingClientRect()
      map.set(item.id, { top: r.top - containerRect.top + scrollTop, height: r.height })
    }
    blockCacheRef.current = map
  }, [trailItems])

  useEffect(() => {
    const el = containerRef.current
    if (!el || trailItems.length === 0) {
      activeTrailStoreRef.current?.set({ currentId: null, visibleIds: [] })
      return
    }
    let frame: number | null = null
    const recompute = (): void => {
      frame = null
      const cache = blockCacheRef.current
      if (cache.size === 0) return
      const scrollTop = el.scrollTop
      const viewH = viewportHeightRef.current
      let current: string | null = trailItems[0]?.id ?? null
      const nextVisible: string[] = []
      for (const item of trailItems) {
        const c = cache.get(item.id)
        if (!c) continue
        if (c.top - scrollTop <= 8) current = item.id
        if (c.top + c.height > scrollTop && c.top < scrollTop + viewH) nextVisible.push(item.id)
      }
      activeTrailStoreRef.current?.set({ currentId: current, visibleIds: nextVisible })
    }
    const onScroll = (): void => {
      if (frame !== null) return
      frame = window.requestAnimationFrame(recompute)
    }
    // Refresh cache + resolve initial highlight after layout settles.
    viewportHeightRef.current = el.clientHeight
    refreshBlockCache()
    recompute()
    el.addEventListener('scroll', onScroll, { passive: true })
    // Keep the cache honest when the scroll content reflows (mermaid render,
    // image load, streaming append). Streaming resizes the content every few
    // frames and a full re-measure forces layout for every query block, so
    // coalesce: measure at most every 250ms (trailing edge picks up the rest).
    let measureTimer: number | null = null
    let lastMeasure = 0
    const scheduleMeasure = (): void => {
      const now = performance.now()
      const wait = Math.max(0, 250 - (now - lastMeasure))
      if (measureTimer !== null) return
      measureTimer = window.setTimeout(() => {
        measureTimer = null
        lastMeasure = performance.now()
        refreshBlockCache()
        if (frame === null) frame = window.requestAnimationFrame(recompute)
      }, wait)
    }
    const contentEl = el.firstElementChild as HTMLElement | null
    const ro = new ResizeObserver(scheduleMeasure)
    if (contentEl) ro.observe(contentEl)
    const viewportRo = new ResizeObserver(() => {
      viewportHeightRef.current = el.clientHeight
      if (frame === null) frame = window.requestAnimationFrame(recompute)
    })
    viewportRo.observe(el)
    return () => {
      el.removeEventListener('scroll', onScroll)
      if (frame !== null) window.cancelAnimationFrame(frame)
      if (measureTimer !== null) window.clearTimeout(measureTimer)
      ro.disconnect()
      viewportRo.disconnect()
    }
  }, [trailItems, visibleTurnCount, refreshBlockCache])

  const timeline = (
    <div
      ref={containerRef}
      onPointerDown={releaseStickOnExpandClick}
      className={`ds-no-drag flex min-w-0 flex-col overflow-x-hidden ${
        stageCentered && showEmptyHeroOnly
          ? 'shrink-0 overflow-visible'
          : 'ds-scroll-surface min-h-0 flex-1 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden'
      }`}
    >
      <div
        className={`ds-timeline-stack flex w-full min-w-0 flex-col ${
          useChatStageWidth ? 'ds-chat-stage px-3 sm:px-4' : 'max-w-none px-0'
        } ${
          showEmptyHeroOnly
            ? 'pb-0 pt-0'
            : withOperationColumn
              ? 'ds-timeline-with-operation ds-timeline-composer-clearance'
              : 'ds-timeline-composer-clearance pt-2'
        }`}
      >
        {!activeThreadId && (
          <EmptyHero
            ready={runtimeConnection === 'ready'}
            hasWorkspace={!!workspaceRoot}
            forceSimpleEmptyHome={forceSimpleEmptyHome}
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
            forceSimpleEmptyHome={forceSimpleEmptyHome}
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
          const turnDiffId = resolveTurnDiffId(
            turn.user?.turnId,
            isLatestTurn,
            currentTurnId,
            lastCompletedTurnId
          )
          const hasLiveStream = isLatestTurn && !!(liveReasoning.trim() || live.trim())
          const processing = (busy && isLatestTurn) || turnPending || hasLiveStream
          return (
            <MemoMessageTurn
              key={userId ?? `turn-${index}`}
              turn={turn}
              isProcessing={processing}
              liveReasoning={isLatestTurn ? liveReasoning : ''}
              live={isLatestTurn ? live : ''}
              liveStartedAt={liveStartedAt}
              durationMs={durationMs}
              reasoningDurationMs={reasoningDurationMs}
              htmlPreviewAction={isLatestTurn ? htmlPreviewAction : null}
              onOpenWorkspaceFile={onOpenWorkspaceFile}
              viewportRef={containerRef}
              turnDiffSnapshot={
                turnDiffId
                  ? turnDiffByTurnId[turnDiffId]
                  : undefined
              }
              turnDiffTurnId={turnDiffId}
              turnDiffRevision={
                turnDiffId
                  ? (turnDiffByTurnId[turnDiffId]?.revision ?? 0)
                  : 0
              }
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
            htmlPreviewAction={htmlPreviewAction}
            onOpenWorkspaceFile={onOpenWorkspaceFile}
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
        {tailAnchorSpacerPx > 0 ? (
          <div
            aria-hidden
            className="ds-tail-anchor-spacer shrink-0"
            style={{ height: tailAnchorSpacerPx }}
          />
        ) : null}
        <div ref={endRef} aria-hidden className="h-px w-full shrink-0" />
        {/* Extra tail so the last answer clears the overlapping composer + pet
            dock (Synara MIN_BOTTOM_CONTENT_INSET). Without this, the bottom-
            right looks like a missing chunk next to the mascot. */}
        {!showEmptyHeroOnly ? (
          <div aria-hidden className="ds-timeline-composer-clearance-spacer shrink-0" />
        ) : null}
      </div>
    </div>
  )

  if (showEmptyHeroOnly) return timeline

  // The wrapper is intentionally NOT position:relative — the rail's `absolute`
  // resolves against the chat main row (`.ds-chat-main-row`, the content card's
  // positioned box), so `left-0` hugs the card's left edge like synara's
  // MessageTrail instead of floating inside the padded dialogue column.
  // No portal: useSyncExternalStore isolates rail re-renders.
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {timeline}
      {trailItems.length > 0 ? (
        <QueryTrail items={trailItems} activeStore={activeTrailStoreRef.current!} />
      ) : null}
    </div>
  )
}

function EmptyHero({
  ready,
  hasWorkspace,
  forceSimpleEmptyHome = false,
  onPickWorkspace,
  onRetry,
  onOpenSettings,
  onOpenDiagnostics,
  onSelectSuggestion
}: {
  ready: boolean
  hasWorkspace: boolean
  forceSimpleEmptyHome?: boolean
  onPickWorkspace: () => void
  onRetry: () => void
  onOpenSettings: () => void
  onOpenDiagnostics: () => void
  onSelectSuggestion?: (prompt: string) => void
}): ReactElement | null {
  const { t } = useTranslation('common')
  const emptyHomeLayout = useSyncExternalStore(subscribeAppearance, getEmptyHomeLayout)

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

  // IDE rail / explicit simple home: skip Overview + GitHub Trending cards.
  if (forceSimpleEmptyHome || emptyHomeLayout === 'simple') return null

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
      // Orchestrator chrome — keep out of the dialogue turn stream.
      if (isInternalSubagentHandoffSystemText(block.text)) {
        continue
      }
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

function blockHasPendingRuntimeWork(block: ChatBlock): boolean {
  if (block.kind === 'tool') return block.status === 'running'
  if (block.kind === 'approval') return block.status === 'pending'
  if (block.kind === 'elevation') return block.status === 'pending'
  if (block.kind === 'evolution') return block.status === 'pending'
  if (block.kind === 'user_input') return block.status === 'pending'
  if (block.kind === 'subagent') {
    return block.status === 'pending' || block.status === 'running'
  }
  return false
}

function blockNeedsAttention(block: ChatBlock): boolean {
  if (blockHasPendingRuntimeWork(block)) return true
  if (block.kind === 'tool') return block.status === 'error'
  if (block.kind === 'approval') return block.status === 'error'
  if (block.kind === 'elevation') return block.status === 'error'
  if (block.kind === 'user_input') return block.status === 'error'
  if (block.kind === 'subagent') return block.status === 'failed' || block.status === 'cancelled'
  return false
}

function isProcessBlock(block: ChatBlock): boolean {
  return (
    block.kind === 'reasoning' ||
    block.kind === 'tool' ||
    block.kind === 'approval' ||
    block.kind === 'elevation' ||
    block.kind === 'user_input' ||
    block.kind === 'subagent' ||
    block.kind === 'system'
  )
}

function turnHasPendingRuntimeWork(turn: Turn): boolean {
  return turn.blocks.some(blockHasPendingRuntimeWork)
}

type AssistantContentBlock = Extract<ChatBlock, { kind: 'assistant' }>

/**
 * Neutral progress line for a narration frame without wording. Everything
 * shown here comes from structured metadata (tool anchors and count), so it is
 * language- and model-independent; i18n supplies the label.
 */
function NeutralIntentLine({
  intent,
  showIndicator
}: {
  intent: NonNullable<AssistantContentBlock['processIntent']>
  /** True only for the newest in-progress thinking/preface row. */
  showIndicator: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  const anchors = (intent.anchors ?? []).slice(0, 3)
  return (
    <div className="ds-process-narration flex items-start gap-1.5 py-0.5">
      {showIndicator ? <SquareGrid className="mt-1 text-ds-faint" /> : null}
      <p className="text-[13.5px] leading-6 text-ds-faint">
        {anchors.length > 0
          ? t('processNeutralIntentTargets', { targets: anchors.join(', ') })
          : t('processNeutralIntent', { count: intent.toolCount ?? 1 })}
      </p>
    </div>
  )
}

function MessageTurn({
  turn,
  isProcessing,
  liveReasoning,
  live,
  liveStartedAt,
  durationMs,
  reasoningDurationMs,
  htmlPreviewAction,
  onOpenWorkspaceFile,
  viewportRef,
  turnDiffSnapshot,
  turnDiffTurnId = null,
  turnDiffRevision = 0
}: {
  turn: Turn
  isProcessing: boolean
  liveReasoning: string
  live: string
  liveStartedAt?: number
  durationMs?: number
  reasoningDurationMs?: number
  htmlPreviewAction?: { path: string; onOpen: () => void } | null
  onOpenWorkspaceFile?: (path: string, line?: number) => void
  viewportRef: RefObject<HTMLDivElement | null>
  /** Ledger snapshot for the latest turn (live or just-completed). */
  turnDiffSnapshot?: TurnDiffSnapshot
  turnDiffTurnId?: string | null
  turnDiffRevision?: number
}): ReactElement {
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  void turnDiffRevision
  const { think: liveThink, content: liveContent } = splitThink(live)
  const liveProcessText = [liveReasoning, liveThink].filter(Boolean).join('\n\n')
  const [workExpanded, setWorkExpanded] = useState(isProcessing)

  useEffect(() => {
    setWorkExpanded(isProcessing)
  }, [isProcessing])

  const todoSession = useMemo(() => buildTodoSessionForTurn(turn.blocks), [turn.blocks])
  const todoEvents = useMemo(() => buildTodoEventsForTurn(turn.blocks), [turn.blocks])
  const subagentSummary = useMemo(
    () => buildSubagentSummaryForTurn(turn.blocks),
    [turn.blocks]
  )

  const { processBlocks, assistantContentBlocks, turnFileChanges, systemBlocks } = useMemo(() => {
    const nextProcessBlocks: ChatBlock[] = []
    const nextSystemBlocks: Array<Extract<ChatBlock, { kind: 'system' }>> = []
    const nextAssistantContentBlocks: Array<Extract<ChatBlock, { kind: 'assistant' }>> = []

    for (const block of turn.blocks) {
      if (block.kind === 'assistant') {
        const split = splitThink(block.text)
        if (split.think) {
          nextProcessBlocks.push({ kind: 'reasoning', id: `${block.id}-think`, text: split.think })
        }
        if (split.content.trim() || block.processIntent) {
          const contentBlock = { ...block, text: split.content }
          placeAssistantContentBlock(
            block,
            contentBlock,
            nextProcessBlocks,
            nextAssistantContentBlocks
          )
        }
        continue
      }
      if (block.kind === 'system') {
        if (!isInternalSubagentHandoffSystemText(block.text)) {
          nextSystemBlocks.push(block)
        }
        continue
      }
      if (isProcessBlock(block)) {
        nextProcessBlocks.push(block)
      }
    }

    if (liveProcessText.trim()) {
      nextProcessBlocks.push({ kind: 'reasoning', id: 'live-reasoning', text: liveProcessText })
    }

    // Live `agent_message` text is rendered in the main answer bubble below
    // (`showLiveAssistant`) so tokens stream in the large answer style. Do NOT
    // also push it into the process rail — MidTurnPrefaceLine clips to 160
    // chars and made long finals look like they only appeared at turn end.
    // When a mid-turn preface settles, the store clears `liveAssistant` and
    // persists a small `mid_turn_preface` row; finals land via `onFinalAnswer`.

    // Receipt for this turn's writes only. Workspace dirt stays in Changes.
    const summary = turnSummaryFromSources(turnDiffSnapshot, turn.blocks)
    const nextTurnFileChanges: ToolBlock[] =
      summary.files.length > 0
        ? toolBlocksFromTurnSummary(turnDiffTurnId || 'legacy', summary).map((block) => ({
            ...block,
            filePath: formatFilePathForDisplay(block.filePath, workspaceRoot) || block.filePath
          }))
        : []

    return {
      processBlocks: nextProcessBlocks,
      assistantContentBlocks: nextAssistantContentBlocks,
      turnFileChanges: nextTurnFileChanges,
      systemBlocks: nextSystemBlocks
    }
  }, [
    turn.blocks,
    liveProcessText,
    workspaceRoot,
    turnDiffSnapshot,
    turnDiffTurnId
  ])

  // Stream into the main answer bubble while the turn is live (and keep a
  // brief fallback if live text remains after busy clears before final upsert).
  const showLiveAssistant = !!liveContent.trim()

  const isSystemOnlyTurn =
    !turn.user &&
    systemBlocks.length > 0 &&
    processBlocks.length === 0 &&
    assistantContentBlocks.length === 0

  const hasProcess = !isSystemOnlyTurn && (isProcessing || processBlocks.length > 0)
  const showWorkMeta =
    hasProcess || (!isSystemOnlyTurn && !isProcessing && typeof durationMs === 'number')

  return (
    <div className="ds-message-turn flex min-w-0 flex-col gap-4">
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
          {showWorkMeta ? (
            <div className="flex flex-col gap-1 pb-2">
              <WorkMetaRow
                processing={isProcessing}
                stepCount={processBlocks.length}
                liveStartedAt={liveStartedAt}
                durationMs={durationMs}
                reasoningDurationMs={reasoningDurationMs}
                collapsible={hasProcess}
                expanded={workExpanded}
                onToggle={() => setWorkExpanded((value) => !value)}
                activeActionLabel={activeRunningActionLabel(processBlocks)}
              />
              {hasProcess && workExpanded ? (
                <ProcessStream
                  blocks={processBlocks}
                  processing={isProcessing}
                  todoSession={todoSession}
                  todoEvents={todoEvents}
                  subagentSummary={subagentSummary}
                  onOpenWorkspaceFile={onOpenWorkspaceFile}
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

          {/* Turn fold-up: only after the turn finishes. Mid-turn edits stay
              in the process rail as per-tool file_change cards. */}
          {!isProcessing && turnFileChanges.length > 0 ? (
            <TurnChangeSummary
              changes={turnFileChanges}
              viewportRef={viewportRef}
              htmlPreview={htmlPreviewAction ?? null}
              onOpenWorkspaceFile={onOpenWorkspaceFile}
            />
          ) : null}

          {!isProcessing && turnFileChanges.length === 0 && htmlPreviewAction ? (
            <HtmlPreviewStandaloneCard
              path={htmlPreviewAction.path}
              onOpen={htmlPreviewAction.onOpen}
            />
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
  prev.htmlPreviewAction === next.htmlPreviewAction &&
  prev.onOpenWorkspaceFile === next.onOpenWorkspaceFile &&
  prev.viewportRef === next.viewportRef &&
  prev.turnDiffSnapshot === next.turnDiffSnapshot &&
  prev.turnDiffTurnId === next.turnDiffTurnId &&
  prev.turnDiffRevision === next.turnDiffRevision
))

function turnChangeBlockStats(block: ToolBlock): DiffStats | null {
  const mutation =
    block.meta?.mutation &&
    typeof block.meta.mutation === 'object' &&
    !Array.isArray(block.meta.mutation)
      ? (block.meta.mutation as Record<string, unknown>)
      : undefined
  return resolvePatchStats(block.detail, {
    added: typeof mutation?.additions === 'number' ? mutation.additions : undefined,
    removed: typeof mutation?.deletions === 'number' ? mutation.deletions : undefined
  })
}

function normalizePathKey(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

function pathsReferToSameFile(a: string, b: string): boolean {
  const na = normalizePathKey(a)
  const nb = normalizePathKey(b)
  if (!na || !nb) return false
  if (na === nb) return true
  return na.endsWith(`/${nb}`) || nb.endsWith(`/${na}`)
}

function TurnChangeSummary({
  changes,
  viewportRef,
  htmlPreview,
  onOpenWorkspaceFile
}: {
  changes: ToolBlock[]
  viewportRef: RefObject<HTMLDivElement | null>
  htmlPreview?: { path: string; onOpen: () => void } | null
  onOpenWorkspaceFile?: (path: string, line?: number) => void
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

  const fileStats = useMemo(
    () => changes.map((change) => turnChangeBlockStats(change)),
    [changes]
  )
  const totals = useMemo(() => sumDiffStatsList(fileStats), [fileStats])
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
  const openableResults = useMemo(() => selectOpenableTurnResults(changes), [changes])
  const compactOpenable = openableResults.length > 1
  const previewPath = htmlPreview?.path?.trim() ?? ''

  const openTurnResult = (result: OpenableTurnResult): void => {
    if (
      result.kind === 'html' &&
      htmlPreview &&
      previewPath &&
      pathsReferToSameFile(result.path, previewPath)
    ) {
      htmlPreview.onOpen()
      return
    }
    onOpenWorkspaceFile?.(result.path)
  }

  return (
    <section className="ds-turn-change-summary ds-card-strong overflow-hidden rounded-[14px] border border-ds-border shadow-[0_16px_40px_rgba(86,103,136,0.08)]">
      <button
        type="button"
        onClick={() => {
          setExpanded((value) => !value)
        }}
        aria-expanded={expanded}
        className="ds-turn-change-summary__header flex w-full items-center gap-4 px-5 py-4 text-left transition hover:bg-ds-hover/40"
      >
        <span className="ds-turn-change-summary__icon flex h-12 w-12 shrink-0 items-center justify-center rounded-[16px] bg-ds-card-muted text-ds-muted">
          <FileEdit className="h-5 w-5" strokeWidth={1.85} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="ds-turn-change-summary__title block text-[18px] font-semibold tracking-[-0.02em] text-ds-ink">
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
            ? changes.map((change, index) => {
            const stats = fileStats[index]
            const open = activeId === change.id
            const filePath = change.filePath?.trim() ?? ''
            const primary = filePath || t('toolActionFile')
            const canOpenFile = Boolean(onOpenWorkspaceFile && filePath)
            const isHtmlFile = Boolean(filePath && isHtmlPreviewPath(filePath))

            return (
              <div key={change.id} className="border-b border-ds-border-muted/60 last:border-b-0">
                <div
                  className={`flex w-full items-start gap-3 px-5 py-3 ${
                    open ? 'bg-ds-hover/45' : 'hover:bg-ds-hover/35'
                  }`}
                >
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-center gap-2">
                      {filePath ? (
                        <FileChip path={filePath} variant="list" skipValidation />
                      ) : (
                        <span className="ds-turn-change-summary__path block break-all text-[14px] font-medium text-ds-ink">
                          {primary}
                        </span>
                      )}
                      {canOpenFile && isHtmlFile ? (
                        <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10.5px] font-medium text-amber-700 dark:text-amber-300">
                          <Globe2 className="h-3 w-3" strokeWidth={2} />
                          HTML
                        </span>
                      ) : null}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => setActiveId(open ? null : change.id)}
                    aria-expanded={open}
                    className="flex shrink-0 items-start gap-3 text-left"
                  >
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
                </div>

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

      {openableResults.length > 0 ? (
        <div className="border-t border-ds-border-muted/70 bg-gradient-to-b from-ds-card-muted/25 to-transparent px-4 py-3">
          <div className={compactOpenable ? 'flex flex-col gap-1' : undefined}>
            {openableResults.map((result) => (
              <TurnOpenableResultRow
                key={result.path}
                result={result}
                compact={compactOpenable}
                onOpen={() => openTurnResult(result)}
              />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}

function TurnOpenableResultRow({
  result,
  compact,
  onOpen
}: {
  result: OpenableTurnResult
  compact: boolean
  onOpen: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const label = formatHtmlPreviewPathLabel(result.path)
  const isHtml = result.kind === 'html'
  const openLabel = isHtml ? t('htmlPreviewCardOpen') : t('turnMarkdownResultOpen')
  const hint = isHtml ? t('htmlPreviewNestedHint') : t('turnMarkdownResultHint')

  if (compact) {
    return (
      <div className="flex items-center gap-3 py-1.5">
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] ${
            isHtml
              ? 'bg-amber-500/10 text-amber-600 dark:bg-amber-300/10 dark:text-amber-300'
              : 'bg-accent/10 text-accent'
          }`}
        >
          {isHtml ? (
            <Globe2 className="h-4 w-4" strokeWidth={1.9} />
          ) : (
            <FileText className="h-4 w-4" strokeWidth={1.9} />
          )}
        </span>
        <div className="min-w-0 flex-1 truncate text-[13.5px] font-semibold tracking-[-0.01em] text-ds-ink">
          {label}
        </div>
        <button
          type="button"
          onClick={onOpen}
          className="inline-flex h-8 shrink-0 items-center justify-center rounded-full bg-accent px-3.5 text-[12.5px] font-semibold text-white shadow-[0_8px_18px_rgba(0,136,255,0.2)] transition hover:brightness-110 active:scale-[0.97]"
          title={openLabel}
        >
          {openLabel}
        </button>
      </div>
    )
  }

  return (
    <div
      className={`relative flex items-center gap-3 overflow-hidden rounded-[12px] border bg-ds-elevated/90 py-2.5 pl-3.5 pr-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] ${
        isHtml
          ? 'border-amber-500/15 dark:border-amber-300/15 dark:bg-white/[0.035]'
          : 'border-ds-border'
      }`}
    >
      <span
        aria-hidden
        className={`absolute inset-y-2 left-0 w-[3px] rounded-full ${
          isHtml ? 'bg-amber-500/70 dark:bg-amber-300/60' : 'bg-accent/70'
        }`}
      />
      <span
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px] ${
          isHtml
            ? 'bg-amber-500/10 text-amber-600 dark:bg-amber-300/10 dark:text-amber-300'
            : 'bg-accent/10 text-accent'
        }`}
      >
        {isHtml ? (
          <Globe2 className="h-4 w-4" strokeWidth={1.9} />
        ) : (
          <FileText className="h-4 w-4" strokeWidth={1.9} />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13.5px] font-semibold tracking-[-0.01em] text-ds-ink">
          {label}
        </div>
        <div className="mt-0.5 truncate text-[11.5px] text-ds-muted">{hint}</div>
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="inline-flex h-8 shrink-0 items-center justify-center rounded-full bg-accent px-3.5 text-[12.5px] font-semibold text-white shadow-[0_8px_18px_rgba(0,136,255,0.2)] transition hover:brightness-110 active:scale-[0.97]"
        title={openLabel}
      >
        {openLabel}
      </button>
    </div>
  )
}

function HtmlPreviewStandaloneCard({
  path,
  onOpen
}: {
  path: string
  onOpen: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const label = formatHtmlPreviewPathLabel(path)
  return (
    <div className="ds-html-preview-card flex min-h-[64px] w-full items-center gap-3 rounded-[14px] border border-ds-border bg-ds-elevated/90 px-4 py-3 shadow-[0_12px_34px_rgba(0,0,0,0.06)]">
      <div className="ds-html-preview-card__icon flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-amber-500/10 text-amber-600 dark:bg-amber-300/10 dark:text-amber-300">
        <Globe2 className="h-5 w-5" strokeWidth={1.9} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="ds-html-preview-card__title truncate text-[14.5px] font-semibold text-ds-ink">{label}</div>
        <div className="mt-0.5 truncate text-[12px] text-ds-muted">
          {t('htmlPreviewStandaloneHint')}
        </div>
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="inline-flex h-9 shrink-0 items-center justify-center rounded-full bg-accent px-4 text-[13px] font-semibold text-white shadow-[0_10px_24px_rgba(0,136,255,0.22)] transition hover:brightness-110 active:scale-[0.97]"
        title={t('htmlPreviewCardOpen')}
      >
        {t('htmlPreviewCardOpen')}
      </button>
    </div>
  )
}

/**
 * Live one-liner for the currently-running tool, e.g. "读取文件 src/foo.ts".
 * Surfaced on the collapsed work-process header so the user knows what the
 * agent is doing right now without expanding the trace (cursor/codex pattern).
 */
function activeRunningActionLabel(blocks: ChatBlock[]): string | undefined {
  // Skip sub-agent orchestration tools (agent/agent_resume/…): a blocking
  // agent action="wait" would otherwise hijack the header for minutes. Sub-agent
  // progress is surfaced by the SubagentSummaryPanel instead.
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
  collapsible,
  expanded,
  onToggle,
  activeActionLabel
}: {
  processing: boolean
  stepCount: number
  liveStartedAt?: number
  durationMs?: number
  reasoningDurationMs?: number
  collapsible: boolean
  expanded: boolean
  onToggle: () => void
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
  const liveActionText = processing ? activeActionLabel : undefined
  const mainLabel = processing
    ? liveActionText
      ? liveActionText
      : durationText
        ? t('workingFor', { duration: durationText })
        : t('working')
    : durationText
      ? t('workedFor', { duration: durationText })
      : t('processSteps', { count: stepCount })

  const showThoughtSuffix =
    !processing &&
    typeof reasoningDurationMs === 'number' &&
    reasoningDurationMs >= 1000

  return (
    <div className="ds-work-meta w-full">
      <button
        type="button"
        onClick={collapsible ? onToggle : undefined}
        aria-expanded={collapsible ? expanded : undefined}
        disabled={!collapsible}
        className={`ds-work-meta-row group flex w-fit max-w-full items-center gap-1.5 rounded-md py-1 text-left text-[15px] font-medium text-ds-muted transition ${collapsible ? 'hover:opacity-85' : ''}`}
      >
        {processing ? (
          <span className="mr-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
            <SquareGrid size="md" className="text-ds-faint" />
          </span>
        ) : null}
        <span className={`min-w-0 truncate tabular-nums ${processing ? 'ds-shiny-text' : ''}`}>
          {mainLabel}
        </span>
        {liveActionText && durationText ? (
          <span className="shrink-0 text-ds-faint">· {durationText}</span>
        ) : null}
        {showThoughtSuffix ? (
          <span className="text-ds-faint">
            · {t('thoughtFor', { duration: formatDuration(reasoningDurationMs!) })}
          </span>
        ) : null}
        {collapsible ? (
          expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
          ) : (
            <ChevronRight
              className="h-3.5 w-3.5 shrink-0 opacity-40 transition group-hover:opacity-65"
              strokeWidth={1.8}
            />
          )
        ) : null}
      </button>
      <div aria-hidden className="h-px w-full bg-ds-border-muted/70" />
    </div>
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
      className="ds-todo-event-row group flex w-fit max-w-full items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1.5 text-left text-[13.5px] text-emerald-800 transition hover:bg-emerald-500/15 dark:text-emerald-200"
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
  return blocks.filter((block) => {
    if (shouldHideTodoToolBlock(block, todoSession)) return false
    if (
      shouldHideSubagentBlock(block, subagentSummary) &&
      !isSubagentSummaryAnchor(block, subagentSummary)
    ) {
      return false
    }
    if (shouldHideSubagentToolBlock(block, subagentSummary)) return false
    return true
  })
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
      id={`block-${summary.anchorBlockId}`}
      className="ds-subagent-summary my-2 overflow-hidden rounded-[12px] border border-ds-border-muted/70 bg-ds-card/55 shadow-[0_10px_28px_rgba(15,23,42,0.04)]"
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="ds-subagent-summary__header group flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-ds-hover/35"
      >
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ds-hover/80 text-ds-ink/75">
          {active ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
          ) : (
            <Bot className="h-3.5 w-3.5" strokeWidth={1.8} />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="ds-subagent-summary__title text-[14px] font-semibold tracking-[-0.015em] text-ds-ink">
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
        {hasFailure ? (
          <span
            className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center text-[15px] font-semibold leading-none tracking-tight text-ds-ink/70"
            aria-hidden
          >
            !
          </span>
        ) : null}
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
              <SubagentSummaryRow
                key={block.id}
                block={block}
                // Anchor id lives on the panel; other rows keep their own jump targets.
                scrollTargetId={block.id === summary.anchorBlockId ? null : block.id}
                onOpen={() => setDetailBlock(block)}
              />
            ))}
          </div>
        </div>
      ) : null}
      {detailBlock ? (
        <SubagentDetailDialog
          block={detailBlock}
          relatedBlocks={summary.blocks}
          onClose={() => setDetailBlock(null)}
        />
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
  if (isShellProbeCandidateTool(toolName)) return Terminal
  return Wrench
}

/**
 * A folded batch of consecutive same-name read-only probes (e.g. "读取文件 · 5
 * 项"). Collapsed by default with neutral styling so the work trace stays calm;
 * expanding reveals each call as its regular lightweight `ToolCard` row.
 */
function ToolBatchPanel({
  toolName,
  blocks,
  mixed = false,
  onOpenWorkspaceFile
}: {
  toolName: string
  blocks: ToolProcessBlock[]
  mixed?: boolean
  onOpenWorkspaceFile?: (path: string, line?: number) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const Icon = pickToolBatchIcon(mixed ? 'probe' : toolName)
  const meta = useMemo(() => {
    const rows = blocks.map((block) => {
      const name = toolNameFromProcessBlock(block)
      const ctx = buildToolRenderContext(block)
      return {
        toolName: name,
        detail: ctx.description || undefined,
        label: ctx.label || name
      }
    })
    return buildProbeBatchMeta(rows)
  }, [blocks])
  const composeTitle = mixed
    ? probeComposeSegments(meta.compose)
        .map((seg) => t(seg.key, { count: seg.count }))
        .join(' · ')
    : ''
  const label = mixed
    ? composeTitle || t('toolBatchProbeLabel')
    : humanizeToolName(toolName) || toolName
  const title = mixed
    ? label
    : t('toolBatchTitle', { label, count: blocks.length })
  const preview = meta.preview

  return (
    <div className="ds-tool-batch overflow-hidden rounded-[12px] border border-ds-border-muted/50 bg-ds-card/40">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="ds-tool-batch__header group w-full text-left transition hover:bg-ds-hover/40"
      >
        <Icon className="ds-tool-batch__icon shrink-0 text-ds-faint" strokeWidth={1.8} />
        <span className="ds-tool-batch__copy min-w-0 flex-1">
          <span className="ds-tool-batch__title block truncate text-ds-muted">
            {title}
          </span>
          {!expanded && preview ? (
            <span className="ds-tool-batch__preview mt-0.5 block truncate text-ds-faint" title={preview}>
              {preview}
            </span>
          ) : null}
        </span>
        <span className="ds-tool-batch__chevron" aria-hidden>
          {expanded ? (
            <ChevronDown strokeWidth={1.8} />
          ) : (
            <ChevronRight className="opacity-40 transition group-hover:opacity-65" strokeWidth={1.8} />
          )}
        </span>
      </button>
      {expanded ? (
        <div className="ds-tool-batch__body">
          {blocks.map((block) => (
            <ToolCard key={block.id} block={block} onOpenWorkspaceFile={onOpenWorkspaceFile} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function flowItemsForSubagentBlock(block: SubagentBlock): StepFlowItem[] {
  if (block.cardKind === 'delegate') {
    // Prefer the concrete tool rail; keep lifecycle tails for start/end feel.
    return subagentStepsToFlowItems(block.steps, 0, block.status)
  }
  const items: StepFlowItem[] = []
  for (const worker of block.workers ?? []) {
    const workerSteps = subagentStepsToFlowItems(block.workerSteps?.[worker.id], 1, worker.status)
    if (workerSteps.length === 0) {
      items.push({
        id: `${worker.id}-status`,
        status: lifecycleToStepStatus(worker.status),
        label: `worker · ${worker.id.slice(0, 8)} · ${worker.status}`,
        depth: 0
      })
      continue
    }
    items.push({
      id: `${worker.id}-head`,
      status: lifecycleToStepStatus(worker.status),
      label: `worker · ${worker.id.slice(0, 8)}`,
      depth: 0
    })
    items.push(...workerSteps)
  }
  return items
}

function subagentCardTitle(
  block: Pick<SubagentBlock, 'cardKind' | 'agentId' | 'agentType' | 'prompt'>,
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  const promptTitle = subagentListTitle(
    { agentId: block.agentId, agentType: block.agentType, prompt: block.prompt },
    72,
    ''
  )
  // Prefer the spawn assignment when we have one; type-only labels are the
  // fallback for cards that never received prompt (legacy / incomplete events).
  if (block.prompt?.trim()) return promptTitle
  if (block.cardKind === 'fanout') {
    return t('subagentFanoutTitle', { kind: humanizeAgentType(block.agentType) })
  }
  return t('subagentDelegateTitle', { type: humanizeAgentType(block.agentType) })
}

function SubagentSummaryRow({
  block,
  scrollTargetId,
  onOpen
}: {
  block: SubagentBlock
  scrollTargetId: string | null
  onOpen: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const statusLabel = subagentStatusLabel(block.status, t)
  const isActive = block.status === 'running' || block.status === 'pending'
  const failed = block.status === 'failed'
  const flowItems = useMemo(() => flowItemsForSubagentBlock(block), [block])
  // Collapsed by default so many agents don't flood the timeline.
  const [stepsOpen, setStepsOpen] = useState(false)
  const title = subagentCardTitle(block, t)

  return (
    <div
      id={scrollTargetId ? `block-${scrollTargetId}` : undefined}
      className="rounded-xl border border-ds-border-muted/60 bg-ds-elevated/40 px-3 py-2 text-[12.5px] leading-5 transition hover:bg-ds-hover/30"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <button
          type="button"
          onClick={() => setStepsOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={stepsOpen}
          title={block.prompt?.trim() || undefined}
        >
          <ChevronDown
            className={[
              'h-3.5 w-3.5 shrink-0 text-ds-faint transition-transform duration-200',
              stepsOpen ? 'rotate-0' : '-rotate-90'
            ].join(' ')}
            strokeWidth={1.8}
          />
          <span className="min-w-0 flex-1 truncate font-semibold tracking-[-0.01em] text-ds-ink">
            {title}
          </span>
          {isActive ? (
            <Loader2
              className="h-3 w-3 shrink-0 animate-spin text-ds-muted"
              strokeWidth={2}
            />
          ) : null}
          <span className="shrink-0 whitespace-nowrap font-medium text-ds-muted">
            {statusLabel}
          </span>
          {flowItems.length > 0 ? (
            <span className="shrink-0 whitespace-nowrap text-[11px] text-ds-faint">
              {t('subagentStepCount', {
                count: countSubagentRailSteps(flowItems)
              })}
            </span>
          ) : null}
        </button>
        {failed ? (
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center text-[14px] font-semibold leading-none tracking-tight text-ds-ink/70"
            aria-hidden
          >
            !
          </span>
        ) : null}
        {!isActive ? (
          <button
            type="button"
            onClick={onOpen}
            className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
          >
            {t('subagentDetails')}
          </button>
        ) : null}
      </div>

      {block.cardKind === 'fanout' && block.workers && block.workers.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5 pl-5">
          {block.workers.map((worker) => (
            <span
              key={worker.id}
              title={`${worker.id} · ${worker.status}`}
              className={[
                'inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-ds-hover px-1 font-mono text-[10px] text-ds-muted',
                worker.status === 'failed' ? 'font-semibold text-ds-ink' : '',
                worker.status === 'running' ? 'ring-1 ring-ds-border' : '',
                worker.status === 'completed' ? 'opacity-70' : ''
              ].join(' ')}
            >
              {worker.status === 'failed' ? '!' : worker.id.slice(-2)}
            </span>
          ))}
        </div>
      ) : null}

      {stepsOpen ? (
        <div className="mt-1.5 border-t border-ds-border-muted/50 pt-1.5">
          {flowItems.length > 0 ? (
            <StepFlow
              items={flowItems}
              compact
              emptyLabel={t('subagentStepFlowEmpty')}
            />
          ) : (
            <p className="px-1 py-1.5 text-[11.5px] text-ds-faint">
              {isActive
                ? t('subagentStepFlowWaiting')
                : t('subagentStepFlowEmpty')}
            </p>
          )}
        </div>
      ) : null}
    </div>
  )
}

/** Terminal statuses `agent_resume` accepts (manager rejects running/completed). */
function isResumableSubagentStatus(status: SubagentBlock['status']): boolean {
  return status === 'failed' || status === 'cancelled'
}

function subagentStatusDotClass(
  status: SubagentBlock['status']
): string {
  switch (status) {
    case 'running':
    case 'pending':
      return 'text-ds-ink/70'
    case 'completed':
      return 'text-ds-muted'
    case 'failed':
      return 'text-ds-ink/80 font-semibold'
    default:
      return 'text-ds-faint'
  }
}

function subagentStatusGlyph(status: SubagentBlock['status']): string {
  switch (status) {
    case 'running':
      return '●'
    case 'pending':
      return '○'
    case 'completed':
      return '✓'
    case 'failed':
      return '!'
    default:
      return '−'
  }
}

type SubagentTreeNode = {
  id: string
  label: string
  status: SubagentBlock['status']
  depth: number
}

function buildSubagentTreeNodes(
  root: SubagentBlock,
  related: SubagentBlock[]
): SubagentTreeNode[] {
  const byId = new Map<string, SubagentBlock>()
  for (const b of related) byId.set(b.agentId, b)
  byId.set(root.agentId, root)

  const nodes: SubagentTreeNode[] = []
  const seen = new Set<string>()

  const visit = (id: string, depth: number): void => {
    if (seen.has(id)) return
    seen.add(id)
    const block = byId.get(id)
    if (block) {
      nodes.push({
        id,
        label:
          block.cardKind === 'fanout'
            ? `${humanizeAgentType(block.agentType)} · fanout`
            : humanizeAgentType(block.agentType),
        status: block.status,
        depth
      })
      if (block.cardKind === 'fanout') {
        for (const worker of block.workers ?? []) {
          if (byId.has(worker.id)) {
            visit(worker.id, depth + 1)
          } else {
            nodes.push({
              id: worker.id,
              label: `worker`,
              status: worker.status,
              depth: depth + 1
            })
          }
        }
      }
      for (const childId of block.childIds ?? []) {
        visit(childId, depth + 1)
      }
      return
    }
    nodes.push({
      id,
      label: 'agent',
      status: 'pending',
      depth
    })
  }

  visit(root.agentId, 0)
  return nodes
}

function resolveSubagentFlowItems(
  root: SubagentBlock,
  related: SubagentBlock[],
  selectedId: string
): StepFlowItem[] {
  const byId = new Map<string, SubagentBlock>()
  for (const b of related) byId.set(b.agentId, b)
  byId.set(root.agentId, root)

  const selected = byId.get(selectedId)
  if (selected) {
    if (selected.cardKind === 'fanout' && selectedId === selected.agentId) {
      // Root fanout: concatenate worker rails with indent.
      const items: StepFlowItem[] = [
        {
          id: `${selected.agentId}-root`,
          status: lifecycleToStepStatus(selected.status),
          label: `${humanizeAgentType(selected.agentType)} · ${selected.status}`,
          depth: 0
        }
      ]
      for (const worker of selected.workers ?? []) {
        items.push({
          id: `${worker.id}-head`,
          status: lifecycleToStepStatus(worker.status),
          label: `worker ${worker.id.slice(0, 8)} · ${worker.status}`,
          depth: 1
        })
        items.push(
          ...subagentStepsToFlowItems(selected.workerSteps?.[worker.id], 2, worker.status)
        )
      }
      return items
    }
    return subagentStepsToFlowItems(selected.steps, 0, selected.status)
  }

  // Fanout worker without its own block — steps live on the root fanout card.
  if (root.cardKind === 'fanout') {
    return subagentStepsToFlowItems(root.workerSteps?.[selectedId], 0, root.status)
  }
  return []
}

function SubagentDetailDialog({
  block: initialBlock,
  relatedBlocks,
  onClose
}: {
  block: SubagentBlock
  relatedBlocks: SubagentBlock[]
  onClose: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  // Select the blocks array by reference — never filter inside the Zustand
  // selector (a new array each call trips useSyncExternalStore into a loop).
  const allBlocks = useChatStore((s) => s.blocks)
  const [resuming, setResuming] = useState(false)
  const [resumeError, setResumeError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState(initialBlock.agentId)

  // Prefer live store blocks so the step rail updates while the dialog is open.
  const related = useMemo(() => {
    const map = new Map<string, SubagentBlock>()
    for (const b of relatedBlocks) map.set(b.agentId, b)
    for (const b of allBlocks) {
      if (b.kind === 'subagent') map.set(b.agentId, b)
    }
    return [...map.values()]
  }, [relatedBlocks, allBlocks])

  const block =
    related.find((b) => b.agentId === initialBlock.agentId) ?? initialBlock

  const treeNodes = useMemo(
    () => buildSubagentTreeNodes(block, related),
    [block, related]
  )
  const flowItems = useMemo(
    () => resolveSubagentFlowItems(block, related, selectedId),
    [block, related, selectedId]
  )

  const selectedBlock = related.find((b) => b.agentId === selectedId) ?? null
  const selectedStatus =
    selectedBlock?.status ??
    (block.cardKind === 'fanout'
      ? block.workers?.find((w) => w.id === selectedId)?.status
      : undefined) ??
    block.status

  const title =
    block.cardKind === 'fanout'
      ? t('subagentFanoutTitle', { kind: humanizeAgentType(block.agentType) })
      : t('subagentDelegateTitle', { type: humanizeAgentType(block.agentType) })
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

  // Delegate cards resume as a single agent; fanout cards resume every
  // failed/cancelled worker via direct API (no per-worker UI exists yet).
  const resumableWorkerIds =
    block.cardKind === 'fanout'
      ? (block.workers ?? [])
          .filter((worker) => isResumableSubagentStatus(worker.status))
          .map((worker) => worker.id)
      : []
  const canResumeDelegate =
    block.cardKind === 'delegate' && isResumableSubagentStatus(block.status)
  const canResume =
    (canResumeDelegate || resumableWorkerIds.length > 0) &&
    Boolean(activeThreadId) &&
    !resuming

  const onResume = async (): Promise<void> => {
    if (!canResume || !activeThreadId) return
    setResuming(true)
    setResumeError(null)
    try {
      const ids =
        block.cardKind === 'fanout' ? resumableWorkerIds : [block.agentId]
      for (const agentId of ids) {
        await resumeThreadAgent(activeThreadId, agentId)
      }
    } catch (err) {
      setResumeError(
        err instanceof Error && err.message.trim()
          ? err.message
          : t('subagentResumeFailed')
      )
    } finally {
      setResuming(false)
    }
  }

  const [stepsOpen, setStepsOpen] = useState(() => !hasResult)

  return (
    <ResizableFullscreenDialog
      open
      onClose={onClose}
      ariaLabel={title}
      overlayClassName="ds-subagent-dialog"
      panelClassName="ds-subagent-dialog-panel"
      bodyClassName="ds-subagent-dialog-body"
      dataAttr="subagent-dialog"
      header={
        <>
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-ds-hover/80 text-ds-ink/80">
              <Bot className="h-5 w-5" strokeWidth={1.7} />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="ds-subagent-dialog__title text-[18px] font-semibold leading-tight tracking-[-0.025em] text-ds-ink">
                {title}
              </h3>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px] leading-5 text-ds-muted">
                <span className="font-mono tabular-nums text-ds-faint">{block.agentId}</span>
                <span className="inline-flex items-center rounded-full bg-ds-hover/70 px-2 py-0.5 text-[11px] font-semibold text-ds-muted">
                  {statusLabel}
                </span>
                {selectedStatus === 'failed' ? (
                  <span
                    className="text-[14px] font-semibold leading-none tracking-tight text-ds-ink/70"
                    aria-hidden
                  >
                    !
                  </span>
                ) : null}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {hasResult ? <ToolCopyButton text={resultText} className="!opacity-100" /> : null}
            {canResumeDelegate || resumableWorkerIds.length > 0 ? (
              <button
                type="button"
                disabled={!canResume}
                onClick={() => void onResume()}
                className="rounded-full bg-ds-hover px-3 py-1.5 text-[12.5px] font-semibold text-ds-ink transition active:scale-[0.97] hover:bg-ds-hover/80 disabled:opacity-45"
              >
                {resuming
                  ? t('subagentResuming')
                  : block.cardKind === 'fanout'
                    ? t('subagentResumeMulti', { count: resumableWorkerIds.length })
                    : t('subagentResume')}
              </button>
            ) : null}
            <button
              type="button"
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-black/[0.06] text-ds-muted transition active:scale-95 hover:bg-black/[0.1] hover:text-ds-ink dark:bg-white/[0.08] dark:hover:bg-white/[0.12]"
              aria-label={t('close')}
            >
              <X className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
          </div>
        </>
      }
    >
      <div className="flex min-h-full flex-col gap-4">
        {resumeError ? (
          <p className="rounded-[12px] bg-ds-hover/70 px-3 py-2 text-[12.5px] leading-5 text-ds-ink/80">
            {resumeError}
          </p>
        ) : null}
        {treeNodes.length > 1 ? (
          <section>
            <div className="mb-2 px-1 text-[12px] font-semibold tracking-[0.02em] text-ds-muted">
              {t('subagentTreeTitle')}
            </div>
            <div className="flex gap-1.5 overflow-x-auto pb-0.5 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              {treeNodes.map((node) => {
                const active = node.id === selectedId
                return (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => setSelectedId(node.id)}
                    className={[
                      'flex shrink-0 items-center gap-2 rounded-full px-3 py-1.5 text-left transition active:scale-[0.98]',
                      active
                        ? 'bg-ds-hover text-ds-ink ring-1 ring-ds-ink/20'
                        : 'bg-ds-card/70 text-ds-ink ring-1 ring-ds-border/60 hover:bg-ds-hover/50'
                    ].join(' ')}
                    style={node.depth > 0 ? { marginLeft: node.depth > 1 ? 4 : 0 } : undefined}
                  >
                    <span
                      className={`text-[11px] ${subagentStatusDotClass(node.status)}`}
                      aria-hidden
                    >
                      {subagentStatusGlyph(node.status)}
                    </span>
                    <span className="max-w-[9rem] truncate text-[12.5px] font-medium tracking-[-0.01em]">
                      {node.label}
                    </span>
                    <span className="font-mono text-[10px] text-ds-faint">
                      {node.id.slice(0, 6)}
                    </span>
                  </button>
                )
              })}
            </div>
          </section>
        ) : null}

        <section>
          <button
            type="button"
            className="mb-2 flex w-full items-center justify-between gap-2 px-1 text-left"
            onClick={() => setStepsOpen((value) => !value)}
            aria-expanded={stepsOpen}
          >
            <h4 className="text-[12px] font-semibold tracking-[0.02em] text-ds-muted">
              {t('subagentStepFlowTitle')}
            </h4>
            <span className="flex items-center gap-1.5 font-mono text-[11px] tabular-nums text-ds-faint">
              {selectedId.slice(0, 10)} · {subagentStatusLabel(selectedStatus, t)}
              <ChevronDown
                className={`h-3.5 w-3.5 transition ${stepsOpen ? 'rotate-180' : ''}`}
                strokeWidth={1.9}
              />
            </span>
          </button>
          {stepsOpen ? (
            <div className="overflow-hidden rounded-[16px] border border-ds-border/70 bg-ds-card/55 px-1.5 py-1">
              <StepFlow items={flowItems} emptyLabel={t('subagentStepFlowEmpty')} />
            </div>
          ) : null}
        </section>

        <section className="ds-subagent-report min-h-0 flex-1">
          <div className="mb-2 px-1 text-[12px] font-semibold tracking-[0.02em] text-ds-muted">
            {resultTitle}
          </div>
          <div className="ds-subagent-report-body ds-markdown ds-markdown--answer ds-chat-answer text-ds-ink">
            <AssistantMarkdown text={finalText} streaming={false} />
          </div>
        </section>
      </div>
    </ResizableFullscreenDialog>
  )
}

function MidTurnPrefaceLine({
  text,
  showIndicator
}: {
  text: string
  /** True only for the newest in-progress thinking/preface row. */
  showIndicator: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const { preview, clipped } = clipMidTurnPrefaceText(text)
  const shown = expanded || !clipped ? text.trim() : preview

  return (
    <div className="ds-process-narration flex items-start gap-1.5 py-0.5">
      {showIndicator ? <SquareGrid className="mt-1 text-ds-faint" /> : null}
      <div className="min-w-0 flex-1">
        <p className="whitespace-pre-wrap text-[13.5px] leading-6 text-ds-muted">{shown}</p>
        {clipped ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-0.5 text-[11.5px] font-medium text-ds-faint transition hover:text-ds-muted"
          >
            {expanded ? t('collapse') : t('expand')}
          </button>
        ) : null}
      </div>
    </div>
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
 *  - approval         → null (pending cards live on the tool + composer dock)
 *  - user_input       → pending null (composer dock); submitted = quiet Q→A summary
 *  - elevation        → pending null (tool + composer dock); resolved stays inline
 *  - evol/etc         → existing Bubble/Block components, never hidden
 *
 * The 4 `shouldHide*` patches are gone: todo/subagent were never wrong-blocked
 * because we no longer group reasoning+tools into phases that misplace them.
 */
function ProcessStream({
  blocks,
  processing,
  todoSession = null,
  todoEvents = [],
  subagentSummary = null,
  onOpenWorkspaceFile
}: {
  blocks: ChatBlock[]
  processing: boolean
  todoSession?: TodoTurnSession | null
  todoEvents?: TodoTurnEvent[]
  subagentSummary?: SubagentTurnSummary | null
  onOpenWorkspaceFile?: (path: string, line?: number) => void
}): ReactElement {
  const visible = visibleExecutionBlocks(
    blocks,
    todoSession,
    subagentSummary
  )
  const rows = groupProcessRows(visible)
  const chunks = planProcessRenderChunks(rows, processing)
  // Only the first reasoning segment of a turn earns a live preview. Once a
  // completed reasoning item exists, later reasoning stays collapsed so the
  // transcript remains an execution story rather than a scrolling thought log.
  const showLiveReasoningPreview = !blocks.some(
    (block) => block.kind === 'reasoning' && block.id !== 'live-reasoning'
  )
  const thinkingIndicatorId = trailingThinkingIndicatorId(rows, processing)

  const renderRow = (row: RenderRow): ReactElement =>
    row.type === 'tool_batch' ? (
      <ToolBatchPanel
        key={`batch-${row.blocks[0]!.id}`}
        toolName={row.toolName}
        blocks={row.blocks}
        mixed={row.mixed}
        onOpenWorkspaceFile={onOpenWorkspaceFile}
      />
    ) : (
      <ProcessStreamEntry
        key={row.block.id}
        block={row.block}
        processing={processing}
        showThinkingIndicator={thinkingIndicatorId === row.block.id}
        todoSession={todoSession}
        todoEvents={todoEvents}
        subagentSummary={subagentSummary}
        showLiveReasoningPreview={showLiveReasoningPreview}
        onOpenWorkspaceFile={onOpenWorkspaceFile}
      />
    )

  return (
    <div className="ds-process-rail flex flex-col gap-1.5 pt-1">
      {chunks.map((chunk) =>
        chunk.type === 'work_summary' ? (
          <SettledWorkSummaryRow
            key={chunk.id}
            summary={chunk.summary}
            rows={chunk.rows}
            renderRow={renderRow}
          />
        ) : (
          renderRow(chunk.row)
        )
      )}
    </div>
  )
}

function SettledWorkSummaryRow({
  summary,
  rows,
  renderRow
}: {
  summary: ProcessWorkSummary
  rows: RenderRow[]
  renderRow: (row: RenderRow) => ReactElement
}): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const parts = [
    ...probeComposeSegments(summary.compose).map((seg) => t(seg.key, { count: seg.count })),
    summary.editCount > 0
      ? summary.editCount === 1
        ? t('groupEditedFile')
        : t('groupEditedFiles', { count: summary.editCount })
      : '',
    summary.toolCount > 0
      ? summary.toolCount === 1
        ? t('groupUsedTool')
        : t('groupUsedTools', { count: summary.toolCount })
      : ''
  ].filter(Boolean)
  const label = parts.join(' · ') || t('processSteps', { count: rows.length })

  return (
    <div className="ds-work-summary">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="group flex w-fit max-w-full items-center gap-1.5 py-0.5 text-left text-[13.5px] font-medium text-ds-faint transition hover:text-ds-muted"
      >
        <span className="min-w-0 truncate">{label}</span>
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
        ) : (
          <ChevronRight
            className="h-3.5 w-3.5 shrink-0 opacity-40 transition group-hover:opacity-65"
            strokeWidth={1.8}
          />
        )}
      </button>
      {expanded ? <div className="flex flex-col gap-1.5 pt-1">{rows.map(renderRow)}</div> : null}
    </div>
  )
}

function ProcessStreamEntry({
  block,
  processing,
  showThinkingIndicator = false,
  todoSession = null,
  todoEvents = [],
  subagentSummary = null,
  showLiveReasoningPreview = false,
  onOpenWorkspaceFile
}: {
  block: ChatBlock
  processing: boolean
  /** Pulse Square Grid only on the newest thinking/preface row. */
  showThinkingIndicator?: boolean
  todoSession?: TodoTurnSession | null
  todoEvents?: TodoTurnEvent[]
  subagentSummary?: SubagentTurnSummary | null
  showLiveReasoningPreview?: boolean
  onOpenWorkspaceFile?: (path: string, line?: number) => void
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
    return <ToolCard block={block} onOpenWorkspaceFile={onOpenWorkspaceFile} />
  }
  if (block.kind === 'reasoning') {
    return (
      <ReasoningEntry
        block={block}
        processing={processing}
        showIndicator={showThinkingIndicator}
        showLivePreview={showLiveReasoningPreview}
      />
    )
  }
  if (block.kind === 'assistant') {
    // The model's 承上启下 storyline line written before a tool batch. Render
    // it like the reasoning narration line (SquareGrid + muted text) so it reads as
    // the throughline the user follows while tools execute. When the frame
    // carries no wording yet (structured intent only), show a neutral
    // progress state derived from metadata instead of fabricating prose.
    // Long prefaces are clipped — repair plans / mini-reports belong in the
    // final answer bubble, not the process rail.
    if (block.agentSegment === 'mid_turn_preface' || block.agentSegment == null) {
      if (!block.text.trim()) {
        if (!block.processIntent) return null
        return (
          <NeutralIntentLine intent={block.processIntent} showIndicator={showThinkingIndicator} />
        )
      }
      return <MidTurnPrefaceLine text={block.text} showIndicator={showThinkingIndicator} />
    }
    // Other assistant content that landed in the work trace (interstitial
    // final-answer segments). These are already persisted — do not keep
    // parseIncompleteMarkdown on for the whole turn.
    return (
      <div className="ds-process-assistant-md ds-markdown text-[13.5px] leading-6 text-ds-muted">
        <AssistantMarkdown
          text={block.text}
          streaming={shouldParseIncompleteAssistantMarkdown(false)}
        />
      </div>
    )
  }
  // Approvals + pending elevation/user_input render on the tool card and in
  // the composer dock. Resolved elevation stays here as an audit row.
  if (block.kind === 'approval') return null
  if (block.kind === 'elevation') {
    if (block.status === 'pending') return null
    return <ElevationBubble block={block} />
  }
  if (block.kind === 'evolution') return <EvolutionBubble block={block} />
  if (block.kind === 'user_input') {
    if (block.status === 'pending') return null
    return <UserInputBubble block={block} />
  }
  if (block.kind === 'subagent') return <SubagentBubble block={block} />
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
  processing,
  showIndicator,
  showLivePreview
}: {
  block: Extract<ChatBlock, { kind: 'reasoning' }>
  processing: boolean
  /** Newest thinking row only — older steps stay text-only. */
  showIndicator: boolean
  showLivePreview: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const narration = block.narration?.trim()
  const text = block.text.trim()
  const isLive = block.id === 'live-reasoning'
  const showStreamingPreview = isLive && processing && showLivePreview && !!text

  if (showStreamingPreview) {
    // Keep a short trailing window so the preview stays scannable while
    // streaming; older tokens dissolve under the top fade mask.
    const preview = text.length > 480 ? text.slice(-480) : text
    return (
      <div className="ds-live-thinking py-0.5">
        <div className="flex items-center gap-1.5 text-[12px] font-medium text-ds-faint">
          <SquareGrid className="text-ds-faint" />
          <span className="ds-shiny-text">{t('thinkingNow')}</span>
        </div>
        <div className="ds-live-thinking-viewport mt-1.5">
          <p className="whitespace-pre-wrap text-[12.5px] leading-[1.55] text-ds-faint/70">
            {preview}
            <span className="ds-live-thinking-caret" aria-hidden />
          </p>
        </div>
      </div>
    )
  }

  // Narration is the user-facing line — show it directly, no toggle.
  // Indicator only on the newest step; earlier steps are text-only.
  if (narration) {
    return (
      <div className="ds-process-narration flex items-start gap-1.5 py-0.5">
        {showIndicator ? <SquareGrid className="mt-1 text-ds-faint" /> : null}
        <p className="text-[13.5px] leading-6 text-ds-faint/85">{narration}</p>
      </div>
    )
  }

  // No narration: collapsible raw reasoning.
  if (!text) return <></>
  return (
    <div className="ds-process-reasoning flex flex-col">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="ds-process-reasoning__toggle group flex w-fit items-center gap-1.5 py-0.5 text-left text-[14px] font-medium text-ds-muted transition hover:opacity-85"
      >
        {showIndicator ? <SquareGrid className="text-ds-faint" /> : null}
        <span className={showIndicator ? 'ds-shiny-text' : ''}>{t('thinkingLabel')}</span>
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-0 transition group-hover:opacity-55" strokeWidth={1.8} />
        )}
      </button>
      {expanded ? (
        <div className="mt-1 border-l-2 border-ds-border-muted/35 pl-3">
          <div className="ds-markdown text-[13.5px] leading-6 text-ds-faint/80">
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
      className={`ds-model-meta-tag flex min-w-0 text-right ${className}`.trim()}
      title={t('turnModelBadgeTitle', { model: label })}
    >
      <span className="truncate text-[12px] tracking-tight text-ds-faint/85">
        {label}
      </span>
    </div>
  )
}

/** Icon + name chip for `@plugin:` / `/skill` / `@connector` wire prefixes. */
function UserFocusChip({
  kind,
  name
}: {
  kind: 'plugin' | 'skill' | 'connector'
  name: string
}): ReactElement {
  const { t, i18n } = useTranslation('common')
  const displayName =
    kind === 'plugin' ? pluginDisplayTitle(name, i18n.language) : name
  const meta =
    kind === 'plugin'
      ? {
          Icon: Puzzle,
          className:
            'border-[rgba(168,85,247,0.22)] bg-[rgba(168,85,247,0.08)] text-[#a855f7]',
          title: t('composerPluginFocus', { name: displayName })
        }
      : kind === 'skill'
        ? {
            Icon: Sparkles,
            className:
              'border-[rgba(79,124,255,0.22)] bg-[rgba(79,124,255,0.08)] text-[#4f7cff]',
            title: t('composerSkillFocus', { name })
          }
        : {
            Icon: Plug,
            className:
              'border-[rgba(16,185,129,0.22)] bg-[rgba(16,185,129,0.08)] text-[#10b981]',
            title: t('composerConnectorFocus', { name })
          }
  const Icon = meta.Icon
  return (
    <span
      title={meta.title}
      className={`ds-user-message-chip ${meta.className}`}
    >
      <Icon strokeWidth={1.75} aria-hidden />
      <span className="truncate">
        {kind === 'plugin' ? t('composerPluginBadge', { name: displayName }) : name}
      </span>
    </span>
  )
}

/** Chip for HTML preview element picks — wire JSON stays hidden in the bubble. */
function PreviewPickChip({
  label,
  onRemove
}: {
  label: string
  onRemove?: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <span
      title={t('composerPreviewPickFocus', { name: label })}
      className={`ds-user-message-chip border-[rgba(14,165,233,0.22)] bg-[rgba(14,165,233,0.08)] text-[#0ea5e9] ${
        onRemove ? 'ds-user-message-chip--action' : ''
      }`}
    >
      <Wand2 strokeWidth={1.75} aria-hidden />
      <span className="truncate">{label}</span>
      {onRemove ? (
        <button
          type="button"
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            onRemove()
          }}
          aria-label={t('composerPreviewPickRemove', { name: label })}
          title={t('composerPreviewPickRemove', { name: label })}
          className="inline-flex h-[1.2em] w-[1.2em] shrink-0 items-center justify-center rounded-full text-[#0ea5e9]/70 transition hover:bg-[rgba(14,165,233,0.22)] hover:opacity-100"
        >
          <X className="h-[0.75em] w-[0.75em]" strokeWidth={2.25} aria-hidden />
        </button>
      ) : null}
    </span>
  )
}

const REWIND_CONFIRM_FILE_LIMIT = 8

/**
 * User message bubble: pencil enters edit mode. A single Resend action rewinds
 * the conversation; when rewind-preview reports file changes, a confirm dialog
 * asks whether to restore code or keep workspace edits.
 */
function UserMessageBubble({
  block
}: {
  block: Extract<ChatBlock, { kind: 'user' }>
}): ReactElement {
  const { t } = useTranslation('common')
  const busy = useChatStore((s) => s.busy)
  const rewindAndResend = useChatStore((s) => s.rewindAndResend)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const previewPick = useMemo(() => parsePreviewPickWireMessage(block.text), [block.text])
  const focus = useMemo(
    () => (previewPick ? null : parseUserFocusPrefix(block.text)),
    [block.text, previewPick]
  )
  const displayBody = previewPick
    ? previewPick.userRequest
    : focus
      ? focus.body
      : block.text
  const previewChipLabels = previewPick?.chipLabels ?? []
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(displayBody)
  const [editPicks, setEditPicks] = useState(() => previewPick?.picks ?? [])
  const [submitting, setSubmitting] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [confirm, setConfirm] = useState<{
    files: string[]
    conflicts: string[]
    skipped: string[]
    previewFailed: boolean
    missingRoots: string[]
    noCheckpoint: number
  } | null>(null)
  const [forceConflicts, setForceConflicts] = useState(false)
  // File restore only works for messages persisted on the runtime (`item_…`).
  // Restore writes the recorded execution root. After a successful publish that
  // root is the project; a vanished copy skips file restore.
  const canRestoreFiles = activeThreadId != null && block.id.startsWith('item_')
  const hasMissingRoots = (confirm?.missingRoots.length ?? 0) > 0
  const hasNoCheckpoint = (confirm?.noCheckpoint ?? 0) > 0
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!editing || confirm) return
    const el = textareaRef.current
    if (!el) return
    el.focus()
    const len = el.value.length
    el.setSelectionRange(len, len)
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 360)}px`
  }, [editing, confirm])

  useEffect(() => {
    if (!confirm) return
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setConfirm(null)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [confirm])

  const startEdit = (): void => {
    if (busy) return
    setDraft(
      previewPick ? previewPick.userRequest : focus ? focus.body : block.text
    )
    setEditPicks(previewPick?.picks ?? [])
    setConfirm(null)
    setEditing(true)
  }

  const cancelEdit = (): void => {
    setDraft(
      previewPick ? previewPick.userRequest : focus ? focus.body : block.text
    )
    setEditPicks(previewPick?.picks ?? [])
    setConfirm(null)
    setEditing(false)
  }

  const commitResend = async (restoreFiles: boolean, force = false): Promise<void> => {
    const trimmed = draft.trim()
    if (!trimmed || busy || submitting) return
    const wireText =
      editPicks.length > 0
        ? formatPreviewPickWireMessage(editPicks, trimmed)
        : focus
          ? composeUserFocusMessage(focus, trimmed)
          : trimmed
    setConfirm(null)
    setSubmitting(true)
    try {
      const succeeded = await rewindAndResend(block.id, wireText, {
        restoreFiles: restoreFiles && canRestoreFiles,
        forceConflicts: restoreFiles && canRestoreFiles && force,
        retryDraft: trimmed
      })
      if (succeeded) setEditing(false)
    } finally {
      setSubmitting(false)
    }
  }

  const requestResend = async (): Promise<void> => {
    const trimmed = draft.trim()
    if (!trimmed || busy || submitting || previewing || confirm) return

    if (!canRestoreFiles || !activeThreadId) {
      await commitResend(false)
      return
    }

    const provider = getProvider(useChatStore.getState().providerId)
    if (typeof provider.rewindPreview !== 'function') {
      // Older runtimes can still support rewind-with-restore even when the
      // preview endpoint is absent. Preserve the new default via a generic
      // warning instead of silently falling back to conversation-only rewind.
      setForceConflicts(false)
      setConfirm({
        files: [],
        conflicts: [],
        skipped: [],
        previewFailed: true,
        missingRoots: [],
        noCheckpoint: 0
      })
      return
    }

    setPreviewing(true)
    try {
      const preview = await provider.rewindPreview(activeThreadId, block.id)
      if (
        !rewindPreviewNeedsConfirmation(
          preview.files,
          preview.missingRoots ?? [],
          preview.noCheckpoint
        )
      ) {
        await commitResend(false)
        return
      }
      setForceConflicts(false)
      setConfirm({
        files: preview.files,
        conflicts: preview.conflicts ?? [],
        skipped: preview.skipped ?? [],
        previewFailed: false,
        missingRoots: preview.missingRoots ?? [],
        noCheckpoint: preview.noCheckpoint
      })
    } catch {
      setForceConflicts(false)
      setConfirm({
        files: [],
        conflicts: [],
        skipped: [],
        previewFailed: true,
        missingRoots: [],
        noCheckpoint: 0
      })
    } finally {
      setPreviewing(false)
    }
  }

  if (editing) {
    const actionsDisabled = !draft.trim() || busy || submitting || previewing || confirm !== null
    const conflictSet = new Set(confirm?.conflicts ?? [])
    const skippedSet = new Set(confirm?.skipped ?? [])
    // Unresolved paths first so they stay visible when the list is cut.
    const confirmFiles = [...(confirm?.files ?? [])].sort(
      (a, b) =>
        Number(conflictSet.has(b) || skippedSet.has(b)) -
        Number(conflictSet.has(a) || skippedSet.has(a))
    )
    const visibleFiles = confirmFiles.slice(0, REWIND_CONFIRM_FILE_LIMIT)
    const moreFiles = confirmFiles.length - visibleFiles.length
    const hasConflicts = conflictSet.size > 0
    const hasSkipped = skippedSet.size > 0
    const confirmModel = confirm ? rewindResendConfirmModel(confirm.previewFailed) : null

    return (
      <div id={`block-${block.id}`} className="ds-user-message">
        <div className="ds-user-message-bubble ds-user-message-edit-bubble min-w-0">
          {editPicks.length > 0 || focus ? (
            <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
              {editPicks.map((pick, index) => {
                const label = formatPreviewPickChipLabel(pick)
                return (
                  <PreviewPickChip
                    key={`${pick.filePath}:${pick.selector}:${index}`}
                    label={label}
                    onRemove={() => {
                      setEditPicks((current) => current.filter((_, i) => i !== index))
                    }}
                  />
                )
              })}
              {focus ? <UserFocusChip kind={focus.kind} name={focus.name} /> : null}
            </div>
          ) : null}
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
                if (confirm) setConfirm(null)
                else cancelEdit()
              } else if (
                !confirm &&
                e.key === 'Enter' &&
                (e.metaKey || e.ctrlKey)
              ) {
                e.preventDefault()
                void requestResend()
              }
            }}
            rows={2}
            className="ds-user-message-edit-textarea block w-full min-w-0 resize-none break-words bg-transparent text-[15px] font-medium leading-[1.58] text-ds-ink outline-none [overflow-wrap:anywhere]"
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={cancelEdit}
              disabled={submitting || previewing}
              className="rounded-md px-3 py-1 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
            >
              {t('rewindCancel')}
            </button>
            <button
              type="button"
              onClick={() => void requestResend()}
              disabled={actionsDisabled}
              title={t('rewindResendHint')}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1 text-[13px] font-medium text-white shadow-sm transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {previewing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} aria-hidden />
              ) : null}
              {previewing ? t('rewindResendPreviewing') : t('rewindResend')}
            </button>
          </div>
        </div>
        <div className="mt-2 flex min-w-0 items-center justify-end">
          <ModelMetaTag label={block.modelLabel} />
        </div>
        {confirm && typeof document !== 'undefined'
          ? createPortal(
              <div
                className="ds-no-drag fixed inset-0 z-[80] flex items-center justify-center bg-[var(--ds-material-overlay)] p-4"
                onClick={(event) => {
                  if (event.target === event.currentTarget) setConfirm(null)
                }}
              >
                <div
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby={`rewind-resend-confirm-${block.id}`}
                  className="ds-chat-rail-modal ds-modal-surface ds-modal-surface--solid flex w-full max-w-md flex-col overflow-hidden rounded-2xl"
                >
                  <div className="flex shrink-0 items-start justify-between gap-3 border-b border-ds-border-muted px-5 py-3.5">
                    <h2
                      id={`rewind-resend-confirm-${block.id}`}
                      className="ds-chat-rail-modal__title min-w-0 text-[16px] font-semibold leading-snug text-ds-ink"
                    >
                      {t('rewindResendConfirmTitle')}
                    </h2>
                    <button
                      type="button"
                      onClick={() => setConfirm(null)}
                      aria-label={t('close')}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
                    >
                      <X className="h-4 w-4" strokeWidth={1.9} />
                    </button>
                  </div>
                  <div className="space-y-3 px-5 py-4">
                    <p className="text-[13px] leading-5 text-ds-muted">
                      {confirmModel?.body === 'preview_failed'
                        ? t('rewindResendConfirmPreviewFailed')
                        : t('rewindResendConfirmBody')}
                    </p>
                    {!confirm.previewFailed && visibleFiles.length > 0 ? (
                      <ul className="max-h-40 overflow-y-auto rounded-xl border border-ds-border-muted/70 bg-ds-main/30 px-3 py-2 font-mono text-[12px] leading-5 text-ds-ink">
                        {visibleFiles.map((file) => (
                          <li
                            key={file}
                            className="flex min-w-0 items-center gap-2"
                            title={file}
                          >
                            <span className="min-w-0 truncate">{file}</span>
                            {conflictSet.has(file) ? (
                              <span className="shrink-0 rounded bg-amber-500/15 px-1.5 text-[10px] font-sans font-medium leading-4 text-amber-500">
                                {t('rewindResendConfirmConflictTag')}
                              </span>
                            ) : skippedSet.has(file) ? (
                              <span className="shrink-0 rounded bg-ds-hover px-1.5 text-[10px] font-sans font-medium leading-4 text-ds-muted">
                                {t('rewindResendConfirmSkippedTag')}
                              </span>
                            ) : null}
                          </li>
                        ))}
                        {moreFiles > 0 ? (
                          <li className="pt-1 text-ds-faint">
                            {t('rewindResendConfirmMoreFiles', { count: moreFiles })}
                          </li>
                        ) : null}
                      </ul>
                    ) : null}
                    {hasConflicts ? (
                      <div className="space-y-2">
                        <p className="text-[12px] leading-5 text-amber-500">
                          {t('rewindResendConfirmConflictNote', {
                            count: conflictSet.size
                          })}
                        </p>
                        <label className="flex cursor-pointer items-center gap-2 text-[12px] leading-5 text-ds-muted">
                          <input
                            type="checkbox"
                            checked={forceConflicts}
                            onChange={(e) => setForceConflicts(e.target.checked)}
                            className="h-3.5 w-3.5 accent-amber-500"
                          />
                          {t('rewindResendConfirmForce')}
                        </label>
                      </div>
                    ) : null}
                    {hasSkipped || hasMissingRoots ? (
                      <p className="text-[12px] leading-5 text-ds-muted">
                        {t('rewindResendConfirmUnavailableNote', {
                          count: Math.max(skippedSet.size, confirm.missingRoots.length)
                        })}
                      </p>
                    ) : null}
                    {hasNoCheckpoint ? (
                      <p className="text-[12px] leading-5 text-amber-500">
                        {t('rewindResendConfirmNoCheckpoint', {
                          count: confirm.noCheckpoint
                        })}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-2 border-t border-ds-border-muted px-5 py-3">
                    <button
                      type="button"
                      onClick={() => setConfirm(null)}
                      className="rounded-md px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
                    >
                      {t('rewindCancel')}
                    </button>
                    {confirmModel?.actions.includes('conversation_only') ? (
                      <button
                        type="button"
                        onClick={() => void commitResend(false)}
                        disabled={submitting}
                        className="rounded-md px-3 py-1.5 text-[13px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {t('rewindResendConfirmConversationOnly')}
                      </button>
                    ) : null}
                    {confirmModel?.actions.includes('restore_code') ? (
                      <button
                        type="button"
                        autoFocus
                        onClick={() => void commitResend(true, forceConflicts)}
                        disabled={submitting}
                        className="rounded-md bg-accent px-3 py-1.5 text-[13px] font-medium text-white shadow-sm transition hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {hasSkipped || hasMissingRoots || hasNoCheckpoint
                          ? t('rewindResendConfirmRestoreAvailable')
                          : t('rewindResendConfirmRestore')}
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>,
              document.body
            )
          : null}
      </div>
    )
  }

  return (
    <div id={`block-${block.id}`} className="ds-user-message group relative">
      <div className="ds-user-message-bubble min-w-0">
        {previewChipLabels.length > 0 || focus || displayBody ? (
          <div
            className={`whitespace-pre-wrap break-words [overflow-wrap:anywhere] ${
              previewChipLabels.length > 0 || focus
                ? 'text-start'
                : 'text-justify [text-justify:inter-ideograph]'
            }`}
          >
            {[
              ...previewChipLabels.map((label, index) => (
                <PreviewPickChip key={`${label}:${index}`} label={label} />
              )),
              focus ? (
                <UserFocusChip key="focus" kind={focus.kind} name={focus.name} />
              ) : null,
              displayBody ? <UserMessageRichText key="body" text={displayBody} /> : null
            ]}
          </div>
        ) : null}
      </div>
      <div className="mt-2 flex min-w-0 items-center justify-between gap-3 text-ds-faint opacity-90 transition group-hover:opacity-100">
        <ModelMetaTag label={block.modelLabel} className="flex-1 justify-start text-left" />
        <div className="ds-user-message-actions flex items-center justify-end gap-3">
          <CopyFeedbackButton text={displayBody || block.text} iconOnly />
          <button
            type="button"
            onClick={startEdit}
            disabled={busy}
            title={t('rewindEditMessage')}
            aria-label={t('rewindEditMessage')}
            className="ds-rewind-trigger rounded-md p-1 hover:bg-ds-hover hover:text-ds-muted disabled:cursor-not-allowed disabled:hover:text-ds-faint"
          >
            <PencilLine className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>
      </div>
    </div>
  )
}

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
  const title = subagentCardTitle(block, t)
  const statusLabel = subagentStatusLabel(block.status, t)

  return (
    <div
      id={`block-${block.id}`}
      className="ds-subagent-bubble rounded-[14px] border border-ds-border-muted/70 bg-ds-card/55 px-4 py-4 text-[13px] leading-6 text-ds-ink shadow-[0_12px_30px_rgba(15,23,42,0.04)]"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-center gap-2 font-semibold tracking-[-0.015em] text-ds-ink">
          <Bot className="h-4 w-4 shrink-0 text-ds-muted" strokeWidth={1.8} />
          {title}
          {block.status === 'failed' ? (
            <span className="text-[14px] font-semibold leading-none text-ds-ink/70" aria-hidden>
              !
            </span>
          ) : null}
        </div>
        <span className="font-mono text-[11px] text-ds-faint">{block.agentId.slice(0, 10)}</span>
      </div>
      <p className="mt-1 text-[12px] text-ds-muted">{statusLabel}</p>
      {block.cardKind === 'fanout' && block.workers && block.workers.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {block.workers.map((worker) => (
            <span
              key={worker.id}
              title={`${worker.id} · ${worker.status}`}
              className={[
                'inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-ds-hover px-1 font-mono text-[10px] text-ds-muted',
                worker.status === 'failed' ? 'font-semibold text-ds-ink' : '',
                worker.status === 'running' ? 'ring-1 ring-ds-border' : '',
                worker.status === 'completed' ? 'opacity-70' : ''
              ].join(' ')}
            >
              {worker.status === 'failed' ? '!' : worker.id.slice(-2)}
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

function formatMessageDateTime(
  input: string,
  locale: string,
  timestampFormat: ReturnType<typeof getTimestampFormat> = 'locale'
): string {
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) return input
  const now = new Date()
  const sameYear = date.getFullYear() === now.getFullYear()
  return new Intl.DateTimeFormat(locale, {
    ...(sameYear ? {} : { year: 'numeric' }),
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    ...(timestampFormat === 'locale' ? {} : { hour12: timestampFormat === '12-hour' })
  }).format(date)
}

function MessageBubble({ block }: { block: ChatBlock }): ReactElement | null {
  const { t, i18n } = useTranslation('common')
  const timestampFormat = useSyncExternalStore(subscribeAppearance, getTimestampFormat)
  if (block.kind === 'user') {
    return <UserMessageBubble block={block} />
  }
  if (block.kind === 'assistant') {
    const streaming = shouldParseIncompleteAssistantMarkdown(block.id === 'live-assistant')
    const createdAtLabel = block.createdAt
      ? formatMessageDateTime(block.createdAt, i18n.language, timestampFormat)
      : null
    return (
      <div id={`block-${block.id}`} className="group/message flex min-w-0 max-w-full flex-col">
        <div className="ds-markdown ds-markdown--answer ds-chat-answer min-w-0 max-w-full text-ds-ink">
          <AssistantMarkdown text={block.text} streaming={streaming} />
        </div>
        {!streaming ? (
          <div className="ds-assistant-message-meta mt-1 flex min-h-5 min-w-0 items-center justify-between gap-3 text-[11.5px] text-ds-faint opacity-0 transition duration-150 group-hover/message:opacity-100">
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
      <div id={`block-${block.id}`} className="ds-card-soft rounded-[12px] px-4 py-3 text-[13.5px] leading-6 text-ds-faint/80">
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
    if (block.status === 'pending') return null
    return <UserInputBubble block={block} />
  }
  if (block.kind === 'subagent') {
    return <SubagentBubble block={block} />
  }
  if (block.kind === 'approval') {
    return null
  }
  if (block.kind === 'evolution') {
    return <EvolutionBubble block={block} />
  }
  if (block.kind === 'elevation') {
    if (block.status === 'pending') return null
    return <ElevationBubble block={block} />
  }
  return (
    <div className="ds-card-soft rounded-[12px] px-3 py-2 text-[13.5px] text-ds-muted">
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
