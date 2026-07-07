import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { Loader2, Plus, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal as XTerm, type ITheme } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { readTerminalFontFamily } from '../lib/apply-theme'
import { getTerminalFontSizePx, subscribeAppearance } from '../lib/apply-appearance'
import { terminalLabelFromPath } from '../lib/workspace-label'
import {
  closeTerminalSessionById,
  createTerminalSessionForWorkspace,
  useTerminalSessionStore,
  type TerminalXtermMount
} from '../store/terminal-session-store'

type TerminalHandle = {
  terminal: XTerm
  fitAddon: FitAddon
  inputDisposable: { dispose: () => void }
}

type Props = {
  workspaceRoot: string
  mountSurface: TerminalXtermMount
  mountActive: boolean
  visible?: boolean
  onClose?: () => void
  className?: string
}

function readTerminalTheme(): ITheme {
  const styles = getComputedStyle(document.documentElement)
  const dark = document.documentElement.getAttribute('data-theme') === 'dark'
  const accent = styles.getPropertyValue('--ds-accent').trim() || (dark ? '#339cff' : '#0088ff')
  const success = styles.getPropertyValue('--ds-success').trim() || (dark ? '#40c977' : '#128a4a')
  const danger = styles.getPropertyValue('--ds-danger').trim() || (dark ? '#fa423e' : '#c92a2a')
  const skill = styles.getPropertyValue('--ds-skill').trim() || (dark ? '#ad7bf9' : '#7c3aed')
  const canvasBg =
    styles.getPropertyValue('--ds-bg-canvas').trim() || (dark ? '#181818' : '#ffffff')
  const foreground = styles.getPropertyValue('--ds-text').trim() || (dark ? '#ffffff' : '#222222')
  return {
    background: canvasBg,
    foreground,
    cursor: foreground,
    selectionBackground: dark ? 'rgba(51,156,255,0.28)' : 'rgba(0,136,255,0.2)',
    black: dark ? '#242424' : '#374151',
    red: danger,
    green: success,
    yellow: '#f59e0b',
    blue: accent,
    magenta: skill,
    cyan: '#06b6d4',
    white: dark ? '#f4f4f4' : '#111827',
    brightBlack: dark ? '#7a7a7a' : '#6b7280',
    brightRed: dark ? '#ff7d79' : '#f87171',
    brightGreen: dark ? '#72df9b' : '#4ade80',
    brightYellow: '#fbbf24',
    brightBlue: dark ? '#7bbcff' : '#60a5fa',
    brightMagenta: dark ? '#c49bff' : '#e879f9',
    brightCyan: '#22d3ee',
    brightWhite: dark ? '#ffffff' : '#030712'
  }
}

export function AppTerminalPanel({
  workspaceRoot,
  mountSurface,
  mountActive,
  visible = true,
  onClose,
  className
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const sessions = useTerminalSessionStore((s) => s.sessions)
  const activeSessionId = useTerminalSessionStore((s) => s.activeSessionId)
  const creatingSession = useTerminalSessionStore((s) => s.creatingSession)
  const createError = useTerminalSessionStore((s) => s.createError)
  const hasStartedInitialSession = useTerminalSessionStore((s) => s.hasStartedInitialSession)
  const setActiveSessionId = useTerminalSessionStore((s) => s.setActiveSessionId)
  const updateSession = useTerminalSessionStore((s) => s.updateSession)
  const markInitialSessionStarted = useTerminalSessionStore((s) => s.markInitialSessionStarted)
  const setXtermMount = useTerminalSessionStore((s) => s.setXtermMount)

  const viewportRef = useRef<HTMLDivElement | null>(null)
  const sessionNodeRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const terminalHandlesRef = useRef<Map<string, TerminalHandle>>(new Map())
  const fitFrameRef = useRef<number | null>(null)
  const trimmedWorkspaceRoot = workspaceRoot.trim()

  const baseLabel = useMemo(() => {
    const label = terminalLabelFromPath(workspaceRoot)
    return label || t('terminalPanelTitle')
  }, [t, workspaceRoot])

  const scheduleFit = useCallback(
    (sessionId: string | null): void => {
      if (!sessionId || !mountActive || !visible) return
      if (fitFrameRef.current !== null) {
        window.cancelAnimationFrame(fitFrameRef.current)
      }
      fitFrameRef.current = window.requestAnimationFrame(() => {
        const handle = terminalHandlesRef.current.get(sessionId)
        if (!handle) return
        handle.fitAddon.fit()
        if (handle.terminal.cols > 0 && handle.terminal.rows > 0) {
          void window.dsGui?.resizeTerminalSession?.({
            sessionId,
            cols: handle.terminal.cols,
            rows: handle.terminal.rows
          })
        }
      })
    },
    [mountActive, visible]
  )

  const createSession = useCallback(async (): Promise<void> => {
    await createTerminalSessionForWorkspace(trimmedWorkspaceRoot)
  }, [trimmedWorkspaceRoot])

  useEffect(() => {
    if (mountActive) setXtermMount(mountSurface)
  }, [mountActive, mountSurface, setXtermMount])

  useEffect(() => {
    if (!trimmedWorkspaceRoot || !mountActive) return
    if (hasStartedInitialSession) return
    markInitialSessionStarted()
    void createSession()
  }, [
    createSession,
    hasStartedInitialSession,
    markInitialSessionStarted,
    mountActive,
    trimmedWorkspaceRoot
  ])

  useEffect(() => {
    if (typeof window.dsGui?.onTerminalData !== 'function' || typeof window.dsGui?.onTerminalExit !== 'function') {
      return
    }

    const offData = window.dsGui.onTerminalData(({ sessionId, data }) => {
      terminalHandlesRef.current.get(sessionId)?.terminal.write(data)
    })

    const offExit = window.dsGui.onTerminalExit(({ sessionId, exitCode }) => {
      const handle = terminalHandlesRef.current.get(sessionId)
      handle?.terminal.write(`\r\n${t('terminalExited', { code: exitCode })}\r\n`)
      updateSession(sessionId, { status: 'exited', exitCode })
    })

    return () => {
      offData()
      offExit()
    }
  }, [t, updateSession])

  useEffect(() => {
    if (!mountActive) return

    for (const session of sessions) {
      const host = sessionNodeRefs.current[session.id]
      if (!host || terminalHandlesRef.current.has(session.id)) continue

      const terminal = new XTerm({
        cursorBlink: true,
        convertEol: true,
        fontFamily: readTerminalFontFamily(),
        fontSize: getTerminalFontSizePx(),
        lineHeight: 1.35,
        scrollback: 8_000,
        theme: readTerminalTheme()
      })
      const fitAddon = new FitAddon()
      terminal.loadAddon(fitAddon)
      terminal.open(host)
      const inputDisposable = terminal.onData((data) => {
        void window.dsGui?.writeTerminalSession?.({ sessionId: session.id, data })
      })

      terminalHandlesRef.current.set(session.id, {
        terminal,
        fitAddon,
        inputDisposable
      })

      scheduleFit(session.id)
    }

    for (const [sessionId, handle] of terminalHandlesRef.current.entries()) {
      if (sessions.some((session) => session.id === sessionId)) continue
      handle.inputDisposable.dispose()
      handle.terminal.dispose()
      terminalHandlesRef.current.delete(sessionId)
      delete sessionNodeRefs.current[sessionId]
    }
  }, [mountActive, scheduleFit, sessions])

  useEffect(() => {
    scheduleFit(activeSessionId)
  }, [activeSessionId, mountActive, scheduleFit, sessions.length])

  // Keep open terminals in sync with appearance settings (font family/size)
  // and theme changes (data-theme flips or custom palette updates).
  useEffect(() => {
    if (!mountActive) return
    const syncTerminalAppearance = (): void => {
      const theme = readTerminalTheme()
      const fontFamily = readTerminalFontFamily()
      const fontSize = getTerminalFontSizePx()
      for (const handle of terminalHandlesRef.current.values()) {
        handle.terminal.options.theme = theme
        handle.terminal.options.fontFamily = fontFamily
        handle.terminal.options.fontSize = fontSize
      }
      scheduleFit(activeSessionId)
    }

    const unsubscribe = subscribeAppearance(syncTerminalAppearance)
    const observer = new MutationObserver(syncTerminalAppearance)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    })
    return () => {
      unsubscribe()
      observer.disconnect()
    }
  }, [activeSessionId, mountActive, scheduleFit])

  useEffect(() => {
    if (!mountActive) return
    const onResize = (): void => scheduleFit(activeSessionId)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [activeSessionId, mountActive, scheduleFit])

  useEffect(() => {
    if (!mountActive || !viewportRef.current || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => scheduleFit(activeSessionId))
    observer.observe(viewportRef.current)
    return () => observer.disconnect()
  }, [activeSessionId, mountActive, scheduleFit])

  useEffect(() => {
    if (mountActive) return
    for (const handle of terminalHandlesRef.current.values()) {
      handle.inputDisposable.dispose()
      handle.terminal.dispose()
    }
    terminalHandlesRef.current.clear()
    sessionNodeRefs.current = {}
  }, [mountActive])

  // Unmount cleanup: the bottom terminal is conditionally rendered
  // ({bottomTerminalOpen ? <AppTerminalPanel/> : null}), so closing it
  // unmounts the component while `mountActive` stays `true` — the effect
  // above never fires. Dispose any surviving xterm handles here so we don't
  // leak one xterm instance (DOM, scrollback, listeners) per open/close.
  // We intentionally read the ref at cleanup time (not capture-at-mount)
  // because handles are added/removed over the component's lifetime; the
  // exhaustive-deps warning assumes React-rendered nodes and does not apply
  // to this manually-managed Map of xterm instances (same pattern as the
  // mountActive dispose effect above).
  useEffect(() => {
    return () => {
      for (const handle of terminalHandlesRef.current.values()) {
        handle.inputDisposable.dispose()
        handle.terminal.dispose()
      }
      terminalHandlesRef.current.clear()
      sessionNodeRefs.current = {}
    }
  }, [])

  const closeSession = (sessionId: string): void => {
    const handle = terminalHandlesRef.current.get(sessionId)
    if (handle) {
      handle.inputDisposable.dispose()
      handle.terminal.dispose()
      terminalHandlesRef.current.delete(sessionId)
    }
    delete sessionNodeRefs.current[sessionId]
    closeTerminalSessionById(sessionId)
  }

  if (!mountActive) {
    return null
  }

  return (
    <section className={`ds-tool-panel ds-no-drag ds-terminal-panel flex min-h-0 flex-col overflow-hidden ${className ?? ''}`}>
      <div className="ds-terminal-panel__tabs flex shrink-0 items-center justify-between gap-2 border-b border-ds-border-muted px-2.5 py-1.5">
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {sessions.map((session, index) => {
            const active = session.id === activeSessionId
            return (
              <span
                key={session.id}
                className={`inline-flex shrink-0 items-center gap-0.5 rounded-lg border transition ${
                  active
                    ? 'border-ds-border-muted bg-white/90 text-ds-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.72)] dark:border-white/10 dark:bg-white/10 dark:shadow-none'
                    : 'border-transparent text-ds-faint hover:border-ds-border-muted/60 hover:bg-ds-hover/50 hover:text-ds-ink'
                }`}
              >
                <button
                  type="button"
                  onClick={() => setActiveSessionId(session.id)}
                  className="max-w-[200px] truncate px-2.5 py-1 text-[12.5px] font-medium"
                  title={session.cwd}
                >
                  {`${baseLabel} ${index + 1}`}
                  {session.status === 'exited' ? (
                    <span className="ml-1.5 rounded bg-ds-hover px-1 py-0.5 text-[10px] font-medium text-ds-faint">
                      {session.exitCode ?? 0}
                    </span>
                  ) : null}
                </button>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    closeSession(session.id)
                  }}
                  className="mr-1 inline-flex h-4 w-4 items-center justify-center rounded text-ds-faint hover:bg-ds-hover/80 hover:text-ds-ink"
                  aria-label={t('terminalCloseTab')}
                  title={t('terminalCloseTab')}
                >
                  <X className="h-3 w-3" strokeWidth={2} />
                </button>
              </span>
            )
          })}
          <button
            type="button"
            onClick={() => void createSession()}
            disabled={creatingSession || !trimmedWorkspaceRoot}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover/70 hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-45"
            aria-label={t('terminalNewTab')}
            title={t('terminalNewTab')}
          >
            {creatingSession ? (
              <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.9} />
            ) : (
              <Plus className="h-4 w-4" strokeWidth={1.9} />
            )}
          </button>
        </div>

        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover/70 hover:text-ds-ink"
            aria-label={t('terminalClose')}
            title={t('terminalClose')}
          >
            <X className="h-4 w-4" strokeWidth={1.85} />
          </button>
        ) : null}
      </div>

      {createError ? (
        <div className="shrink-0 border-b border-red-200/70 bg-red-50/80 px-3 py-2 text-[12.5px] text-red-700 dark:border-red-500/20 dark:bg-red-500/8 dark:text-red-200">
          {t('terminalCreateFailed', { message: createError })}
        </div>
      ) : null}

      <div ref={viewportRef} className="min-h-0 flex-1">
        {sessions.length === 0 ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-[13px] text-ds-faint">
            {creatingSession ? t('terminalStarting') : t('terminalEmpty')}
          </div>
        ) : (
          sessions.map((session) => (
            <div
              key={session.id}
              className={session.id === activeSessionId ? 'h-full w-full' : 'hidden h-full w-full'}
            >
              <div
                ref={(node) => {
                  sessionNodeRefs.current[session.id] = node
                }}
                className="ds-terminal-host h-full w-full"
              />
            </div>
          ))
        )}
      </div>
    </section>
  )
}
