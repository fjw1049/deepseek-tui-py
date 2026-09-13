import type { WorkspaceTreeEntry } from '@shared/workspace-file'

const auxiliaryDirectories = new Set([
  '.git', '.hg', '.svn', 'node_modules', 'dist', 'out', 'build', '.next', 'coverage',
  '.venv', 'venv', '__pycache__', '.mypy_cache', '.pytest_cache', '.ruff_cache', '.cache'
])

/** Hide generated material, not dotfiles or project configuration in general. */
export function isAuxiliaryWorkspaceEntry(entry: WorkspaceTreeEntry): boolean {
  return entry.kind === 'directory'
    ? auxiliaryDirectories.has(entry.name) || entry.name.startsWith('.node_modules_trash_')
    : entry.name === '.DS_Store' || entry.name === 'Thumbs.db' || entry.name.startsWith('._')
}
