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
import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Download,
  FileEdit,
  GitCommitHorizontal,
  GitCompareArrows,
  GitPullRequest,
  Loader2,
  Minus,
  Plus,
  Search,
  Sparkles,
  TriangleAlert,
  Upload,
  X
} from 'lucide-react'
import { FileTypeIcon } from './chat/FileChip'
import type {
  GitChangeScope,
  GitWorkingChangeFile,
  GitWorkingChangeStage
} from '@shared/git-working-changes'
import type { GitRemoteRepository } from '@shared/github-repository'
import { ChangeDiffStatsLabel } from './ChangeDiffStatsLabel'
import { DiffView, type DiffRenderStyle } from './DiffView'
import { EditorListSkeleton } from './workspace-editor/EditorListSkeleton'
import {
  useGitBranchCompareBase,
  useGitWorkingChanges
} from '../hooks/use-git-working-changes'
import { useGitBranches } from '../hooks/use-git-branches'
import { useGitHubRepository } from '../hooks/use-github-repository'
import { useWorkspaceDirtyGitRefresh } from '../hooks/use-workspace-dirty-git-refresh'
import { formatFilePathForDisplay } from '../lib/diff-stats'
import {
  collectWorkspaceChangeEntries,
  sumWorkspaceChangeStats,
  workspaceChangeEntryStats,
  type WorkspaceChangeEntry
} from '../lib/workspace-change-stats'
import { formatComposerPathMention, insertComposerSnippet } from '../lib/composer-insert'
import { splitFileNameAndParent } from '../lib/editor-breadcrumb'
import {
  resolveThreadFilesystemRoot,
  resolveThreadGitActionRoot,
  resolveThreadTaskReviewRoot
} from '../lib/workspace-path'
import {
  buildBranchComparisonOptions,
  type ChangeReviewContext
} from '../lib/change-review'
import { resolveInspectorSelectionUpdate } from '../lib/change-inspector-selection'
import { toolBlocksFromTurnSummary, turnSummaryFromSources } from '../lib/turn-mutation-view'
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


function InspectorGitActions({
  root,
  stagedFiles,
  unstagedFiles,
  branch,
  upstream,
  ahead,
  behind,
  hasRemote,
  remoteRepository,
  onChanged
}: {
  root: string
  stagedFiles: GitWorkingChangeFile[]
  unstagedFiles: GitWorkingChangeFile[]
  branch: string | null
  upstream: string | null
  ahead: number
  behind: number
  hasRemote: boolean
  remoteRepository: GitRemoteRepository | null
  onChanged: () => Promise<void>
}): ReactElement {
  const { t } = useTranslation('common')
  const [message, setMessage] = useState('')
  const [feedback, setFeedback] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [commitOpen, setCommitOpen] = useState(false)
  const [commitPushPreferred, setCommitPushPreferred] = useState(false)
  const popoverRef = useRef<HTMLDivElement | null>(null)
  const [busyAction, setBusyAction] = useState<
    'stage' | 'unstage' | 'suggest' | 'commit' | 'pull' | 'push' | null
  >(null)
  const stagedPaths = useMemo(() => [...new Set(stagedFiles.map((file) => file.path))], [stagedFiles])
  const unstagedPaths = useMemo(
    () => [...new Set(unstagedFiles.map((file) => file.path))],
    [unstagedFiles]
  )
  const hasLocalChanges = stagedPaths.length > 0 || unstagedPaths.length > 0

  useEffect(() => {
    if (!menuOpen && !commitOpen) return
    const close = (event: MouseEvent): void => {
      if (popoverRef.current?.contains(event.target as Node)) return
      setMenuOpen(false)
      setCommitOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      setMenuOpen(false)
      setCommitOpen(false)
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [commitOpen, menuOpen])

  useEffect(() => {
    if (feedback?.kind !== 'success') return
    const timer = window.setTimeout(() => setFeedback(null), 3_500)
    return () => window.clearTimeout(timer)
  }, [feedback])

  const refresh = async (): Promise<void> => {
    useChatStore.setState((s) => ({ workspaceDirtyTick: s.workspaceDirtyTick + 1 }))
    await onChanged()
  }

  const runPathAction = async (
    action: 'stage' | 'unstage',
    paths: string[]
  ): Promise<void> => {
    if (paths.length === 0) return
    const method = action === 'stage' ? window.dsGui?.stageGitChanges : window.dsGui?.unstageGitChanges
    if (typeof method !== 'function') {
      setFeedback({ kind: 'error', text: t('gitActionUnavailable') })
      return
    }
    setMenuOpen(false)
    setBusyAction(action)
    setFeedback(null)
    try {
      const result = await method(root, paths)
      if (!result.ok) {
        setFeedback({ kind: 'error', text: result.message })
        return
      }
      setFeedback({
        kind: 'success',
        text: action === 'stage' ? t('gitStageSuccess') : t('gitUnstageSuccess')
      })
      await refresh()
    } catch (error) {
      setFeedback({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusyAction(null)
    }
  }

  const suggest = async (): Promise<void> => {
    if (stagedPaths.length === 0 || typeof window.dsGui?.suggestGitCommitMessage !== 'function') return
    setBusyAction('suggest')
    setFeedback(null)
    try {
      const result = await window.dsGui.suggestGitCommitMessage(root, stagedPaths)
      if (result.ok) setMessage(result.message)
      else setFeedback({ kind: 'error', text: result.message })
    } catch (error) {
      setFeedback({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusyAction(null)
    }
  }

  const push = async (): Promise<boolean> => {
    if (typeof window.dsGui?.pushGitBranch !== 'function') {
      setFeedback({ kind: 'error', text: t('gitActionUnavailable') })
      return false
    }
    setBusyAction('push')
    setMenuOpen(false)
    setFeedback(null)
    try {
      const result = await window.dsGui.pushGitBranch(root)
      if (!result.ok) {
        setFeedback({ kind: 'error', text: result.message })
        return false
      }
      setFeedback({
        kind: 'success',
        text: result.pushed ? t('gitPushSuccess', { branch: result.branch }) : t('gitPushUpToDate')
      })
      await refresh()
      return true
    } catch (error) {
      setFeedback({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
      return false
    } finally {
      setBusyAction(null)
    }
  }

  const pull = async (): Promise<void> => {
    if (typeof window.dsGui?.pullGitBranch !== 'function') {
      setFeedback({ kind: 'error', text: t('gitActionUnavailable') })
      return
    }
    setBusyAction('pull')
    setMenuOpen(false)
    setFeedback(null)
    try {
      const result = await window.dsGui.pullGitBranch(root)
      if (!result.ok) {
        setFeedback({ kind: 'error', text: result.message })
        return
      }
      setFeedback({
        kind: 'success',
        text: result.updated ? t('gitPullSuccess') : t('gitPullUpToDate')
      })
      await refresh()
    } catch (error) {
      setFeedback({ kind: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusyAction(null)
    }
  }

  const submit = async (pushAfterCommit: boolean): Promise<void> => {
    const trimmed = message.trim()
    if (!trimmed) {
      setFeedback({ kind: 'error', text: t('operationDockCommitEmptyMessage') })
      return
    }
    if (stagedPaths.length === 0) {
      setFeedback({ kind: 'error', text: t('gitCommitNeedsStaged') })
      return
    }
    if (typeof window.dsGui?.commitGitChanges !== 'function') {
      setFeedback({ kind: 'error', text: t('operationDockCommitUnavailable') })
      return
    }
    setBusyAction('commit')
    setFeedback(null)
    try {
      const result = await window.dsGui.commitGitChanges(root, trimmed)
      if (!result.ok) {
        setFeedback({ kind: 'error', text: result.message })
        return
      }
      setMessage('')
      setCommitOpen(false)
      setFeedback({
        kind: 'success',
        text: t('gitCommitLocalSuccess', { hash: result.commitHash })
      })
      await refresh()
      if (pushAfterCommit) await push()
    } catch (commitError) {
      setFeedback({ kind: 'error', text: commitError instanceof Error ? commitError.message : String(commitError) })
    } finally {
      setBusyAction(null)
    }
  }

  const createPullRequest = async (): Promise<void> => {
    if (!remoteRepository || !branch || typeof window.dsGui?.openExternal !== 'function') return
    setMenuOpen(false)
    const encodedBranch = encodeURIComponent(branch)
    const url =
      remoteRepository.provider === 'github'
        ? `${remoteRepository.url}/compare/${encodedBranch}?expand=1`
        : remoteRepository.provider === 'gitlab'
          ? `${remoteRepository.url}/-/merge_requests/new?merge_request[source_branch]=${encodedBranch}`
          : remoteRepository.url
    await window.dsGui.openExternal(url)
  }

  const supportsPullRequest =
    remoteRepository?.provider === 'github' || remoteRepository?.provider === 'gitlab'
  const featureBranch = Boolean(branch && !['main', 'master'].includes(branch))
  const openCommit = (pushAfterCommit = false): void => {
    setMenuOpen(false)
    setCommitOpen(true)
    setCommitPushPreferred(pushAfterCommit)
    setFeedback(null)
  }
  const primaryAction:
    | 'commit'
    | 'pull'
    | 'publish'
    | 'push'
    | 'pull-request'
    | 'menu' =
    stagedPaths.length > 0
      ? 'commit'
      : behind > 0 && ahead === 0
        ? 'pull'
        : !upstream && hasRemote && branch
          ? 'publish'
          : ahead > 0 && behind === 0
            ? 'push'
            : supportsPullRequest && featureBranch && upstream
              ? 'pull-request'
              : 'menu'
  const primaryDisabled =
    busyAction !== null ||
    ((primaryAction === 'pull' || primaryAction === 'publish') && hasLocalChanges)
  const primaryLabel = (() => {
    if (primaryAction === 'commit') return t('gitCommitStagedCount', { count: stagedPaths.length })
    if (primaryAction === 'pull') return t('gitPullCommits', { count: behind })
    if (primaryAction === 'publish') return t('gitPublishBranch')
    if (primaryAction === 'push') return t('gitPushCommits', { count: ahead })
    if (primaryAction === 'pull-request') {
      return remoteRepository?.provider === 'gitlab'
        ? t('gitCreateMergeRequest')
        : t('gitCreatePullRequest')
    }
    if (behind > 0 && ahead > 0) return t('gitBranchDiverged')
    return t('gitActionsMenu')
  })()
  const primaryIcon = (() => {
    if (busyAction !== null) return <Loader2 className="h-4 w-4 animate-spin" />
    if (primaryAction === 'commit') return <GitCommitHorizontal className="h-4 w-4" />
    if (primaryAction === 'pull') return <Download className="h-4 w-4" />
    if (primaryAction === 'publish' || primaryAction === 'push') return <Upload className="h-4 w-4" />
    if (primaryAction === 'pull-request') return <GitPullRequest className="h-4 w-4" />
    if (behind > 0 && ahead > 0) return <TriangleAlert className="h-4 w-4 text-amber-600" />
    return <CheckCircle2 className="h-4 w-4" />
  })()
  const runPrimaryAction = (): void => {
    if (primaryAction === 'commit') openCommit(false)
    else if (primaryAction === 'pull') void pull()
    else if (primaryAction === 'publish' || primaryAction === 'push') void push()
    else if (primaryAction === 'pull-request') void createPullRequest()
    else setMenuOpen((open) => !open)
  }
  const menuItemClass =
    'flex min-h-8 w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover active:scale-[0.99] disabled:pointer-events-none disabled:opacity-35'

  return (
    <div ref={popoverRef} className="relative ml-auto flex shrink-0 items-center">
      <div className="inline-flex h-8 overflow-hidden rounded-lg border border-ds-border bg-ds-elevated shadow-sm">
        <button
          type="button"
          disabled={primaryDisabled}
          onClick={runPrimaryAction}
          title={
            primaryDisabled && hasLocalChanges
              ? primaryAction === 'publish'
                ? t('gitPublishNeedsClean')
                : t('gitPullNeedsClean')
              : primaryLabel
          }
          aria-label={primaryLabel}
          className="inline-flex w-10 items-center justify-center text-ds-ink transition hover:bg-ds-hover active:scale-[0.96] disabled:opacity-40"
        >
          {primaryIcon}
        </button>
        <span className="w-px bg-ds-border" aria-hidden />
        <button
          type="button"
          disabled={busyAction !== null}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => {
            setCommitOpen(false)
            setMenuOpen((open) => !open)
          }}
          title={t('gitActionsMenu')}
          aria-label={t('gitActionsMenu')}
          className="inline-flex w-8 items-center justify-center text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.96] disabled:opacity-40"
        >
          <ChevronDown className={`h-3.5 w-3.5 transition-transform ${menuOpen ? 'rotate-180' : ''}`} />
        </button>
      </div>

      {menuOpen ? (
        <div
          role="menu"
          aria-label={t('gitActionsMenu')}
          className="absolute right-0 top-[calc(100%+6px)] z-[70] w-56 rounded-xl border border-ds-border bg-ds-elevated p-1.5 shadow-xl"
        >
          {unstagedPaths.length > 0 ? (
            <button type="button" role="menuitem" className={menuItemClass} onClick={() => void runPathAction('stage', unstagedPaths)}>
              <Plus className="h-3.5 w-3.5" />
              <span>{t('gitStageAll')}</span>
            </button>
          ) : null}
          {stagedPaths.length > 0 ? (
            <button type="button" role="menuitem" className={menuItemClass} onClick={() => void runPathAction('unstage', stagedPaths)}>
              <Minus className="h-3.5 w-3.5" />
              <span>{t('gitUnstageAll')}</span>
            </button>
          ) : null}
          {hasLocalChanges ? <div className="my-1 h-px bg-ds-border-muted" /> : null}
          <button type="button" role="menuitem" disabled={stagedPaths.length === 0} className={menuItemClass} onClick={() => openCommit(false)}>
            <GitCommitHorizontal className="h-3.5 w-3.5" />
            <span>{t('gitCommitLocal')}</span>
          </button>
          <button type="button" role="menuitem" disabled={stagedPaths.length === 0 || !hasRemote || behind > 0} className={menuItemClass} onClick={() => openCommit(true)}>
            <Upload className="h-3.5 w-3.5" />
            <span>{t('gitCommitAndPush')}</span>
          </button>
          {upstream ? (
            <button type="button" role="menuitem" disabled={ahead > 0 || hasLocalChanges} className={menuItemClass} onClick={() => void pull()}>
              <Download className="h-3.5 w-3.5" />
              <span>{behind > 0 ? t('gitPullCommits', { count: behind }) : t('gitPullCheck')}</span>
            </button>
          ) : null}
          {hasRemote ? (
            <button
              type="button"
              role="menuitem"
              disabled={behind > 0 || (!upstream && hasLocalChanges) || (Boolean(upstream) && ahead === 0)}
              className={menuItemClass}
              onClick={() => void push()}
            >
              <Upload className="h-3.5 w-3.5" />
              <span>{upstream ? t('gitPushCommits', { count: ahead }) : t('gitPublishBranch')}</span>
            </button>
          ) : null}
          {supportsPullRequest && featureBranch ? (
            <button type="button" role="menuitem" disabled={!upstream || ahead > 0 || behind > 0} className={menuItemClass} onClick={() => void createPullRequest()}>
              <GitPullRequest className="h-3.5 w-3.5" />
              <span>{remoteRepository?.provider === 'gitlab' ? t('gitCreateMergeRequest') : t('gitCreatePullRequest')}</span>
            </button>
          ) : null}
          {behind > 0 && ahead > 0 ? (
            <p className="mt-1 flex items-start gap-1.5 rounded-lg bg-amber-500/10 px-2 py-1.5 text-[11px] leading-4 text-amber-700 dark:text-amber-200">
              <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" />
              <span>{t('gitBranchDiverged')}</span>
            </p>
          ) : null}
        </div>
      ) : null}

      {commitOpen ? (
        <div className="absolute right-0 top-[calc(100%+6px)] z-[70] w-[min(320px,calc(100vw-24px))] rounded-xl border border-ds-border bg-ds-elevated p-3 shadow-xl">
          <div className="mb-2 flex items-center gap-2">
            <GitCommitHorizontal className="h-4 w-4 text-ds-muted" />
            <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-ds-ink">
              {t('gitCommitStagedCount', { count: stagedPaths.length })}
            </span>
            <button type="button" onClick={() => setCommitOpen(false)} aria-label={t('close')} className="rounded-md p-1 text-ds-faint hover:bg-ds-hover hover:text-ds-ink">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="relative">
            <textarea
              autoFocus
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={t('operationDockCommitMessagePlaceholder')}
              rows={3}
              className="w-full resize-none rounded-lg border border-ds-border bg-ds-card px-2.5 py-2 pr-9 text-[12px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-ds-border-strong"
            />
            <button type="button" disabled={busyAction !== null} onClick={() => void suggest()} title={t('operationDockCommitGenerate')} aria-label={t('operationDockCommitGenerate')} className="absolute right-1.5 top-1.5 rounded-md p-1.5 text-ds-faint hover:bg-ds-hover hover:text-ds-ink disabled:opacity-40">
              {busyAction === 'suggest' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            </button>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            <button type="button" disabled={busyAction !== null || !message.trim()} onClick={() => void submit(false)} className={`inline-flex h-8 items-center justify-center rounded-lg text-[11.5px] font-medium active:scale-[0.98] disabled:opacity-40 ${commitPushPreferred ? 'bg-ds-hover text-ds-ink' : 'bg-accent text-white'}`}>
              {t('gitCommitLocal')}
            </button>
            <button type="button" disabled={busyAction !== null || !message.trim() || !hasRemote || behind > 0} onClick={() => void submit(true)} className={`inline-flex h-8 items-center justify-center gap-1 rounded-lg px-2 text-[11.5px] font-medium active:scale-[0.98] disabled:opacity-40 ${commitPushPreferred ? 'bg-accent text-white' : 'bg-ds-hover text-ds-ink'}`}>
              <Upload className="h-3.5 w-3.5" />
              {t('gitCommitAndPush')}
            </button>
          </div>
        </div>
      ) : null}

      {feedback ? (
        <div role="status" className={`absolute right-0 top-[calc(100%+6px)] z-[80] flex w-max max-w-72 items-start gap-1.5 rounded-lg border border-ds-border bg-ds-elevated px-2.5 py-2 text-[11px] leading-4 shadow-lg ${feedback.kind === 'success' ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-200'}`}>
          {feedback.kind === 'success' ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" /> : <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" />}
          <span>{feedback.text}</span>
        </div>
      ) : null}
    </div>
  )
}

const GIT_REVIEW_CONTEXTS: ChangeReviewContext[] = [
  'working-tree',
  'staged',
  'unstaged',
  'branch'
]

function isGitReviewContext(context: ChangeReviewContext): boolean {
  return GIT_REVIEW_CONTEXTS.includes(context)
}

function gitScopeForContext(context: ChangeReviewContext): GitChangeScope {
  return isGitReviewContext(context) ? (context as GitChangeScope) : 'working-tree'
}

function ChangeSourcePicker({
  context,
  conflictCount,
  branchBase,
  hint,
  onChange
}: {
  context: ChangeReviewContext
  conflictCount: number
  branchBase?: string
  hint?: string
  onChange: (context: ChangeReviewContext) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent): void => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const items: Array<{
    group: 'git' | 'agent' | 'issue'
    value: ChangeReviewContext
    label: string
    hint?: string
  }> = [
    { group: 'git', value: 'working-tree', label: t('changeContextWorkingTree') },
    { group: 'git', value: 'staged', label: t('changeContextStaged') },
    { group: 'git', value: 'unstaged', label: t('changeContextUnstaged') },
    {
      group: 'git',
      value: 'branch',
      label: t('changeContextBranch'),
      hint: branchBase
    },
    { group: 'agent', value: 'all-turns', label: t('changeContextAllTurns') },
    { group: 'agent', value: 'last-turn', label: t('changeContextLastTurn') },
    ...(conflictCount > 0
      ? [{
          group: 'issue' as const,
          value: 'conflicts' as const,
          label: t('changeContextConflicts', { count: conflictCount })
        }]
      : [])
  ]
  const selected = items.find((item) => item.value === context) ?? items[0]!

  const groupLabel = (group: 'git' | 'agent' | 'issue'): string => {
    if (group === 'git') return t('changeSourceGitGroup')
    if (group === 'agent') return t('changeSourceAgentGroup')
    return t('changeSourceNeedsAttentionGroup')
  }

  return (
    <div ref={menuRef} className="ds-change-source relative min-w-0">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        title={hint}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-8 min-w-0 max-w-full items-center gap-1.5 rounded-lg px-2 text-left text-[12.5px] font-semibold text-ds-ink transition hover:bg-ds-hover active:scale-[0.98]"
      >
        {context === 'conflicts' ? (
          <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-amber-600" strokeWidth={1.9} />
        ) : isGitReviewContext(context) ? (
          <GitCompareArrows className="h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={1.9} />
        ) : null}
        <span className="min-w-0 flex-1 truncate">{selected.label}</span>
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-ds-faint transition-transform ${open ? 'rotate-180' : ''}`}
          strokeWidth={1.9}
        />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={t('changeSourceMenuLabel')}
          className="ds-change-source__menu absolute left-0 top-[calc(100%+6px)] z-50 w-[min(272px,calc(100vw-32px))] overflow-hidden rounded-xl border border-ds-border bg-ds-elevated p-1.5 shadow-xl"
        >
          {(['git', 'agent', 'issue'] as const).map((group) => {
            const groupItems = items.filter((item) => item.group === group)
            if (groupItems.length === 0) return null
            return (
              <div key={group} className="ds-change-source__group">
                <div className="px-2 pb-1 pt-1.5 text-[10.5px] font-medium text-ds-faint">
                  {groupLabel(group)}
                </div>
                {groupItems.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={context === item.value}
                    onClick={() => {
                      onChange(item.value)
                      setOpen(false)
                    }}
                    className="flex min-h-8 w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover active:scale-[0.99]"
                  >
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                      {context === item.value ? <Check className="h-3.5 w-3.5" strokeWidth={2.2} /> : null}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.hint ? (
                      <span className="max-w-24 shrink-0 truncate text-[10.5px] text-ds-faint">
                        {item.hint}
                      </span>
                    ) : null}
                  </button>
                ))}
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

function BranchComparisonPicker({
  currentBranch,
  branches,
  defaultBranch,
  dirtyCount,
  selectedBase,
  loading,
  onChange
}: {
  currentBranch: string | null
  branches: Array<{ name: string }>
  defaultBranch: string | null
  dirtyCount: number
  selectedBase?: string
  loading: boolean
  onChange: (baseRef: string) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const menuRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent): void => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', onKeyDown)
    window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const options = buildBranchComparisonOptions({
    currentBranch,
    defaultBranch,
    branches: branches.map((branch) => branch.name)
  })
  const filteredBranches = query.trim()
    ? options.searchable.filter((branch) =>
        branch.toLowerCase().includes(query.trim().toLowerCase())
      )
    : []

  const option = (branch: string): ReactElement => (
    <button
      key={branch}
      type="button"
      role="option"
      aria-selected={selectedBase === branch}
      onClick={() => {
        onChange(branch)
        setOpen(false)
        setQuery('')
      }}
      className="flex min-h-8 w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover active:scale-[0.99]"
    >
      <span className="flex h-4 w-4 shrink-0 items-center justify-center">
        {selectedBase === branch ? <Check className="h-3.5 w-3.5" strokeWidth={2.2} /> : null}
      </span>
      <span className="min-w-0 flex-1 truncate">{branch}</span>
    </button>
  )

  const currentLabel = currentBranch ?? 'HEAD'
  const baseLabel = selectedBase ?? (loading ? t('gitBranchLoading') : t('gitNoBranch'))
  const workspaceTitle = t('changeBranchWorkspaceTitle', {
    branch: currentLabel,
    count: dirtyCount
  })
  return (
    <div ref={menuRef} className="relative flex min-w-0 items-center gap-2 px-2 text-[12.5px]">
      <button
        type="button"
        disabled={loading && !selectedBase}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t('changeBranchBaseTitle', { branch: baseLabel })}
        title={t('changeBranchBaseTitle', { branch: baseLabel })}
        onClick={() => setOpen((value) => !value)}
        className="flex h-7 min-w-0 max-w-[42%] items-center gap-1 rounded-md px-1.5 font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.98] disabled:opacity-45"
      >
        <span className="truncate">{baseLabel}</span>
        {loading ? (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-ds-faint" />
        ) : (
          <ChevronDown
            className={`h-3 w-3 shrink-0 text-ds-faint transition-transform ${open ? 'rotate-180' : ''}`}
            strokeWidth={2}
          />
        )}
      </button>
      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
      <span
        className="flex min-w-0 max-w-[50%] items-center gap-1 font-medium text-ds-muted"
        title={workspaceTitle}
      >
        <span className="truncate">
          {t('changeBranchWorkspaceLabel')} · {currentLabel}
        </span>
        {dirtyCount > 0 ? (
          <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-ds-hover px-1 text-[10px] tabular-nums text-ds-faint">
            {dirtyCount}
          </span>
        ) : null}
      </span>

      {open ? (
        <div
          role="dialog"
          aria-label={t('changeBranchBaseMenuLabel')}
          className="absolute left-0 top-[calc(100%+6px)] z-[80] w-[min(300px,calc(100vw-32px))] overflow-hidden rounded-xl border border-ds-border bg-ds-elevated shadow-xl"
        >
          <div className="border-b border-ds-border-muted p-2">
            <label className="flex h-8 items-center gap-2 rounded-lg bg-ds-hover/60 px-2">
              <Search className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.9} />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t('gitSearchBranches')}
                className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ds-ink outline-none placeholder:text-ds-faint"
              />
            </label>
          </div>
          <div className="max-h-72 overflow-y-auto p-1.5" role="listbox">
            {query.trim() ? (
              filteredBranches.length > 0 ? (
                filteredBranches.map(option)
              ) : (
                <div className="px-2 py-3 text-[12px] text-ds-faint">{t('gitNoBranches')}</div>
              )
            ) : (
              <>
                {options.current ? (
                  <div>
                    <div className="px-2 pb-1 pt-1 text-[10.5px] font-medium text-ds-faint">
                      {t('changeBranchCurrentGroup')}
                    </div>
                    {option(options.current)}
                  </div>
                ) : null}
                {options.default ? (
                  <div>
                    <div className="px-2 pb-1 pt-1 text-[10.5px] font-medium text-ds-faint">
                      {t('changeBranchDefaultGroup')}
                    </div>
                    {option(options.default)}
                  </div>
                ) : null}
                {options.recent.length > 0 ? (
                  <div className="mt-1 border-t border-ds-border-muted pt-1">
                    <div className="px-2 pb-1 pt-1 text-[10.5px] font-medium text-ds-faint">
                      {t('changeBranchRecentGroup')}
                    </div>
                    {options.recent.map(option)}
                  </div>
                ) : null}
                {!options.current && !options.default && options.recent.length === 0 ? (
                  <div className="px-2 py-3 text-[12px] text-ds-faint">{t('gitNoBranches')}</div>
                ) : null}
              </>
            )}
          </div>
        </div>
      ) : null}
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
  className,
  variant = 'stack',
  onOpenFile,
  onRevealInEditor,
  onSelectFile,
  onCollapse,
  context = 'branch',
  turnId = null,
  projectRootOverride = null,
  onContextChange,
  requestedPath = null,
  onRequestedPathConsumed
}: {
  className?: string
  variant?: 'review' | 'stack' | 'list' | 'diff'
  /** Chat / review: open the file (IDE keep-alive editor). */
  onOpenFile?: (path: string, line?: number) => void
  /** IDE list: double-click / Enter jumps to source in the Files editor. */
  onRevealInEditor?: (path: string, line?: number) => void
  /** IDE list: a single click selects the file and opens its diff. */
  onSelectFile?: (path: string, line?: number) => void
  /** IDE diff: collapse the center diff while preserving the change list. */
  onCollapse?: () => void
  context?: ChangeReviewContext
  turnId?: string | null
  projectRootOverride?: string | null
  onContextChange?: (context: ChangeReviewContext) => void
  /** Select this path when the list contains it (from a file_change jump). */
  requestedPath?: string | null
  onRequestedPathConsumed?: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const selectedId = useChatStore((s) => s.inspectorSelectedId)
  const selectInspectorItem = useChatStore((s) => s.selectInspectorItem)
  const {
    workspaceRoot,
    activeThreadId,
    threads,
    workspaceDirtyTick,
    turnDiffByTurnId,
    currentTurnId,
    lastCompletedTurnId
  } =
    useChatStore(
      useShallow((s) => ({
        workspaceRoot: s.workspaceRoot,
        activeThreadId: s.activeThreadId,
        threads: s.threads,
        workspaceDirtyTick: s.workspaceDirtyTick,
        turnDiffByTurnId: s.turnDiffByTurnId,
        currentTurnId: s.currentTurnId,
        lastCompletedTurnId: s.lastCompletedTurnId
      }))
  )
  const activeThread = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId)
    : undefined
  const resolvedProjectRoot = resolveThreadFilesystemRoot(
    activeThreadId,
    threads,
    workspaceRoot
  ).trim()
  const threadProjectRoot = resolvedProjectRoot || workspaceRoot.trim()
  const projectRoot = projectRootOverride?.trim() || threadProjectRoot
  const isGitContext = isGitReviewContext(context)
  const gitActionRoot =
    projectRootOverride?.trim() ||
    resolveThreadGitActionRoot(activeThreadId, threads, workspaceRoot).trim() ||
    projectRoot
  const taskReviewRoot = resolveThreadTaskReviewRoot(
    activeThreadId,
    threads,
    workspaceRoot
  ).trim()
  const changeRoot = isGitContext
    ? gitActionRoot
    : context === 'conflicts'
      ? taskReviewRoot || projectRoot
      : projectRoot
  const isMutableGitContext =
    context === 'working-tree' || context === 'staged' || context === 'unstaged'
  const gitScope = gitScopeForContext(context)
  const needsProjectGit = isGitContext || context === 'conflicts'
  const {
    result: workingTreeChanges,
    loading: workingTreeLoading,
    reload: reloadWorkingTreeChanges
  } = useGitWorkingChanges(needsProjectGit ? changeRoot : '', 'working-tree')
  const { result: gitBranches, reload: reloadGitBranches } = useGitBranches(
    needsProjectGit ? changeRoot : ''
  )
  const [branchBase, setBranchBase] = useGitBranchCompareBase(
    changeRoot,
    gitBranches?.ok ? gitBranches.currentBranch : null
  )
  const {
    result: scopedChanges,
    loading: scopedLoading,
    reload: reloadScopedChanges
  } = useGitWorkingChanges(
    isGitContext && gitScope !== 'working-tree' ? changeRoot : '',
    gitScope,
    context === 'branch' ? branchBase : undefined
  )
  const gitChanges = gitScope === 'working-tree' ? workingTreeChanges : scopedChanges
  const canMutateGit = Boolean(gitBranches?.ok && !gitBranches.detached)
  const gitLoading =
    workingTreeLoading || (isGitContext && gitScope !== 'working-tree' && scopedLoading)
  const { result: remoteRepositoryResult } = useGitHubRepository(
    isGitContext ? changeRoot : ''
  )

  useEffect(() => {
    if (!branchBase || !gitBranches?.ok) return
    const valid =
      branchBase === gitBranches.defaultBranch ||
      gitBranches.branches.some((branch) => branch.name === branchBase)
    if (!valid) setBranchBase()
  }, [branchBase, gitBranches, setBranchBase])
  const refreshGit = useCallback(async (): Promise<void> => {
    await Promise.all([
      reloadWorkingTreeChanges(),
      reloadScopedChanges(),
      reloadGitBranches()
    ])
  }, [reloadGitBranches, reloadScopedChanges, reloadWorkingTreeChanges])
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, refreshGit)

  const reviewTurnId = turnId || currentTurnId || lastCompletedTurnId
  const turnBlocks = useMemo(() => {
    if (context !== 'last-turn' || !reviewTurnId) return []
    const summary = turnSummaryFromSources(turnDiffByTurnId[reviewTurnId], [])
    return toolBlocksFromTurnSummary(reviewTurnId, summary)
  }, [context, reviewTurnId, turnDiffByTurnId])
  const sourceBlocks = useMemo(
    () => (context === 'last-turn' ? turnBlocks : []),
    [context, turnBlocks]
  )
  const sourceTurnDiffs = useMemo(
    () => {
      if (context === 'all-turns') return turnDiffByTurnId
      return context === 'last-turn' && reviewTurnId && turnDiffByTurnId[reviewTurnId]
        ? { [reviewTurnId]: turnDiffByTurnId[reviewTurnId] }
        : {}
    },
    [context, reviewTurnId, turnDiffByTurnId]
  )
  const scopedGitFiles = useMemo(
    () => {
      if (isGitContext) {
        if (!gitChanges?.ok) return null
        if (context === 'working-tree') {
          const staged = gitChanges.stagedFiles
          const unstaged = gitChanges.unstagedFiles
          if (staged && unstaged) return [...staged, ...unstaged]
        }
        return gitChanges.files
      }
      if (context === 'conflicts') {
        if (!workingTreeChanges?.ok) return null
        const conflictPaths = new Set(
          (activeThread?.publishConflicts ?? []).map((path) => normalizeChangePath(path))
        )
        return workingTreeChanges.files.filter((file) =>
          conflictPaths.has(normalizeChangePath(file.path))
        )
      }
      return null
    },
    [activeThread?.publishConflicts, context, gitChanges, isGitContext, workingTreeChanges]
  )

  const isReview = variant === 'review'
  const isList = variant === 'list'
  const isDiff = variant === 'diff'
  const isStack = variant === 'stack'
  const compactList = isReview || isList
  const [listSize, setListSize] = useState(isReview ? FILE_LIST_DEFAULT : STACK_LIST_DEFAULT)
  const [diffCollapsed, setDiffCollapsed] = useState(false)
  // Unified by default — denser, no empty half-pane on new/deleted files.
  const [diffStyle, setDiffStyle] = useState<DiffRenderStyle>('unified')
  const resizeDrag = useRef<{ start: number; startSize: number } | null>(null)

  useEffect(() => {
    if (!isGitContext || isDiff || !changeRoot) return
    void reloadGitBranches(true)
  }, [changeRoot, isDiff, isGitContext, reloadGitBranches])

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
    if (scopedGitFiles) {
      return scopedGitFiles.flatMap((file, index) =>
        collectWorkspaceChangeEntries({
          blocks: [],
          turnDiffByTurnId: {},
          gitFiles: [file]
        }).map((entry) => ({
          ...entry,
          id: `git:${context}:${file.stage}:${index}:${file.path}`,
          committable: isMutableGitContext && canMutateGit && entry.committable
        }))
      )
    }
    return collectWorkspaceChangeEntries({
        blocks: sourceBlocks,
        turnDiffByTurnId: sourceTurnDiffs,
        gitFiles: null,
        retainSessionEntriesWhenGitClean:
          context === 'last-turn' || context === 'all-turns'
      }).map((entry) => ({ ...entry, committable: false }))
  }, [canMutateGit, context, isMutableGitContext, scopedGitFiles, sourceBlocks, sourceTurnDiffs])

  const changeStats = useMemo(() => {
    if (context === 'working-tree' && workingTreeChanges?.ok) {
      return sumWorkspaceChangeStats(
        collectWorkspaceChangeEntries({
          blocks: [],
          turnDiffByTurnId: {},
          gitFiles: workingTreeChanges.files
        })
      )
    }
    return sumWorkspaceChangeStats(fileChanges)
  }, [context, fileChanges, workingTreeChanges])
  const visibleFileCount = useMemo(
    () =>
      new Set(
        fileChanges.map((entry) => normalizeChangePath(entry.filePath)).filter(Boolean)
      ).size,
    [fileChanges]
  )

  useEffect(() => {
    if (fileChanges.length === 0) {
      const nextSelectedId = resolveInspectorSelectionUpdate({
        fileIds: [],
        selectedId,
        loading: gitLoading,
        passive: isDiff
      })
      if (nextSelectedId !== undefined) selectInspectorItem(nextSelectedId)
      if (requestedPath && !gitLoading) onRequestedPathConsumed?.()
      return
    }
    if (requestedPath) {
      const matchedId = findChangeItemId(fileChanges, requestedPath)
      if (matchedId) {
        if (matchedId !== selectedId) selectInspectorItem(matchedId)
        if (isStack) setDiffCollapsed(false)
        onRequestedPathConsumed?.()
        return
      }
      // Git may still be loading the matching path; wait. Otherwise don't
      // pin an unmatched path forever — fall through and show the list.
      if (gitLoading) return
      onRequestedPathConsumed?.()
    }
    const nextSelectedId = resolveInspectorSelectionUpdate({
      fileIds: fileChanges.map((item) => item.id),
      selectedId,
      loading: gitLoading,
      passive: isDiff
    })
    if (nextSelectedId !== undefined) selectInspectorItem(nextSelectedId)
  }, [
    fileChanges,
    selectedId,
    selectInspectorItem,
    requestedPath,
    onRequestedPathConsumed,
    gitLoading,
    isStack,
    isDiff
  ])

  useEffect(() => {
    if (isStack) setDiffCollapsed(false)
  }, [changeRoot, context, isStack])

  const selectedItem = useMemo(
    () => fileChanges.find((item) => item.id === selectedId) ?? null,
    [fileChanges, selectedId]
  )

  const gitStageLabel = (stage: GitWorkingChangeStage): string => {
    if (stage === 'staged') return t('gitStageStaged')
    if (stage === 'partial') return t('gitStagePartial')
    return t('gitStageUnstaged')
  }

  const conflictCount = activeThread?.publishConflicts?.length ?? 0
  const contextHint = (() => {
    switch (context) {
      case 'last-turn':
        return t('changeContextLastTurnHint')
      case 'all-turns':
        return t('changeContextAllTurnsHint')
      case 'staged':
        return t('changeContextStagedHint')
      case 'unstaged':
        return t('changeContextUnstagedHint')
      case 'branch':
        return t('changeContextBranchHint', {
          base: gitChanges?.ok ? (gitChanges.baseRef ?? 'HEAD') : 'HEAD'
        })
      case 'conflicts':
        return t('changeContextConflictsHint')
      default:
        return t('changeContextWorkingTreeHint')
    }
  })()
  const emptyMessage = (() => {
    switch (context) {
      case 'last-turn':
        return t('inspectorEmptyTurn')
      case 'all-turns':
        return t('inspectorEmptyAllTurns')
      case 'staged':
        return t('inspectorEmptyStaged')
      case 'unstaged':
        return t('inspectorEmptyUnstaged')
      case 'branch':
        return t('inspectorEmptyBranch')
      case 'conflicts':
        return t('inspectorEmptyConflicts')
      default:
        return t('inspectorEmptyWorkspace')
    }
  })()
  const selectedBranchBase =
    branchBase ?? (gitChanges?.ok ? gitChanges.baseRef : undefined)
  const [pathActionBusy, setPathActionBusy] = useState<string | null>(null)
  const [pathActionError, setPathActionError] = useState<string | null>(null)

  const runFileStageAction = useCallback(
    async (action: 'stage' | 'unstage', path: string): Promise<void> => {
      const method =
        action === 'stage' ? window.dsGui?.stageGitChanges : window.dsGui?.unstageGitChanges
      if (typeof method !== 'function') {
        setPathActionError(t('gitActionUnavailable'))
        return
      }
      setPathActionBusy(`${action}:${path}`)
      setPathActionError(null)
      try {
        const result = await method(changeRoot, [path])
        if (!result.ok) {
          setPathActionError(result.message)
          return
        }
        useChatStore.setState((state) => ({ workspaceDirtyTick: state.workspaceDirtyTick + 1 }))
        await refreshGit()
      } catch (error) {
        setPathActionError(error instanceof Error ? error.message : String(error))
      } finally {
        setPathActionBusy(null)
      }
    },
    [changeRoot, refreshGit, t]
  )

  const fileGroups = useMemo(() => {
    if (context !== 'working-tree') {
      return [{ key: context, label: null, items: fileChanges }]
    }
    return [
      {
        key: 'staged',
        label: t('gitGroupStaged'),
        items: fileChanges.filter((item) => item.gitStage === 'staged')
      },
      {
        key: 'changes',
        label: t('gitGroupChanges'),
        items: fileChanges.filter((item) => item.gitStage !== 'staged')
      }
    ].filter((group) => group.items.length > 0)
  }, [context, fileChanges, t])

  const renderFileRow = (item: WorkspaceChangeEntry): ReactElement => {
    const stats = workspaceChangeEntryStats(item)
    const displayPath = formatFilePathForDisplay(item.filePath, changeRoot || workspaceRoot)
    const { name, parent } = splitFileNameAndParent(displayPath ?? item.filePath ?? '')
    const isSelected = selectedId === item.id
    const rowClass = compactList
      ? `flex min-h-8 w-full items-center gap-1.5 px-2 transition ${
          isSelected ? 'bg-ds-hover text-ds-ink' : 'text-ds-ink hover:bg-ds-hover/70'
        }`
      : `flex w-full items-start gap-2 px-2 py-1.5 transition ${
          isSelected ? 'bg-ds-hover text-ds-ink' : 'text-ds-ink hover:bg-ds-hover/70'
        }`
    const selectRow = (): void => {
      onRequestedPathConsumed?.()
      selectInspectorItem(item.id)
      if (isStack) setDiffCollapsed(false)
      if (item.filePath) onSelectFile?.(item.filePath, item.editLine)
      if (!isList && onOpenFile && item.filePath) onOpenFile(item.filePath, item.editLine)
    }
    const revealRow = (): void => {
      selectInspectorItem(item.id)
      if (item.filePath) onRevealInEditor?.(item.filePath, item.editLine)
    }
    const stageAction = item.gitStage === 'staged' ? 'unstage' : 'stage'
    const actionBusy = item.filePath && pathActionBusy === `${stageAction}:${item.filePath}`

    return (
      <li key={item.id}>
        <div className={rowClass}>
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
              onRevealInEditor && item.filePath
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
                  {item.filePath ? (
                    <FileTypeIcon
                      path={item.filePath}
                      className="mr-1.5 inline-block h-3.5 w-3.5 align-[-0.2em]"
                    />
                  ) : null}
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
                {item.gitStage === 'partial' ? (
                  <span className="shrink-0 text-[10px] font-medium text-ds-muted">
                    {gitStageLabel(item.gitStage)}
                  </span>
                ) : null}
                {item.status === 'running' ? (
                  <span className="shrink-0 text-[10px] font-medium text-amber-700 dark:text-amber-200">
                    {t('inspectorStatusRunning')}
                  </span>
                ) : null}
                {stats ? <ChangeDiffStatsLabel stats={stats} size="sm" /> : null}
              </>
            ) : (
              <>
                <div className="flex min-w-0 items-center gap-2">
                  {item.filePath ? (
                    <FileTypeIcon path={item.filePath} className="h-3.5 w-3.5 shrink-0" />
                  ) : null}
                  <div className="min-w-0 flex-1 truncate text-[13px] text-ds-ink">
                    {displayPath ?? t('toolActionFile')}
                  </div>
                  {item.status === 'running' ? (
                    <span className="shrink-0 text-[11px] font-medium text-amber-700 dark:text-amber-200">
                      {t('inspectorStatusRunning')}
                    </span>
                  ) : null}
                </div>
                {stats ? <ChangeDiffStatsLabel stats={stats} size="sm" /> : null}
              </>
            )}
          </button>
          {item.committable && item.filePath ? (
            <button
              type="button"
              disabled={pathActionBusy !== null}
              onClick={() => void runFileStageAction(stageAction, item.filePath!)}
              title={stageAction === 'stage' ? t('gitStageFile') : t('gitUnstageFile')}
              aria-label={
                stageAction === 'stage'
                  ? t('gitStageFileNamed', { file: displayPath ?? item.filePath })
                  : t('gitUnstageFileNamed', { file: displayPath ?? item.filePath })
              }
              className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-card hover:text-ds-ink active:scale-[0.96] disabled:opacity-40"
            >
              {actionBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : stageAction === 'stage' ? (
                <Plus className="h-3.5 w-3.5" strokeWidth={2} />
              ) : (
                <Minus className="h-3.5 w-3.5" strokeWidth={2} />
              )}
            </button>
          ) : null}
        </div>
      </li>
    )
  }

  const fileList = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {pathActionError ? (
        <div role="alert" className="border-b border-ds-border-muted px-2 py-1.5 text-[11px] text-amber-700 dark:text-amber-200">
          {pathActionError}
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {fileGroups.map((group) => (
          <div key={group.key}>
            {group.label ? (
              <div className="sticky top-0 z-10 flex h-7 items-center bg-ds-sidebar px-2 text-[10.5px] font-semibold uppercase tracking-wide text-ds-faint">
                {group.label}
                <span className="ml-auto tabular-nums">{group.items.length}</span>
              </div>
            ) : null}
            <ul>{group.items.map(renderFileRow)}</ul>
          </div>
        ))}
      </div>
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
            onCollapse={isStack ? () => setDiffCollapsed(true) : onCollapse}
            onAddToChat={
              selectedItem.filePath
                ? () => {
                    const relative =
                      formatFilePathForDisplay(selectedItem.filePath, changeRoot || workspaceRoot) ||
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
      {onContextChange ? (
        <div
          className={`relative z-30 shrink-0 border-b border-ds-border-muted/70 px-2 ${
            context === 'branch' ? 'py-1.5' : 'flex h-12 items-center gap-2'
          }`}
        >
          <div className="flex h-8 w-full min-w-0 items-center gap-2">
            <div className="min-w-0 flex-1">
              <ChangeSourcePicker
                context={context}
                conflictCount={conflictCount}
                branchBase={gitChanges?.ok ? gitChanges.baseRef : undefined}
                hint={contextHint}
                onChange={onContextChange}
              />
            </div>
            {visibleFileCount > 0 || changeStats ? (
              <div className="ds-change-inspector__summary flex shrink-0 items-center gap-2">
                {visibleFileCount > 0 ? (
                  <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-ds-hover px-1.5 text-[10.5px] font-medium tabular-nums text-ds-muted">
                    {visibleFileCount}
                  </span>
                ) : null}
                {changeStats ? (
                  <ChangeDiffStatsLabel stats={changeStats} size="sm" className="shrink-0" />
                ) : null}
              </div>
            ) : null}
            {isGitContext && !isDiff && canMutateGit && gitBranches?.ok && workingTreeChanges?.ok ? (
              <InspectorGitActions
                root={changeRoot}
                stagedFiles={workingTreeChanges.stagedFiles ?? []}
                unstagedFiles={workingTreeChanges.unstagedFiles ?? []}
                branch={gitBranches.currentBranch}
                upstream={gitBranches.upstream}
                ahead={gitBranches.ahead}
                behind={gitBranches.behind}
                hasRemote={gitBranches.hasRemote}
                remoteRepository={remoteRepositoryResult?.ok ? remoteRepositoryResult : null}
                onChanged={refreshGit}
              />
            ) : null}
          </div>
          {context === 'branch' ? (
            <BranchComparisonPicker
              currentBranch={gitBranches?.ok ? gitBranches.currentBranch : null}
              branches={gitBranches?.ok ? gitBranches.branches : []}
              defaultBranch={gitBranches?.ok ? gitBranches.defaultBranch : null}
              dirtyCount={gitBranches?.ok ? gitBranches.dirtyCount : 0}
              selectedBase={selectedBranchBase}
              loading={!gitBranches?.ok || scopedLoading}
              onChange={setBranchBase}
            />
          ) : null}
        </div>
      ) : null}
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
              <div className="mt-1 text-[12px] leading-6 text-ds-faint">
                {emptyMessage}
              </div>
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
            <div
              className={`flex min-h-0 flex-col overflow-hidden ${diffCollapsed ? 'flex-1' : 'shrink-0'}`}
              style={diffCollapsed ? undefined : { height: listSize }}
            >
              {fileList}
            </div>
            {!diffCollapsed ? (
              <>
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
              </>
            ) : null}
          </div>
        )}
      </div>
    </aside>
  )
}
