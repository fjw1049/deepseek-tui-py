export type GitRemoteProvider = 'github' | 'gitlab' | 'other'

export type GitRemoteRepository = {
  nameWithOwner: string
  url: string
  host: string
  provider: GitRemoteProvider
}

export type GitHubRepositoryResult =
  | ({ ok: true } & GitRemoteRepository)
  | {
      ok: false
      reason: 'no_workspace' | 'not_git_repo' | 'no_github_remote' | 'git_unavailable' | 'error'
      message: string
    }

const MAX_PATH_SEGMENTS = 12
const MAX_SEGMENT_LENGTH = 100

function isBlockedHost(host: string): boolean {
  const normalized = host.trim().toLowerCase()
  return (
    normalized === 'localhost' ||
    normalized === '127.0.0.1' ||
    normalized === '0.0.0.0' ||
    normalized === '::1' ||
    normalized.endsWith('.localhost')
  )
}

export function detectGitRemoteProvider(host: string): GitRemoteProvider {
  const normalized = host.trim().toLowerCase()
  if (normalized === 'github.com' || normalized === 'www.github.com') return 'github'
  if (normalized === 'gitlab.com' || normalized.includes('gitlab')) return 'gitlab'
  return 'other'
}

function isValidPathSegment(segment: string): boolean {
  if (segment.length === 0 || segment.length > MAX_SEGMENT_LENGTH) return false
  if (segment === '.' || segment === '..' || segment === '-') return false
  return /^[A-Za-z0-9._-]+$/.test(segment)
}

export function isValidGitRemoteRepositoryPath(path: string, provider: GitRemoteProvider): boolean {
  const segments = path.split('/')
  if (segments.length < 2 || segments.length > MAX_PATH_SEGMENTS) return false
  if (provider === 'github' && segments.length !== 2) return false
  if (provider === 'github') {
    const [owner, name] = segments
    return (
      Boolean(owner) &&
      Boolean(name) &&
      /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/.test(owner ?? '') &&
      isValidPathSegment(name ?? '') &&
      name !== '.' &&
      name !== '..'
    )
  }
  return segments.every(isValidPathSegment)
}

/** Conservative validation for the GitHub.com `owner/repository` form. */
export function isValidGitHubRepositoryNameWithOwner(repository: string): boolean {
  return isValidGitRemoteRepositoryPath(repository.trim(), 'github')
}

function normalizeRemotePath(rawPath: string): string | null {
  const trimmed = rawPath.trim().replace(/^\/+/, '').replace(/\/+$/, '')
  if (!trimmed) return null
  return trimmed.replace(/\.git$/i, '')
}

function repositoryFromHostPath(
  host: string,
  rawPath: string,
  webPort?: string
): GitRemoteRepository | null {
  const normalizedHost = host.trim().toLowerCase()
  if (!normalizedHost || isBlockedHost(normalizedHost) || !normalizedHost.includes('.')) {
    return null
  }

  const path = normalizeRemotePath(rawPath)
  if (!path) return null

  const provider = detectGitRemoteProvider(normalizedHost)
  if (!isValidGitRemoteRepositoryPath(path, provider)) return null

  const webHost = normalizedHost === 'www.github.com' ? 'github.com' : normalizedHost
  const origin =
    webPort && webPort !== '443' && webPort !== '80'
      ? `https://${webHost}:${webPort}`
      : `https://${webHost}`
  return {
    nameWithOwner: path,
    host: webHost,
    provider: detectGitRemoteProvider(webHost),
    url: `${origin}/${path}`
  }
}

function parseScpLikeRemote(url: string): GitRemoteRepository | null {
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(url)) return null
  const match = /^(?:([\w.-]+)@)?((?:[\w-]+\.)+[\w-]+):(.+)$/.exec(url)
  if (!match) return null
  return repositoryFromHostPath(match[2] ?? '', match[3] ?? '')
}

function parseSchemeRemote(url: string): GitRemoteRepository | null {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }

  if (parsed.search || parsed.hash) return null

  const protocol = parsed.protocol.toLowerCase()
  if (protocol !== 'https:' && protocol !== 'http:' && protocol !== 'ssh:' && protocol !== 'git:') {
    return null
  }

  // HTTPS remotes with embedded credentials are unsafe to surface. SSH's
  // `git@host` username is the normal transport identity, not a secret.
  if ((protocol === 'https:' || protocol === 'http:') && (parsed.username || parsed.password)) {
    return null
  }
  if (parsed.password) return null

  const webPort =
    (protocol === 'https:' || protocol === 'http:') && parsed.port ? parsed.port : undefined
  return repositoryFromHostPath(parsed.hostname, parsed.pathname, webPort)
}

/** Parse a git remote into a browsable repository identity. */
export function parseGitRemoteRepository(url: string | null | undefined): GitRemoteRepository | null {
  const trimmed = url?.trim() ?? ''
  if (trimmed.length === 0) return null
  return parseSchemeRemote(trimmed) ?? parseScpLikeRemote(trimmed)
}

/**
 * Normalize a supported GitHub remote URL into `owner/repository`.
 * Rejects credential-bearing HTTPS remotes and non-github.com hosts.
 */
export function parseGitHubRepositoryNameWithOwnerFromRemoteUrl(
  url: string | null | undefined
): string | null {
  const parsed = parseGitRemoteRepository(url)
  return parsed?.provider === 'github' ? parsed.nameWithOwner : null
}

export function githubRepositoryWebUrl(nameWithOwner: string): string {
  return `https://github.com/${nameWithOwner}`
}
