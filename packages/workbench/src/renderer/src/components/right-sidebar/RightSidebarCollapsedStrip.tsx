import type { ReactElement } from 'react'
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useGitBranches } from '../../hooks/use-git-branches'
import { useGitWorkingChanges } from '../../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../../hooks/use-workspace-dirty-git-refresh'
import { sumDiffStats } from '../../lib/diff-stats'
import { useChatStore } from '../../store/chat-store'
import { ChangeDiffStatsLabel } from '../ChangeDiffStatsLabel'

type Props = {
  workspaceRoot: string
  onExpand: () => void
}

export function RightSidebarCollapsedStrip({ workspaceRoot, onExpand }: Props): ReactElement {
  const { t } = useTranslation('common')
  const root = workspaceRoot.trim()
  const workspaceDirtyTick = useChatStore((s) => s.workspaceDirtyTick)
  const { result: gitResult, reload: reloadGitBranches } = useGitBranches(root)
  const { result: gitChanges, reload: reloadGitChanges } = useGitWorkingChanges(root)
  const refreshGit = useCallback((): void => {
    void reloadGitBranches()
    void reloadGitChanges()
  }, [reloadGitBranches, reloadGitChanges])
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, refreshGit)
  const changeStats = gitChanges?.ok
    ? sumDiffStats(gitChanges.files.map((file) => file.patch))
    : null

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
      {root ? (
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
