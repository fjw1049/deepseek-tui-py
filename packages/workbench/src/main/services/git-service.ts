import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { GitCommitMessageSuggestionResult, GitCommitResult } from '../../shared/git-commit'
import type { GitLogCommit, GitLogResult, GitLogUpstream } from '../../shared/git-log'
import type { GitBranchesResult } from '../../shared/git-branches'
import type {
  GitWorkingChangeFile,
  GitWorkingChangeStage,
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

function resolveGitStage(indexStatus: string, workTreeStatus: string): GitWorkingChangeStage {
  const indexDirty = indexStatus !== ' ' && indexStatus !== '?'
  const workTreeDirty = workTreeStatus !== ' ' && workTreeStatus !== '?'
  if (indexDirty && workTreeDirty) return 'partial'
  if (indexDirty) return 'staged'
  return 'unstaged'
}

function parsePorcelainEntry(
  line: string
): { path: string; status: GitWorkingChangeStatus; stage: GitWorkingChangeStage } | null {
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

  return { path: pathPart, status, stage: resolveGitStage(indexStatus, workTreeStatus) }
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

function isDirtyWorktreeError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return (
    /would be overwritten by (checkout|merge)/i.test(message) ||
    /commit your changes or stash them/i.test(message)
  )
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
    } catch (switchError) {
      if (isDirtyWorktreeError(switchError)) throw switchError
      await runGit(cwd, ['checkout', branch], 20_000)
    }
    return getGitBranches(cwd)
  } catch (error) {
    if (isDirtyWorktreeError(error)) {
      return {
        ok: false,
        reason: 'dirty_worktree',
        message: error instanceof Error ? error.message : String(error)
      }
    }
    return gitFailure(error)
  }
}

export async function stashAndSwitchGitBranch(
  workspaceRoot: string,
  branchName: string
): Promise<GitBranchesResult> {
  const cwd = workspaceRoot.trim()
  const branch = branchName.trim()
  if (!cwd) return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  if (!branch) return { ok: false, reason: 'error', message: 'Branch name is required.' }
  try {
    const stashMessage = `workbench: auto stash before switching to ${branch}`
    const pushResult = await runGit(
      cwd,
      ['stash', 'push', '--include-untracked', '-m', stashMessage],
      30_000
    )
    const stashed = !/No local changes to save/i.test(pushResult.stdout)

    try {
      try {
        await runGit(cwd, ['switch', branch], 20_000)
      } catch {
        await runGit(cwd, ['checkout', branch], 20_000)
      }
    } catch (switchError) {
      // Restore the user's changes on the original branch before reporting.
      if (stashed) {
        try {
          await runGit(cwd, ['stash', 'pop'], 30_000)
        } catch {
          // Leave the stash in place; it is still recoverable via `git stash pop`.
        }
      }
      throw switchError
    }

    if (stashed) {
      try {
        await runGit(cwd, ['stash', 'pop'], 30_000)
      } catch (popError) {
        return {
          ok: false,
          reason: 'stash_pop_conflict',
          message: popError instanceof Error ? popError.message : String(popError)
        }
      }
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
      .filter(
        (
          entry
        ): entry is {
          path: string
          status: GitWorkingChangeStatus
          stage: GitWorkingChangeStage
        } => entry !== null
      )

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
        stage: entry.stage,
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

const GIT_PATH_BATCH_SIZE = 50

function isSafeGitPath(path: string): boolean {
  const normalized = path.replace(/\\/g, '/').trim()
  if (!normalized || normalized.startsWith('/') || normalized.includes('\0')) return false
  return !normalized.split('/').some((part) => part === '..')
}

function gitCommitFailure(error: unknown): GitCommitResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

async function hasStagedChanges(cwd: string): Promise<boolean> {
  try {
    await runGit(cwd, ['diff', '--cached', '--quiet'], 10_000)
    return false
  } catch {
    return true
  }
}

async function stageGitPaths(cwd: string, paths: string[]): Promise<void> {
  for (let index = 0; index < paths.length; index += GIT_PATH_BATCH_SIZE) {
    const batch = paths.slice(index, index + GIT_PATH_BATCH_SIZE)
    await runGit(cwd, ['add', '--', ...batch], 60_000)
  }
}

export async function commitGitChanges(
  workspaceRoot: string,
  message: string,
  paths?: string[]
): Promise<GitCommitResult> {
  const cwd = workspaceRoot.trim()
  const commitMessage = message.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }
  if (!commitMessage) {
    return { ok: false, reason: 'invalid_message', message: 'Commit message is required.' }
  }

  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    let targetPaths = paths?.map((path) => path.trim()).filter(Boolean) ?? []

    if (targetPaths.length === 0) {
      const changes = await getGitWorkingChanges(cwd)
      if (!changes.ok) {
        return { ok: false, reason: changes.reason, message: changes.message }
      }
      targetPaths = changes.files.map((file) => file.path)
    }

    const safePaths = [...new Set(targetPaths.filter(isSafeGitPath))]
    if (safePaths.length === 0) {
      return { ok: false, reason: 'nothing_to_commit', message: 'No changes to commit.' }
    }

    await stageGitPaths(cwd, safePaths)

    if (!(await hasStagedChanges(cwd))) {
      return { ok: false, reason: 'nothing_to_commit', message: 'No changes staged for commit.' }
    }

    await runGit(cwd, ['commit', '-m', commitMessage], 60_000)
    const commitHash = (await runGit(cwd, ['rev-parse', '--short', 'HEAD'])).stdout.trim()
    const summary = (await runGit(cwd, ['show', '-s', '--format=%s', 'HEAD'])).stdout.trim()

    return {
      ok: true,
      repositoryRoot,
      commitHash,
      summary,
      fileCount: safePaths.length
    }
  } catch (error) {
    return gitCommitFailure(error)
  }
}

function gitPathBasename(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || path
}

function gitMessageSuggestionFailure(error: unknown): GitCommitMessageSuggestionResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

export async function suggestGitCommitMessage(
  workspaceRoot: string,
  paths?: string[]
): Promise<GitCommitMessageSuggestionResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }

  try {
    const changes = await getGitWorkingChanges(cwd)
    if (!changes.ok) {
      return { ok: false, reason: changes.reason, message: changes.message }
    }

    let targetFiles = changes.files
    if (paths && paths.length > 0) {
      const allowed = new Set(paths)
      targetFiles = targetFiles.filter((file) => allowed.has(file.path))
    }
    if (targetFiles.length === 0) {
      return { ok: false, reason: 'nothing_to_commit', message: 'No changes to suggest for.' }
    }

    if (targetFiles.length === 1) {
      const file = targetFiles[0]!
      const name = gitPathBasename(file.path)
      const message =
        file.status === 'added' || file.status === 'untracked' || file.status === 'copied'
          ? `Add ${name}`
          : file.status === 'deleted'
            ? `Remove ${name}`
            : `Update ${name}`
      return { ok: true, message }
    }

    let added = 0
    let deleted = 0
    let modified = 0
    for (const file of targetFiles) {
      if (file.status === 'added' || file.status === 'untracked' || file.status === 'copied') {
        added += 1
      } else if (file.status === 'deleted') {
        deleted += 1
      } else {
        modified += 1
      }
    }

    const summaryParts: string[] = []
    if (added > 0) summaryParts.push(`add ${added} file(s)`)
    if (modified > 0) summaryParts.push(`update ${modified} file(s)`)
    if (deleted > 0) summaryParts.push(`remove ${deleted} file(s)`)

    const headline =
      summaryParts.length === 1
        ? summaryParts[0]!.charAt(0).toUpperCase() + summaryParts[0]!.slice(1)
        : `Update ${targetFiles.length} files`

    const listing = targetFiles
      .slice(0, 5)
      .map((file) => `- ${file.path}`)
      .join('\n')
    const remainder =
      targetFiles.length > 5 ? `\n- …and ${targetFiles.length - 5} more` : ''

    return { ok: true, message: `${headline}\n\n${listing}${remainder}` }
  } catch (error) {
    return gitMessageSuggestionFailure(error)
  }
}

const GIT_LOG_LIMIT = 200

function gitLogFailure(error: unknown): GitLogResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

async function tryGitStdout(cwd: string, args: string[]): Promise<string | null> {
  try {
    return (await runGit(cwd, args)).stdout.trim()
  } catch {
    return null
  }
}

function parseGitLogLine(line: string): GitLogCommit | null {
  const parts = line.split('\0')
  if (parts.length < 5) return null
  const [hash, parentsRaw, subject, author, atRaw] = parts
  if (!hash || !subject || !author || !atRaw) return null
  const authoredAtMs = Number(atRaw) * 1000
  if (!Number.isFinite(authoredAtMs)) return null
  return {
    hash,
    shortHash: hash.slice(0, 7),
    parents: parentsRaw.split(' ').filter(Boolean),
    subject,
    author,
    authoredAt: new Date(authoredAtMs).toISOString()
  }
}

async function readGitUpstream(cwd: string): Promise<GitLogUpstream | null> {
  const upstreamRef = await tryGitStdout(cwd, ['rev-parse', '--abbrev-ref', '@{upstream}'])
  if (!upstreamRef || upstreamRef === '@{upstream}') return null

  const upstreamHash = await tryGitStdout(cwd, ['rev-parse', '@{upstream}'])
  if (!upstreamHash) return null

  const countRaw = await runGitStdout(cwd, ['rev-list', '--left-right', '--count', 'HEAD...@{upstream}'], {
    allowNonZero: true
  })
  const [aheadRaw, behindRaw] = countRaw.trim().split(/\s+/)
  const ahead = Number(aheadRaw)
  const behind = Number(behindRaw)

  return {
    ref: upstreamRef,
    hash: upstreamHash,
    ahead: Number.isFinite(ahead) ? ahead : 0,
    behind: Number.isFinite(behind) ? behind : 0
  }
}

export async function getGitLog(workspaceRoot: string): Promise<GitLogResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }

  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    const currentBranch = (await runGit(cwd, ['branch', '--show-current'])).stdout.trim() || null
    const headHash = (await runGit(cwd, ['rev-parse', 'HEAD'])).stdout.trim()
    const upstream = await readGitUpstream(cwd)
    const logRef = currentBranch ?? 'HEAD'
    const raw = await runGitStdout(cwd, [
      'log',
      `--topo-order`,
      `-n${GIT_LOG_LIMIT}`,
      logRef,
      '--format=%H%x00%P%x00%s%x00%an%x00%at'
    ])
    const commits = raw
      .split('\n')
      .map((line) => parseGitLogLine(line.trim()))
      .filter((entry): entry is GitLogCommit => entry !== null)

    return {
      ok: true,
      repositoryRoot,
      branch: currentBranch,
      headHash,
      upstream,
      commits
    }
  } catch (error) {
    return gitLogFailure(error)
  }
}
