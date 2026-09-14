import { Columns2, Rows2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { splitTerminalSession, useTerminalSessionStore } from '../store/terminal-session-store'

export function TerminalSplitActions({ workspaceRoot }: { workspaceRoot: string }) {
  const { t } = useTranslation('common')
  const creating = useTerminalSessionStore((s) => s.creatingSession)
  const activeId = useTerminalSessionStore((s) => s.activeSessionId)
  return <>
    {(['right', 'down'] as const).map((direction) => {
      const Icon = direction === 'right' ? Columns2 : Rows2
      const label = t(direction === 'right' ? 'terminalSplitRight' : 'terminalSplitDown')
      return <button key={direction} type="button" title={label} aria-label={label}
        disabled={creating || !activeId}
        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink disabled:opacity-40"
        onClick={() => void splitTerminalSession(workspaceRoot, direction)}>
        <Icon className="h-3.5 w-3.5" strokeWidth={1.85} />
      </button>
    })}
  </>
}
