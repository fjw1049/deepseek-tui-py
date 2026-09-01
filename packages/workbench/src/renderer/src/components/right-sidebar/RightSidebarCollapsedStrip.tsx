import type { ReactElement } from 'react'
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useGitBranches } from '../../hooks/use-git-branches'
import {
  useGitBranchCompareBase,
  useGitWorkingChanges
} from '../../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../../hooks/use-workspace-dirty-git-refresh'
import {
  collectWorkspaceChangeEntries,
  sumWorkspaceChangeStats
} from '../../lib/workspace-change-stats'
import { useChatStore } from '../../store/chat-store'
import { ChangeDiffStatsLabel } from '../ChangeDiffStatsLabel'
import {
  resolveThreadFilesystemRoot,
  resolveThreadGitActionRoot
} from '../../lib/workspace-path'

type Props = {
  workspaceRoot: string
  onExpand: () => void
}

export function RightSidebarCollapsedStrip({ workspaceRoot, onExpand }: Props): ReactElement {
  const { t } = useTranslation('common')
  const workspaceDirtyTick = useChatStore((s) => s.workspaceDirtyTick)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const threads = useChatStore((s) => s.threads)
  const visibleRoot = resolveThreadFilesystemRoot(activeThreadId, threads, workspaceRoot).trim()
  const gitRoot = resolveThreadGitActionRoot(activeThreadId, threads, workspaceRoot).trim()
  const { result: gitResult, reload: reloadGitBranches } = useGitBranches(gitRoot)
  const [branchBase] = useGitBranchCompareBase(
    gitRoot,
    gitResult?.ok ? gitResult.currentBranch : null
  )
  const { result: gitChanges, reload: reloadGitChanges } = useGitWorkingChanges(
    gitRoot,
    'branch',
    branchBase
  )
  const refreshGit = useCallback((): void => {
    void reloadGitBranches()
    void reloadGitChanges()
  }, [reloadGitBranches, reloadGitChanges])
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, refreshGit)
  const changeStats = sumWorkspaceChangeStats(
    collectWorkspaceChangeEntries({
      blocks: [],
      gitFiles: gitChanges?.ok ? gitChanges.files : null
    })
  )

  return (
    <button
      type="button"
      onClick={onExpand}
      className="ds-no-drag flex h-full w-full flex-col items-center gap-3 border-l border-ds-border-muted/50 bg-ds-sidebar/70 px-1 py-3 transition hover:bg-ds-hover/30"
      title={t('rightSidebarExpand')}
    >
      <span className="[writing-mode:vertical-rl] rotate-180 text-[11px] font-medium text-ds-muted">
        {t('rightSidebarTitle')}
      </span>
      {visibleRoot ? (
        <>
          <span className="max-w-full truncate px-0.5 text-[10px] text-ds-faint [writing-mode:vertical-rl] rotate-180">
            {gitResult?.ok ? gitResult.currentBranch ?? t('gitNoBranch') : t('gitNoBranch')}
          </span>
          {changeStats ? (
            <ChangeDiffStatsLabel stats={changeStats} size="sm" className="flex-col gap-0.5" />
          ) : gitChanges?.ok && gitChanges.files.length > 0 ? (
            <span className="text-[11px] tabular-nums text-ds-muted [writing-mode:vertical-rl] rotate-180">
              {t('gitDirtyFiles', { count: gitChanges.files.length })}
            </span>
          ) : null}
        </>
      ) : null}
    </button>
  )
}
