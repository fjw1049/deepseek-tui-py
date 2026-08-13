/** Live files-changed strip above the composer while a turn is mutating files. */

import { memo, useMemo } from 'react'
import { FileEdit } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import { useGitWorkingChanges } from '../../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../../hooks/use-workspace-dirty-git-refresh'
import {
  collectWorkspaceChangeEntries,
  sumWorkspaceChangeStats
} from '../../lib/workspace-change-stats'
import { resolveActiveThreadWorkspace } from '../../lib/workspace-path'
import { useChatStore } from '../../store/chat-store'

export const ComposerLiveChangesHeader = memo(function ComposerLiveChangesHeader({
  onReview
}: {
  onReview?: () => void
}): React.JSX.Element | null {
  const { t } = useTranslation('common')
  const {
    busy,
    blocks,
    turnDiffByTurnId,
    workspaceRoot,
    activeThreadId,
    threads,
    workspaceDirtyTick
  } = useChatStore(
    useShallow((s) => ({
      busy: s.busy,
      blocks: s.blocks,
      turnDiffByTurnId: s.turnDiffByTurnId,
      workspaceRoot: s.workspaceRoot,
      activeThreadId: s.activeThreadId,
      threads: s.threads,
      workspaceDirtyTick: s.workspaceDirtyTick
    }))
  )
  const root = resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot)
  const { result: gitChanges, reload: reloadGitChanges } = useGitWorkingChanges(root)
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, reloadGitChanges)

  const entries = useMemo(
    () =>
      collectWorkspaceChangeEntries({
        blocks,
        turnDiffByTurnId,
        gitFiles: gitChanges?.ok ? gitChanges.files : null
      }),
    [blocks, gitChanges, turnDiffByTurnId]
  )
  const stats = useMemo(() => sumWorkspaceChangeStats(entries), [entries])

  if (!busy || entries.length === 0) {
    return null
  }

  const label =
    entries.length === 1
      ? t('turnChangeFilesOne', { defaultValue: '1 file changed' })
      : t('turnChangeFilesMany', {
          count: entries.length,
          defaultValue: `${entries.length} files changed`
        })

  return (
    <div className="mb-1.5 flex items-center gap-2 rounded-[12px] border border-ds-border-muted/70 bg-ds-card/70 px-3 py-2 text-[12.5px] text-ds-ink">
      <FileEdit className="h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={1.8} />
      <span className="min-w-0 flex-1 truncate font-medium">{label}</span>
      {stats && stats.added + stats.removed > 0 ? (
        <span className="shrink-0 tabular-nums">
          <span className="text-ds-diff-added">+{stats.added}</span>
          <span className="mx-1 text-ds-faint">·</span>
          <span className="text-ds-diff-removed">-{stats.removed}</span>
        </span>
      ) : null}
      {onReview ? (
        <button
          type="button"
          onClick={onReview}
          className="shrink-0 rounded-full bg-ds-hover px-2.5 py-0.5 text-[11.5px] font-semibold text-ds-ink transition hover:bg-ds-hover/80"
        >
          {t('turnMarkdownResultOpen', { defaultValue: 'Review' })}
        </button>
      ) : null}
    </div>
  )
})
