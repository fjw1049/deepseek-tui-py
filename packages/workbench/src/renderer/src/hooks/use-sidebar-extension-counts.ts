import { useEffect, useState } from 'react'
import { listMcpServers } from '../lib/mcp-json-merge'

type ExtensionCounts = {
  plugins: number
  skills: number
  connectors: number
}

const EMPTY: ExtensionCounts = { plugins: 0, skills: 0, connectors: 0 }

export function useSidebarExtensionCounts(workspaceRoot: string): ExtensionCounts {
  const [counts, setCounts] = useState<ExtensionCounts>(EMPTY)

  useEffect(() => {
    let cancelled = false

    const load = async (): Promise<void> => {
      const next = { ...EMPTY }

      if (typeof window.dsGui?.runtimeRequest === 'function') {
        try {
          const qs = workspaceRoot ? `?workspace=${encodeURIComponent(workspaceRoot)}` : ''
          const result = await window.dsGui.runtimeRequest(`/v1/plugins${qs}`, 'GET')
          if (result.ok) {
            const parsed = JSON.parse(result.body) as { plugins?: unknown[] }
            next.plugins = parsed.plugins?.length ?? 0
          }
        } catch {
          /* best-effort badge */
        }
      }

      if (typeof window.dsGui?.getDeepseekPaths === 'function' && typeof window.dsGui?.listSkillsInRoot === 'function') {
        try {
          const paths = await window.dsGui.getDeepseekPaths()
          const skills = await window.dsGui.listSkillsInRoot(paths.skillsDir)
          if (skills.ok) next.skills = skills.skills.length
        } catch {
          /* best-effort badge */
        }
      }

      if (typeof window.dsGui?.getMcpConfigFile === 'function') {
        try {
          const file = await window.dsGui.getMcpConfigFile()
          next.connectors = listMcpServers(file.content).length
        } catch {
          /* best-effort badge */
        }
      }

      if (!cancelled) setCounts(next)
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [workspaceRoot])

  return counts
}
