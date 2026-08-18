import { describe, expect, it } from 'vitest'
import {
  detectGitRemoteProvider,
  githubRepositoryWebUrl,
  isValidGitHubRepositoryNameWithOwner,
  parseGitHubRepositoryNameWithOwnerFromRemoteUrl,
  parseGitRemoteRepository
} from './github-repository'

describe('parseGitHubRepositoryNameWithOwnerFromRemoteUrl', () => {
  it.each([
    ['git@github.com:openai/codex.git', 'openai/codex'],
    ['ssh://git@github.com/openai/codex.git', 'openai/codex'],
    ['https://github.com/openai/codex', 'openai/codex'],
    ['https://github.com/openai/codex.git/', 'openai/codex'],
    ['git://github.com/openai/codex/', 'openai/codex'],
    ['org-12345678@github.com:acme/widgets.git', 'acme/widgets']
  ])('parses %s', (remote, expected) => {
    expect(parseGitHubRepositoryNameWithOwnerFromRemoteUrl(remote)).toBe(expected)
  })

  it.each([
    'https://user:token@github.com/openai/codex',
    'https://github.com/owner',
    'https://github.com/-owner/repo',
    'git@gitlab.com:acme/widgets.git',
    'https://github.com/openai/codex/issues',
    ''
  ])('rejects %s', (remote) => {
    expect(parseGitHubRepositoryNameWithOwnerFromRemoteUrl(remote)).toBeNull()
  })
})

describe('parseGitRemoteRepository', () => {
  it('parses GitHub remotes', () => {
    expect(parseGitRemoteRepository('git@github.com:fjw1049/deepseek-tui-py.git')).toEqual({
      nameWithOwner: 'fjw1049/deepseek-tui-py',
      host: 'github.com',
      provider: 'github',
      url: 'https://github.com/fjw1049/deepseek-tui-py'
    })
  })

  it.each([
    [
      'git@gitlab.com:acme/widgets.git',
      {
        nameWithOwner: 'acme/widgets',
        host: 'gitlab.com',
        provider: 'gitlab',
        url: 'https://gitlab.com/acme/widgets'
      }
    ],
    [
      'https://gitlab.com/group/sub/project.git',
      {
        nameWithOwner: 'group/sub/project',
        host: 'gitlab.com',
        provider: 'gitlab',
        url: 'https://gitlab.com/group/sub/project'
      }
    ],
    [
      'git@gitlab.company.com:team/app.git',
      {
        nameWithOwner: 'team/app',
        host: 'gitlab.company.com',
        provider: 'gitlab',
        url: 'https://gitlab.company.com/team/app'
      }
    ],
    [
      'ssh://git@gitlab.internal.corp:2222/group/sub/app.git',
      {
        nameWithOwner: 'group/sub/app',
        host: 'gitlab.internal.corp',
        provider: 'gitlab',
        url: 'https://gitlab.internal.corp/group/sub/app'
      }
    ],
    [
      'https://git.company.com/platform/checkout.git',
      {
        nameWithOwner: 'platform/checkout',
        host: 'git.company.com',
        provider: 'other',
        url: 'https://git.company.com/platform/checkout'
      }
    ],
    [
      'git@git.company.com:org/team/service.git',
      {
        nameWithOwner: 'org/team/service',
        host: 'git.company.com',
        provider: 'other',
        url: 'https://git.company.com/org/team/service'
      }
    ],
    [
      'https://gitlab.company.com:8443/team/app.git',
      {
        nameWithOwner: 'team/app',
        host: 'gitlab.company.com',
        provider: 'gitlab',
        url: 'https://gitlab.company.com:8443/team/app'
      }
    ]
  ])('parses %s', (remote, expected) => {
    expect(parseGitRemoteRepository(remote)).toEqual(expected)
  })

  it.each([
    'https://user:token@gitlab.com/acme/widgets',
    'https://gitlab.com/acme/widgets/-/issues/1',
    'https://github.com/openai/codex/issues',
    'git@localhost:acme/widgets.git',
    '/local/path/repo.git',
    'https://git.company.com/only-one-segment',
    ''
  ])('rejects %s', (remote) => {
    expect(parseGitRemoteRepository(remote)).toBeNull()
  })
})

describe('detectGitRemoteProvider', () => {
  it('classifies common hosts', () => {
    expect(detectGitRemoteProvider('github.com')).toBe('github')
    expect(detectGitRemoteProvider('gitlab.com')).toBe('gitlab')
    expect(detectGitRemoteProvider('gitlab.company.com')).toBe('gitlab')
    expect(detectGitRemoteProvider('git.company.com')).toBe('other')
  })
})

describe('isValidGitHubRepositoryNameWithOwner', () => {
  it('accepts owner/name', () => {
    expect(isValidGitHubRepositoryNameWithOwner('fjw1049/deepseek-tui-py')).toBe(true)
  })

  it('rejects empty or extra path segments', () => {
    expect(isValidGitHubRepositoryNameWithOwner('owner')).toBe(false)
    expect(isValidGitHubRepositoryNameWithOwner('owner/repo/extra')).toBe(false)
  })
})

describe('githubRepositoryWebUrl', () => {
  it('builds the github.com https URL', () => {
    expect(githubRepositoryWebUrl('fjw1049/deepseek-tui-py')).toBe(
      'https://github.com/fjw1049/deepseek-tui-py'
    )
  })
})
