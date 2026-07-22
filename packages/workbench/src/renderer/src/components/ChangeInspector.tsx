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
import { ChevronRight, FileEdit, Pencil } from 'lucide-react'
import type { GitWorkingChangeFile, GitWorkingChangeStage } from '@shared/git-working-changes'
import type { ChatBlock } from '../agent/types'
import { ChangeDiffStatsLabel } from './ChangeDiffStatsLabel'
import { DiffView } from './DiffView'
import { useGitWorkingChanges } from '../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../hooks/use-workspace-dirty-git-refresh'
import {
  countDiffStats,
  extractDiffFilePath,
  formatFilePathForDisplay,
  looksLikeUnifiedDiff,
  sumDiffStats
} from '../lib/diff-stats'
import { resolveActiveThreadWorkspace } from '../lib/workspace-path'
import { useChatStore } from '../store/chat-store'

type InspectorChangeItem = {
  id: string
  filePath?: string
  detail: string
  status: 'running' | 'success' | 'error'
  committable?: boolean
  gitStage?: GitWorkingChangeStage
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
        status: block.status
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
        status: 'success'
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
    committable: true,
    gitStage: file.stage
  }))
}

function mergeChangeItems(
  sessionItems: InspectorChangeItem[],
  gitItems: InspectorChangeItem[]
): InspectorChangeItem[] {
  // Prefer session/ledger detail (agent turn), but keep git commit metadata so
  // AI-touched files that are also dirty in git still show checkboxes.
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

const DIFF_HEIGHT_DEFAULT = 360
const DIFF_HEIGHT_MIN = 160
const DIFF_HEIGHT_MAX = 900

/**
 * Right-side change list — expand a file to review its unified diff;
 * open the full file in the workspace editor via an explicit action.
 */
export function ChangeInspector({
  blocks,
  className,
  onOpenFileInEditor
}: {
  blocks: ChatBlock[]
  className?: string
  onOpenFileInEditor: (path: string) => void
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
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [diffHeight, setDiffHeight] = useState(DIFF_HEIGHT_DEFAULT)
  const resizeDrag = useRef<{ startY: number; startHeight: number } | null>(null)

  const onDiffResizePointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
    const target = event.currentTarget
    target.setPointerCapture(event.pointerId)
    resizeDrag.current = { startY: event.clientY, startHeight: diffHeight }
  }, [diffHeight])

  const onDiffResizePointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = resizeDrag.current
    if (!drag) return
    const next = Math.min(
      DIFF_HEIGHT_MAX,
      Math.max(DIFF_HEIGHT_MIN, drag.startHeight + (event.clientY - drag.startY))
    )
    setDiffHeight(next)
  }, [])

  const onDiffResizePointerUp = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (resizeDrag.current) {
      resizeDrag.current = null
      try {
        event.currentTarget.releasePointerCapture(event.pointerId)
      } catch {
        /* already released */
      }
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
      setExpandedId(null)
      return
    }
    if (selectedId && fileChanges.some((item) => item.id === selectedId)) return
    selectInspectorItem(fileChanges[fileChanges.length - 1]?.id ?? null)
  }, [fileChanges, selectedId, selectInspectorItem])

  useEffect(() => {
    if (expandedId && !fileChanges.some((item) => item.id === expandedId)) {
      setExpandedId(null)
    }
  }, [expandedId, fileChanges])

  const gitStageLabel = (stage: GitWorkingChangeStage): string => {
    if (stage === 'staged') return t('gitStageStaged')
    if (stage === 'partial') return t('gitStagePartial')
    return t('gitStageUnstaged')
  }

  const toggleItem = (item: InspectorChangeItem): void => {
    selectInspectorItem(item.id)
    setExpandedId((current) => (current === item.id ? null : item.id))
  }

  return (
    <aside
      className={`ds-change-inspector ds-tool-panel ds-no-drag flex flex-col ${className ?? ''}`}
    >
      <div className="flex min-h-[58px] shrink-0 items-center gap-3 border-b border-ds-border-muted px-3 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div className="text-[13px] font-semibold tracking-wide text-ds-muted">
              {t('inspectorTitle')}
            </div>
            {changeStats ? <ChangeDiffStatsLabel stats={changeStats} size="md" /> : null}
          </div>
          <div className="mt-1 truncate text-[12px] text-ds-faint">
            {gitLoading && fileChanges.length === 0
              ? t('gitBranchLoading')
              : fileChanges.length > 0
                ? t('inspectorSummaryFiles', { count: fileChanges.length })
                : t('inspectorEmpty')}
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
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
        ) : (
          <>
            {gitFilePaths.length > 0 ? (
              <div className="flex shrink-0 items-center gap-2 border-b border-ds-border-muted/60 px-4 py-2 text-[12px] text-ds-faint">
                <span className="min-w-0 flex-1 truncate">
                  {t('gitCommitSelectionSummary', {
                    selected: selectedCommitCount,
                    total: gitFilePaths.length
                  })}
                </span>
              </div>
            ) : null}
            <div className="min-h-0 flex-1 overflow-y-auto py-2">
              <ul className="divide-y divide-ds-border-muted/60">
                {fileChanges.map((item) => {
                  const stats = countDiffStats(item.detail)
                  const displayPath = formatFilePathForDisplay(item.filePath, root || workspaceRoot)
                  const commitSelected = Boolean(
                    item.committable &&
                      item.filePath &&
                      gitCommitSelectedPaths.includes(item.filePath)
                  )
                  const isExpanded = expandedId === item.id
                  const hasPatch = Boolean(item.detail.trim())
                  return (
                    <li key={item.id}>
                      <div
                        className={`flex w-full items-start gap-2.5 px-4 py-2.5 transition ${
                          isExpanded ? 'bg-ds-hover text-ds-ink' : 'text-ds-ink hover:bg-ds-hover/70'
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
                          onClick={() => toggleItem(item)}
                          aria-expanded={isExpanded}
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
                            <ChevronRight
                              className={`h-4 w-4 shrink-0 text-ds-faint transition-transform ${
                                isExpanded ? 'rotate-90' : ''
                              }`}
                              strokeWidth={1.85}
                            />
                          </div>
                          {stats ? <ChangeDiffStatsLabel stats={stats} size="sm" /> : null}
                        </button>
                        {item.filePath ? (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation()
                              onOpenFileInEditor(item.filePath!)
                            }}
                            className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
                            title={t('inspectorOpenInEditor')}
                            aria-label={t('inspectorOpenInEditor')}
                          >
                            <Pencil className="h-3.5 w-3.5" strokeWidth={1.85} />
                          </button>
                        ) : null}
                      </div>
                      {isExpanded ? (
                        <div className="border-t border-ds-border-muted/50 bg-ds-sidebar/40 px-3 py-2.5">
                          {hasPatch ? (
                            <div className="flex min-w-0 flex-col">
                              <DiffView
                                patch={item.detail}
                                filePath={item.filePath}
                                maxHeight={diffHeight}
                              />
                              <div
                                role="separator"
                                aria-orientation="horizontal"
                                aria-label={t('inspectorResizeDiff')}
                                title={t('inspectorResizeDiff')}
                                className="ds-no-drag group mt-1 flex h-2.5 cursor-row-resize touch-none items-center justify-center"
                                onPointerDown={onDiffResizePointerDown}
                                onPointerMove={onDiffResizePointerMove}
                                onPointerUp={onDiffResizePointerUp}
                                onPointerCancel={onDiffResizePointerUp}
                              >
                                <span className="h-0.5 w-8 rounded-full bg-ds-border-strong transition group-hover:bg-ds-muted" />
                              </div>
                            </div>
                          ) : (
                            <div className="px-1 py-3 text-center text-[12px] text-ds-faint">
                              {t('inspectorDiffEmpty')}
                            </div>
                          )}
                        </div>
                      ) : null}
                    </li>
                  )
                })}
              </ul>
            </div>
          </>
        )}
      </div>
    </aside>
  )
}
