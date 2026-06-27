import type { ReactElement, RefObject } from 'react'
import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  FolderOpen,
  Loader2,
  PencilLine,
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

function AssistantMarkdown({
  text,
  streaming,
  className
}: AssistantMarkdownProps): ReactElement {
  return (
    <Suspense
      fallback={
        <div className={className}>
          {text}
        </div>
      }
    >
      <LazyStreamdownAssistant text={text} streaming={streaming} className={className} />
    </Suspense>
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
          : 'min-h-0 flex-1 overflow-y-auto'
      }`}
    >
      <div
        className={`flex w-full min-w-0 flex-col gap-6 ${
          useChatStageWidth ? 'ds-chat-stage px-3 sm:px-4' : 'max-w-none px-0'
        } ${showEmptyHeroOnly ? 'pb-0 pt-0' : withOperationColumn ? 'ds-timeline-with-operation pb-8' : 'pb-8 pt-2'}`}
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
  // Mid-turn model prefaces are persisted for debugging but not shown in the
  // work trace; phase_bridge narration under reasoning is the user-facing line.
  if (block.agentSegment === 'mid_turn_preface') {
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

type ProcessSection = {
  id: string
  kind: 'reasoning' | 'execution' | 'output'
  blocks: ChatBlock[]
}

function groupProcessSections(blocks: ChatBlock[]): ProcessSection[] {
  const sections: ProcessSection[] = []

  for (const block of blocks) {
    const kind =
      block.kind === 'reasoning'
        ? 'reasoning'
        : block.kind === 'assistant'
          ? 'output'
          : 'execution'
    const last = sections[sections.length - 1]
    if (last && last.kind === kind) {
      last.blocks.push(block)
      continue
    }
    sections.push({
      id: `${kind}-${block.id}`,
      kind,
      blocks: [block]
    })
  }

  return sections
}

// ── Phase grouping: merge reasoning→execution pairs into phases ──────

type ProcessPhase = {
  id: string
  label: string
  reasoningBlocks: ChatBlock[]
  executionBlocks: ChatBlock[]
  outputBlocks: ChatBlock[]
  hasLiveReasoning: boolean
}

function classifyPhaseLabel(executionBlocks: ChatBlock[]): string {
  const toolBlocks = executionBlocks.filter((b) => b.kind === 'tool') as ToolBlock[]
  if (toolBlocks.length === 0) return '整理回复'

  const names = toolBlocks.map((b) => toolNameFromProcessBlock(b))
  const hasListDir = names.some((n) => /^list_dir$/.test(n))
  const hasRead = names.some((n) => /^(read_file|file_search)$/.test(n))
  const hasGrep = names.some((n) => /^grep/.test(n))
  const hasMutate = toolBlocks.some((b) => b.toolKind === 'file_change')
  const hasShell = toolBlocks.some((b) => b.toolKind === 'command_execution')
  const hasWebSearch = names.some((n) => /^(web_search|fetch_url)$/.test(n))

  if (hasMutate) return '实施修改'
  if (hasShell && !hasRead && !hasGrep && !hasListDir) return '执行命令'
  if (hasWebSearch) return '网络搜索'
  if (hasListDir && !hasRead && !hasGrep) return '浏览结构'
  if (hasGrep && hasRead) return '代码探索'
  if (hasGrep) return '搜索代码'
  if (hasRead && hasListDir) return '代码探索'
  if (hasRead) return '阅读代码'
  if (hasListDir) return '浏览结构'
  return '工具调用'
}

function groupProcessPhases(sections: ProcessSection[]): ProcessPhase[] {
  const phases: ProcessPhase[] = []
  let currentPhase: ProcessPhase | null = null

  for (const section of sections) {
    if (section.kind === 'reasoning') {
      // Start a new phase on each reasoning section
      if (currentPhase) phases.push(currentPhase)
      currentPhase = {
        id: section.id,
        label: '',
        reasoningBlocks: [...section.blocks],
        executionBlocks: [],
        outputBlocks: [],
        hasLiveReasoning: section.blocks.some((b) => b.id === 'live-reasoning')
      }
    } else if (section.kind === 'execution') {
      if (!currentPhase) {
        currentPhase = {
          id: section.id,
          label: '',
          reasoningBlocks: [],
          executionBlocks: [],
          outputBlocks: [],
          hasLiveReasoning: false
        }
      }
      currentPhase.executionBlocks.push(...section.blocks)
    } else if (section.kind === 'output') {
      if (!currentPhase) {
        currentPhase = {
          id: section.id,
          label: '',
          reasoningBlocks: [],
          executionBlocks: [],
          outputBlocks: [],
          hasLiveReasoning: false
        }
      }
      currentPhase.outputBlocks.push(...section.blocks)
    }
  }
  if (currentPhase) phases.push(currentPhase)

  // Assign labels based on execution block content
  for (const phase of phases) {
    phase.label = classifyPhaseLabel(phase.executionBlocks)
  }

  return phases
}

function getReasoningSectionText(section: ProcessSection): string {
  if (section.kind !== 'reasoning') return ''
  return reasoningDetailTextFromBlocks(section.blocks)
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

export function processPhaseHeadingParts({
  label,
  toolCount,
  narration,
  hasLiveReasoning
}: {
  label: string
  toolCount: number
  narration: string
  hasLiveReasoning: boolean
}): { primary: string; meta: string } {
  const displayLabel = (toolCount === 0 && hasLiveReasoning) ? '思考中…' : label
  const toolSuffix = toolCount > 0 ? ` · ${toolCount} 个工具` : ''
  const toolLabel = `${displayLabel}${toolSuffix}`
  const primary = narration.trim()
  if (primary) return { primary, meta: toolLabel }
  if (toolCount === 0 && hasLiveReasoning) return { primary: displayLabel, meta: '' }
  return { primary: processPhaseFallbackHeading(label), meta: toolLabel }
}

function processPhaseFallbackHeading(label: string): string {
  switch (label) {
    case '网络搜索':
      return '正在通过网络搜索补充信息'
    case '执行命令':
      return '正在执行命令收集结果'
    case '浏览结构':
      return '正在浏览项目结构'
    case '代码探索':
      return '正在梳理代码结构'
    case '搜索代码':
      return '正在定位相关实现'
    case '阅读代码':
      return '正在阅读关键文件'
    case '实施修改':
      return '正在实施代码修改'
    case '整理回复':
      return '正在整理回复'
    default:
      return '正在调用工具推进任务'
  }
}

export function processPhaseReasoningDetailText(blocks: ChatBlock[], toolCount: number): string {
  if (toolCount > 0) return ''
  return reasoningDetailTextFromBlocks(blocks)
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

function sectionHasDetails(
  section: ProcessSection,
  t: (key: string, opts?: Record<string, unknown>) => string
): boolean {
  if (section.kind === 'reasoning') {
    return getReasoningSectionText(section).length > 0
  }
  if (section.kind === 'output') {
    return section.blocks.some(
      (block) => getProcessDetail(block, describeProcessBlock(block, t)).kind === 'assistant'
    )
  }
  if (section.blocks.length > 1) return true
  const [block] = section.blocks
  return block ? getProcessDetail(block, describeProcessBlock(block, t)).kind !== 'none' : false
}

function isProcessSectionActive(
  section: ProcessSection,
  processing: boolean,
  hasLiveAssistantStream = false
): boolean {
  if (!processing) return false
  if (section.kind === 'reasoning') {
    return (
      !hasLiveAssistantStream &&
      section.blocks.some((block) => block.id === 'live-reasoning')
    )
  }
  if (section.kind === 'output') {
    return section.blocks.some((block) => block.id === 'live-assistant')
  }
  return section.blocks.some(
    (block) => block.id === 'live-assistant' || blockHasPendingRuntimeWork(block)
  )
}

export function shouldDefaultExpandProcessSection(args: {
  kind: ProcessSection['kind']
  active: boolean
  hasAttention: boolean
}): boolean {
  if (args.kind === 'reasoning') return args.active
  return args.active || args.hasAttention
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
  const subagentInfrastructureToolIds = useMemo(
    () => buildSubagentInfrastructureToolIds(turn.blocks, subagentSummary),
    [turn.blocks, subagentSummary]
  )

  const { processBlocks, assistantContentBlocks, turnFileChanges } = useMemo(() => {
    const nextProcessBlocks: ChatBlock[] = []
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
      if (isProcessBlock(block)) {
        nextProcessBlocks.push(block)
      }
    }

    if (liveProcessText.trim()) {
      nextProcessBlocks.push({ kind: 'reasoning', id: 'live-reasoning', text: liveProcessText })
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
        turnFileChanges: nextTurnFileChanges
      }
    }

    return {
      processBlocks: nextProcessBlocks,
      assistantContentBlocks: nextAssistantContentBlocks,
      turnFileChanges: nextTurnFileChanges
    }
  }, [turn.blocks, isProcessing, liveProcessText, workspaceRoot])

  const processSections = useMemo(
    () => (workExpanded || isProcessing ? groupProcessSections(processBlocks) : []),
    [processBlocks, workExpanded, isProcessing]
  )
  const processPhases = useMemo(
    () => (workExpanded || isProcessing ? groupProcessPhases(processSections) : []),
    [processSections, workExpanded, isProcessing]
  )
  const reasoningSectionCount = useMemo(
    () => processSections.filter((section) => section.kind === 'reasoning').length,
    [processSections]
  )
  const showLiveAssistant = !isProcessing && !!liveContent.trim()

  // The work process keeps the full chronological trace, including assistant
  // text output. The final assistant answer is also rendered below as the
  // normal message body, but we keep it in the timeline so reopening
  // "processed" still shows the real sequence.

  const hasProcess = isProcessing || processBlocks.length > 0

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {turn.user ? <MessageBubble block={turn.user} /> : null}

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
          />
          {workExpanded && processPhases.length > 0 ? (
            <div className="flex flex-col gap-2">
              {processPhases.map((phase) => (
                <ProcessPhaseRow
                  key={phase.id}
                  phase={phase}
                  processing={isProcessing}
                  viewportRef={viewportRef}
                  todoSession={todoSession}
                  todoEvents={todoEvents}
                  subagentSummary={subagentSummary}
                  subagentInfrastructureToolIds={subagentInfrastructureToolIds}
                />
              ))}
            </div>
          ) : null}
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

/** Turn-level work-process summary. It auto-collapses when the turn finishes. */
function WorkMetaRow({
  processing,
  stepCount,
  liveStartedAt,
  durationMs,
  reasoningDurationMs,
  expanded,
  onToggle,
  activeWorkflowName
}: {
  processing: boolean
  stepCount: number
  liveStartedAt?: number
  durationMs?: number
  reasoningDurationMs?: number
  expanded: boolean
  onToggle: () => void
  activeWorkflowName?: string
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

  const mainLabel = processing
    ? typeof displayDurationMs === 'number'
      ? `${t('processing')} ${formatDuration(displayDurationMs)}`
      : t('processing')
    : typeof displayDurationMs === 'number'
      ? `${t('processed')} ${formatDuration(displayDurationMs)}`
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
      <span className={`tabular-nums ${processing ? 'ds-shiny-text' : ''}`}>{mainLabel}</span>
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

function renderInlineTodoAtBlock(
  block: ChatBlock,
  todoSession: TodoTurnSession | null,
  processing: boolean
): ReactElement | null {
  if (!todoSession || !isTodoToolBlock(block)) return null
  if (block.id !== todoSession.anchorBlockId) return null
  return (
    <InlineTodoBlock
      session={todoSession}
      active={processing && !todoSession.isComplete}
    />
  )
}

function renderTodoEventAtBlock(
  block: ChatBlock,
  todoSession: TodoTurnSession | null,
  todoEvents: TodoTurnEvent[]
): ReactElement | null {
  if (!todoSession || !isTodoToolBlock(block)) return null
  const events = todoEvents.filter((event) => event.blockId === block.id)
  if (events.length === 0) return null
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
  toolFailed: number
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

function subagentBlockHasToolFailure(block: SubagentBlock): boolean {
  return !!block.actions?.some((action) => /\bfailed\b/i.test(action))
}

function buildSubagentSummaryForTurn(blocks: ChatBlock[]): SubagentTurnSummary | null {
  const subagentBlocks = blocks.filter(
    (block): block is SubagentBlock => block.kind === 'subagent'
  )
  if (subagentBlocks.length === 0) return null

  const counts = {
    toolFailed: 0,
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
    if (subagentBlockHasToolFailure(block)) {
      counts.toolFailed += 1
      counts.failed += 1
    } else {
      addSubagentStatus(counts, block.status)
    }
  }

  return {
    anchorBlockId: subagentBlocks[0]!.id,
    blockIds: subagentBlocks.map((block) => block.id),
    blocks: subagentBlocks,
    total,
    ...counts
  }
}

function renderSubagentSummaryAtBlock(
  block: ChatBlock,
  summary: SubagentTurnSummary | null
): ReactElement | null {
  if (!summary || block.kind !== 'subagent' || block.id !== summary.anchorBlockId) return null
  return <SubagentSummaryPanel summary={summary} />
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

export function buildSubagentInfrastructureToolIds(
  blocks: ChatBlock[],
  summary: SubagentTurnSummary | null
): Set<string> {
  if (!summary) return new Set()
  const ids = new Set<string>()
  const firstSubagentIndex = blocks.findIndex(
    (block) => block.kind === 'subagent' && block.id === summary.anchorBlockId
  )
  if (firstSubagentIndex < 0) return ids

  for (let index = 0; index < firstSubagentIndex; index += 1) {
    const block = blocks[index]
    if (block?.kind === 'tool' && block.status === 'success') {
      ids.add(block.id)
    }
  }
  return ids
}

function shouldHideSubagentInfrastructureToolBlock(
  block: ChatBlock,
  infrastructureToolIds: Set<string>
): boolean {
  return block.kind === 'tool' && infrastructureToolIds.has(block.id)
}

function visibleExecutionBlocks(
  blocks: ChatBlock[],
  todoSession: TodoTurnSession | null,
  subagentSummary: SubagentTurnSummary | null,
  subagentInfrastructureToolIds: Set<string>
): ChatBlock[] {
  return blocks.filter(
    (block) =>
      !shouldHideTodoToolBlock(block, todoSession) &&
      (!shouldHideSubagentBlock(block, subagentSummary) ||
        isSubagentSummaryAnchor(block, subagentSummary)) &&
      !shouldHideSubagentToolBlock(block, subagentSummary) &&
      !shouldHideSubagentInfrastructureToolBlock(block, subagentInfrastructureToolIds)
  )
}

function SubagentSummaryPanel({ summary }: { summary: SubagentTurnSummary }): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(true)
  const [detailBlock, setDetailBlock] = useState<SubagentBlock | null>(null)
  const active = summary.running > 0 || summary.pending > 0
  const hasFailure = summary.failed > 0 || summary.toolFailed > 0
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

function SubagentSummaryRow({
  block,
  onOpen
}: {
  block: SubagentBlock
  onOpen: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const toolFailed = subagentBlockHasToolFailure(block)
  const statusLabel = toolFailed
    ? t('subagentStatusToolFailed')
    : subagentStatusLabel(block.status, t)
  const statusTone =
    toolFailed
      ? 'text-red-700 dark:text-red-300'
      : block.status === 'completed'
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
        {block.status === 'running' || block.status === 'pending' ? (
          <Loader2 className="h-3 w-3 animate-spin text-amber-700 dark:text-amber-200" strokeWidth={2} />
        ) : null}
        <span className={`font-medium ${statusTone}`}>{statusLabel}</span>
        <span className="font-mono text-[11px] text-ds-faint">{block.agentId.slice(0, 10)}</span>
        <span className="ml-auto text-[11px] text-ds-faint opacity-0 transition group-hover:opacity-100">
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
  const toolFailed = subagentBlockHasToolFailure(block)
  const statusLabel = toolFailed ? t('subagentStatusToolFailed') : subagentStatusLabel(block.status, t)
  const resultTitle =
    toolFailed || block.status === 'failed'
      ? t('subagentFailureReason')
      : t('subagentFinalResult')
  const finalText =
    block.summary?.trim() ||
    (block.status === 'running' || block.status === 'pending'
      ? t('subagentDetailNoResultRunning')
      : t('subagentDetailNoResult'))

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4 py-6 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className="flex max-h-[82vh] w-full max-w-3xl flex-col overflow-hidden rounded-[22px] border border-ds-border bg-ds-panel shadow-[0_24px_80px_rgba(15,23,42,0.22)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-3 border-b border-ds-border-muted/70 px-5 py-4">
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
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-1 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label={t('close')}
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          <div className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ds-faint">
            {resultTitle}
          </div>
          <div className="ds-markdown mt-2 text-[13.5px] leading-6 text-ds-ink">
            <AssistantMarkdown text={finalText} streaming={false} />
          </div>
        </div>
      </div>
    </div>
  )
}

function ProcessPhaseRow({
  phase,
  processing,
  viewportRef,
  todoSession = null,
  todoEvents = [],
  subagentSummary = null,
  subagentInfrastructureToolIds = new Set()
}: {
  phase: ProcessPhase
  processing: boolean
  viewportRef: RefObject<HTMLDivElement | null>
  todoSession?: TodoTurnSession | null
  todoEvents?: TodoTurnEvent[]
  subagentSummary?: SubagentTurnSummary | null
  subagentInfrastructureToolIds?: Set<string>
}): ReactElement | null {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(true)
  const isActive = phase.hasLiveReasoning || phase.executionBlocks.some(blockHasPendingRuntimeWork)

  const filteredTools = visibleExecutionBlocks(
    phase.executionBlocks,
    todoSession,
    subagentSummary,
    subagentInfrastructureToolIds
  )
  const toolCount = filteredTools.length
  const hasError = filteredTools.some(
    (block) =>
      (block.kind === 'tool' && block.status === 'error') ||
      (block.kind === 'subagent' && (block.status === 'failed' || block.status === 'cancelled'))
  )

  // Extract narration from reasoning blocks in this phase
  const narration = useMemo(
    () => reasoningNarrationFromBlocks(phase.reasoningBlocks),
    [phase.reasoningBlocks]
  )

  const heading = processPhaseHeadingParts({
    label: phase.label,
    toolCount,
    narration,
    hasLiveReasoning: phase.hasLiveReasoning
  })

  // Skip phases with no tools (pure reasoning without action — the final
  // thinking round before the answer). Also skip truly empty phases.
  if (toolCount === 0 && !phase.hasLiveReasoning) {
    return null
  }

  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={`group flex w-fit max-w-full items-center gap-1.5 rounded-md py-0.5 text-left text-[14px] font-medium transition hover:opacity-85 ${
          hasError ? 'text-red-600 dark:text-red-300' : 'text-ds-muted'
        }`}
      >
        {isActive ? (
          <span className="mr-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
            <Bot className="h-3.5 w-3.5 text-ds-faint ds-work-logo-pulse" strokeWidth={1.8} />
          </span>
        ) : null}
        <span className={isActive ? 'ds-shiny-text' : ''}>{heading.primary}</span>
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-0 transition group-hover:opacity-55" strokeWidth={1.8} />
        )}
      </button>

      {heading.meta ? (
        <p className="mt-0.5 pl-1 text-[12.5px] leading-5 text-ds-faint">{heading.meta}</p>
      ) : null}

      {expanded ? (
        <div className="mt-1 border-l-2 border-ds-border-muted/35 pl-3">
          {(() => {
            const reasoningText = processPhaseReasoningDetailText(phase.reasoningBlocks, toolCount)
            if (!reasoningText) return null
            return (
              <div className="ds-markdown mb-1 text-[13.5px] leading-6 text-ds-muted">
                <div className="line-clamp-3">
                  <AssistantMarkdown text={reasoningText} streaming={isActive && processing} />
                </div>
              </div>
            )
          })()}
          <div className="flex flex-col gap-0.5">
            {filteredTools.map((block) => {
              const inlineTodo = renderInlineTodoAtBlock(block, todoSession, processing)
              if (inlineTodo) return <div key={`todo-${block.id}`}>{inlineTodo}</div>
              const todoEvent = renderTodoEventAtBlock(block, todoSession, todoEvents)
              if (todoEvent) return <div key={`todo-event-${block.id}`}>{todoEvent}</div>
              if (shouldHideTodoToolBlock(block, todoSession)) return null
              const subagentNode = renderSubagentSummaryAtBlock(block, subagentSummary)
              if (subagentNode) return <div key={`sa-${block.id}`}>{subagentNode}</div>
              if (shouldHideSubagentBlock(block, subagentSummary)) return null
              if (shouldHideSubagentToolBlock(block, subagentSummary)) return null
              if (shouldHideSubagentInfrastructureToolBlock(block, subagentInfrastructureToolIds)) return null
              return <ProcessEntryRow key={block.id} block={block} processing={processing} />
            })}
          </div>
        </div>
      ) : (
        toolCount > 0 ? (
          <div className="mt-0.5 pl-1 text-[13px] text-ds-faint">
            {filteredTools.slice(0, 3).map((block) => {
              const desc = describeProcessBlock(block, t)
              const { verb, rest } = splitVerb(desc)
              return (
                <div key={block.id} className="truncate">
                  <span className="font-medium text-ds-muted">{verb}</span>
                  {rest ? <span className="ml-1 tabular-nums text-[12px]">{rest}</span> : null}
                </div>
              )
            })}
            {toolCount > 3 ? (
              <div className="text-ds-faint/70">… {toolCount - 3} more</div>
            ) : null}
          </div>
        ) : null
      )}
    </div>
  )
}

function ProcessSectionRow({
  section,
  processing,
  hasLiveAssistantStream,
  reasoningDurationMs,
  singleReasoningSection,
  viewportRef,
  todoSession = null,
  todoEvents = [],
  subagentSummary = null,
  subagentInfrastructureToolIds = new Set()
}: {
  section: ProcessSection
  processing: boolean
  hasLiveAssistantStream: boolean
  reasoningDurationMs?: number
  singleReasoningSection: boolean
  viewportRef: RefObject<HTMLDivElement | null>
  todoSession?: TodoTurnSession | null
  todoEvents?: TodoTurnEvent[]
  subagentSummary?: SubagentTurnSummary | null
  subagentInfrastructureToolIds?: Set<string>
}): ReactElement | null {
  const { t } = useTranslation('common')
  const [userExpanded, setUserExpanded] = useState<boolean | null>(null)
  const visibleBlocks =
    section.kind === 'execution'
      ? visibleExecutionBlocks(
          section.blocks,
          todoSession,
          subagentSummary,
          subagentInfrastructureToolIds
        )
      : section.blocks
  const assistantBlocks =
    section.kind === 'output'
      ? section.blocks.filter(
          (block): block is Extract<ChatBlock, { kind: 'assistant' }> => block.kind === 'assistant'
        )
      : []
  const hasDetails = sectionHasDetails(section, t)
  const active =
    section.kind === 'execution'
      ? visibleBlocks.some(
          (block) => block.id === 'live-assistant' || blockHasPendingRuntimeWork(block)
        )
      : isProcessSectionActive(section, processing, hasLiveAssistantStream)
  const hasError = visibleBlocks.some(
    (block) =>
      (block.kind === 'tool' && block.status === 'error') ||
      (block.kind === 'approval' && block.status === 'error') ||
      (block.kind === 'user_input' && block.status === 'error') ||
      (block.kind === 'subagent' && (block.status === 'failed' || block.status === 'cancelled')) ||
      (block.kind === 'workflow' && (block.status === 'failed' || block.status === 'cancelled'))
  )
  const hasAttention = visibleBlocks.some(blockNeedsAttention)
  const defaultExpanded = shouldDefaultExpandProcessSection({
    kind: section.kind,
    active,
    hasAttention
  })
  const expanded = hasDetails && (userExpanded ?? defaultExpanded)
  const title = describeProcessSection(section, t, {
    processing,
    hasLiveAssistantStream,
    reasoningDurationMs,
    singleReasoningSection,
    todoSession,
    subagentSummary,
    subagentInfrastructureToolIds
  })
  const reasoningText = section.kind === 'reasoning' ? getReasoningSectionText(section) : ''
  const reasoningNarration =
    section.kind === 'reasoning' ? reasoningNarrationFromBlocks(section.blocks) : ''
  const canToggleSection = hasDetails
  const { ref: deferredDetailRef, shouldRender: shouldRenderDetail } = useDeferredRender<HTMLDivElement>({
    enabled: expanded,
    immediate: active,
    root: viewportRef
  })

  if (section.kind === 'execution' && visibleBlocks.length === 0) {
    return null
  }

  if (section.kind === 'reasoning') {
    const isLiveReasoning = section.blocks.some((block) => block.id === 'live-reasoning')
    if (!reasoningNarration && !isLiveReasoning) {
      return null
    }
  }

  if (section.kind === 'execution' && visibleBlocks.length === 1) {
    const [block] = visibleBlocks
    if (block) {
      const inlineTodo = renderInlineTodoAtBlock(block, todoSession, processing)
      if (inlineTodo) return inlineTodo
      const todoEvent = renderTodoEventAtBlock(block, todoSession, todoEvents)
      if (todoEvent) return todoEvent
      if (shouldHideTodoToolBlock(block, todoSession)) return <></>
      const subagentSummaryNode = renderSubagentSummaryAtBlock(block, subagentSummary)
      if (subagentSummaryNode) return subagentSummaryNode
      if (shouldHideSubagentBlock(block, subagentSummary)) return <></>
      if (shouldHideSubagentToolBlock(block, subagentSummary)) return <></>
      if (shouldHideSubagentInfrastructureToolBlock(block, subagentInfrastructureToolIds)) return <></>
      return <ProcessEntryRow block={block} processing={processing} />
    }
  }

  if (section.kind === 'output') {
    return hasDetails ? (
      <div className="min-w-0">
        <div className="flex flex-col gap-2">
          {assistantBlocks.map((block) => (
            <ProcessEntryDetail
              key={block.id}
              block={block}
              detail={getProcessDetail(block)}
              processing={processing}
            />
          ))}
        </div>
      </div>
    ) : (
      <></>
    )
  }

  return (
    <div className="flex flex-col">
      {canToggleSection ? (
        <button
          type="button"
          onClick={() => setUserExpanded(!(userExpanded ?? defaultExpanded))}
          className={`group flex w-fit max-w-full items-center gap-1.5 rounded-md py-0.5 text-left text-[14px] font-medium transition hover:opacity-85 ${
            hasError ? 'text-red-600 dark:text-red-300' : 'text-ds-muted'
          }`}
        >
          {active ? (
            <span className="mr-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
              <Bot
                className={`h-3.5 w-3.5 ${
                  hasError ? 'text-red-500 dark:text-red-300' : 'text-ds-faint ds-work-logo-pulse'
                }`}
                strokeWidth={1.8}
              />
            </span>
          ) : null}
          <span className={active && !hasError ? 'ds-shiny-text' : ''}>{title}</span>
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-0 transition group-hover:opacity-55" strokeWidth={1.8} />
          )}
        </button>
      ) : (
        <div
          className={`flex w-fit max-w-full items-center gap-1.5 py-0.5 text-[14px] font-medium ${
            hasError ? 'text-red-600 dark:text-red-300' : 'text-ds-muted'
          }`}
        >
          {active ? (
            <span className="mr-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
              <Bot
                className={`h-3.5 w-3.5 ${
                  hasError ? 'text-red-500 dark:text-red-300' : 'text-ds-faint ds-work-logo-pulse'
                }`}
                strokeWidth={1.8}
              />
            </span>
          ) : null}
          <span className={active && !hasError ? 'ds-shiny-text' : ''}>{title}</span>
        </div>
      )}

      {section.kind === 'reasoning' && reasoningNarration ? (
        <p className="mt-1 text-[13.5px] leading-6 text-ds-muted/90">{reasoningNarration}</p>
      ) : null}

      {expanded ? (
        <div
          ref={deferredDetailRef}
          className="mt-1 border-l-2 border-ds-border-muted/35 pl-3"
          style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 220px' }}
        >
          {shouldRenderDetail ? (
            section.kind === 'reasoning' ? (
            <div className="ds-markdown text-[13.5px] leading-6 text-ds-muted">
              <AssistantMarkdown text={reasoningText} streaming={active && processing} />
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              {visibleBlocks.map((block) => {
                const inlineTodo = renderInlineTodoAtBlock(block, todoSession, processing)
                if (inlineTodo) {
                  return <div key={`todo-${block.id}`}>{inlineTodo}</div>
                }
                const todoEvent = renderTodoEventAtBlock(block, todoSession, todoEvents)
                if (todoEvent) {
                  return <div key={`todo-event-${block.id}`}>{todoEvent}</div>
                }
                if (shouldHideTodoToolBlock(block, todoSession)) return null
                const subagentSummaryNode = renderSubagentSummaryAtBlock(block, subagentSummary)
                if (subagentSummaryNode) {
                  return <div key={`subagent-summary-${block.id}`}>{subagentSummaryNode}</div>
                }
                if (shouldHideSubagentBlock(block, subagentSummary)) return null
                if (shouldHideSubagentToolBlock(block, subagentSummary)) return null
                if (shouldHideSubagentInfrastructureToolBlock(block, subagentInfrastructureToolIds)) {
                  return null
                }
                return <ProcessEntryRow key={block.id} block={block} processing={processing} />
              })}
            </div>
          )
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

/** One line inside an execution section. */
function ProcessEntryRow({
  block,
  processing
}: {
  block: ChatBlock
  processing: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  const [userOpen, setUserOpen] = useState(false)
  const summary = describeProcessBlock(block, t)
  const detail = getProcessDetail(block, summary)
  const canExpand = detail.kind !== 'none'
  const isAssistantProcessText = block.kind === 'assistant'
  const isRunningToolOrPending =
    processing &&
    ((block.kind === 'tool' && block.status === 'running') ||
      (block.kind === 'approval' && block.status === 'pending') ||
      (block.kind === 'user_input' && block.status === 'pending'))
  const isStreamingAssistant = processing && block.kind === 'assistant' && block.id === 'live-assistant'
  const isError =
    (block.kind === 'tool' && block.status === 'error') ||
    (block.kind === 'approval' && block.status === 'error') ||
    (block.kind === 'user_input' && block.status === 'error')
  const open =
    canExpand && (isAssistantProcessText || isRunningToolOrPending || isStreamingAssistant || userOpen)

  const { verb, rest } = splitVerb(summary)
  const rowActive = isRunningToolOrPending || isStreamingAssistant
  const wrapSummary = (block.kind === 'system' && !canExpand) || isAssistantProcessText

  return (
    <div id={`block-${block.id}`} className="flex flex-col">
      <button
        type="button"
        onClick={canExpand && !isRunningToolOrPending ? () => setUserOpen((v) => !v) : undefined}
        disabled={!canExpand}
        className={`group flex w-full items-start gap-2 rounded-md px-2 py-1 text-left text-[13.5px] leading-[1.55] transition ${
          isError
            ? 'text-red-600 dark:text-red-300'
            : 'text-ds-faint hover:text-ds-ink'
        } ${
          canExpand && !isRunningToolOrPending && !isAssistantProcessText
            ? 'cursor-pointer hover:bg-ds-hover/70'
            : 'cursor-default'
        }`}
      >
        {isRunningToolOrPending ? (
          <Loader2 className="mt-1 h-3 w-3 shrink-0 animate-spin opacity-75" strokeWidth={2} />
        ) : null}
        <span
          className={`min-w-0 flex-1 ${wrapSummary ? 'whitespace-pre-wrap break-words' : 'truncate'}`}
        >
          <span
            className={`font-medium ${isError ? '' : rowActive ? 'ds-shiny-text' : 'text-ds-muted'}`}
          >
            {verb}
          </span>
          {rest ? (
            <span className={`ml-1.5 tabular-nums text-[13px] ${rowActive ? 'ds-shiny-text' : ''}`}>
              {rest}
            </span>
          ) : null}
        </span>
        {canExpand ? (
          open ? (
            <ChevronDown className="mt-1 h-3 w-3 shrink-0 opacity-40" strokeWidth={2} />
          ) : (
            <ChevronRight className="mt-1 h-3 w-3 shrink-0 opacity-0 transition group-hover:opacity-45" strokeWidth={2} />
          )
        ) : null}
      </button>
      {canExpand && open ? (
        detail.kind === 'assistant' ? (
          <div className="mt-1">
            <ProcessEntryDetail block={block} detail={detail} processing={processing} />
          </div>
        ) : (
          <div className="ds-work-timeline-detail">
            <ProcessEntryDetail block={block} detail={detail} processing={processing} />
          </div>
        )
      ) : null}
    </div>
  )
}

function describeProcessSection(
  section: ProcessSection,
  t: (key: string, opts?: Record<string, unknown>) => string,
  opts: {
    processing: boolean
    hasLiveAssistantStream: boolean
    reasoningDurationMs?: number
    singleReasoningSection: boolean
    todoSession?: TodoTurnSession | null
    subagentSummary?: SubagentTurnSummary | null
    subagentInfrastructureToolIds?: Set<string>
  }
): string {
  if (section.kind === 'reasoning') {
    if (
      opts.processing &&
      isProcessSectionActive(section, true, opts.hasLiveAssistantStream)
    ) {
      return t('thinkingNow')
    }
    if (
      opts.singleReasoningSection &&
      typeof opts.reasoningDurationMs === 'number' &&
      opts.reasoningDurationMs >= 1000
    ) {
      return t('thoughtFor', { duration: formatDuration(opts.reasoningDurationMs) })
    }
    return section.blocks.length > 1
      ? t('thoughtSteps', { count: section.blocks.length })
      : t('thinkingLabel')
  }

  if (section.kind === 'output') {
    return t('processTextLabel')
  }

  const summaryBlocks = visibleExecutionBlocks(
    section.blocks,
    opts.todoSession ?? null,
    opts.subagentSummary ?? null,
    opts.subagentInfrastructureToolIds ?? new Set()
  )
  if (summaryBlocks.length === 0) {
    return t('processSteps', { count: section.blocks.length })
  }
  if (summaryBlocks.length === 1) {
    return describeProcessBlock(summaryBlocks[0]!, t)
  }

  return summarizeExecutionSection(summaryBlocks, t)
}

function summarizeExecutionSection(
  blocks: ChatBlock[],
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  let fileCount = 0
  let commandCount = 0
  let toolCount = 0
  let approvalCount = 0

  for (const block of blocks) {
    if (block.kind === 'approval') {
      approvalCount += 1
      continue
    }
    if (block.kind !== 'tool') continue
    if (block.toolKind === 'file_change') {
      fileCount += 1
    } else if (block.toolKind === 'command_execution') {
      commandCount += 1
    } else {
      toolCount += 1
    }
  }

  const parts: string[] = []
  if (fileCount > 0) {
    parts.push(
      fileCount === 1 ? t('groupEditedFile') : t('groupEditedFiles', { count: fileCount })
    )
  }
  if (commandCount > 0) {
    parts.push(
      commandCount === 1
        ? t('groupRanCommand')
        : t('groupRanCommands', { count: commandCount })
    )
  }
  if (toolCount > 0) {
    parts.push(toolCount === 1 ? t('groupUsedTool') : t('groupUsedTools', { count: toolCount }))
  }
  if (approvalCount > 0) {
    parts.push(
      approvalCount === 1 ? t('groupApproval') : t('groupApprovals', { count: approvalCount })
    )
  }

  if (parts.length > 0) return parts.join(' · ')
  return t('processSteps', { count: blocks.length })
}

function splitVerb(summary: string): { verb: string; rest: string } {
  const trimmed = summary.trim()
  if (!trimmed) return { verb: '', rest: '' }
  const space = trimmed.search(/\s/)
  if (space < 0) return { verb: trimmed, rest: '' }
  return { verb: trimmed.slice(0, space), rest: trimmed.slice(space + 1).trim() }
}

type ProcessDetail =
  | { kind: 'none' }
  | { kind: 'reasoning'; text: string }
  | { kind: 'assistant'; text: string }
  | { kind: 'tool'; text: string; isPatch: boolean; isError: boolean; filePath?: string }
  | { kind: 'approval' }
  | { kind: 'user_input' }
  | { kind: 'subagent' }
  | { kind: 'workflow' }
  | { kind: 'text'; text: string }

function summarizeProcessText(text: string, max = 96): string {
  const oneLine = text.replace(/\s+/g, ' ').trim()
  if (!oneLine) return ''
  if (oneLine.length <= max) return oneLine
  return `${oneLine.slice(0, max - 1).trimEnd()}…`
}

// Tool summaries sometimes carry their raw JSON args/result inline, e.g.
// "list_dir: [ { \"name\": ... } ]". Drop the JSON payload so the row shows a
// clean human-readable label instead of a truncated blob of JSON.
function stripInlineJsonPayload(text: string): string {
  const match = text.match(/\s*[[{]\s*["{[]/)
  if (match && match.index !== undefined) {
    return text.slice(0, match.index).trim()
  }
  return text.trim()
}

const TOOL_NAME_LABELS: Record<string, string> = {
  apply_patch: '应用补丁',
  edit_file: '编辑文件',
  exec_shell: '执行命令',
  exec_shell_interact: '交互命令',
  exec_shell_wait: '等待命令',
  fetch_url: '获取网页',
  file_search: '搜索文件',
  github_issue_context: '读取 GitHub 上下文',
  glob_file_search: '搜索文件',
  grep: '搜索代码',
  grep_files: '搜索文件',
  list_dir: '浏览目录',
  read_file: '读取文件',
  run_terminal_cmd: '执行命令',
  search_files: '搜索文件',
  web_search: '网络搜索',
  write_file: '写入文件'
}

function humanizeToolName(name: string): string {
  const canonical = name.trim().toLowerCase()
  const mapped = TOOL_NAME_LABELS[canonical]
  if (mapped) return mapped
  const trimmed = canonical.replace(/[_-]+/g, ' ')
  if (!trimmed) return ''
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1)
}

function extractToolName(summary: string): string {
  const match = summary.trim().match(/^([a-z0-9_-]+)\s*:/i)
  return match?.[1] ?? ''
}

function extractQuotedField(text: string, field: string): string | undefined {
  const escaped = field.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const attr = new RegExp(`${escaped}="([^"]+)"`, 'i').exec(text)
  if (attr?.[1]) return attr[1]
  const json = new RegExp(`"${escaped}"\\s*:\\s*"([^"]+)"`, 'i').exec(text)
  if (json?.[1]) return json[1]
  return undefined
}

function readMetaString(meta: Record<string, unknown> | undefined, key: string): string | undefined {
  if (!meta) return undefined
  const value = meta[key]
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function summarizeToolBlock(
  block: ToolBlock,
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  const rawSummary = block.summary?.trim() ?? ''
  const toolName = extractToolName(rawSummary)
  const label = humanizeToolName(toolName) || formatToolTitle(block, t)
  const sourceText = [rawSummary, block.detail ?? ''].filter(Boolean).join('\n')
  const filePath =
    block.filePath ||
    extractQuotedField(sourceText, 'path') ||
    extractQuotedField(sourceText, 'file_path') ||
    extractQuotedField(sourceText, 'file')
  const pattern =
    extractQuotedField(sourceText, 'pattern') ||
    extractQuotedField(sourceText, 'query') ||
    readMetaString(block.meta, 'pattern')
  const command = readMetaString(block.meta, 'command')

  if (toolName === 'read_file' && filePath) {
    return `${label} ${filePath}`
  }
  if ((toolName === 'grep_files' || toolName === 'search_files') && pattern) {
    return filePath ? `${label} ${pattern} · ${filePath}` : `${label} ${pattern}`
  }
  if (command && block.toolKind === 'command_execution') {
    return `${formatToolTitle(block, t)} ${summarizeProcessText(command, 72)}`
  }
  if (filePath) {
    return `${label} ${filePath}`
  }
  if (pattern) {
    return `${label} ${pattern}`
  }
  if (rawSummary) {
    const withoutPrefix = toolName ? rawSummary.replace(/^([a-z0-9_-]+)\s*:\s*/i, '') : rawSummary
    const compact = stripInlineJsonPayload(withoutPrefix)
    const summary = summarizeProcessText(compact, 72)
    return summary ? `${label} ${summary}` : label
  }
  return label
}

function normalizeProcessText(text: string): string {
  return text.replace(/\s+/g, ' ').trim().toLowerCase()
}

function getProcessDetail(block: ChatBlock, summaryText?: string): ProcessDetail {
  if (block.kind === 'reasoning') {
    return block.text.trim() ? { kind: 'reasoning', text: block.text } : { kind: 'none' }
  }
  if (block.kind === 'assistant') {
    const split = splitThink(block.text)
    const text = split.content || split.think
    return text.trim() ? { kind: 'assistant', text } : { kind: 'none' }
  }
  if (block.kind === 'tool') {
    const detailText = block.detail?.trim() ?? ''
    if (!detailText) return { kind: 'none' }
    if (summaryText && normalizeProcessText(detailText) === normalizeProcessText(summaryText)) {
      return { kind: 'none' }
    }
    const isError = block.status === 'error'
    const isPatch =
      block.toolKind === 'file_change' && !isError && looksLikeUnifiedDiff(detailText)
    return {
      kind: 'tool',
      text: block.detail!,
      isPatch,
      isError,
      filePath: block.filePath
    }
  }
  if (block.kind === 'approval') return { kind: 'approval' }
  if (block.kind === 'user_input') return { kind: 'user_input' }
  if (block.kind === 'subagent') return { kind: 'subagent' }
  if (block.kind === 'workflow') return { kind: 'workflow' }
  if (block.kind === 'system' && block.text.trim()) {
    // Short system messages already fit in the summary line — skip the
    // expand affordance so we don't duplicate the same string.
    if (block.text.length <= 140) return { kind: 'none' }
    return { kind: 'text', text: block.text }
  }
  return { kind: 'none' }
}

function useFullToolDetail(
  itemId: string | undefined,
  truncated: boolean | undefined
): { loading: boolean; detail: string | null; expand: () => void } {
  const [state, setState] = useState<{ loading: boolean; detail: string | null }>({
    loading: false,
    detail: null
  })
  const expand = useCallback((): void => {
    if (!itemId || state.loading || state.detail !== null) return
    const providerId = useChatStore.getState().providerId
    const provider = getProvider(providerId)
    if (typeof provider.fetchItemDetail !== 'function') return
    setState({ loading: true, detail: null })
    void provider
      .fetchItemDetail(itemId)
      .then((result) => setState({ loading: false, detail: result.detail ?? '' }))
      .catch(() => setState({ loading: false, detail: '' }))
  }, [itemId, state.detail, state.loading])
  // Reset when the underlying item changes.
  useEffect(() => {
    setState({ loading: false, detail: null })
  }, [itemId])
  // If nothing is truncated, there's nothing to fetch.
  if (!truncated) return { loading: false, detail: null, expand: () => {} }
  return { loading: state.loading, detail: state.detail, expand }
}

function LazyToolDetail({
  text,
  truncated,
  itemId
}: {
  text: string
  truncated?: boolean
  itemId?: string
}): ReactElement {
  const { t } = useTranslation('common')
  const { loading, detail, expand } = useFullToolDetail(itemId, truncated)
  const display = detail !== null ? detail : text
  return (
    <div className="relative">
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-ds-ink">
        {display}
      </pre>
      {truncated && detail === null ? (
        <button
          type="button"
          onClick={expand}
          disabled={loading}
          className="absolute bottom-1 right-1 rounded-md border border-ds-border-muted bg-ds-card/90 px-2 py-0.5 text-[11px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
        >
          {loading ? '…' : t('toolDetailExpandFull')}
        </button>
      ) : null}
    </div>
  )
}

function ProcessEntryDetail({
  block,
  detail,
  processing
}: {
  block: ChatBlock
  detail: ProcessDetail
  processing: boolean
}): ReactElement | null {
  if (detail.kind === 'reasoning') {
    const streamReason = block.id === 'live-reasoning' && processing
    return (
      <div className="ds-markdown text-[13.5px] leading-6 text-ds-muted">
        <AssistantMarkdown text={detail.text} streaming={streamReason} />
      </div>
    )
  }
  if (detail.kind === 'assistant') {
    return (
      <div className="ds-markdown text-[13.5px] leading-6 text-ds-ink">
        <AssistantMarkdown
          text={detail.text}
          streaming={processing && block.kind === 'assistant' && block.id === 'live-assistant'}
        />
      </div>
    )
  }
  if (detail.kind === 'tool') {
    const truncated = block.kind === 'tool' ? block.detailTruncated : undefined
    if (detail.isPatch) {
      return <DiffView patch={detail.text} filePath={detail.filePath} />
    }
    if (detail.isError) {
      return (
        <div className="overflow-hidden rounded-[10px] border border-red-200/80 bg-red-50/80 dark:border-red-800/40 dark:bg-red-500/10">
          {detail.filePath ? (
            <div className="border-b border-red-200/70 bg-red-100/50 px-3 py-1.5 font-mono text-[12px] text-red-700 dark:border-red-800/40 dark:bg-red-500/15 dark:text-red-300">
              {detail.filePath}
            </div>
          ) : null}
          <LazyToolDetail text={detail.text} truncated={truncated} itemId={block.id} />
        </div>
      )
    }
    return (
      <LazyToolDetail text={detail.text} truncated={truncated} itemId={block.id} />
    )
  }
  if (detail.kind === 'text') {
    return <p className="whitespace-pre-wrap text-[13.5px] leading-6 text-ds-muted">{detail.text}</p>
  }
  if (detail.kind === 'approval' && block.kind === 'approval') {
    return <MessageBubble block={block} nested />
  }
  if (detail.kind === 'user_input' && block.kind === 'user_input') {
    return <MessageBubble block={block} nested />
  }
  if (detail.kind === 'subagent' && block.kind === 'subagent') {
    return <MessageBubble block={block} nested />
  }
  if (detail.kind === 'workflow' && block.kind === 'workflow') {
    return (
      <WorkflowBlock
        workflowName={block.workflowName}
        status={block.status}
        snapshot={block.snapshot}
      />
    )
  }
  return null
}

function describeProcessBlock(
  block: ChatBlock,
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  if (block.kind === 'reasoning') {
    return t('thinkingLabel')
  }
  if (block.kind === 'assistant') {
    return t('processTextLabel')
  }
  if (block.kind === 'tool') {
    return summarizeToolBlock(block, t)
  }
  if (block.kind === 'approval') {
    return block.summary || t('approvalTitle')
  }
  if (block.kind === 'user_input') {
    return t('userInputTitle')
  }
  if (block.kind === 'subagent') {
    return block.cardKind === 'fanout'
      ? t('subagentFanoutTitle', { kind: block.agentType })
      : t('subagentDelegateTitle', { type: block.agentType })
  }
  if (block.kind === 'workflow') {
    return t('workflowProcessTitle', {
      defaultValue: 'workflow: {{name}}',
      name: block.workflowName
    })
  }
  if (block.kind === 'system') {
    return block.text
  }
  return 'text' in block ? block.text : t('processed')
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
      {block.cardKind === 'delegate' && block.actions && block.actions.length > 0 ? (
        <ul className="mt-2 space-y-1 text-[12px] text-ds-muted">
          {block.truncated ? (
            <li className="text-ds-faint">…</li>
          ) : null}
          {block.actions.map((action, index) => (
            <li key={`${block.id}-action-${index}`} className="truncate">
              {action}
            </li>
          ))}
        </ul>
      ) : null}
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

function MessageBubble({ block, nested = false }: { block: ChatBlock; nested?: boolean }): ReactElement {
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
            <CopyFeedbackButton text={block.text} />
          </div>
        ) : null}
      </div>
    )
  }
  if (block.kind === 'reasoning') {
    return (
      <div id={`block-${block.id}`} className="ds-card-soft rounded-[20px] px-4 py-3 text-[13.5px] leading-6 text-ds-muted">
        <div className="ds-markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.text}</ReactMarkdown>
        </div>
      </div>
    )
  }
  if (block.kind === 'tool') {
    return <ToolEntry block={block} nested={nested} />
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

function ToolEntry({ block, nested = false }: { block: ToolBlock; nested?: boolean }): ReactElement {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(() => block.status === 'error' || block.status === 'running')

  useEffect(() => {
    if (block.status === 'running') {
      setOpen(true)
    }
  }, [block.status, block.id])

  const effectiveOpen = block.status === 'running' ? true : open

  const tone =
    block.status === 'error'
      ? 'border-red-300/80 bg-red-500/10 text-red-950 dark:border-red-800/60 dark:bg-red-950/35 dark:text-red-100'
      : block.status === 'running'
        ? 'border-amber-300/80 bg-amber-500/10 text-amber-950 dark:border-amber-800/50 dark:bg-amber-950/30 dark:text-amber-100'
        : 'border-ds-border bg-ds-subtle text-ds-ink'

  const Icon = block.toolKind === 'file_change' ? FileEdit : block.toolKind === 'command_execution' ? Terminal : Wrench
  const kindLabel =
    block.toolKind === 'file_change'
      ? t('toolKindFile')
      : block.toolKind === 'command_execution'
        ? t('toolKindCommand')
        : t('toolKindTool')

  const exitCode = readNumber(block.meta, 'exit_code')
  const durationMs = readNumber(block.meta, 'duration_ms')

  const hasDetail = !!(block.detail && block.detail.trim().length > 0)
  const isPatch = block.toolKind === 'file_change' && hasDetail
  const canExpand = hasDetail || block.status === 'running'

  return (
    <div className={`rounded-[22px] border shadow-[0_12px_30px_rgba(86,103,136,0.04)] ${tone}`}>
      <button
        type="button"
        onClick={() => {
          if (!canExpand || block.status === 'running') return
          setOpen((v) => !v)
        }}
        className={`flex w-full items-start gap-2 px-4 py-3 text-left text-[13.5px] leading-6 ${
          canExpand && block.status !== 'running' ? 'cursor-pointer' : 'cursor-default'
        }`}
      >
        <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-80" strokeWidth={1.75} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold uppercase tracking-[0.12em] text-[11px] opacity-75">
              {kindLabel}
            </span>
            {block.status === 'running' ? (
              <span className="rounded-full bg-amber-200/40 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:bg-amber-700/30 dark:text-amber-100">
                {t('inspectorStatusRunning')}
              </span>
            ) : null}
            {typeof exitCode === 'number' ? (
              <span
                className={`rounded-full px-2 py-0.5 text-[11px] tabular-nums ${
                  exitCode === 0
                    ? 'bg-ds-success-soft text-ds-success'
                    : 'bg-ds-danger-soft text-ds-danger'
                }`}
              >
                exit {exitCode}
              </span>
            ) : null}
            {typeof durationMs === 'number' ? (
              <span className="rounded-full bg-ds-card px-2 py-0.5 text-[11px] tabular-nums text-ds-muted">
                {formatDuration(durationMs)}
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 break-words">
            {block.filePath ? (
              <span className="font-mono text-[12px] opacity-90">{block.filePath} — </span>
            ) : null}
            <span>{block.summary}</span>
          </div>
        </div>
        {canExpand ? (
          effectiveOpen ? (
            <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-70" strokeWidth={1.75} />
          ) : (
            <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-70" strokeWidth={1.75} />
          )
        ) : null}
      </button>
      {effectiveOpen && hasDetail ? (
        <div className="ds-panel-strip min-w-0 border-t border-ds-border-muted/60 px-4 py-3">
          {isPatch ? (
            <DiffView patch={block.detail!} filePath={block.filePath} />
          ) : (
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-ds-ink">
              {block.detail}
            </pre>
          )}
        </div>
      ) : null}
    </div>
  )
}

function readNumber(meta: Record<string, unknown> | undefined, key: string): number | undefined {
  if (!meta) return undefined
  const v = meta[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined
}

function formatToolTitle(block: ToolBlock, t: (key: string) => string): string {
  if (block.toolKind === 'file_change') return t('toolActionFile')
  if (block.toolKind === 'command_execution') return t('toolActionCommand')
  return t('toolActionTool')
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m ${s}s`
}
