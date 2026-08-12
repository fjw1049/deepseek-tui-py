import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, Check, ChevronDown, GitBranch, History, Loader2, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useGitBranches } from '../../hooks/use-git-branches'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { useWorkspaceDirtyGitRefresh } from '../../hooks/use-workspace-dirty-git-refresh'
import { useChatStore } from '../../store/chat-store'
import { GitLogDialog } from './GitLogDialog'

type Props = {
  workspaceRoot: string
  compact?: boolean
  usePortal?: boolean
  menuPlacement?: 'above' | 'below'
  /** Compact tray: drop the branch name, keep the git icon. */
  hideLabel?: boolean
  /** Compact tray: drop the chevron before hiding the control. */
  hideChevron?: boolean
}

const MENU_WIDTH = 420

export function GitBranchPicker({
  workspaceRoot,
  compact = false,
  usePortal = false,
  menuPlacement = 'above',
  hideLabel = false,
  hideChevron = false
}: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const root = workspaceRoot.trim()
  const [open, setOpen] = useState(false)
  const [logOpen, setLogOpen] = useState(false)
  const [query, setQuery] = useState('')
  const { result, loading, reload, setResult } = useGitBranches(root)
  // Keep the branch / dirty-count badge fresh when the workspace changes on
  // disk (agent edits, external editors) — not only when the menu opens.
  const workspaceDirtyTick = useChatStore((s) => s.workspaceDirtyTick)
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, reload)
  const [actingBranch, setActingBranch] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Action-level warning that must survive branch list refreshes (unlike `error`).
  const [notice, setNotice] = useState<string | null>(null)
  const [dirtyConflictBranch, setDirtyConflictBranch] = useState<string | null>(null)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    setOpen(false)
    setLogOpen(false)
    setQuery('')
    setError(null)
    setNotice(null)
    setDirtyConflictBranch(null)
    setActingBranch(null)
  }, [root])

  useEffect(() => {
    if (!result) {
      setError(null)
      return
    }
    setError(result.ok ? null : result.message)
  }, [result])

  useEffect(() => {
    if (!open) return
    void reload()
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }, [open, reload])

  const updateMenuPosition = useCallback((): void => {
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const width = Math.min(MENU_WIDTH, window.innerWidth - 24)
    const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))

    if (usePortal) {
      if (menuPlacement === 'below') {
        setMenuStyle({
          position: 'fixed',
          left,
          top: rect.bottom + 8,
          width,
          zIndex: 120
        })
        return
      }
      setMenuStyle({
        position: 'fixed',
        left,
        bottom: window.innerHeight - rect.top + 8,
        width,
        zIndex: 120
      })
      return
    }

    setMenuStyle({
      position: 'absolute',
      left: 0,
      width: `min(${MENU_WIDTH}px, calc(100vw - 48px))`,
      ...(menuPlacement === 'below'
        ? { top: 'calc(100% + 8px)' }
        : { bottom: 'calc(100% + 8px)' })
    })
  }, [menuPlacement, usePortal])

  useLayoutEffect(() => {
    if (!open) return
    updateMenuPosition()
    window.addEventListener('resize', updateMenuPosition)
    window.addEventListener('scroll', updateMenuPosition, true)
    return () => {
      window.removeEventListener('resize', updateMenuPosition)
      window.removeEventListener('scroll', updateMenuPosition, true)
    }
  }, [open, updateMenuPosition])

  useLightDismiss({
    open,
    onDismiss: () => setOpen(false),
    refs: [wrapRef, menuRef]
  })

  const branches = useMemo(() => (result?.ok ? result.branches : []), [result])
  const filteredBranches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return branches
    return branches.filter((branch) => branch.name.toLowerCase().includes(q))
  }, [branches, query])

  const currentBranch = result?.ok ? result.currentBranch : null
  const label =
    currentBranch ||
    (loading && !result ? t('gitBranchLoading') : t('gitNoBranch'))

  const switchBranch = async (branch: string): Promise<void> => {
    if (!root || !branch || branch === currentBranch) {
      setOpen(false)
      return
    }
    setActingBranch(branch)
    setError(null)
    setNotice(null)
    setDirtyConflictBranch(null)
    try {
      const next = await window.dsGui.switchGitBranch(root, branch)
      if (!next.ok && next.reason === 'dirty_worktree') {
        setDirtyConflictBranch(branch)
        setNotice(t('gitDirtySwitchBlocked', { branch }))
        return
      }
      setResult(next)
      if (!next.ok) {
        setError(next.message)
        return
      }
      setOpen(false)
      setQuery('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setActingBranch(null)
    }
  }

  const stashAndSwitch = async (branch: string): Promise<void> => {
    if (!root || !branch) return
    setActingBranch(branch)
    setError(null)
    setNotice(null)
    setDirtyConflictBranch(null)
    try {
      const next = await window.dsGui.stashAndSwitchGitBranch(root, branch)
      if (!next.ok && next.reason === 'stash_pop_conflict') {
        setNotice(t('gitStashPopConflict'))
        void reload()
        return
      }
      setResult(next)
      if (!next.ok) {
        setError(next.message)
        return
      }
      setOpen(false)
      setQuery('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setActingBranch(null)
    }
  }

  const openCommitLog = (): void => {
    setOpen(false)
    setLogOpen(true)
  }

  const closeCommitLog = (): void => {
    setLogOpen(false)
    setOpen(true)
  }

  if (!root) return null

  const menu = open ? (
    <div
      ref={menuRef}
      style={menuStyle}
      className="z-50 overflow-hidden rounded-xl border border-ds-border bg-ds-elevated shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)]"
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="ds-project-context-menu__header">
        <label className="ds-project-context-menu__search">
          <Search className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.85} aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.preventDefault()
                setOpen(false)
              }
            }}
            placeholder={t('gitSearchBranches')}
            className="ds-project-context-menu__search-input"
          />
        </label>
      </div>

      <div className="max-h-[320px] overflow-y-auto px-3 py-3">
        <div className="mb-2 px-1 text-[13px] font-medium text-ds-faint">{t('gitBranches')}</div>

        {loading && !result ? (
          <div className="flex items-center gap-2 px-1 py-3 text-[13px] text-ds-muted">
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
            {t('gitBranchLoading')}
          </div>
        ) : null}

        {error || notice ? (
          <div className="mb-2 rounded-lg border border-amber-300/70 bg-amber-50 px-3 py-2 text-[12px] leading-5 text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/35 dark:text-amber-100">
            <div className="flex gap-2">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2} />
              <span className="min-w-0 break-words">{error ?? notice}</span>
            </div>
            {dirtyConflictBranch ? (
              <button
                type="button"
                disabled={actingBranch != null}
                onClick={() => void stashAndSwitch(dirtyConflictBranch)}
                className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-amber-400/70 bg-amber-100 px-2.5 py-1 text-[12px] font-medium text-amber-900 transition hover:bg-amber-200 disabled:opacity-45 dark:border-amber-600/60 dark:bg-amber-900/40 dark:text-amber-100 dark:hover:bg-amber-900/70"
              >
                {actingBranch === dirtyConflictBranch ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
                ) : null}
                {t('gitStashAndSwitch', { branch: dirtyConflictBranch })}
              </button>
            ) : null}
          </div>
        ) : null}

        {filteredBranches.map((branch) => (
          <button
            key={branch.name}
            type="button"
            className="flex w-full items-start gap-3 rounded-lg px-1 py-2.5 text-left text-ds-ink transition hover:bg-ds-hover"
            onClick={() => void switchBranch(branch.name)}
            disabled={actingBranch != null}
          >
            <GitBranch className="mt-0.5 h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[15px] font-medium">{branch.name}</span>
              {branch.current && result?.ok && result.dirtyCount > 0 ? (
                <span className="mt-0.5 block text-[12px] text-ds-faint">
                  {t('gitDirtyFiles', { count: result.dirtyCount })}
                </span>
              ) : null}
            </span>
            {actingBranch === branch.name ? (
              <Loader2 className="mt-1 h-4 w-4 shrink-0 animate-spin text-ds-muted" strokeWidth={2} />
            ) : branch.current ? (
              <Check className="mt-0.5 h-5 w-5 shrink-0 text-ds-muted" strokeWidth={2} />
            ) : null}
          </button>
        ))}

        {!loading && result?.ok && filteredBranches.length === 0 ? (
          <div className="px-1 py-3 text-[13px] text-ds-faint">{t('gitNoBranches')}</div>
        ) : null}
      </div>

      <div className="border-t border-ds-border-muted px-3 py-3">
        <button
          type="button"
          disabled={actingBranch != null || !result?.ok}
          className="flex w-full items-center gap-3 rounded-lg px-1 py-2 text-left text-[14px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
          onClick={openCommitLog}
        >
          <History className="h-4 w-4 shrink-0 text-ds-muted" strokeWidth={1.9} />
          <span className="min-w-0 truncate">{t('gitLogOpen')}</span>
        </button>
      </div>
    </div>
  ) : null

  return (
    <div ref={wrapRef} className="ds-no-drag relative">
      <button
        ref={triggerRef}
        type="button"
        className={
          compact
            ? `ds-workspace-context-chip flex h-7 items-center gap-1.5 rounded-md px-2 py-1 text-left ${
                hideLabel ? 'shrink-0' : 'max-w-[160px] min-w-0'
              }`
            : 'flex h-8 max-w-[320px] items-center gap-2 rounded-lg px-2 text-[14px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink'
        }
        onClick={() => setOpen((v) => !v)}
        title={label || t('gitBranch')}
        aria-label={label || t('gitBranch')}
      >
        <GitBranch className="h-3.5 w-3.5 shrink-0" strokeWidth={1.7} />
        {!hideLabel ? <span className="min-w-0 flex-1 truncate">{label}</span> : null}
        {loading ? (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-ds-faint" strokeWidth={2} />
        ) : !hideChevron ? (
          <ChevronDown className="ds-workspace-context-chip__chevron" strokeWidth={2.2} />
        ) : null}
      </button>

      {usePortal && typeof document !== 'undefined'
        ? createPortal(menu, document.body)
        : menu}
      <GitLogDialog
        workspaceRoot={root}
        currentBranch={currentBranch}
        open={logOpen}
        onClose={closeCommitLog}
      />
    </div>
  )
}
