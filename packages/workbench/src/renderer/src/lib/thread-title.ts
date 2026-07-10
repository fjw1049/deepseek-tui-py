import type { NormalizedThread } from '../agent/types'
import i18n from '../i18n'
import { parseUserFocusPrefix } from './user-focus-prefix'

const LEGACY_PLACEHOLDER_TITLES = new Set(['New Thread', '新会话'])
const MAX_THREAD_TITLE_LENGTH = 48

function normalizeTitleLine(line: string): string {
  return line
    .replace(/^#{1,6}\s+/, '')
    .replace(/^>\s+/, '')
    .replace(/^[-*+]\s+/, '')
    .replace(/^\d+[.)]\s+/, '')
    .replace(/`+/g, '')
    .replace(/\[(.*?)\]\((.*?)\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

function stripTrailingPunctuation(text: string): string {
  return text.replace(/[\s,.;:!?，。；：！？、'"`()[\]{}]+$/g, '').trim()
}

function shortenTitle(text: string): string {
  if (text.length <= MAX_THREAD_TITLE_LENGTH) return text
  return text.slice(0, MAX_THREAD_TITLE_LENGTH).trim()
}

export function getDefaultThreadTitle(): string {
  return i18n.t('common:untitledThread')
}

export function deriveThreadTitleFromPrompt(prompt: string): string {
  const fallback = getDefaultThreadTitle()
  // Strip focus prefixes (@plugin:, /skill, @connector) so the sidebar title
  // shows the user's actual question, not the raw wire command.
  const focus = parseUserFocusPrefix(prompt)
  const cleanPrompt = focus ? focus.body || focus.name : prompt
  const lines = cleanPrompt
    .split(/\r?\n/)
    .filter((line) => !/^\s*(```|~~~)/.test(line))
    .map((line) => normalizeTitleLine(line))
    .filter((line) => line)

  const firstLine = lines[0] ?? normalizeTitleLine(prompt)
  if (!firstLine) return fallback

  const sentenceBreak = firstLine.search(/[。！？.!?]/)
  const core = sentenceBreak >= 8 ? firstLine.slice(0, sentenceBreak) : firstLine
  const trimmed = stripTrailingPunctuation(shortenTitle(core))
  return trimmed || fallback
}

export function shouldAutoTitleThread(
  thread: Pick<NormalizedThread, 'id' | 'title'> | null | undefined
): boolean {
  const raw = thread?.title?.trim() ?? ''
  if (!raw) return true
  if (raw === getDefaultThreadTitle()) return true
  if (LEGACY_PLACEHOLDER_TITLES.has(raw)) return true
  if (thread && raw === thread.id.slice(0, 8)) return true
  return false
}
