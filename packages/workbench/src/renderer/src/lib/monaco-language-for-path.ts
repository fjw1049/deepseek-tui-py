export function isMarkdownPath(path: string): boolean {
  const fileName = path.split(/[/\\]/).pop() ?? path
  const ext = fileName.includes('.') ? fileName.split('.').pop()?.toLowerCase() : ''
  return ext === 'md' || ext === 'markdown'
}

export function languageForPath(path: string): string {
  const fileName = path.split(/[/\\]/).pop() ?? path
  const ext = fileName.includes('.') ? fileName.split('.').pop()?.toLowerCase() : ''
  switch (ext) {
    case 'ts':
    case 'tsx':
      return 'typescript'
    case 'js':
    case 'jsx':
    case 'mjs':
    case 'cjs':
      return 'javascript'
    case 'json':
      return 'json'
    case 'md':
    case 'markdown':
      return 'markdown'
    case 'py':
      return 'python'
    case 'css':
      return 'css'
    case 'scss':
      return 'scss'
    case 'less':
      return 'less'
    case 'html':
    case 'htm':
      return 'html'
    case 'yaml':
    case 'yml':
      return 'yaml'
    case 'xml':
      return 'xml'
    case 'sh':
    case 'bash':
      return 'shell'
    case 'go':
      return 'go'
    case 'rs':
      return 'rust'
    case 'toml':
      return 'ini'
    default:
      return 'plaintext'
  }
}
