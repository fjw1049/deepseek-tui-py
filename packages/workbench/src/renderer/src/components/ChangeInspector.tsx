import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactElement
} from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import { FileEdit } from 'lucide-react'
import type { GitWorkingChangeFile, GitWorkingChangeStage } from '@shared/git-working-changes'
import type { ChatBlock } from '../agent/types'
import { ChangeDiffStatsLabel } from './ChangeDiffStatsLabel'
import { DiffView, type DiffRenderStyle } from './DiffView'
import { useGitWorkingChanges } from '../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../hooks/use-workspace-dirty-git-refresh'
import {
  countDiffStats,
  extractDiffFilePath,
  formatFilePathForDisplay,
  looksLikeUnifiedDiff,
  sumDiffStats
} from '../lib/diff-stats'
import { firstChangedEditorLineFromPatch } from '../lib/parse-unified-diff-for-editor'
import { resolveActiveThreadWorkspace } from '../lib/workspace-path'
import { useChatStore } from '../store/chat-store'

type InspectorChangeItem = {
  id: string
  filePath?: string
  detail: string
  status: 'running' | 'success' | 'error'
  /** First changed line in the new file (1-based), for open-in-editor jumps. */
  editLine?: number
  committable?: boolean
  gitStage?: GitWorkingChangeStage
}

function editLineFromChange(
  detail: string,
  meta?: Record<string, unknown>
): number | undefined {
  const mutation =
    meta?.mutation && typeof meta.mutation === 'object' && !Array.isArray(meta.mutation)
      ? (meta.mutation as Record<string, unknown>)
      : undefined
  const fromMeta = mutation?.line_start
  if (typeof fromMeta === 'number' && Number.isFinite(fromMeta) && fromMeta >= 1) {
    return Math.floor(fromMeta)
  }
  return firstChangedEditorLineFromPatch(detail)
}

function normalizeChangePath(path: string | undefined): string {
  return (path ?? '').replace(/\\/g, '/').trim().toLowerCase()
}

function sessionChangeItems(blocks: ChatBlock[]): InspectorChangeItem[] {
  return blocks.flatMap((block): InspectorChangeItem[] => {
    if (!(block.kind === 'tool' && block.toolKind === 'file_change')) {
      return []
    }

    const detailText = block.detail?.trim() ?? ''
    if (!looksLikeUnifiedDiff(detailText)) return []

    return [
      {
        id: block.id,
        filePath: extractDiffFilePath(detailText, block.filePath),
        detail: detailText,
        status: block.status,
        editLine: editLineFromChange(detailText, block.meta)
      }
    ]
  })
}

function turnLedgerChangeItems(
  turnDiffByTurnId: Record<
    string,
    {
      turn_id: string
      files: Array<{ path: string; unified_diff: string; additions: number; deletions: number }>
    }
  >
): InspectorChangeItem[] {
  const items: InspectorChangeItem[] = []
  for (const snap of Object.values(turnDiffByTurnId)) {
    for (const file of snap.files ?? []) {
      const detail = file.unified_diff?.trim() ?? ''
      if (!looksLikeUnifiedDiff(detail)) continue
      items.push({
        id: `turn-ledger:${snap.turn_id}:${file.path}`,
        filePath: file.path,
        detail,
        status: 'success',
        editLine: firstChangedEditorLineFromPatch(detail)
      })
    }
  }
  return items
}

function gitChangeItems(files: GitWorkingChangeFile[]): InspectorChangeItem[] {
  return files.map((file) => ({
    id: `git:${file.path}`,
    filePath: file.path,
    detail: file.patch,
    status: 'success' as const,
    editLine: firstChangedEditorLineFromPatch(file.patch),
    committable: true,
    gitStage: file.stage
  }))
}

function mergeChangeItems(
  sessionItems: InspectorChangeItem[],
  gitItems: InspectorChangeItem[]
): InspectorChangeItem[] {
  const gitByPath = new Map<string, InspectorChangeItem>()
  for (const item of gitItems) {
    const key = normalizeChangePath(item.filePath)
    if (key) gitByPath.set(key, item)
  }

  const seen = new Set<string>()
  const merged: InspectorChangeItem[] = []

  for (const item of sessionItems) {
    const key = normalizeChangePath(item.filePath) || item.id
    if (seen.has(key)) continue
    seen.add(key)
    const git = item.filePath ? gitByPath.get(normalizeChangePath(item.filePath)) : undefined
    if (git) {
      merged.push({
        ...item,
        committable: true,
        gitStage: git.gitStage,
        detail: item.detail.trim() ? item.detail : git.detail
      })
    } else {
      merged.push(item)
    }
  }

  for (const item of gitItems) {
    const key = normalizeChangePath(item.filePath) || item.id
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }

  return merged
}

const FILE_LIST_DEFAULT = 280
const FILE_LIST_MIN = 180
const FILE_LIST_MAX = 480
const STACK_LIST_DEFAULT = 220
const STACK_LIST_MIN = 120
const STACK_LIST_MAX = 420

/**
 * Change review panel.
 * - `review`: IDE center — file list | full-height compare viewport (default split).
 * - `stack`: right sidebar — file list above, compare below.
 */
export function ChangeInspector({
  blocks,
  className,
  variant = 'stack'
}: {
  blocks: ChatBlock[]
  className?: string
  variant?: 'review' | 'stack'
}): ReactElement {
  const { t } = useTranslation('common')
  const selectedId = useChatStore((s) => s.inspectorSelectedId)
  const selectInspectorItem = useChatStore((s) => s.selectInspectorItem)
  const gitCommitSelectedPaths = useChatStore((s) => s.gitCommitSelectedPaths)
  const syncGitCommitSelection = useChatStore((s) => s.syncGitCommitSelection)
  const toggleGitCommitPath = useChatStore((s) => s.toggleGitCommitPath)
  const { workspaceRoot, activeThreadId, threads, workspaceDirtyTick, turnDiffByTurnId } =
    useChatStore(
      useShallow((s) => ({
        workspaceRoot: s.workspaceRoot,
        activeThreadId: s.activeThreadId,
        threads: s.threads,
        workspaceDirtyTick: s.workspaceDirtyTick,
        turnDiffByTurnId: s.turnDiffByTurnId
      }))
    )
  const root = resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot)
  const { result: gitChanges, loading: gitLoading, reload: reloadGitChanges } = useGitWorkingChanges(root)
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, reloadGitChanges)
  const gitFilePaths = useMemo(
    () => (gitChanges?.ok ? gitChanges.files.map((file) => file.path) : []),
    [gitChanges]
  )

  const isReview = variant === 'review'
  const [listSize, setListSize] = useState(isReview ? FILE_LIST_DEFAULT : STACK_LIST_DEFAULT)
  // Unified by default — denser, no empty half-pane on new/deleted files.
  const [diffStyle, setDiffStyle] = useState<DiffRenderStyle>('unified')
  const resizeDrag = useRef<{ start: number; startSize: number } | null>(null)

  const onListResizePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault()
      event.stopPropagation()
      event.currentTarget.setPointerCapture(event.pointerId)
      resizeDrag.current = {
        start: isReview ? event.clientX : event.clientY,
        startSize: listSize
      }
    },
    [isReview, listSize]
  )

  const onListResizePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const drag = resizeDrag.current
      if (!drag) return
      const delta = (isReview ? event.clientX : event.clientY) - drag.start
      const min = isReview ? FILE_LIST_MIN : STACK_LIST_MIN
      const max = isReview ? FILE_LIST_MAX : STACK_LIST_MAX
      setListSize(Math.min(max, Math.max(min, drag.startSize + delta)))
    },
    [isReview]
  )

  const onListResizePointerUp = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizeDrag.current) return
    resizeDrag.current = null
    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      /* already released */
    }
  }, [])

  const fileChanges = useMemo(() => {
    const sessionItems = mergeChangeItems(
      sessionChangeItems(blocks),
      turnLedgerChangeItems(turnDiffByTurnId)
    )
    const gitItems = gitChanges?.ok ? gitChangeItems(gitChanges.files) : []
    return mergeChangeItems(sessionItems, gitItems)
  }, [blocks, gitChanges, turnDiffByTurnId])

  const changeStats = useMemo(
    () => sumDiffStats(fileChanges.map((item) => item.detail)),
    [fileChanges]
  )

  useEffect(() => {
    if (gitChanges == null || !gitChanges.ok) return
    syncGitCommitSelection(gitFilePaths)
  }, [gitChanges, gitFilePaths, syncGitCommitSelection])

  const selectedCommitCount = useMemo(() => {
    const allowed = new Set(gitFilePaths)
    return gitCommitSelectedPaths.filter((path) => allowed.has(path)).length
  }, [gitCommitSelectedPaths, gitFilePaths])

  useEffect(() => {
    if (fileChanges.length === 0) {
      if (selectedId !== null) selectInspectorItem(null)
      return
    }
    if (selectedId && fileChanges.some((item) => item.id === selectedId)) return
    selectInspectorItem(fileChanges[fileChanges.length - 1]?.id ?? null)
  }, [fileChanges, selectedId, selectInspectorItem])

  const selectedItem = useMemo(
    () => fileChanges.find((item) => item.id === selectedId) ?? null,
    [fileChanges, selectedId]
  )

  const gitStageLabel = (stage: GitWorkingChangeStage): string => {
    if (stage === 'staged') return t('gitStageStaged')
    if (stage === 'partial') return t('gitStagePartial')
    return t('gitStageUnstaged')
  }

  const fileList = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {/* Same h-9 + px-2 + border as DiffView header so both columns share one rule. */}
      <div className="ds-change-inspector__pane-header flex shrink-0 items-center gap-2">
        <div className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-ds-muted">
          {t('inspectorTitle')}
          {changeStats ? (
            <span className="ml-2 inline-flex align-middle">
              <ChangeDiffStatsLabel stats={changeStats} size="sm" />
            </span>
          ) : null}
        </div>
        {gitFilePaths.length > 0 ? (
          <span className="max-w-[46%] shrink-0 truncate text-[11px] text-ds-faint" title={t('gitCommitSelectionSummary', {
            selected: selectedCommitCount,
            total: gitFilePaths.length
          })}>
            {t('gitCommitSelectionSummary', {
              selected: selectedCommitCount,
              total: gitFilePaths.length
            })}
          </span>
        ) : fileChanges.length > 0 ? (
          <span className="shrink-0 text-[11px] text-ds-faint">
            {t('inspectorSummaryFiles', { count: fileChanges.length })}
          </span>
        ) : null}
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {fileChanges.map((item) => {
          const stats = countDiffStats(item.detail)
          const displayPath = formatFilePathForDisplay(item.filePath, root || workspaceRoot)
          const commitSelected = Boolean(
            item.committable && item.filePath && gitCommitSelectedPaths.includes(item.filePath)
          )
          const isSelected = selectedId === item.id
          return (
            <li key={item.id}>
              <div
                className={`flex w-full items-start gap-2 px-2 py-1.5 transition ${
                  isSelected ? 'bg-ds-hover text-ds-ink' : 'text-ds-ink hover:bg-ds-hover/70'
                }`}
              >
                {item.committable && item.filePath ? (
                  <input
                    type="checkbox"
                    checked={commitSelected}
                    aria-label={t('gitCommitIncludeFile', {
                      file: displayPath ?? item.filePath
                    })}
                    className="mt-1 shrink-0"
                    onClick={(event) => event.stopPropagation()}
                    onChange={() => toggleGitCommitPath(item.filePath!, gitFilePaths)}
                  />
                ) : (
                  <FileEdit
                    className={`mt-0.5 h-4 w-4 shrink-0 ${
                      item.status === 'error' ? 'text-red-700' : 'text-ds-muted'
                    }`}
                    strokeWidth={1.75}
                  />
                )}
                <button
                  type="button"
                  onClick={() => selectInspectorItem(item.id)}
                  aria-current={isSelected ? 'true' : undefined}
                  className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <div className="min-w-0 flex-1 truncate text-[13px] text-ds-ink">
                      {displayPath ?? t('toolActionFile')}
                    </div>
                    {item.gitStage && item.gitStage !== 'unstaged' ? (
                      <span className="shrink-0 rounded-full bg-ds-hover px-2 py-0.5 text-[11px] font-medium leading-none text-ds-muted">
                        {gitStageLabel(item.gitStage)}
                      </span>
                    ) : null}
                    {item.status === 'running' ? (
                      <span className="shrink-0 rounded-full bg-amber-200/40 px-2 py-0.5 text-[11px] font-medium leading-none text-amber-900 dark:bg-amber-700/30 dark:text-amber-100">
                        {t('inspectorStatusRunning')}
                      </span>
                    ) : null}
                  </div>
                  {stats ? <ChangeDiffStatsLabel stats={stats} size="sm" /> : null}
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )

  const diffViewport = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {selectedItem ? (
        selectedItem.detail.trim() ? (
          <DiffView
            patch={selectedItem.detail}
            filePath={selectedItem.filePath}
            maxHeight={9000}
            diffStyle={diffStyle}
            showStyleToggle
            onDiffStyleChange={setDiffStyle}
            chrome="flush"
            className="min-h-0 flex-1"
          />
        ) : (
          <div className="flex flex-1 items-center justify-center text-[12px] text-ds-faint">
            {t('inspectorDiffEmpty')}
          </div>
        )
      ) : (
        <div className="flex flex-1 items-center justify-center px-4 text-center text-[13px] text-ds-faint">
          {t('inspectorSelectHint')}
        </div>
      )}
    </div>
  )

  return (
    <aside
      className={`ds-change-inspector ds-change-inspector--${variant} ds-tool-panel ds-no-drag flex h-full min-h-0 flex-col ${className ?? ''}`}
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {gitLoading && fileChanges.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-6 py-10 text-center text-[13px] text-ds-faint">
            {t('gitBranchLoading')}
          </div>
        ) : fileChanges.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-6 py-10 text-center">
            <div>
              <FileEdit className="mx-auto h-7 w-7 text-ds-faint" strokeWidth={1.25} />
              <div className="mt-3 text-[13px] font-medium text-ds-muted">
                {t('inspectorEmptyTitle')}
              </div>
              <div className="mt-1 text-[12px] leading-6 text-ds-faint">{t('inspectorEmpty')}</div>
            </div>
          </div>
        ) : isReview ? (
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <div className="flex h-full min-h-0 shrink-0 flex-col" style={{ width: listSize }}>
              {fileList}
            </div>
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label={t('inspectorResizeSplit')}
              className="ds-change-inspector__split-handle ds-no-drag relative z-10 w-px shrink-0 cursor-col-resize touch-none bg-[color-mix(in_srgb,var(--ds-text)_10%,transparent)] hover:bg-ds-hover"
              onPointerDown={onListResizePointerDown}
              onPointerMove={onListResizePointerMove}
              onPointerUp={onListResizePointerUp}
              onPointerCancel={onListResizePointerUp}
            />
            {diffViewport}
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="flex min-h-0 shrink-0 flex-col overflow-hidden" style={{ height: listSize }}>
              {fileList}
            </div>
            <div
              role="separator"
              aria-orientation="horizontal"
              aria-label={t('inspectorResizeSplit')}
              className="ds-change-inspector__split-handle ds-no-drag flex h-1.5 shrink-0 cursor-row-resize touch-none items-center justify-center"
              onPointerDown={onListResizePointerDown}
              onPointerMove={onListResizePointerMove}
              onPointerUp={onListResizePointerUp}
              onPointerCancel={onListResizePointerUp}
            >
              <span className="h-px w-8 bg-ds-border-strong" />
            </div>
            {diffViewport}
          </div>
        )}
      </div>
    </aside>
  )
}
