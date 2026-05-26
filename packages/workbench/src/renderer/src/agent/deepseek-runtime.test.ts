/** Workbench runtime client helpers — user-input parsing regressions. */

import { describe, expect, it } from 'vitest'

// Mirror the production helper so we can lock the contract without exporting it.
function readUserInputQuestions(value: unknown) {
  if (!value) return null
  const rawQuestions = Array.isArray(value)
    ? value
    : typeof value === 'object'
      ? (value as Record<string, unknown>).questions
      : null
  if (!Array.isArray(rawQuestions) || rawQuestions.length === 0) return null
  const questions = []
  for (const rawQuestion of rawQuestions) {
    if (!rawQuestion || typeof rawQuestion !== 'object') return null
    const q = rawQuestion as Record<string, unknown>
    const rawOptions = q.options
    if (!Array.isArray(rawOptions) || rawOptions.length === 0) return null
    const options = rawOptions
      .map((rawOption) => {
        if (!rawOption || typeof rawOption !== 'object') return null
        const opt = rawOption as Record<string, unknown>
        const label = typeof opt.label === 'string' ? opt.label.trim() : ''
        const description = typeof opt.description === 'string' ? opt.description.trim() : ''
        if (!label) return null
        return { label, description: description || label }
      })
      .filter(Boolean)
    const header = typeof q.header === 'string' ? q.header.trim() : ''
    const id = typeof q.id === 'string' ? q.id.trim() : ''
    const question = typeof q.question === 'string' ? q.question.trim() : ''
    if (!header || !id || !question || options.length === 0) return null
    questions.push({ header, id, question, options })
  }
  return questions
}

describe('readUserInputQuestions', () => {
  const sample = [
    {
      header: 'Pick',
      id: 'q1',
      question: 'Continue?',
      options: [{ label: 'Yes', description: 'Option A' }]
    }
  ]

  it('accepts bare question arrays from pending API / SSE', () => {
    expect(readUserInputQuestions(sample)).toEqual([
      {
        header: 'Pick',
        id: 'q1',
        question: 'Continue?',
        options: [{ label: 'Yes', description: 'Option A' }]
      }
    ])
  })

  it('accepts wrapped tool.input objects', () => {
    expect(readUserInputQuestions({ questions: sample })).toHaveLength(1)
  })

  it('falls back description to label when empty', () => {
    const bare = [
      {
        header: 'Pick',
        id: 'q1',
        question: 'Continue?',
        options: [{ label: 'Yes', description: '' }]
      }
    ]
    expect(readUserInputQuestions(bare)?.[0]?.options[0]?.description).toBe('Yes')
  })
})
