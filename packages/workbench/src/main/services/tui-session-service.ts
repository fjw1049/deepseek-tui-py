import { readdir, readFile, stat } from 'node:fs/promises'
import { homedir } from 'node:os'
import { basename, join } from 'node:path'

export type TuiSessionSummary = {
  sessionId: string
  path: string
  title: string
  model?: string
  workspace?: string
  messageCount: number
  modifiedAt: string
}

function deepseekHome(): string {
  return process.env.DEEPSEEK_HOME?.trim() || join(homedir(), '.deepseek')
}

function sessionsDir(): string {
  return join(deepseekHome(), 'sessions')
}

function titleFromMetadata(metadata: Record<string, unknown> | undefined, fallback: string): string {
  const title = metadata?.title
  if (typeof title === 'string' && title.trim()) return title.trim()
  const id = metadata?.id
  if (typeof id === 'string' && id.trim()) return `TUI ${id.trim().slice(0, 8)}`
  return fallback
}

export async function listTuiSessions(limit = 40): Promise<TuiSessionSummary[]> {
  const dir = sessionsDir()
  let names: string[] = []
  try {
    names = await readdir(dir)
  } catch {
    return []
  }

  const candidates = names.filter((name) => name.endsWith('.json'))
  const rows: TuiSessionSummary[] = []

  for (const name of candidates) {
    const path = join(dir, name)
    try {
      const fileStat = await stat(path)
      if (!fileStat.isFile()) continue
      const raw = await readFile(path, 'utf8')
      const parsed = JSON.parse(raw) as {
        metadata?: Record<string, unknown>
        messages?: unknown[]
      }
      const metadata =
        parsed.metadata && typeof parsed.metadata === 'object' ? parsed.metadata : undefined
      const messageCount = Array.isArray(parsed.messages) ? parsed.messages.length : 0
      if (messageCount === 0) continue
      const sessionId =
        typeof metadata?.id === 'string' && metadata.id.trim()
          ? metadata.id.trim()
          : basename(name, '.json')
      rows.push({
        sessionId,
        path,
        title: titleFromMetadata(metadata, basename(name, '.json')),
        model: typeof metadata?.model === 'string' ? metadata.model : undefined,
        workspace: typeof metadata?.workspace === 'string' ? metadata.workspace : undefined,
        messageCount,
        modifiedAt: fileStat.mtime.toISOString()
      })
    } catch {
      /* skip unreadable session files */
    }
  }

  rows.sort((a, b) => Date.parse(b.modifiedAt) - Date.parse(a.modifiedAt))
  return rows.slice(0, limit)
}

export function defaultTuiSessionsDir(): string {
  return sessionsDir()
}
