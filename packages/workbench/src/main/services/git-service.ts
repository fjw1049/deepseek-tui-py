import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { GitBranchesResult } from '../../shared/git-branches'
import type {
  GitWorkingChangeFile,
  GitWorkingChangeStatus,
  GitWorkingChangesResult
} from '../../shared/git-working-changes'

const execFileAsync = promisify(execFile)
const DIFF_MAX_BUFFER = 50 * 1024 * 1024

async function runGit(
  cwd: string,
  args: string[],
  timeout = 10_000,
  maxBuffer = 1024 * 1024
): Promise<{ stdout: string; stderr: string }> {
  const { stdout, stderr } = await execFileAsync('git', args, {
    cwd,
    timeout,
    maxBuffer
  })
  return { stdout: String(stdout), stderr: String(stderr) }
}

async function runGitStdout(
  cwd: string,
  args: string[],
  options?: { timeout?: number; maxBuffer?: number; allowNonZero?: boolean }
): Promise<string> {
  const timeout = options?.timeout ?? 10_000
  const maxBuffer = options?.maxBuffer ?? 1024 * 1024
  try {
    const { stdout } = await execFileAsync('git', args, { cwd, timeout, maxBuffer })
    return String(stdout)
  } catch (error) {
    if (options?.allowNonZero && error && typeof error === 'object' && 'stdout' in error) {
      return String((error as { stdout: unknown }).stdout ?? '')
    }
    throw error
  }
}

function gitFailure(error: unknown): GitBranchesResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

function gitWorkingChangesFailure(error: unknown): GitWorkingChangesResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

function unquoteGitPath(raw: string): string {
  const trimmed = raw.trim()
  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    return trimmed
      .slice(1, -1)
      .replace(/\\(["\\])/g, '$1')
  }
  return trimmed
}

function parsePorcelainEntry(line: string): { path: string; status: GitWorkingChangeStatus } | null {
  if (line.length < 4) return null

  const indexStatus = line[0] ?? ' '
  const workTreeStatus = line[1] ?? ' '
  let pathPart = unquoteGitPath(line.slice(3))
  if (!pathPart) return null

  if (pathPart.includes(' -> ')) {
    const parts = pathPart.split(' -> ')
    pathPart = unquoteGitPath(parts[parts.length - 1] ?? pathPart)
  }

  const statusKey = `${indexStatus}${workTreeStatus}`
  let status: GitWorkingChangeStatus = 'modified'
  if (statusKey === '??') status = 'untracked'
  else if (indexStatus === 'A' || workTreeStatus === 'A') status = 'added'
  else if (indexStatus === 'D' || workTreeStatus === 'D') status = 'deleted'
  else if (indexStatus === 'R' || workTreeStatus === 'R') status = 'renamed'
  else if (indexStatus === 'C' || workTreeStatus === 'C') status = 'copied'

  return { path: pathPart, status }
}

function splitUnifiedDiff(patch: string): Map<string, string> {
  const byPath = new Map<string, string>()
  const trimmed = patch.trim()
  if (!trimmed) return byPath

  const chunks = trimmed.split(/^diff --git /m).filter(Boolean)
  for (const chunk of chunks) {
    const fullPatch = `diff --git ${chunk}`.trimEnd()
    const header = fullPatch.split('\n')[0] ?? ''
    const match = header.match(/ b\/(.+)$/)
    const path = match?.[1]?.trim()
    if (!path) continue
    byPath.set(path, fullPatch)
  }

  return byPath
}

export async function getGitBranches(workspaceRoot: string): Promise<GitBranchesResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }
  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    const currentRaw = (await runGit(cwd, ['branch', '--show-current'])).stdout.trim()
    const currentBranch = currentRaw || null
    const branchLines = (await runGit(cwd, ['branch', '--format=%(refname:short)'])).stdout
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    const branchSet = new Set(branchLines)
    if (currentBranch && !branchSet.has(currentBranch)) branchSet.add(currentBranch)
    const branches = [...branchSet].map((name) => ({
      name,
      current: currentBranch === name
    }))
    const dirtyCount = (await runGit(cwd, ['status', '--porcelain=v1'])).stdout
      .split('\n')
      .filter((line) => line.trim().length > 0).length
    return { ok: true, repositoryRoot, currentBranch, branches, dirtyCount }
  } catch (error) {
    return gitFailure(error)
  }
}

export async function switchGitBranch(
  workspaceRoot: string,
  branchName: string
): Promise<GitBranchesResult> {
  const cwd = workspaceRoot.trim()
  const branch = branchName.trim()
  if (!cwd) return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  if (!branch) return { ok: false, reason: 'error', message: 'Branch name is required.' }
  try {
    try {
      await runGit(cwd, ['switch', branch], 20_000)
    } catch {
      await runGit(cwd, ['checkout', branch], 20_000)
    }
    return getGitBranches(cwd)
  } catch (error) {
    return gitFailure(error)
  }
}

export async function getGitWorkingChanges(workspaceRoot: string): Promise<GitWorkingChangesResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }

  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    const porcelainLines = (await runGit(cwd, ['status', '--porcelain=v1'])).stdout
      .split('\n')
      .map((line) => line.trimEnd())
      .filter((line) => line.trim().length > 0)

    const entries = porcelainLines
      .map((line) => parsePorcelainEntry(line))
      .filter((entry): entry is { path: string; status: GitWorkingChangeStatus } => entry !== null)

    if (entries.length === 0) {
      return { ok: true, repositoryRoot, files: [] }
    }

    const trackedDiff = await runGitStdout(cwd, ['diff', 'HEAD', '--no-color'], {
      timeout: 30_000,
      maxBuffer: DIFF_MAX_BUFFER,
      allowNonZero: true
    })
    const patchByPath = splitUnifiedDiff(trackedDiff)
    const files: GitWorkingChangeFile[] = []

    for (const entry of entries) {
      let patch = ''
      try {
        if (entry.status === 'untracked') {
          patch = await runGitStdout(
            cwd,
            ['diff', '--no-index', '--no-color', '/dev/null', entry.path],
            { timeout: 20_000, maxBuffer: DIFF_MAX_BUFFER, allowNonZero: true }
          )
        } else {
          patch =
            patchByPath.get(entry.path) ??
            (await runGitStdout(cwd, ['diff', 'HEAD', '--no-color', '--', entry.path], {
              timeout: 20_000,
              maxBuffer: DIFF_MAX_BUFFER,
              allowNonZero: true
            }))
        }
      } catch {
        patch = ''
      }

      files.push({
        path: entry.path,
        status: entry.status,
        patch: patch.trimEnd()
      })
    }

    files.sort((a, b) => a.path.localeCompare(b.path))
    return { ok: true, repositoryRoot, files }
  } catch (error) {
    return gitWorkingChangesFailure(error)
  }
}

export async function createAndSwitchGitBranch(
  workspaceRoot: string,
  branchName: string
): Promise<GitBranchesResult> {
  const cwd = workspaceRoot.trim()
  const branch = branchName.trim()
  if (!cwd) return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  if (!branch) return { ok: false, reason: 'error', message: 'Branch name is required.' }
  try {
    await runGit(cwd, ['check-ref-format', '--branch', branch])
    try {
      await runGit(cwd, ['switch', '-c', branch], 20_000)
    } catch {
      await runGit(cwd, ['checkout', '-b', branch], 20_000)
    }
    return getGitBranches(cwd)
  } catch (error) {
    return gitFailure(error)
  }
}
