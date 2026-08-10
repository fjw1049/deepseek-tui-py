import type { NormalizedThread } from '../../agent/types'
import { isWorkspaceHidden } from '../../lib/sidebar-chrome'
import { applyManualOrder } from '../../lib/sidebar-manual-order'
import {
  loadProjectSortMode,
  sortProjectGroups,
  type ProjectSortMode
} from '../../lib/sidebar-project-sort'
import { deriveThreadTitleFromPrompt, shouldAutoTitleThread } from '../../lib/thread-title'
import {
  isChatsWorkspace,
  isClawWorkspacePath,
  isInternalTemporaryWorkspace,
  normalizeWorkspaceRoot
} from '../../lib/workspace-path'
import { workspaceLabelFromPath } from '../../lib/workspace-label'

export type KanbanColumnKey = 'draft' | 'inProgress' | 'done'

export const CHATS_COLUMN_ID = '__chats__'

export const OVERVIEW_RENDER_CAP = 20
export const DONE_RENDER_CAP = 30

export type KanbanCard = {
  cardId: string
  threadId: string
  projectId: string
  column: KanbanColumnKey
  title: string
  branch: string | null
  timestamp: string | null
  sortTimestamp: number
  /** Unsent prompt parked from the kanban New Task dialog. */
  draftPrompt: string
}

export type KanbanProjectBoard = {
  projectId: string
  projectName: string
  /** Absolute workspace path; null for the synthetic Chats column. */
  workspacePath: string | null
  draft: KanbanCard[]
  inProgress: KanbanCard[]
  done: KanbanCard[]
  totalCount: number
}

export type KanbanBoard = {
  projects: KanbanProjectBoard[]
  totalCount: number
}

export type BuildKanbanBoardInput = {
  threads: readonly NormalizedThread[]
  hiddenWorkspacePaths: readonly string[]
  projectOrder: readonly string[]
  projectSortMode?: ProjectSortMode
  /** Thread ids with a live turn / watch flag. */
  inProgressThreadIds: ReadonlySet<string>
  chatsColumnName: string
  /** Prompt text parked on threads that have not been dispatched yet. */
  draftPromptByThreadId?: Readonly<Record<string, string | undefined>>
  /** Manual draft-column order per project. */
  draftOrderByProjectId?: Readonly<Record<string, readonly string[] | undefined>>
  /** Manual card order per project column (draft / inProgress / done). */
  columnOrderByProjectId?: Readonly<
    Record<string, Partial<Record<KanbanColumnKey, readonly string[]>> | undefined>
  >
  /** Threads temporarily forced into In Progress after a kanban send. */
  optimisticInProgressThreadIds?: ReadonlySet<string>
}

function toSortTimestamp(iso: string | null | undefined): number {
  if (!iso) return Number.NEGATIVE_INFINITY
  const ms = Date.parse(iso)
  return Number.isFinite(ms) ? ms : Number.NEGATIVE_INFINITY
}

/**
 * Column meanings (agent control center, not a classic todo board):
 * - In Progress: turn / background task currently running
 * - Draft: not started yet — parked New Task prompt, or an empty unused thread
 * - Done: already used / settled conversations (default for real chats)
 *
 * Missing runtime `status` must NOT force Draft; most list threads omit it.
 */
export function deriveKanbanColumn(
  thread: Pick<NormalizedThread, 'id' | 'title' | 'status'>,
  inProgressThreadIds: ReadonlySet<string>,
  options?: {
    draftPrompt?: string
    optimisticInProgress?: boolean
  }
): KanbanColumnKey {
  const status = thread.status?.trim().toLowerCase() ?? ''
  if (
    options?.optimisticInProgress ||
    inProgressThreadIds.has(thread.id) ||
    status === 'running'
  ) {
    return 'inProgress'
  }
  // Explicit kanban draft text always parks in Draft (even on an old thread).
  if (options?.draftPrompt?.trim()) {
    return 'draft'
  }
  // Brand-new empty session that never got a real title — waiting to be used.
  if (shouldAutoTitleThread(thread)) {
    return 'draft'
  }
  return 'done'
}

function buildCard(
  thread: NormalizedThread,
  projectId: string,
  column: KanbanColumnKey,
  draftPrompt: string
): KanbanCard {
  const timestamp = thread.updatedAt ?? thread.createdAt ?? null
  const titleFromDraft =
    column === 'draft' && draftPrompt.trim()
      ? deriveThreadTitleFromPrompt(draftPrompt)
      : null
  return {
    cardId: thread.id,
    threadId: thread.id,
    projectId,
    column,
    title: titleFromDraft || thread.title?.trim() || thread.id.slice(0, 8),
    branch: null,
    timestamp,
    sortTimestamp: toSortTimestamp(timestamp),
    draftPrompt: column === 'draft' ? draftPrompt.trim() : ''
  }
}

function sortByRecency(cards: KanbanCard[]): KanbanCard[] {
  return [...cards].sort((a, b) => b.sortTimestamp - a.sortTimestamp)
}

function applyCardOrder(
  cards: KanbanCard[],
  manualOrder: readonly string[] | undefined
): KanbanCard[] {
  if (!manualOrder || manualOrder.length === 0) return sortByRecency(cards)
  const byId = new Map(cards.map((card) => [card.cardId, card]))
  const orderedIds = applyManualOrder(
    cards.map((card) => card.cardId),
    [...manualOrder]
  )
  return orderedIds
    .map((id) => byId.get(id))
    .filter((card): card is KanbanCard => Boolean(card))
}

function isBoardThread(thread: NormalizedThread, hiddenWorkspacePaths: readonly string[]): boolean {
  if (thread.archived) return false
  if (isClawWorkspacePath(thread.workspace)) return false
  if (isInternalTemporaryWorkspace(thread.workspace) && !isChatsWorkspace(thread.workspace)) {
    return false
  }
  if (isChatsWorkspace(thread.workspace)) return true
  const key = normalizeWorkspaceRoot(thread.workspace)
  if (!key) return false
  if (isWorkspaceHidden(key, hiddenWorkspacePaths)) return false
  return true
}

function buildProjectBoard(
  projectId: string,
  projectName: string,
  workspacePath: string | null,
  threads: readonly NormalizedThread[],
  input: BuildKanbanBoardInput
): KanbanProjectBoard {
  const draft: KanbanCard[] = []
  const inProgress: KanbanCard[] = []
  const done: KanbanCard[] = []
  const optimistic = input.optimisticInProgressThreadIds ?? new Set<string>()
  const prompts = input.draftPromptByThreadId ?? {}

  for (const thread of threads) {
    const draftPrompt = prompts[thread.id]?.trim() ?? ''
    const column = deriveKanbanColumn(thread, input.inProgressThreadIds, {
      draftPrompt,
      optimisticInProgress: optimistic.has(thread.id)
    })
    const card = buildCard(thread, projectId, column, draftPrompt)
    if (column === 'draft') draft.push(card)
    else if (column === 'inProgress') inProgress.push(card)
    else done.push(card)
  }

  const columnOrders = input.columnOrderByProjectId?.[projectId]
  const draftOrder = columnOrders?.draft ?? input.draftOrderByProjectId?.[projectId]
  return {
    projectId,
    projectName,
    workspacePath,
    draft: applyCardOrder(draft, draftOrder),
    inProgress: applyCardOrder(inProgress, columnOrders?.inProgress),
    done: applyCardOrder(done, columnOrders?.done),
    totalCount: draft.length + inProgress.length + done.length
  }
}

export function flattenProjectBoard(board: KanbanProjectBoard): KanbanCard[] {
  return [...board.inProgress, ...board.draft, ...board.done]
}

export function buildKanbanBoard(input: BuildKanbanBoardInput): KanbanBoard {
  const sortMode = input.projectSortMode ?? loadProjectSortMode()
  const projectMap = new Map<string, NormalizedThread[]>()
  const chatsThreads: NormalizedThread[] = []

  for (const thread of input.threads) {
    if (!isBoardThread(thread, input.hiddenWorkspacePaths)) continue
    if (isChatsWorkspace(thread.workspace)) {
      chatsThreads.push(thread)
      continue
    }
    const key = normalizeWorkspaceRoot(thread.workspace)
    if (!key) continue
    const list = projectMap.get(key) ?? []
    list.push(thread)
    projectMap.set(key, list)
  }

  const autoSorted = sortProjectGroups(Array.from(projectMap.entries()), sortMode)
  const orderedPaths =
    input.projectOrder.length === 0
      ? autoSorted.map(([path]) => path)
      : applyManualOrder(
          autoSorted.map(([path]) => path),
          [...input.projectOrder]
        )
  const byPath = new Map(autoSorted)

  const projects: KanbanProjectBoard[] = []
  for (const path of orderedPaths) {
    const threads = byPath.get(path) ?? []
    if (threads.length === 0) continue
    projects.push(
      buildProjectBoard(path, workspaceLabelFromPath(path), path, threads, input)
    )
  }

  if (chatsThreads.length > 0) {
    projects.push(
      buildProjectBoard(
        CHATS_COLUMN_ID,
        input.chatsColumnName,
        null,
        chatsThreads,
        input
      )
    )
  }

  return {
    projects,
    totalCount: projects.reduce((sum, project) => sum + project.totalCount, 0)
  }
}

export function overviewVisibleCards(board: KanbanProjectBoard): {
  visibleCards: KanbanCard[]
  hiddenCount: number
} {
  const cards = flattenProjectBoard(board)
  const visibleCards =
    cards.length > OVERVIEW_RENDER_CAP ? cards.slice(0, OVERVIEW_RENDER_CAP) : cards
  return { visibleCards, hiddenCount: cards.length - visibleCards.length }
}

export function withProjectBranches(
  board: KanbanBoard,
  branchByProjectId: ReadonlyMap<string, string | null>
): KanbanBoard {
  return {
    ...board,
    projects: board.projects.map((project) => {
      const branch = branchByProjectId.get(project.projectId) ?? null
      if (!branch) return project
      const apply = (cards: KanbanCard[]): KanbanCard[] =>
        cards.map((card) => ({ ...card, branch }))
      return {
        ...project,
        draft: apply(project.draft),
        inProgress: apply(project.inProgress),
        done: apply(project.done)
      }
    })
  }
}

export function reorderKanbanCardIds(
  visibleCardIds: readonly string[],
  activeCardId: string,
  overCardId: string
): string[] | null {
  const fromIndex = visibleCardIds.indexOf(activeCardId)
  const toIndex = visibleCardIds.indexOf(overCardId)
  if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) return null
  const next = [...visibleCardIds]
  const [moved] = next.splice(fromIndex, 1)
  if (moved === undefined) return null
  next.splice(toIndex, 0, moved)
  return next
}

/** @deprecated Prefer {@link reorderKanbanCardIds}. */
export const reorderDraftCardIds = reorderKanbanCardIds

export function cardsForColumn(
  board: KanbanProjectBoard,
  column: KanbanColumnKey
): readonly KanbanCard[] {
  if (column === 'draft') return board.draft
  if (column === 'inProgress') return board.inProgress
  return board.done
}

export function findBoardCard(
  board: KanbanProjectBoard,
  cardId: string
): KanbanCard | null {
  return (
    board.draft.find((card) => card.cardId === cardId) ??
    board.inProgress.find((card) => card.cardId === cardId) ??
    board.done.find((card) => card.cardId === cardId) ??
    null
  )
}

export const COLUMN_DROP_ID_PREFIX = 'kanban-column'

export function kanbanColumnDropId(projectId: string, column: KanbanColumnKey): string {
  return `${COLUMN_DROP_ID_PREFIX}|${column}|${projectId}`
}

export function parseKanbanColumnDropId(
  dropId: string
): { projectId: string; column: KanbanColumnKey } | null {
  const [prefix, column, ...projectIdParts] = dropId.split('|')
  if (prefix !== COLUMN_DROP_ID_PREFIX || projectIdParts.length === 0) return null
  if (column !== 'draft' && column !== 'inProgress' && column !== 'done') return null
  return { projectId: projectIdParts.join('|'), column }
}
