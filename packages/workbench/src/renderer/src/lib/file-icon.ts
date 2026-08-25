import { getIconForDirectoryPath, getIconForFilePath } from 'vscode-material-icons'

const DEFAULT_FILE_ICON = 'file'
const DEFAULT_FOLDER_ICON = 'folder'

export type MaterialIconOptions = {
  directory?: boolean
  expanded?: boolean
}

function openFolderIconName(name: string): string {
  return name.endsWith('-open') ? name : `${name}-open`
}

export function materialIconNameForPath(path: string, options?: MaterialIconOptions): string {
  const trimmed = path.replace(/[\\/]+$/, '').replace(/\\/g, '/')
  const isDirectory =
    Boolean(options?.directory) || path.endsWith('/') || path.endsWith('\\')
  if (isDirectory) {
    const icon = trimmed ? getIconForDirectoryPath(trimmed) : DEFAULT_FOLDER_ICON
    return options?.expanded ? openFolderIconName(icon) : icon
  }
  if (!trimmed) return DEFAULT_FILE_ICON
  const icon = getIconForFilePath(trimmed)
  if (icon !== DEFAULT_FILE_ICON) return icon
  return getIconForFilePath(trimmed.toLowerCase())
}

export function isMaterialRecognizedFile(path: string): boolean {
  return materialIconNameForPath(path) !== DEFAULT_FILE_ICON
}
