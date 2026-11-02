import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AppSettingsV1 } from '../../shared/app-settings'
import {
  buildPetReactionMessages,
  cleanPetReactionLine,
  pickPetReactionModel,
  requestPetReaction
} from './pet-reaction-service'

function settings(patch: { apiKey?: string; models?: string[]; deepseekKey?: string } = {}): AppSettingsV1 {
  return {
    defaultLlmProviderId: 'deepseek',
    deepseek: { apiKey: patch.deepseekKey ?? '' },
    llmProviders: {
      deepseek: {
        apiKey: patch.apiKey ?? 'sk-test',
        models: (patch.models ?? []).map(id => ({ id, enabled: true, contextWindow: 128_000 }))
      }
    }
  } as unknown as AppSettingsV1
}

const request = { reason: 'petted' as const, petName: 'Boba', locale: 'zh-CN', recent: ['嘿嘿'], context: 'user: hi' }

afterEach(() => vi.unstubAllGlobals())

describe('pickPetReactionModel', () => {
  it('prefers a light model and the built-in base URL', () => {
    expect(pickPetReactionModel(settings({ models: ['deepseek-v4-pro'] }))).toEqual({
      model: 'deepseek-v4-flash', apiKey: 'sk-test', baseUrl: 'https://api.deepseek.com'
    })
  })

  it('falls back to the legacy DeepSeek key and gives up without any key', () => {
    expect(pickPetReactionModel(settings({ apiKey: '', deepseekKey: 'sk-old' }))?.apiKey).toBe('sk-old')
    vi.stubEnv('DEEPSEEK_API_KEY', '')
    expect(pickPetReactionModel(settings({ apiKey: '' }))).toBeNull()
    vi.unstubAllEnvs()
  })
})

describe('buildPetReactionMessages', () => {
  it('asks for one short line in the UI language without repeating itself', () => {
    const [system, user] = buildPetReactionMessages(request)
    expect(system!.content).toContain('Simplified Chinese')
    expect(system!.content).toContain('Boba')
    expect(user!.content).toContain('嘿嘿')
    expect(user!.content).toContain('user: hi')
  })
})

describe('cleanPetReactionLine', () => {
  it('keeps the first visible line without quotes or reasoning', () => {
    expect(cleanPetReactionLine('<think>hmm</think>\n「又被摸了」\nsecond')).toBe('又被摸了')
    expect(cleanPetReactionLine('   ')).toBeNull()
    expect(cleanPetReactionLine('x'.repeat(80))).toHaveLength(60)
  })
})

describe('requestPetReaction', () => {
  it('posts a small request and returns the cleaned line', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ choices: [{ message: { content: '"嘿嘿～"' } }] })))
    vi.stubGlobal('fetch', fetchMock)
    await expect(requestPetReaction(settings(), request)).resolves.toEqual({ ok: true, text: '嘿嘿～' })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://api.deepseek.com/v1/chat/completions')
    expect(JSON.parse(init.body as string)).toMatchObject({ model: 'deepseek-v4-flash', max_tokens: 300, stream: false })
  })

  it('reports HTTP failures instead of throwing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('no', { status: 401 })))
    await expect(requestPetReaction(settings(), request)).resolves.toEqual({ ok: false, message: 'HTTP 401' })
  })
})
