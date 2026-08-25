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
import type { GitWorkingChangeStage } from '@shared/git-working-changes'
import type { ChatBlock } from '../agent/types'
import { ChangeDiffStatsLabel } from './ChangeDiffStatsLabel'
import { DiffView, type DiffRenderStyle } from './DiffView'
import { EditorListSkeleton } from './workspace-editor/EditorListSkeleton'
import { useGitWorkingChanges } from '../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../hooks/use-workspace-dirty-git-refresh'
import { formatFilePathForDisplay } from '../lib/diff-stats'
import {
  collectWorkspaceChangeEntries,
  sumWorkspaceChangeStats,
  workspaceChangeEntryStats
} from '../lib/workspace-change-stats'
import { formatComposerPathMention, insertComposerSnippet } from '../lib/composer-insert'
import { splitFileNameAndParent } from '../lib/editor-breadcrumb'
import { resolveGitCommitPaths } from '../lib/git-commit-selection'
import { resolveActiveThreadWorkspace } from '../lib/workspace-path'
import { useChatStore } from '../store/chat-store'

function normalizeChangePath(path: string | undefined): string {
  return (path ?? '').replace(/\\/g, '/').trim().toLowerCase()
}

function changePathsMatch(left: string | undefined, right: string | undefined): boolean {
  const a = normalizeChangePath(left)
  const b = normalizeChangePath(right)
  if (!a || !b) return false
  if (a === b) return true
  return a.endsWith(`/${b}`) || b.endsWith(`/${a}`)
}

export function findChangeItemId(
  items: ReadonlyArray<{ id: string; filePath?: string }>,
  path: string
): string | undefined {
  const key = normalizeChangePath(path)
  if (!key) return undefined
  return items.find((item) => changePathsMatch(item.filePath, key))?.id
}


function InspectorCommitBar({
  root,
  gitFilePaths,
  onCommitted
}: {
  root: string
  gitFilePaths: string[]
  onCommitted: () => void
}): ReactElement | null {
  const { t } = useTranslation('common')
  const gitCommitSelectedPaths = useChatStore((s) => s.gitCommitSelectedPaths)
  const gitCommitSelectionKey = useChatStore((s) => s.gitCommitSelectionKey)
  const [message, setMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const selectedPaths = useMemo(
    () =>
      resolveGitCommitPaths(gitCommitSelectedPaths, gitFilePaths, gitCommitSelectionKey, root),
    [gitCommitSelectedPaths, gitFilePaths, gitCommitSelectionKey, root]
  )

  if (gitFilePaths.length === 0) return null

  const submit = async (): Promise<void> => {
    const trimmed = message.trim()
    if (!trimmed) {
      setError(t('operationDockCommitEmptyMessage'))
      return
    }
    if (selectedPaths.length === 0) {
      setError(t('operationDockCommitSelectFiles'))
      return
    }
    if (typeof window.dsGui?.commitGitChanges !== 'function') {
      setError(t('operationDockCommitUnavailable'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await window.dsGui.commitGitChanges(root, trimmed, selectedPaths)
      if (!result.ok) {
        setError(result.message)
        return
      }
      setMessage('')
      useChatStore.setState((s) => ({ workspaceDirtyTick: s.workspaceDirtyTick + 1 }))
      onCommitted()
    } catch (commitError) {
      setError(commitError instanceof Error ? commitError.message : String(commitError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="shrink-0 border-t border-[color-mix(in_srgb,var(--ds-text)_10%,transparent)] px-2 py-2">
      <textarea
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        placeholder={t('operationDockCommitMessagePlaceholder')}
        rows={2}
        className="w-full resize-none rounded-md border border-ds-border bg-ds-elevated px-2 py-1.5 text-[12px] text-ds-ink outline-none placeholder:text-ds-faint"
      />
      {error ? (
        <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-200">{error}</p>
      ) : null}
      <button
        type="button"
        disabled={busy || selectedPaths.length === 0}
        onClick={() => void submit()}
        className="mt-1.5 inline-flex h-7 w-full items-center justify-center rounded-md bg-ds-hover text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover/80 disabled:opacity-45"
      >
        {busy
          ? t('operationDockCommitSubmitting')
          : `${t('operationDockCommitSubmit')} (${selectedPaths.length})`}
      </button>
    </div>
  )
}

const FILE_LIST_DEFAULT = 280
const FILE_LIST_MIN = 180
const FILE_LIST_MAX = 480
const STACK_LIST_DEFAULT = 220
const STACK_LIST_MIN = 120
const STACK_LIST_MAX = 420

/**
 * Change review panel.
 * - `review`: wide file list | full-height compare — unused leftover layout.
 * - `stack`: file list above, compare below — chat-mode right sidebar.
 * - `list`: file list only — IDE activity sidebar.
 * - `diff`: compare only — IDE center stage.
 */
export function ChangeInspector({
  blocks,
  className,
  variant = 'stack',
  onOpenFile,
  onRevealInEditor,
  requestedPath = null,
  onRequestedPathConsumed
}: {
  blocks: ChatBlock[]
  className?: string
  variant?: 'review' | 'stack' | 'list' | 'diff'
  /** Chat / review: open the file (IDE keep-alive editor). */
  onOpenFile?: (path: string, line?: number) => void
  /** IDE list: double-click / Enter jumps to source in the Files editor. */
  onRevealInEditor?: (path: string, line?: number) => void
  /** Select this path when the list contains it (from a file_change jump). */
  requestedPath?: string | null
  onRequestedPathConsumed?: () => void
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
  const isList = variant === 'list'
  const isDiff = variant === 'diff'
  const compactList = isReview || isList
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

  const fileChanges = useMemo(
    () =>
      collectWorkspaceChangeEntries({
        blocks,
        turnDiffByTurnId,
        gitFiles: gitChanges?.ok ? gitChanges.files : null
      }),
    [blocks, gitChanges, turnDiffByTurnId]
  )

  const changeStats = useMemo(() => sumWorkspaceChangeStats(fileChanges), [fileChanges])

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
      if (requestedPath && !gitLoading) onRequestedPathConsumed?.()
      return
    }
    if (requestedPath) {
      const matchedId = findChangeItemId(fileChanges, requestedPath)
      if (matchedId) {
        selectInspectorItem(matchedId)
        onRequestedPathConsumed?.()
        return
      }
      // Git may still be loading the matching path; wait. Otherwise don't
      // pin an unmatched path forever — fall through and show the list.
      if (gitLoading) return
      onRequestedPathConsumed?.()
    }
    if (selectedId && fileChanges.some((item) => item.id === selectedId)) return
    selectInspectorItem(fileChanges[fileChanges.length - 1]?.id ?? null)
  }, [
    fileChanges,
    selectedId,
    selectInspectorItem,
    requestedPath,
    onRequestedPathConsumed,
    gitLoading
  ])

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
          const stats = workspaceChangeEntryStats(item)
          const displayPath = formatFilePathForDisplay(item.filePath, root || workspaceRoot)
          const { name, parent } = splitFileNameAndParent(displayPath ?? item.filePath ?? '')
          const commitSelected = Boolean(
            item.committable && item.filePath && gitCommitSelectedPaths.includes(item.filePath)
          )
          const isSelected = selectedId === item.id
          const rowClass = compactList
            ? `flex h-7 w-full items-center gap-1.5 px-2 transition ${
                isSelected ? 'bg-ds-hover text-ds-ink' : 'text-ds-ink hover:bg-ds-hover/70'
              }`
            : `flex w-full items-start gap-2 px-2 py-1.5 transition ${
                isSelected ? 'bg-ds-hover text-ds-ink' : 'text-ds-ink hover:bg-ds-hover/70'
              }`
          const selectRow = (): void => {
            onRequestedPathConsumed?.()
            selectInspectorItem(item.id)
            if (!isList && onOpenFile && item.filePath) onOpenFile(item.filePath, item.editLine)
          }
          const revealRow = (): void => {
            selectInspectorItem(item.id)
            if (item.filePath) onRevealInEditor?.(item.filePath, item.editLine)
          }
          return (
            <li key={item.id}>
              <div className={rowClass}>
                {item.committable && item.filePath ? (
                  <input
                    type="checkbox"
                    checked={commitSelected}
                    aria-label={t('gitCommitIncludeFile', {
                      file: displayPath ?? item.filePath
                    })}
                    className={`${compactList ? '' : 'mt-1 '}shrink-0`}
                    onClick={(event) => event.stopPropagation()}
                    onChange={() => toggleGitCommitPath(item.filePath!, gitFilePaths)}
                  />
                ) : compactList ? null : (
                  <FileEdit
                    className={`mt-0.5 h-4 w-4 shrink-0 ${
                      item.status === 'error' ? 'text-red-700' : 'text-ds-muted'
                    }`}
                    strokeWidth={1.75}
                  />
                )}
                <button
                  type="button"
                  onClick={selectRow}
                  onDoubleClick={revealRow}
                  onKeyDown={(event) => {
                    if (event.key !== 'Enter') return
                    event.preventDefault()
                    if (isList) revealRow()
                    else selectRow()
                  }}
                  title={
                    isList && item.filePath
                      ? t('inspectorOpenSourceHint')
                      : (displayPath ?? item.filePath)
                  }
                  aria-current={isSelected ? 'true' : undefined}
                  className={
                    compactList
                      ? 'flex min-w-0 flex-1 items-center gap-1.5 text-left'
                      : 'flex min-w-0 flex-1 flex-col gap-0.5 text-left'
                  }
                >
                  {compactList ? (
                    <>
                      <span className="min-w-0 flex-1 truncate text-[12.5px]">
                        <span
                          className={`font-medium ${
                            item.status === 'error' ? 'text-red-700' : 'text-ds-ink'
                          }`}
                        >
                          {name || t('toolActionFile')}
                        </span>
                        {parent ? (
                          <span className="ml-1.5 text-[11px] text-ds-faint">{parent}</span>
                        ) : null}
                      </span>
                      {item.gitStage && item.gitStage !== 'unstaged' ? (
                        <span className="shrink-0 rounded-full bg-ds-hover px-1.5 py-0.5 text-[10px] font-medium leading-none text-ds-muted">
                          {gitStageLabel(item.gitStage)}
                        </span>
                      ) : null}
                      {item.status === 'running' ? (
                        <span className="shrink-0 rounded-full bg-amber-200/40 px-1.5 py-0.5 text-[10px] font-medium leading-none text-amber-900 dark:bg-amber-700/30 dark:text-amber-100">
                          {t('inspectorStatusRunning')}
                        </span>
                      ) : null}
                      {stats ? <ChangeDiffStatsLabel stats={stats} size="sm" /> : null}
                    </>
                  ) : (
                    <>
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
                    </>
                  )}
                </button>
              </div>
            </li>
          )
        })}
      </ul>
      {isList ? (
        <InspectorCommitBar
          root={root}
          gitFilePaths={gitFilePaths}
          onCommitted={() => void reloadGitChanges()}
        />
      ) : null}
    </div>
  )

  const diffViewport = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {selectedItem ? (
        (selectedItem.detail ?? '').trim() ? (
          <DiffView
            patch={selectedItem.detail}
            filePath={selectedItem.filePath}
            maxHeight={9000}
            diffStyle={diffStyle}
            showStyleToggle
            onDiffStyleChange={setDiffStyle}
            chrome="flush"
            className="min-h-0 flex-1"
            onAddToChat={
              selectedItem.filePath
                ? () => {
                    const relative =
                      formatFilePathForDisplay(selectedItem.filePath, root || workspaceRoot) ||
                      selectedItem.filePath
                    if (relative) insertComposerSnippet(formatComposerPathMention(relative))
                  }
                : undefined
            }
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
          isList || isDiff || isReview ? (
            <EditorListSkeleton rows={isDiff ? 12 : 8} />
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 py-10 text-center text-[13px] text-ds-faint">
              {t('gitBranchLoading')}
            </div>
          )
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
        ) : isList ? (
          fileList
        ) : isDiff ? (
          diffViewport
        ) : isReview ? (
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <div className="flex h-full min-h-0 shrink-0 flex-col" style={{ width: listSize }}>
              {fileList}
            </div>
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label={t('inspectorResizeSplit')}
              className="ds-change-inspector__split-handle ds-no-drag relative z-10 w-px shrink-0 cursor-col-resize touch-none bg-[color-mix(in_srgb,var(--ds-text)_14%,transparent)] hover:bg-ds-hover"
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
              className="ds-change-inspector__split-handle ds-change-inspector__split-handle--horizontal ds-no-drag relative z-10 h-2 shrink-0 cursor-row-resize touch-none"
              onPointerDown={onListResizePointerDown}
              onPointerMove={onListResizePointerMove}
              onPointerUp={onListResizePointerUp}
              onPointerCancel={onListResizePointerUp}
            />
            {diffViewport}
          </div>
        )}
      </div>
    </aside>
  )
}
