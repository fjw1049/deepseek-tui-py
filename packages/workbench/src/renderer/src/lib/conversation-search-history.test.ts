import { afterEach, describe, expect, it } from 'vitest'
import {
  CONVERSATION_SEARCH_HISTORY_LIMIT,
  clearConversationSearchHistory,
  pushConversationSearchHistory,
  readConversationSearchHistory
} from './conversation-search-history'

afterEach(() => {
  clearConversationSearchHistory()
})

describe('conversation search history', () => {
  it('returns empty when unset', () => {
    expect(readConversationSearchHistory()).toEqual([])
  })

  it('pushes newest first, dedupes case-insensitively, and caps length', () => {
    expect(pushConversationSearchHistory('  Alpha  ')).toEqual(['Alpha'])
    expect(pushConversationSearchHistory('beta')).toEqual(['beta', 'Alpha'])
    expect(pushConversationSearchHistory('alpha')).toEqual(['alpha', 'beta'])
    for (let i = 0; i < CONVERSATION_SEARCH_HISTORY_LIMIT + 2; i += 1) {
      pushConversationSearchHistory(`q${i}`)
    }
    const history = readConversationSearchHistory()
    expect(history).toHaveLength(CONVERSATION_SEARCH_HISTORY_LIMIT)
    expect(history[0]).toBe(`q${CONVERSATION_SEARCH_HISTORY_LIMIT + 1}`)
  })

  it('ignores blank queries', () => {
    pushConversationSearchHistory('keep')
    expect(pushConversationSearchHistory('   ')).toEqual(['keep'])
  })
})
