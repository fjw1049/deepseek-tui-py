import type { ReactElement, RefObject } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  lazy,
  memo,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore
} from 'react'
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
  Wrench,
  X
} from 'lucide-react'
import {
  formatHtmlPreviewPathLabel,
  selectPrimaryMarkdownResult
} from '../../lib/html-preview-detection'
import { TaskSuggestionHero, TaskSuggestionOfflineHero } from './TaskSuggestionHero'
import type { ChatBlock, RuntimeConnectionStatus, ToolBlock } from '../../agent/types'
import {
  countDiffStats,
  extractDiffFilePath,
  formatFilePathForDisplay,
  looksLikeUnifiedDiff,
  sumDiffStats
} from '../../lib/diff-stats'
import {
  resolveLatestTurnDiffId,
  toolBlocksFromTurnSummary,
  turnSummaryFromSources,
  type TurnDiffSnapshot
} from '../../lib/turn-mutation-view'
import { useDeferredRender } from '../../hooks/use-deferred-render'
import { getTimestampFormat, subscribeAppearance } from '../../lib/apply-appearance'
import { useChatStore } from '../../store/chat-store'
import { DiffView } from '../DiffView'
import { EvolutionBubble } from './EvolutionBubble'
import { ElevationBubble } from './ElevationBubble'
import { InlineTodoBlock } from './InlineTodoBlock'
import { UserInputBubble } from './UserInputBubble'
import { WorkflowBlock } from './WorkflowBlock'
import { StepFlow, lifecycleToStepStatus, type StepFlowItem } from './StepFlow'
import { humanizeAgentType } from '../../lib/agent-type-label'
import { subagentStepsToFlowItems } from '../../lib/subagent-mailbox'
import {
  buildProbeBatchMeta,
  isMergeableProbeTool,
  probeComposeSegments
} from '../../lib/step-flow-collapse'
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
import { parseUserFocusPrefix, composeUserFocusMessage } from '../../lib/user-focus-prefix'
import { pluginDisplayTitle } from '../extensions/plugin-presentation'
import { QueryTrail } from './QueryTrail'
import { createActiveTrailStore, deriveQueryTrailItems } from './queryTrail.logic'
import { ResizableFullscreenDialog } from './ResizableFullscreenDialog'

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
  /** Localhost / URL web preview card (not a workspace file). */
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
  htmlPreviewAction = null,
  onOpenWorkspaceFile,
  devPreviewCard,
  stageCentered = false,
  useChatStageWidth = true,
  withOperationColumn = false
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const chooseWorkspace = useChatStore((s) => s.chooseWorkspace)
  const busy = useChatStore((s) => s.busy)
  const currentTurnId = useChatStore((s) => s.currentTurnId)
  const lastCompletedTurnId = useChatStore((s) => s.lastCompletedTurnId)
  const turnDiffByTurnId = useChatStore((s) => s.turnDiffByTurnId)
  const currentTurnUserId = useChatStore((s) => s.currentTurnUserId)
  const latestTurnDiffId = resolveLatestTurnDiffId(currentTurnId, lastCompletedTurnId)
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

  useEffect(() => {
    if (!stickToBottomRef.current) return
    // Back off while the user is actively scrolling so streaming per-frame
    // stick-to-bottom doesn't fight their gesture (the jitter the user saw).
    if (performance.now() - userScrolledAtRef.current < 350) return
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null
      // Set scrollTop directly on the timeline container instead of
      // endRef.scrollIntoView: scrollIntoView also repositions every
      // scrollable ancestor, which made the whole dialog layout jitter
      // every frame during streaming.
      const el = containerRef.current
      if (el) el.scrollTop = el.scrollHeight
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
    // Container-scoped jump (not scrollIntoView) to avoid repositioning
    // scrollable ancestors on thread switch.
    const el = containerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [activeThreadId])

  useEffect(() => {
    if (!currentTurnUserId) return
    stickToBottomRef.current = true
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current)
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null
      // Container-scoped smooth scroll on send (not scrollIntoView) so only
      // the timeline scrolls, not its ancestors.
      const el = containerRef.current
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })
  }, [currentTurnUserId])

  useEffect(() => {
    if (!scrollToBlockId) return
    const target = document.getElementById(`block-${scrollToBlockId}`)
    const container = containerRef.current
    if (target && container) {
      stickToBottomRef.current = false
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
              devPreviewCard={isLatestTurn ? devPreviewCard : null}
              viewportRef={containerRef}
              turnDiffSnapshot={
                isLatestTurn && latestTurnDiffId
                  ? turnDiffByTurnId[latestTurnDiffId]
                  : undefined
              }
              turnDiffTurnId={isLatestTurn ? latestTurnDiffId : null}
              turnDiffRevision={
                isLatestTurn && latestTurnDiffId
                  ? (turnDiffByTurnId[latestTurnDiffId]?.revision ?? 0)
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
      // Orchestrator chrome — keep out of the dialogue turn stream.
      if (
        isWorkflowStatusSystemText(block.text) ||
        isInternalSubagentHandoffSystemText(block.text)
      ) {
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

/** Status bubbles that dump render_workflow_text — duplicate of WorkflowBlock. */
export function isWorkflowStatusSystemText(text: string | undefined): boolean {
  const trimmed = text?.trim() ?? ''
  return /^(?:Workflow (?:running|completed|failed|cancelled)\b)/i.test(trimmed)
}

/**
 * Sub-agent wait/resume StatusEvents — internal handoff, not chat content.
 * Same English-prefix debt as `isInternalSubagentHandoffStatusItem` in
 * deepseek-runtime.ts — prefer a `visibility: internal` field when that lands.
 */
export function isInternalSubagentHandoffSystemText(text: string | undefined): boolean {
  const trimmed = text?.trim() ?? ''
  return /^(?:Resuming turn with \d+ sub-agent|Waiting on \d+ sub-agent)/i.test(trimmed)
}

type AssistantContentBlock = Extract<ChatBlock, { kind: 'assistant' }>

/**
 * Neutral progress line for a narration frame without wording. Everything
 * shown here comes from structured metadata (tool anchors and count), so it is
 * language- and model-independent; i18n supplies the label.
 */
function NeutralIntentLine({
  intent
}: {
  intent: NonNullable<AssistantContentBlock['processIntent']>
}): ReactElement {
  const { t } = useTranslation('common')
  const anchors = (intent.anchors ?? []).slice(0, 3)
  return (
    <div className="flex items-start gap-1.5 py-0.5">
      <Bot
        className="mt-1 h-3.5 w-3.5 shrink-0 text-ds-faint ds-work-logo-pulse"
        strokeWidth={1.8}
      />
      <p className="text-[13.5px] leading-6 text-ds-faint">
        {anchors.length > 0
          ? t('processNeutralIntentTargets', { targets: anchors.join(', ') })
          : t('processNeutralIntent', { count: intent.toolCount ?? 1 })}
      </p>
    </div>
  )
}

export function placeAssistantContentBlock(
  block: AssistantContentBlock,
  contentBlock: AssistantContentBlock,
  nextProcessBlocks: ChatBlock[],
  nextAssistantContentBlocks: AssistantContentBlock[]
): void {
  // Route purely on the persisted segment metadata. The runtime tags every
  // agent_message; anything untagged (legacy threads) stays in the work trace
  // rather than being promoted to an answer by position or text shape.
  if (block.agentSegment === 'final_answer') {
    nextAssistantContentBlocks.push(contentBlock)
    return
  }
  nextProcessBlocks.push(contentBlock)
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
  devPreviewCard,
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
  devPreviewCard?: ReactElement | null
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
  const hasLiveAssistantStream = isProcessing && !!liveContent.trim()
  const [workExpanded, setWorkExpanded] = useState(isProcessing)

  useEffect(() => {
    setWorkExpanded(isProcessing)
  }, [isProcessing])

  const todoSession = useMemo(() => buildTodoSessionForTurn(turn.blocks), [turn.blocks])
  const todoEvents = useMemo(() => buildTodoEventsForTurn(turn.blocks), [turn.blocks])
  const subagentSummary = useMemo(() => buildSubagentSummaryForTurn(turn.blocks), [turn.blocks])
  const subagentStepsByAgentId = useMemo(() => collectSubagentStepsByAgentId(turn.blocks), [turn.blocks])

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
        if (
          !isWorkflowStatusSystemText(block.text) &&
          !isInternalSubagentHandoffSystemText(block.text)
        ) {
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

    // Prefer File Mutation Ledger turn.diff snapshot (includes subagent / reconcile);
    // fall back to per-tool file_change blocks for legacy sessions.
    const summary = turnSummaryFromSources(turnDiffSnapshot, turn.blocks)
    let nextTurnFileChanges: ToolBlock[] = []
    if (summary.files.length > 0 && turnDiffTurnId) {
      nextTurnFileChanges = toolBlocksFromTurnSummary(turnDiffTurnId, summary).map((block) => ({
        ...block,
        filePath: formatFilePathForDisplay(block.filePath, workspaceRoot) || block.filePath
      }))
    } else {
      nextTurnFileChanges = turn.blocks.flatMap((block): ToolBlock[] => {
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
    }

    return {
      processBlocks: nextProcessBlocks,
      assistantContentBlocks: nextAssistantContentBlocks,
      turnFileChanges: nextTurnFileChanges,
      systemBlocks: nextSystemBlocks
    }
  }, [
    turn.blocks,
    liveProcessText,
    hasLiveAssistantStream,
    liveContent,
    workspaceRoot,
    turnDiffSnapshot,
    turnDiffTurnId
  ])

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
                activeActionLabel={activeRunningActionLabel(processBlocks)}
              />
              {workExpanded ? (
                <ProcessStream
                  blocks={processBlocks}
                  processing={isProcessing}
                  todoSession={todoSession}
                  todoEvents={todoEvents}
                  subagentSummary={subagentSummary}
                  subagentStepsByAgentId={subagentStepsByAgentId}
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

          {!isProcessing && devPreviewCard ? devPreviewCard : null}
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
  prev.devPreviewCard === next.devPreviewCard &&
  prev.viewportRef === next.viewportRef &&
  prev.turnDiffSnapshot === next.turnDiffSnapshot &&
  prev.turnDiffTurnId === next.turnDiffTurnId &&
  prev.turnDiffRevision === next.turnDiffRevision
))

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
  const primaryMarkdown = useMemo(() => selectPrimaryMarkdownResult(changes), [changes])
  const primaryMarkdownPath = primaryMarkdown?.filePath?.trim() ?? ''
  const primaryMarkdownLabel = primaryMarkdownPath
    ? formatHtmlPreviewPathLabel(primaryMarkdownPath)
    : ''
  const previewPath = htmlPreview?.path?.trim() ?? ''
  // Nest HTML preview only when it matches a real file_change in this turn.
  const nestedHtmlPreview =
    htmlPreview && previewPath
      ? changes.some(
          (change) =>
            change.status !== 'error' &&
            Boolean(change.filePath) &&
            pathsReferToSameFile(change.filePath!, previewPath)
        )
        ? htmlPreview
        : null
      : null
  const nestedPreviewPath = nestedHtmlPreview?.path?.trim() ?? ''
  const previewLabel = nestedPreviewPath ? formatHtmlPreviewPathLabel(nestedPreviewPath) : ''

  return (
    <section className="ds-card-strong overflow-hidden rounded-[14px] border border-ds-border shadow-[0_16px_40px_rgba(86,103,136,0.08)]">
      {primaryMarkdownPath ? (
        <div className="border-b border-ds-border-muted/70 bg-gradient-to-b from-ds-card-muted/30 to-transparent px-4 py-3">
          <div className="relative flex items-center gap-3 overflow-hidden rounded-[12px] border border-ds-border bg-ds-elevated/90 py-2.5 pl-3.5 pr-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
            <span
              aria-hidden
              className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-accent/70"
            />
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px] bg-accent/10 text-accent">
              <FileText className="h-4 w-4" strokeWidth={1.9} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13.5px] font-semibold tracking-[-0.01em] text-ds-ink">
                {primaryMarkdownLabel}
              </div>
              <div className="mt-0.5 truncate text-[11.5px] text-ds-muted">
                {t('turnMarkdownResultHint')}
              </div>
            </div>
            {onOpenWorkspaceFile ? (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation()
                  onOpenWorkspaceFile(primaryMarkdownPath)
                }}
                className="inline-flex h-8 shrink-0 items-center justify-center rounded-full bg-accent px-3.5 text-[12.5px] font-semibold text-white shadow-[0_8px_18px_rgba(0,136,255,0.2)] transition hover:brightness-110 active:scale-[0.97]"
                title={t('turnMarkdownResultOpen')}
              >
                {t('turnMarkdownResultOpen')}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

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
            const isPreviewTarget =
              Boolean(nestedPreviewPath) &&
              Boolean(change.filePath) &&
              pathsReferToSameFile(change.filePath!, nestedPreviewPath)

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
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="block break-all text-[14px] font-medium text-ds-ink">
                        {primary}
                      </span>
                      {isPreviewTarget ? (
                        <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10.5px] font-medium text-amber-700 dark:text-amber-300">
                          <Globe2 className="h-3 w-3" strokeWidth={2} />
                          HTML
                        </span>
                      ) : null}
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

      {nestedHtmlPreview && nestedPreviewPath ? (
        <div className="border-t border-ds-border-muted/70 bg-gradient-to-b from-ds-card-muted/25 to-transparent px-4 py-3">
          <div className="relative flex items-center gap-3 overflow-hidden rounded-[12px] border border-amber-500/15 bg-ds-elevated/85 py-2.5 pl-3.5 pr-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] dark:border-amber-300/15 dark:bg-white/[0.035]">
            <span
              aria-hidden
              className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-amber-500/70 dark:bg-amber-300/60"
            />
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px] bg-amber-500/10 text-amber-600 dark:bg-amber-300/10 dark:text-amber-300">
              <Globe2 className="h-4 w-4" strokeWidth={1.9} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13.5px] font-semibold tracking-[-0.01em] text-ds-ink">
                {previewLabel}
              </div>
              <div className="mt-0.5 truncate text-[11.5px] text-ds-muted">
                {t('htmlPreviewNestedHint')}
              </div>
            </div>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                nestedHtmlPreview.onOpen()
              }}
              className="inline-flex h-8 shrink-0 items-center justify-center rounded-full bg-accent px-3.5 text-[12.5px] font-semibold text-white shadow-[0_8px_18px_rgba(0,136,255,0.2)] transition hover:brightness-110 active:scale-[0.97]"
              title={t('htmlPreviewCardOpen')}
            >
              {t('htmlPreviewCardOpen')}
            </button>
          </div>
        </div>
      ) : null}
    </section>
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
    <div className="flex min-h-[64px] w-full items-center gap-3 rounded-[14px] border border-ds-border bg-ds-elevated/90 px-4 py-3 shadow-[0_12px_34px_rgba(0,0,0,0.06)]">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-amber-500/10 text-amber-600 dark:bg-amber-300/10 dark:text-amber-300">
        <Globe2 className="h-5 w-5" strokeWidth={1.9} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14.5px] font-semibold text-ds-ink">{label}</div>
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
  activeActionLabel
}: {
  processing: boolean
  stepCount: number
  liveStartedAt?: number
  durationMs?: number
  reasoningDurationMs?: number
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
          <Bot className="h-4 w-4 text-ds-faint ds-work-logo-pulse" strokeWidth={1.75} />
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
 * Whether a process block is a read-only probe that can fold into a batch.
 * Aligned with StepFlow: success / running / error probes merge; mutations,
 * shell, todo, and subagent-orchestration stay solo.
 */
function isMergeableProbeBlock(block: ChatBlock): block is ToolProcessBlock {
  if (block.kind !== 'tool') return false
  if (
    block.status !== 'success' &&
    block.status !== 'running' &&
    block.status !== 'error'
  ) {
    return false
  }
  if (block.toolKind === 'file_change' || block.toolKind === 'command_execution') return false
  const name = toolNameFromProcessBlock(block)
  if (SHELL_TOOL_NAMES.has(name)) return false
  if (isTodoToolBlock(block)) return false
  if (isSubagentOrchestrationToolName(name)) return false
  return isMergeableProbeTool(name)
}

export type RenderRow =
  | { type: 'block'; block: ChatBlock }
  | { type: 'tool_batch'; toolName: string; blocks: ToolProcessBlock[]; mixed?: boolean }

/**
 * Fold consecutive settled read-only probes into one `tool_batch`, including
 * mixed read/search/grep runs (same rule as Task/SubAgent StepFlow). A lone
 * probe stays a plain block; non-mergeable rows end the current run.
 */
export function groupProcessRows(visible: ChatBlock[]): RenderRow[] {
  const rows: RenderRow[] = []
  let buffer: ToolProcessBlock[] = []

  const flush = (): void => {
    if (buffer.length >= 2) {
      const names = new Set(buffer.map((b) => toolNameFromProcessBlock(b).toLowerCase()))
      const mixed = names.size > 1
      const toolName = mixed ? 'probe' : [...names][0] || toolNameFromProcessBlock(buffer[0]!)
      rows.push({ type: 'tool_batch', toolName, blocks: buffer, mixed })
    } else if (buffer.length === 1) {
      rows.push({ type: 'block', block: buffer[0]! })
    }
    buffer = []
  }

  for (const block of visible) {
    if (isMergeableProbeBlock(block)) {
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
      id={`block-${summary.anchorBlockId}`}
      className="my-2 overflow-hidden rounded-[12px] border border-ds-border-muted/70 bg-ds-card/55 shadow-[0_10px_28px_rgba(15,23,42,0.04)]"
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="group flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-ds-hover/35"
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
            <span className="text-[14px] font-semibold tracking-[-0.015em] text-ds-ink">
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
    <div className="overflow-hidden rounded-[12px] border border-ds-border-muted/50 bg-ds-card/40">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="group flex w-full items-start gap-2 px-2.5 py-1.5 text-left transition hover:bg-ds-hover/40"
      >
        <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] leading-6 text-ds-muted">{title}</span>
          {!expanded && preview ? (
            <span className="mt-0.5 block truncate text-[11px] leading-4 text-ds-faint" title={preview}>
              {preview}
            </span>
          ) : null}
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
        <div className="flex flex-col gap-1.5 border-t border-ds-border-muted/40 px-2.5 py-2">
          {blocks.map((block) => (
            <ToolCard key={block.id} block={block} onOpenWorkspaceFile={onOpenWorkspaceFile} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

/** Count tool / batch rows for the compact “N 步” chrome (skip narration). */
export function countSubagentRailSteps(items: StepFlowItem[]): number {
  return items.filter((i) => {
    if (i.variant === 'narration') return false
    if (i.variant === 'batch') return true
    return Boolean(i.toolName)
  }).length
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

/** Live tool-step rails for workflow DAG agent rows, keyed by agent id. */
function collectSubagentStepsByAgentId(blocks: ChatBlock[]): Record<string, StepFlowItem[]> {
  const out: Record<string, StepFlowItem[]> = {}
  for (const block of blocks) {
    if (block.kind !== 'subagent') continue
    if (block.cardKind === 'delegate') {
      const items = subagentStepsToFlowItems(block.steps, 0, block.status)
      if (items.length > 0) out[block.agentId] = items
      continue
    }
    for (const [workerId, steps] of Object.entries(block.workerSteps ?? {})) {
      const workerStatus = block.workers?.find((worker) => worker.id === workerId)?.status
      const items = subagentStepsToFlowItems(steps, 0, workerStatus)
      if (items.length > 0) out[workerId] = items
    }
  }
  return out
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
        >
          <ChevronDown
            className={[
              'h-3.5 w-3.5 shrink-0 text-ds-faint transition-transform duration-200',
              stepsOpen ? 'rotate-0' : '-rotate-90'
            ].join(' ')}
            strokeWidth={1.8}
          />
          <span className="font-semibold tracking-[-0.01em] text-ds-ink">
            {block.cardKind === 'fanout'
              ? t('subagentFanoutTitle', {
                  kind: humanizeAgentType(block.agentType)
                })
              : t('subagentDelegateTitle', {
                  type: humanizeAgentType(block.agentType)
                })}
          </span>
          {isActive ? (
            <Loader2 className="h-3 w-3 animate-spin text-ds-muted" strokeWidth={2} />
          ) : null}
          <span className="font-medium text-ds-muted">{statusLabel}</span>
          {flowItems.length > 0 ? (
            <span className="text-[11px] text-ds-faint">
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

/** Terminal statuses `resume_agent` accepts (manager rejects running/completed). */
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
  const sendMessage = useChatStore((s) => s.sendMessage)
  const busy = useChatStore((s) => s.busy)
  // Select the blocks array by reference — never filter inside the Zustand
  // selector (a new array each call trips useSyncExternalStore into a loop).
  const allBlocks = useChatStore((s) => s.blocks)
  const [resuming, setResuming] = useState(false)
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
  // failed/cancelled worker in one prompt (no per-worker UI exists yet).
  const resumableWorkerIds =
    block.cardKind === 'fanout'
      ? (block.workers ?? [])
          .filter((worker) => isResumableSubagentStatus(worker.status))
          .map((worker) => worker.id)
      : []
  const canResumeDelegate =
    block.cardKind === 'delegate' && isResumableSubagentStatus(block.status)
  const canResume = (canResumeDelegate || resumableWorkerIds.length > 0) && !busy && !resuming

  const onResume = async (): Promise<void> => {
    if (!canResume) return
    setResuming(true)
    try {
      const prompt =
        block.cardKind === 'fanout'
          ? t('subagentResumePromptMulti', { agentIds: resumableWorkerIds.join(', ') })
          : t('subagentResumePrompt', { agentId: block.agentId })
      await sendMessage(prompt, 'subagent')
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
              <h3 className="text-[18px] font-semibold leading-tight tracking-[-0.025em] text-ds-ink">
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

/** Soft cap for process-rail mid-turn prefaces (one short storyline line). */
export const MID_TURN_PREFACE_MAX_CHARS = 160

/** Clip a mid-turn preface for the process rail; full text stays expand-able. */
export function clipMidTurnPrefaceText(
  text: string,
  maxChars: number = MID_TURN_PREFACE_MAX_CHARS
): { preview: string; clipped: boolean } {
  const trimmed = text.trim()
  if (!trimmed) return { preview: '', clipped: false }

  // Prefer the first line when the model dumps a multi-line mini-report.
  const firstLine = trimmed.split(/\n/, 1)[0] ?? trimmed
  const source =
    firstLine.length > 0 && firstLine.length < trimmed.length ? firstLine : trimmed

  if (source === trimmed && source.length <= maxChars) {
    return { preview: trimmed, clipped: false }
  }

  let cut = source.length <= maxChars ? source : source.slice(0, maxChars)
  if (cut.length < source.length) {
    const ws = cut.lastIndexOf(' ')
    if (ws >= Math.floor(maxChars * 0.6)) cut = cut.slice(0, ws)
  }
  return { preview: `${cut.trimEnd()}…`, clipped: true }
}

function MidTurnPrefaceLine({ text }: { text: string }): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const { preview, clipped } = clipMidTurnPrefaceText(text)
  const shown = expanded || !clipped ? text.trim() : preview

  return (
    <div className="flex items-start gap-1.5 py-0.5">
      <Bot
        className="mt-1 h-3.5 w-3.5 shrink-0 text-ds-faint ds-work-logo-pulse"
        strokeWidth={1.8}
      />
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
 *  - approval         → null (pending cards live in the composer dock)
 *  - user_input       → pending null (composer dock); resolved stays in timeline
 *  - elev/evol/etc    → existing Bubble/Block components, never hidden
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
  subagentStepsByAgentId,
  onOpenWorkspaceFile
}: {
  blocks: ChatBlock[]
  processing: boolean
  todoSession?: TodoTurnSession | null
  todoEvents?: TodoTurnEvent[]
  subagentSummary?: SubagentTurnSummary | null
  subagentStepsByAgentId?: Record<string, StepFlowItem[]>
  onOpenWorkspaceFile?: (path: string, line?: number) => void
}): ReactElement {
  const visible = visibleExecutionBlocks(blocks, todoSession, subagentSummary)
  const rows = groupProcessRows(visible)
  // Only the first reasoning segment of a turn earns a live preview. Once a
  // completed reasoning item exists, later reasoning stays collapsed so the
  // transcript remains an execution story rather than a scrolling thought log.
  const showLiveReasoningPreview = !blocks.some(
    (block) => block.kind === 'reasoning' && block.id !== 'live-reasoning'
  )

  return (
    <div className="ds-process-rail flex flex-col gap-1.5 pt-1">
      {rows.map((row) =>
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
            todoSession={todoSession}
            todoEvents={todoEvents}
            subagentSummary={subagentSummary}
            subagentStepsByAgentId={subagentStepsByAgentId}
            showLiveReasoningPreview={showLiveReasoningPreview}
            onOpenWorkspaceFile={onOpenWorkspaceFile}
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
  subagentSummary = null,
  subagentStepsByAgentId,
  showLiveReasoningPreview = false,
  onOpenWorkspaceFile
}: {
  block: ChatBlock
  processing: boolean
  todoSession?: TodoTurnSession | null
  todoEvents?: TodoTurnEvent[]
  subagentSummary?: SubagentTurnSummary | null
  subagentStepsByAgentId?: Record<string, StepFlowItem[]>
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
        showLivePreview={showLiveReasoningPreview}
      />
    )
  }
  if (block.kind === 'assistant') {
    // The model's 承上启下 storyline line written before a tool batch. Render
    // it like the reasoning narration line (Bot + muted text) so it reads as
    // the throughline the user follows while tools execute. When the frame
    // carries no wording yet (structured intent only), show a neutral
    // progress state derived from metadata instead of fabricating prose.
    // Long prefaces are clipped — repair plans / mini-reports belong in the
    // final answer bubble, not the process rail.
    if (block.agentSegment === 'mid_turn_preface' || block.agentSegment == null) {
      if (!block.text.trim()) {
        if (!block.processIntent) return null
        return <NeutralIntentLine intent={block.processIntent} />
      }
      return <MidTurnPrefaceLine text={block.text} />
    }
    // Other assistant content that landed in the work trace (interstitial
    // final-answer segments).
    return (
      <div className="ds-markdown text-[13.5px] leading-6 text-ds-muted">
        <AssistantMarkdown text={block.text} streaming={processing} />
      </div>
    )
  }
  // Approvals + pending user_input render in the composer dock above the input.
  if (block.kind === 'approval') return null
  if (block.kind === 'elevation') return <ElevationBubble block={block} />
  if (block.kind === 'evolution') return <EvolutionBubble block={block} />
  if (block.kind === 'user_input') {
    if (block.status === 'pending') return null
    return <UserInputBubble block={block} />
  }
  if (block.kind === 'subagent') return <SubagentBubble block={block} />
  if (block.kind === 'workflow') {
    return (
      <WorkflowBlock
        workflowName={block.workflowName}
        status={block.status}
        snapshot={block.snapshot}
        runId={block.runId}
        subagentStepsByAgentId={subagentStepsByAgentId}
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
  processing,
  showLivePreview
}: {
  block: Extract<ChatBlock, { kind: 'reasoning' }>
  processing: boolean
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
          <Bot className="h-3.5 w-3.5 ds-work-logo-pulse" strokeWidth={1.8} />
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
  if (narration) {
    return (
      <div className="flex items-start gap-1.5 py-0.5">
        {isLive || processing ? (
          <Bot className="mt-1 h-3.5 w-3.5 shrink-0 text-ds-faint ds-work-logo-pulse" strokeWidth={1.8} />
        ) : null}
        <p className="text-[13.5px] leading-6 text-ds-faint/85">{narration}</p>
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
      className={`flex min-w-0 text-right ${className}`.trim()}
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
            'border-[rgba(168,85,247,0.4)] bg-[rgba(168,85,247,0.14)] text-[#a855f7]',
          title: t('composerPluginFocus', { name: displayName })
        }
      : kind === 'skill'
        ? {
            Icon: Sparkles,
            className:
              'border-[rgba(79,124,255,0.4)] bg-[rgba(79,124,255,0.14)] text-[#4f7cff]',
            title: t('composerSkillFocus', { name })
          }
        : {
            Icon: Plug,
            className:
              'border-[rgba(16,185,129,0.4)] bg-[rgba(16,185,129,0.14)] text-[#10b981]',
            title: t('composerConnectorFocus', { name })
          }
  const Icon = meta.Icon
  return (
    <span
      title={meta.title}
      className={`mb-1.5 inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium ${meta.className}`}
    >
      <Icon className="h-3 w-3 shrink-0" strokeWidth={2} aria-hidden />
      <span className="truncate">
        {kind === 'plugin' ? t('composerPluginBadge', { name: displayName }) : name}
      </span>
    </span>
  )
}

/**
 * User message bubble: pencil enters edit mode directly. Edit footer offers
 * cancel, resend (conversation only), or rollback (conversation + code).
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
  const focus = useMemo(() => parseUserFocusPrefix(block.text), [block.text])
  const displayBody = focus ? focus.body : block.text
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(displayBody)
  const [submitting, setSubmitting] = useState(false)
  // File restore only works for messages persisted on the runtime (`item_…`).
  const canRestoreFiles = activeThreadId != null && block.id.startsWith('item_')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!editing) return
    const el = textareaRef.current
    if (!el) return
    el.focus()
    const len = el.value.length
    el.setSelectionRange(len, len)
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 360)}px`
  }, [editing])

  const startEdit = (): void => {
    if (busy) return
    setDraft(focus ? focus.body : block.text)
    setEditing(true)
  }

  const cancelEdit = (): void => {
    setDraft(focus ? focus.body : block.text)
    setEditing(false)
  }

  const submit = async (restoreFiles: boolean): Promise<void> => {
    const trimmed = draft.trim()
    if (!trimmed || busy || submitting) return
    const wireText = focus ? composeUserFocusMessage(focus, trimmed) : trimmed
    setSubmitting(true)
    setEditing(false)
    try {
      await rewindAndResend(block.id, wireText, {
        restoreFiles: restoreFiles && canRestoreFiles
      })
    } finally {
      setSubmitting(false)
    }
  }

  if (editing) {
    const actionsDisabled = !draft.trim() || busy || submitting
    return (
      <div id={`block-${block.id}`} className="ds-user-message">
        <div className="ds-user-message-bubble ds-user-message-edit-bubble min-w-0">
          {focus ? <UserFocusChip kind={focus.kind} name={focus.name} /> : null}
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
                // Default: rollback conversation + code, then resend.
                void submit(true)
              }
            }}
            rows={2}
            className="ds-user-message-edit-textarea block w-full min-w-0 resize-none break-words bg-transparent text-[15px] font-medium leading-[1.58] text-ds-ink outline-none [overflow-wrap:anywhere]"
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={cancelEdit}
              disabled={submitting}
              className="rounded-md px-3 py-1 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
            >
              {t('rewindCancel')}
            </button>
            <button
              type="button"
              onClick={() => void submit(false)}
              disabled={actionsDisabled}
              title={t('rewindResendHint')}
              className="rounded-md px-3 py-1 text-[13px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('rewindResend')}
            </button>
            <button
              type="button"
              onClick={() => void submit(true)}
              disabled={actionsDisabled}
              title={
                canRestoreFiles ? t('rewindRollbackHint') : t('rewindRollbackFilesUnavailable')
              }
              className="rounded-md bg-accent px-3 py-1 text-[13px] font-medium text-white shadow-sm transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('rewindRollback')}
            </button>
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
        {focus ? <UserFocusChip kind={focus.kind} name={focus.name} /> : null}
        {displayBody ? (
          <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-justify [text-justify:inter-ideograph]">
            {displayBody}
          </div>
        ) : null}
      </div>
      <div className="mt-2 flex min-w-0 items-center justify-between gap-3 text-ds-faint opacity-90 transition group-hover:opacity-100">
        <ModelMetaTag label={block.modelLabel} className="flex-1 justify-start text-left" />
        <div className="flex items-center justify-end gap-3">
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
  const title =
    block.cardKind === 'fanout'
      ? t('subagentFanoutTitle', { kind: humanizeAgentType(block.agentType) })
      : t('subagentDelegateTitle', { type: humanizeAgentType(block.agentType) })
  const statusLabel = subagentStatusLabel(block.status, t)

  return (
    <div
      id={`block-${block.id}`}
      className="rounded-[14px] border border-ds-border-muted/70 bg-ds-card/55 px-4 py-4 text-[13px] leading-6 text-ds-ink shadow-[0_12px_30px_rgba(15,23,42,0.04)]"
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
    const streaming = block.id === 'live-assistant'
    const createdAtLabel = block.createdAt
      ? formatMessageDateTime(block.createdAt, i18n.language, timestampFormat)
      : null
    return (
      <div id={`block-${block.id}`} className="group/message flex min-w-0 max-w-full flex-col">
        <div className="ds-markdown ds-markdown--answer ds-chat-answer min-w-0 max-w-full text-ds-ink">
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
  if (block.kind === 'workflow') {
    return (
      <WorkflowBlock
        workflowName={block.workflowName}
        status={block.status}
        snapshot={block.snapshot}
        runId={block.runId}
      />
    )
  }
  if (block.kind === 'approval') {
    return null
  }
  if (block.kind === 'evolution') {
    return <EvolutionBubble block={block} />
  }
  if (block.kind === 'elevation') {
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
