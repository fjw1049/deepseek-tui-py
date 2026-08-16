import type { PointerEvent as ReactPointerEvent, ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  resolveTerminalPanes,
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
  /** Hide the built-in tab row (IDE chat-rail header owns those tabs). */
  hideTabs?: boolean
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

/** Probe the viewport with a throwaway xterm so PTY starts at the real size. */
function proposeTerminalDimensions(container: HTMLElement | null): { cols: number; rows: number } {
  const fallback = { cols: 120, rows: 32 }
  if (!container) return fallback
  const width = container.clientWidth
  const height = container.clientHeight
  if (width < 40 || height < 40) return fallback

  const host = document.createElement('div')
  host.style.cssText = `position:fixed;left:-10000px;top:0;width:${width}px;height:${height}px;overflow:hidden;visibility:hidden;pointer-events:none`
  document.body.appendChild(host)

  const terminal = new XTerm({
    fontFamily: readTerminalFontFamily(),
    fontSize: getTerminalFontSizePx(),
    lineHeight: 1.2,
    scrollback: 1
  })
  const fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  try {
    terminal.open(host)
    fitAddon.fit()
    return {
      cols: Math.max(20, terminal.cols || fallback.cols),
      rows: Math.max(8, terminal.rows || fallback.rows)
    }
  } finally {
    terminal.dispose()
    host.remove()
  }
}

export function AppTerminalPanel({
  workspaceRoot,
  mountSurface,
  mountActive,
  visible = true,
  onClose,
  hideTabs = false,
  className
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const sessions = useTerminalSessionStore((s) => s.sessions)
  const activeSessionId = useTerminalSessionStore((s) => s.activeSessionId)
  const splitSessionId = useTerminalSessionStore((s) => s.splitSessionId)
  const creatingSession = useTerminalSessionStore((s) => s.creatingSession)
  const createError = useTerminalSessionStore((s) => s.createError)
  const hasStartedInitialSession = useTerminalSessionStore((s) => s.hasStartedInitialSession)
  const setActiveSessionId = useTerminalSessionStore((s) => s.setActiveSessionId)
  const updateSession = useTerminalSessionStore((s) => s.updateSession)
  const markInitialSessionStarted = useTerminalSessionStore((s) => s.markInitialSessionStarted)
  const setXtermMount = useTerminalSessionStore((s) => s.setXtermMount)
  const panes = useMemo(
    () => resolveTerminalPanes(activeSessionId, splitSessionId, sessions),
    [activeSessionId, sessions, splitSessionId]
  )
  const [splitRatio, setSplitRatio] = useState(0.5)

  const viewportRef = useRef<HTMLDivElement | null>(null)
  const sessionNodeRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const terminalHandlesRef = useRef<Map<string, TerminalHandle>>(new Map())
  const pendingOutputRef = useRef<Map<string, string>>(new Map())
  const fitFrameRef = useRef<number | null>(null)
  const trimmedWorkspaceRoot = workspaceRoot.trim()

  const baseLabel = useMemo(() => {
    const label = terminalLabelFromPath(workspaceRoot)
    return label || t('terminalPanelTitle')
  }, [t, workspaceRoot])

  const scheduleFit = useCallback(
    (sessionIds: Array<string | null> | string | null): void => {
      const ids = (Array.isArray(sessionIds) ? sessionIds : [sessionIds]).filter(
        (id): id is string => Boolean(id)
      )
      if (ids.length === 0 || !mountActive || !visible) return
      if (fitFrameRef.current !== null) {
        window.cancelAnimationFrame(fitFrameRef.current)
      }
      fitFrameRef.current = window.requestAnimationFrame(() => {
        for (const sessionId of ids) {
          const handle = terminalHandlesRef.current.get(sessionId)
          if (!handle) continue
          handle.fitAddon.fit()
          if (handle.terminal.cols > 0 && handle.terminal.rows > 0) {
            void window.dsGui?.resizeTerminalSession?.({
              sessionId,
              cols: handle.terminal.cols,
              rows: handle.terminal.rows
            })
          }
        }
      })
    },
    [mountActive, visible]
  )

  const fitVisiblePanes = useCallback((): void => {
    scheduleFit([panes.top, panes.bottom])
  }, [panes.bottom, panes.top, scheduleFit])

  const createSession = useCallback(async (): Promise<void> => {
    // Spawn at the fitted viewport size so zsh prompt_sp can erase its EOL mark.
    const dimensions = proposeTerminalDimensions(viewportRef.current)
    await createTerminalSessionForWorkspace(trimmedWorkspaceRoot, dimensions)
  }, [trimmedWorkspaceRoot])

  useEffect(() => {
    if (mountActive) setXtermMount(mountSurface)
  }, [mountActive, mountSurface, setXtermMount])

  // Wait until the panel has a real size before the first PTY spawn; otherwise
  // zsh starts at the 120-col fallback and leaves a visible "%" above the prompt.
  useEffect(() => {
    if (!trimmedWorkspaceRoot || !mountActive || !visible) return
    if (hasStartedInitialSession) return

    const viewport = viewportRef.current
    if (!viewport) return

    const tryStart = (): boolean => {
      if (useTerminalSessionStore.getState().hasStartedInitialSession) return true
      if (viewport.clientWidth < 40 || viewport.clientHeight < 40) return false
      markInitialSessionStarted()
      void createSession()
      return true
    }

    if (tryStart()) return

    if (typeof ResizeObserver === 'undefined') {
      markInitialSessionStarted()
      void createSession()
      return
    }

    const observer = new ResizeObserver(() => {
      if (tryStart()) observer.disconnect()
    })
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [
    createSession,
    hasStartedInitialSession,
    markInitialSessionStarted,
    mountActive,
    trimmedWorkspaceRoot,
    visible
  ])

  useEffect(() => {
    if (typeof window.dsGui?.onTerminalData !== 'function' || typeof window.dsGui?.onTerminalExit !== 'function') {
      return
    }

    const offData = window.dsGui.onTerminalData(({ sessionId, data }) => {
      const handle = terminalHandlesRef.current.get(sessionId)
      if (handle) {
        handle.terminal.write(data)
        return
      }
      // PTY often emits the first prompt before React mounts xterm; keep it.
      const pending = pendingOutputRef.current.get(sessionId) ?? ''
      pendingOutputRef.current.set(sessionId, pending + data)
    })

    const offExit = window.dsGui.onTerminalExit(({ sessionId, exitCode }) => {
      const handle = terminalHandlesRef.current.get(sessionId)
      handle?.terminal.write(`\r\n${t('terminalExited', { code: exitCode })}\r\n`)
      updateSession(sessionId, { status: 'exited', exitCode })
      pendingOutputRef.current.delete(sessionId)
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
        lineHeight: 1.2,
        scrollback: 8_000,
        theme: readTerminalTheme()
      })
      const fitAddon = new FitAddon()
      terminal.loadAddon(fitAddon)
      terminal.open(host)
      // Fit before any shell output hits the screen — zsh prompt_sp clears its
      // "%" mark using the current column width; writing at the default 80x24
      // leaves a permanent mark when the PTY was started at the panel size.
      fitAddon.fit()
      if (terminal.cols > 0 && terminal.rows > 0) {
        void window.dsGui?.resizeTerminalSession?.({
          sessionId: session.id,
          cols: terminal.cols,
          rows: terminal.rows
        })
      }

      const inputDisposable = terminal.onData((data) => {
        void window.dsGui?.writeTerminalSession?.({ sessionId: session.id, data })
      })

      terminalHandlesRef.current.set(session.id, {
        terminal,
        fitAddon,
        inputDisposable
      })

      const pending = pendingOutputRef.current.get(session.id)
      if (pending) {
        pendingOutputRef.current.delete(session.id)
        terminal.write(pending)
      }

      scheduleFit(session.id)
    }

    for (const [sessionId, handle] of terminalHandlesRef.current.entries()) {
      if (sessions.some((session) => session.id === sessionId)) continue
      handle.inputDisposable.dispose()
      handle.terminal.dispose()
      terminalHandlesRef.current.delete(sessionId)
      delete sessionNodeRefs.current[sessionId]
      pendingOutputRef.current.delete(sessionId)
    }
  }, [mountActive, scheduleFit, sessions])

  useEffect(() => {
    fitVisiblePanes()
  }, [fitVisiblePanes, mountActive, panes.bottom, panes.top, sessions.length, splitRatio])

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
      fitVisiblePanes()
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
  }, [fitVisiblePanes, mountActive])

  useEffect(() => {
    if (!mountActive) return
    const onResize = (): void => fitVisiblePanes()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [fitVisiblePanes, mountActive])

  useEffect(() => {
    if (!mountActive || !viewportRef.current || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => fitVisiblePanes())
    observer.observe(viewportRef.current)
    return () => observer.disconnect()
  }, [fitVisiblePanes, mountActive])

  useEffect(() => {
    if (mountActive) return
    for (const handle of terminalHandlesRef.current.values()) {
      handle.inputDisposable.dispose()
      handle.terminal.dispose()
    }
    terminalHandlesRef.current.clear()
    sessionNodeRefs.current = {}
    pendingOutputRef.current.clear()
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
      pendingOutputRef.current.clear()
    }
  }, [])

  const beginSplitResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0 || !viewportRef.current) return
    event.preventDefault()
    const host = viewportRef.current
    const startY = event.clientY
    const startRatio = splitRatio
    const height = host.clientHeight
    if (height < 40) return

    const onMove = (moveEvent: PointerEvent): void => {
      const delta = (moveEvent.clientY - startY) / height
      setSplitRatio(Math.min(0.75, Math.max(0.25, startRatio + delta)))
    }
    const onUp = (): void => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const closeSession = (sessionId: string): void => {
    const handle = terminalHandlesRef.current.get(sessionId)
    if (handle) {
      handle.inputDisposable.dispose()
      handle.terminal.dispose()
      terminalHandlesRef.current.delete(sessionId)
    }
    delete sessionNodeRefs.current[sessionId]
    pendingOutputRef.current.delete(sessionId)
    closeTerminalSessionById(sessionId)
  }

  if (!mountActive) {
    return null
  }

  return (
    <section className={`ds-tool-panel ds-no-drag ds-terminal-panel flex min-h-0 flex-col overflow-hidden ${className ?? ''}`}>
      {hideTabs ? null : (
      <div className="ds-terminal-panel__tabs flex shrink-0 items-center justify-between gap-1.5 border-b border-ds-border-muted px-2 py-0.5">
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
          {sessions.map((session, index) => {
            const active = session.id === activeSessionId
            return (
              <span
                key={session.id}
                className={`inline-flex shrink-0 items-center gap-0.5 rounded-md border transition ${
                  active
                    ? 'border-ds-border-muted bg-white/90 text-ds-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.72)] dark:border-white/10 dark:bg-white/10 dark:shadow-none'
                    : 'border-transparent text-ds-faint hover:border-ds-border-muted/60 hover:bg-ds-hover/50 hover:text-ds-ink'
                }`}
              >
                <button
                  type="button"
                  onClick={() => setActiveSessionId(session.id)}
                  className="max-w-[200px] truncate px-2 py-0.5 text-[12px] font-medium leading-5"
                  title={session.cwd}
                >
                  {`${baseLabel} ${index + 1}`}
                  {session.status === 'exited' ? (
                    <span className="ml-1 rounded bg-ds-hover px-1 py-px text-[10px] font-medium text-ds-faint">
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
                  className="mr-0.5 inline-flex h-3.5 w-3.5 items-center justify-center rounded text-ds-faint hover:bg-ds-hover/80 hover:text-ds-ink"
                  aria-label={t('terminalCloseTab')}
                  title={t('terminalCloseTab')}
                >
                  <X className="h-2.5 w-2.5" strokeWidth={2} />
                </button>
              </span>
            )
          })}
          <button
            type="button"
            onClick={() => void createSession()}
            disabled={creatingSession || !trimmedWorkspaceRoot}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover/70 hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-45"
            aria-label={t('terminalNewTab')}
            title={t('terminalNewTab')}
          >
            {creatingSession ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.9} />
            ) : (
              <Plus className="h-3.5 w-3.5" strokeWidth={1.9} />
            )}
          </button>
        </div>

        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover/70 hover:text-ds-ink"
            aria-label={t('terminalClose')}
            title={t('terminalClose')}
          >
            <X className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
        ) : null}
      </div>
      )}

      {createError ? (
        <div className="shrink-0 border-b border-red-200/70 bg-red-50/80 px-3 py-2 text-[12.5px] text-red-700 dark:border-red-500/20 dark:bg-red-500/8 dark:text-red-200">
          {t('terminalCreateFailed', { message: createError })}
        </div>
      ) : null}

      <div ref={viewportRef} className="flex min-h-0 flex-1 flex-col">
        {sessions.length === 0 ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-[13px] text-ds-faint">
            {creatingSession ? t('terminalStarting') : t('terminalEmpty')}
          </div>
        ) : (
          <>
            {sessions.map((session) => {
              const inTop = session.id === panes.top
              const inBottom = Boolean(panes.bottom) && session.id === panes.bottom
              const visible = inTop || inBottom
              return (
                <div
                  key={session.id}
                  className={visible ? 'min-h-0 w-full' : 'hidden h-full w-full'}
                  style={
                    visible
                      ? inBottom
                        ? { flex: `${1 - splitRatio} 1 0`, order: 2 }
                        : panes.bottom
                          ? { flex: `${splitRatio} 1 0`, order: 0 }
                          : { flex: '1 1 0', order: 0 }
                      : undefined
                  }
                  onMouseDown={() => {
                    if (session.id !== activeSessionId) setActiveSessionId(session.id)
                  }}
                >
                  <div
                    ref={(node) => {
                      sessionNodeRefs.current[session.id] = node
                    }}
                    className="ds-terminal-host h-full w-full"
                  />
                </div>
              )
            })}
            {panes.bottom ? (
              <div
                role="separator"
                aria-orientation="horizontal"
                aria-label={t('terminalSplitResize')}
                title={t('terminalSplitResize')}
                className="ds-terminal-split-handle ds-no-drag group flex h-2 shrink-0 cursor-row-resize items-center justify-center touch-none select-none"
                style={{ order: 1 }}
                onPointerDown={beginSplitResize}
              >
                <span className="pointer-events-none h-0.5 w-8 rounded-full bg-ds-border-strong transition group-hover:w-12 group-hover:bg-ds-accent/70" />
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  )
}
