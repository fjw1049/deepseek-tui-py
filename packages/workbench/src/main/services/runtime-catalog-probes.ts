import type { DeepseekRuntimeCatalogProbe } from '../../shared/ds-gui-api'

export type RuntimeProbeResult = {
  ok: boolean
  status: number
  body: string
  message?: string
}

export function parseSkillsProbe(result: RuntimeProbeResult): DeepseekRuntimeCatalogProbe {
  if (!result.ok) {
    return {
      ok: false,
      status: result.status,
      count: null,
      message: result.message || result.body || `HTTP ${result.status}`
    }
  }
  try {
    const parsed = JSON.parse(result.body) as { skills?: unknown[]; warnings?: unknown[] }
    const skills = Array.isArray(parsed.skills) ? parsed.skills : []
    const warnings = Array.isArray(parsed.warnings) ? parsed.warnings : []
    return {
      ok: true,
      status: result.status,
      count: skills.length,
      warningCount: warnings.length
    }
  } catch {
    return {
      ok: false,
      status: result.status,
      count: null,
      message: 'Invalid skills response'
    }
  }
}

export function parseTasksProbe(result: RuntimeProbeResult): DeepseekRuntimeCatalogProbe {
  if (result.status === 503) {
    return {
      ok: false,
      status: 503,
      count: null,
      message: 'Task manager not configured'
    }
  }
  if (!result.ok) {
    return {
      ok: false,
      status: result.status,
      count: null,
      message: result.message || result.body || `HTTP ${result.status}`
    }
  }
  try {
    const parsed = JSON.parse(result.body) as unknown
    const tasks = Array.isArray(parsed) ? parsed : []
    return {
      ok: true,
      status: result.status,
      count: tasks.length
    }
  } catch {
    return {
      ok: false,
      status: result.status,
      count: null,
      message: 'Invalid tasks response'
    }
  }
}

export function parseSessionsProbe(result: RuntimeProbeResult): DeepseekRuntimeCatalogProbe {
  if (!result.ok) {
    return {
      ok: false,
      status: result.status,
      count: null,
      message: result.message || result.body || `HTTP ${result.status}`
    }
  }
  try {
    const parsed = JSON.parse(result.body) as { sessions?: Array<{ kind?: string; import_state?: string }> }
    const sessions = Array.isArray(parsed.sessions) ? parsed.sessions : []
    const tuiCount = sessions.filter((row) => row.kind === 'tui').length
    const linkedCount = sessions.filter((row) => row.import_state === 'linked').length
    return {
      ok: true,
      status: result.status,
      count: tuiCount,
      warningCount: linkedCount
    }
  } catch {
    return {
      ok: false,
      status: result.status,
      count: null,
      message: 'Invalid sessions response'
    }
  }
}
