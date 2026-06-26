import { useCallback, useMemo, useEffect, type ReactElement } from 'react'
import {
  ArrowRight,
  CheckCircle2,
  Circle,
  Code2,
  FileEdit,
  Globe2,
  Terminal
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import type { ChatBlock } from '../../agent/types'
import { ChangeDiffStatsLabel } from '../ChangeDiffStatsLabel'
import { useGitBranches } from '../../hooks/use-git-branches'
import { useGitWorkingChanges } from '../../hooks/use-git-working-changes'
import { sumDiffStats } from '../../lib/diff-stats'
import { extractTodosFromBlocks } from '../../lib/extract-todos-from-blocks'
import {
  isExplicitGitCommitSelectionNone,
  resolveGitCommitPaths
} from '../../lib/git-commit-selection'
import { resolveActiveThreadWorkspace } from '../../lib/workspace-path'
import { useChatStore } from '../../store/chat-store'
import { GitBranchPicker } from './GitBranchPicker'
import { GitCommitPopover } from './GitCommitPopover'

type Props = {
  onOpenChanges?: () => void
  onOpenEditor?: () => void
  previewActive: boolean
  terminalPanelOpen: boolean
  terminalPanelEnabled: boolean
  previewEnabled: boolean
  onTogglePreview: () => void
  onToggleTerminalPanel: () => void
}

function sessionChangePatches(blocks: ChatBlock[]): Array<string | undefined> {
  return blocks.flatMap((block) =>
    block.kind === 'tool' && block.toolKind === 'file_change' ? [block.detail] : []
  )
}

const DOCK_ROW_CLASS =
  'flex w-full items-center gap-2 rounded-lg px-1 py-1.5 text-left text-[13px] leading-5 transition'

export function OperationContextDock({
  onOpenChanges,
  onOpenEditor,
  previewActive,
  terminalPanelOpen,
  terminalPanelEnabled,
  previewEnabled,
  onTogglePreview,
  onToggleTerminalPanel
}: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const {
    workspaceRoot,
    blocks,
    activeThreadId,
    threads,
    gitCommitSelectionKey,
    gitCommitSelectedPaths,
    syncGitCommitSelection
  } = useChatStore(
    useShallow((s) => ({
      workspaceRoot: s.workspaceRoot,
      blocks: s.blocks,
      activeThreadId: s.activeThreadId,
      threads: s.threads,
      gitCommitSelectionKey: s.gitCommitSelectionKey,
      gitCommitSelectedPaths: s.gitCommitSelectedPaths,
      syncGitCommitSelection: s.syncGitCommitSelection
    }))
  )
  const root = resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot)
  const { result: gitResult, loading: gitLoading, reload: reloadGitBranches } = useGitBranches(root)
  const { result: gitChanges, loading: gitChangesLoading, reload: reloadGitChanges } = useGitWorkingChanges(root)
  const todoSnapshot = useMemo(() => extractTodosFromBlocks(blocks), [blocks])
  const todos = todoSnapshot?.items ?? []
  const openTodos = todos.filter((item) => item.status !== 'completed')
  const doneCount = todos.filter((item) => item.status === 'completed').length
  const totalCount = todos.length
  const changeStats = useMemo(() => {
    const gitPatches = gitChanges?.ok ? gitChanges.files.map((file) => file.patch) : []
    return sumDiffStats([...sessionChangePatches(blocks), ...gitPatches])
  }, [blocks, gitChanges])
  const gitDirtyCount = gitResult?.ok ? gitResult.dirtyCount : 0
  const gitReady = gitResult?.ok ?? false
  const gitFilePaths = useMemo(
    () => (gitChanges?.ok ? gitChanges.files.map((file) => file.path) : []),
    [gitChanges]
  )
  useEffect(() => {
    if (gitChanges == null || !gitChanges.ok) return
    syncGitCommitSelection(gitFilePaths)
  }, [gitChanges, gitFilePaths, syncGitCommitSelection])
  const commitFilePaths = useMemo(
    () =>
      resolveGitCommitPaths(gitCommitSelectedPaths, gitFilePaths, gitCommitSelectionKey, root),
    [gitCommitSelectedPaths, gitFilePaths, gitCommitSelectionKey, root]
  )
  const explicitSelectNone = isExplicitGitCommitSelectionNone(
    gitCommitSelectionKey,
    gitCommitSelectedPaths,
    gitFilePaths,
    root
  )
  const canCommit = gitReady && gitDirtyCount > 0 && !explicitSelectNone
  const hasGitChanges = gitDirtyCount > 0 || gitFilePaths.length > 0
  const hasChanges = changeStats !== null || hasGitChanges

  const refreshGitState = useCallback((): void => {
    void reloadGitBranches()
    void reloadGitChanges()
  }, [reloadGitBranches, reloadGitChanges])

  const openChangesPanel = (): void => {
    if (!hasChanges) return
    onOpenChanges?.()
  }

  if (!root) return null

  return (
    <div className="ds-operation-dock ds-hero-panel ds-glass ds-content-card--interactive ds-no-drag relative z-10 w-full overflow-hidden rounded-[22px] px-4 py-3.5">
      <div className="text-[14px] font-medium text-ds-ink">{t('operationDockToolsTitle')}</div>

      <button
        type="button"
        onClick={() => onOpenEditor?.()}
        className={`${DOCK_ROW_CLASS} mt-2 cursor-pointer text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink`}
      >
        <Code2 className="h-4 w-4 shrink-0" strokeWidth={1.85} />
        <span className="min-w-0 flex-1 truncate">{t('rightSidebarTabEditor')}</span>
      </button>

      <button
        type="button"
        onClick={onTogglePreview}
        disabled={!previewEnabled}
        className={`${DOCK_ROW_CLASS} mt-1 ${
          previewEnabled
            ? previewActive
              ? 'bg-ds-hover/70 text-ds-ink'
              : 'cursor-pointer text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
            : 'cursor-default text-ds-faint opacity-55'
        }`}
        aria-pressed={previewActive}
        title={previewEnabled ? t('rightPanelBrowser') : t('terminalWorkspaceRequired')}
      >
        <Globe2 className="h-4 w-4 shrink-0" strokeWidth={1.85} />
        <span className="min-w-0 flex-1 truncate">{t('rightPanelBrowser')}</span>
        {previewActive ? (
          <span className="ml-auto shrink-0 text-[12px] text-ds-faint">{t('operationDockToolOpen')}</span>
        ) : null}
      </button>

      <button
        type="button"
        onClick={onToggleTerminalPanel}
        disabled={!terminalPanelEnabled}
        className={`${DOCK_ROW_CLASS} mt-1 ${
          terminalPanelEnabled
            ? terminalPanelOpen
              ? 'bg-ds-hover/70 text-ds-ink'
              : 'cursor-pointer text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
            : 'cursor-default text-ds-faint opacity-55'
        }`}
        aria-pressed={terminalPanelOpen}
        title={terminalPanelEnabled ? t('terminalToggle') : t('terminalWorkspaceRequired')}
      >
        <Terminal className="h-4 w-4 shrink-0" strokeWidth={1.85} />
        <span className="min-w-0 flex-1 truncate">{t('terminalPanelTitle')}</span>
        {terminalPanelOpen ? (
          <span className="ml-auto shrink-0 text-[12px] text-ds-faint">{t('operationDockToolOpen')}</span>
        ) : null}
      </button>

      <div className="my-2 border-t border-ds-border-muted/55" />

      <div className="text-[14px] font-medium text-ds-ink">{t('operationDockGitTitle')}</div>

      <button
        type="button"
        onClick={openChangesPanel}
        disabled={!hasChanges}
        title={hasChanges ? t('operationDockOpenChanges') : t('operationDockNoChanges')}
        className={`${DOCK_ROW_CLASS} mt-2 ${
          hasChanges
            ? 'cursor-pointer text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
            : 'cursor-default text-ds-faint'
        }`}
      >
        <FileEdit className="h-4 w-4 shrink-0" strokeWidth={1.85} />
        <span className="min-w-0 flex-1 truncate">{t('operationDockChanges')}</span>
        {hasChanges ? (
          changeStats ? (
            <ChangeDiffStatsLabel stats={changeStats} size="md" className="ml-auto shrink-0" />
          ) : (
            <span className="ml-auto shrink-0 text-[12px] tabular-nums text-ds-muted">
              {t('gitDirtyFiles', { count: gitDirtyCount })}
            </span>
          )
        ) : (
          <span className="ml-auto shrink-0 text-[12px] text-ds-faint">{t('operationDockNoChanges')}</span>
        )}
      </button>

      {gitReady ? (
        <>
          <div className="mt-1">
            <GitBranchPicker
              key={root}
              workspaceRoot={root}
              compact
              usePortal
              menuPlacement="below"
            />
          </div>
          <GitCommitPopover
            workspaceRoot={root}
            currentBranch={gitResult?.ok ? gitResult.currentBranch : null}
            gitFiles={gitChanges?.ok ? gitChanges.files : []}
            gitFilesLoading={gitChangesLoading}
            gitDirtyCount={gitDirtyCount}
            enabled={canCommit}
            rowClassName={DOCK_ROW_CLASS}
            onOpenChanges={hasChanges ? openChangesPanel : undefined}
            onRefreshGit={refreshGitState}
            onCommitted={refreshGitState}
          />
          {hasChanges && !hasGitChanges ? (
            <p className="mt-1 px-1 text-[12px] leading-5 text-ds-faint">
              {t('operationDockCommitSessionOnly')}
            </p>
          ) : null}
        </>
      ) : gitLoading && !gitResult ? (
        <p className="mt-2 text-[13px] leading-5 text-ds-faint">{t('gitBranchLoading')}</p>
      ) : (
        <p className="mt-2 text-[13px] leading-5 text-ds-faint">{t('gitNoBranch')}</p>
      )}

      <div className="my-2 border-t border-ds-border-muted/55" />

      <div className="flex items-center gap-2">
        <span className="text-[14px] font-medium text-ds-ink">{t('contextRailProcess')}</span>
        <span className="text-[12px] tabular-nums text-ds-faint">
          {doneCount}/{totalCount}
        </span>
      </div>

      {totalCount > 0 ? (
        <ul className="mt-1.5 max-h-[min(36vh,240px)] space-y-1 overflow-y-auto">
          {openTodos.slice(0, 8).map((item) => (
            <li key={`${item.id}-${item.content}`} className="flex items-start gap-2 py-0.5">
              <span className="mt-0.5 shrink-0" aria-hidden>
                {item.status === 'in_progress' ? (
                  <ArrowRight className="h-4 w-4 text-accent" strokeWidth={1.85} />
                ) : (
                  <Circle className="h-4 w-4 text-ds-faint" strokeWidth={1.85} />
                )}
              </span>
              <span className="min-w-0 text-[13px] leading-5 text-ds-muted">{item.content}</span>
            </li>
          ))}
          {openTodos.length === 0 ? (
            <li className="flex items-start gap-2 py-0.5 text-[13px] text-ds-faint">
              <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600/85" strokeWidth={1.85} />
              <span>{t('todoInlineDone', { count: doneCount })}</span>
            </li>
          ) : null}
        </ul>
      ) : (
        <p className="mt-1.5 text-[13px] leading-5 text-ds-faint">{t('contextRailEmptyProcess')}</p>
      )}
    </div>
  )
}
