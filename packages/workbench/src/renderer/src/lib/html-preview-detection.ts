import type { ChatBlock } from '../agent/types'
import { isHtmlPreviewPath } from '@shared/html-preview'
import { findFileReferences } from './file-references'

const MAX_DETECTED_HTML_PATHS = 4

function textFromBlock(block: ChatBlock): string {
  if (block.kind === 'tool') {
    let meta = ''
    try {
      meta = block.meta ? JSON.stringify(block.meta) : ''
    } catch {
      meta = ''
    }
    return [block.summary, block.detail, block.filePath, meta].filter(Boolean).join('\n')
  }
  if (block.kind === 'approval' || block.kind === 'user_input') return ''
  return 'text' in block ? block.text : ''
}

function pushPath(paths: string[], seen: Set<string>, candidate: string): boolean {
  const value = candidate.trim()
  if (!value || !isHtmlPreviewPath(value) || seen.has(value)) return false
  seen.add(value)
  paths.push(value)
  return paths.length >= MAX_DETECTED_HTML_PATHS
}

export function extractDetectedHtmlPreviewPaths(blocks: ChatBlock[]): string[] {
  const paths: string[] = []
  const seen = new Set<string>()

  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    const block = blocks[i]!

    if (block.kind === 'tool') {
      if (block.toolKind === 'file_change' && block.filePath) {
        if (pushPath(paths, seen, block.filePath)) return paths
      }
      // Shell/command output often prints the written path.
      for (const match of findFileReferences(textFromBlock(block))) {
        if (pushPath(paths, seen, match.target.path)) return paths
      }
      continue
    }

    if (block.kind !== 'assistant') continue
    for (const match of findFileReferences(block.text)) {
      if (pushPath(paths, seen, match.target.path)) return paths
    }
  }

  return paths
}

export function extractLatestTurnHtmlPreviewPaths(blocks: ChatBlock[]): string[] {
  let latestUserIndex = -1
  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    if (blocks[i]?.kind === 'user') {
      latestUserIndex = i
      break
    }
  }
  if (latestUserIndex === -1) return []
  return extractDetectedHtmlPreviewPaths(blocks.slice(latestUserIndex + 1))
}

export function formatHtmlPreviewPathLabel(path: string): string {
  const normalized = path.replace(/\\/g, '/')
  const parts = normalized.split('/')
  return parts[parts.length - 1] || normalized
}
