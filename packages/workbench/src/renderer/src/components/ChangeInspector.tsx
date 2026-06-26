import { useEffect, useMemo, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import { ChevronRight, FileEdit, PanelRightClose } from 'lucide-react'
import type { GitWorkingChangeFile, GitWorkingChangeStage } from '@shared/git-working-changes'
import type { ChatBlock } from '../agent/types'
import { ChangeDiffStatsLabel } from './ChangeDiffStatsLabel'
import { useGitWorkingChanges } from '../hooks/use-git-working-changes'
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
  const seen = new Set<string>()
  const merged: InspectorChangeItem[] = []

  for (const item of [...sessionItems, ...gitItems]) {
    const key = normalizeChangePath(item.filePath) || item.id
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }

  return merged
}

/**
 * Right-side change list — opens files in the workspace editor with inline diff highlights.
 */
export function ChangeInspector({
  blocks,
  className,
  onCollapse,
  onOpenFileInEditor
}: {
  blocks: ChatBlock[]
  className?: string
  onCollapse: () => void
  onOpenFileInEditor: (path: string) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const selectedId = useChatStore((s) => s.inspectorSelectedId)
  const selectInspectorItem = useChatStore((s) => s.selectInspectorItem)
  const gitCommitSelectedPaths = useChatStore((s) => s.gitCommitSelectedPaths)
  const syncGitCommitSelection = useChatStore((s) => s.syncGitCommitSelection)
  const toggleGitCommitPath = useChatStore((s) => s.toggleGitCommitPath)
  const setGitCommitSelectedPaths = useChatStore((s) => s.setGitCommitSelectedPaths)
  const { workspaceRoot, activeThreadId, threads } = useChatStore(
    useShallow((s) => ({
      workspaceRoot: s.workspaceRoot,
      activeThreadId: s.activeThreadId,
      threads: s.threads
    }))
  )
  const root = resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot)
  const { result: gitChanges, loading: gitLoading } = useGitWorkingChanges(root)
  const gitFilePaths = useMemo(
    () => (gitChanges?.ok ? gitChanges.files.map((file) => file.path) : []),
    [gitChanges]
  )

  const fileChanges = useMemo(() => {
    const sessionItems = sessionChangeItems(blocks)
    const gitItems = gitChanges?.ok ? gitChangeItems(gitChanges.files) : []
    return mergeChangeItems(sessionItems, gitItems)
  }, [blocks, gitChanges])

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

  const active =
    fileChanges.find((item) => item.id === selectedId) ?? fileChanges[fileChanges.length - 1]

  const gitStageLabel = (stage: GitWorkingChangeStage): string => {
    if (stage === 'staged') return t('gitStageStaged')
    if (stage === 'partial') return t('gitStagePartial')
    return t('gitStageUnstaged')
  }

  const openItem = (item: InspectorChangeItem): void => {
    selectInspectorItem(item.id)
    if (item.filePath) onOpenFileInEditor(item.filePath)
  }

  return (
    <aside
      className={`ds-change-inspector ds-tool-panel ds-no-drag flex flex-col ${className ?? ''}`}
    >
      <div className="flex min-h-[58px] shrink-0 items-center gap-3 border-b border-ds-border-muted px-3 py-3">
        <button
          type="button"
          onClick={onCollapse}
          className="ds-sidebar-toggle-button shrink-0"
          aria-label={t('rightPanelCollapse')}
          title={t('rightPanelCollapse')}
        >
          <PanelRightClose className="h-4 w-4" strokeWidth={1.85} />
        </button>
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
                <button
                  type="button"
                  className="shrink-0 text-ds-muted transition hover:text-ds-ink"
                  onClick={() => setGitCommitSelectedPaths([...gitFilePaths])}
                >
                  {t('gitCommitSelectAll')}
                </button>
                <span aria-hidden className="text-ds-border-strong">
                  ·
                </span>
                <button
                  type="button"
                  className="shrink-0 text-ds-muted transition hover:text-ds-ink"
                  onClick={() => setGitCommitSelectedPaths([])}
                >
                  {t('gitCommitSelectNone')}
                </button>
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
                  const isActive = active?.id === item.id
                  return (
                    <li key={item.id}>
                      <div
                        className={`flex w-full items-start gap-2.5 px-4 py-2.5 transition ${
                          isActive ? 'bg-ds-hover text-ds-ink' : 'text-ds-ink hover:bg-ds-hover/70'
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
                          onClick={() => openItem(item)}
                          className="flex min-w-0 flex-1 items-start gap-2 text-left"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-[13px] text-ds-ink">
                              {displayPath ?? t('toolActionFile')}
                            </div>
                            {stats ? (
                              <div className="mt-0.5">
                                <ChangeDiffStatsLabel stats={stats} size="sm" />
                              </div>
                            ) : null}
                          </div>
                          {item.gitStage ? (
                            <span className="shrink-0 rounded-full bg-ds-hover px-2 py-0.5 text-[11px] font-medium text-ds-muted">
                              {gitStageLabel(item.gitStage)}
                            </span>
                          ) : null}
                          {item.status === 'running' ? (
                            <span className="rounded-full bg-amber-200/40 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:bg-amber-700/30 dark:text-amber-100">
                              {t('inspectorStatusRunning')}
                            </span>
                          ) : null}
                          <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.85} />
                        </button>
                      </div>
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
