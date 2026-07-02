import { describe, expect, it } from 'vitest'
import {
  AUTOMATION_COMPOSER_HEADING,
  CLAW_CURRENT_USER_REQUEST_HEADING,
  buildAutomationComposerPrompt,
  mergeMemorySettings,
  normalizeAppSettings,
  normalizeCustomEndpoints,
  normalizeUiFontFamily,
  unwrapAutomationComposerPromptForDisplay,
  unwrapClawUserPromptForDisplay
} from './app-settings'

describe('unwrapAutomationComposerPromptForDisplay', () => {
  it('migrates one-model endpoints to provider models without losing credentials', () => {
    const endpoints = normalizeCustomEndpoints([
      {
        name: 'Qingyun',
        baseUrl: 'https://api.example.test',
        apiKey: 'test-key',
        model: 'claude-sonnet',
        active: true
      }
    ])

    expect(endpoints).toEqual([
      {
        id: 'qingyun-1',
        name: 'Qingyun',
        protocol: 'openai',
        baseUrl: 'https://api.example.test',
        apiKey: 'test-key',
        enabled: true,
        models: [
          {
            id: 'claude-sonnet',
            label: undefined,
            enabled: true,
            testStatus: 'untested',
            toolCalling: undefined,
            lastTestedAt: undefined
          }
        ]
      }
    ])
  })

  it('keeps multiple models on one endpoint and removes duplicate ids', () => {
    const [endpoint] = normalizeCustomEndpoints([
      {
        id: 'ark',
        name: 'Ark',
        protocol: 'anthropic',
        baseUrl: 'https://ark.example',
        apiKey: 'test-key',
        models: [
          { id: 'model-a', enabled: true, testStatus: 'passed' },
          { id: 'model-a', enabled: true },
          { id: 'model-b', enabled: false }
        ]
      }
    ])

    expect(endpoint.protocol).toBe('anthropic')
    expect(endpoint.models.map((model) => model.id)).toEqual(['model-a', 'model-b'])
  })

  it('reserves the built-in DeepSeek provider id', () => {
    const [endpoint] = normalizeCustomEndpoints([
      { id: 'deepseek', name: 'DeepSeek proxy', models: [] }
    ])
    expect(endpoint.id).toBe('deepseek-2')
  })

  it('strips playbook wrapper and keeps user text only', () => {
    const wrapped = buildAutomationComposerPrompt('一分钟后发到飞书', {
      feishuChatId: 'oc_test',
      userTimezone: 'Asia/Shanghai'
    })
    expect(wrapped).toContain(AUTOMATION_COMPOSER_HEADING)
    expect(unwrapClawUserPromptForDisplay(wrapped)).toBe('一分钟后发到飞书')
    expect(unwrapAutomationComposerPromptForDisplay(wrapped)).toBe('一分钟后发到飞书')
  })

  it('leaves ordinary messages unchanged', () => {
    const plain = '普通对话消息'
    expect(unwrapClawUserPromptForDisplay(plain)).toBe(plain)
  })

  it('playbook forbids tool_search and lists direct tool names', () => {
    const wrapped = buildAutomationComposerPrompt('两分钟后总结', {
      feishuChatId: 'oc_test',
      userTimezone: 'Asia/Shanghai'
    })
    expect(wrapped).toContain('Do NOT call tool_search_tool_regex')
    expect(wrapped).toContain('current_time')
    expect(wrapped).toContain('automation_create')
  })

  it('normalizes memory settings with safe defaults and clamps risky values', () => {
    const normalized = normalizeAppSettings({
      version: 1,
      locale: 'en',
      theme: 'system',
      uiFontScale: 'small',
      uiFontFamily: 'inter-noto',
      agentProvider: 'deepseek-runtime',
      workspaceRoot: '',
      deepseek: {
        binaryPath: '',
        port: 7878,
        autoStart: true,
        apiKey: '',
        baseUrl: '',
        runtimeToken: '',
        extraCorsOrigins: [],
        approvalPolicy: 'on-request',
        sandboxMode: 'workspace-write'
      },
      log: { enabled: true, retentionDays: 2 },
      notifications: { turnComplete: true },
      skills: { extraDirs: [] },
      memory: {
        enabled: true,
        mode: 'auto',
        smart: {
          enabled: true,
          recallLimit: 999,
          recallScoreThreshold: 2,
          captureMinUserChars: -1,
          embeddingProvider: 'openai'
        }
      },
      claw: undefined,
      guiUpdate: { channel: 'frontier' }
    } as never)

    expect(normalized.memory.enabled).toBe(true)
    expect(normalized.memory.mode).toBe('auto')
    expect(normalized.memory.smart.enabled).toBe(true)
    expect(normalized.memory.smart.recallLimit).toBe(20)
    expect(normalized.memory.smart.recallScoreThreshold).toBe(1)
    expect(normalized.memory.smart.captureMinUserChars).toBe(0)
    expect(normalized.memory.smart.embeddingProvider).toBe('openai')
  })

  it('merges memory patches even when old settings have no memory block', () => {
    const merged = mergeMemorySettings(undefined, {
      enabled: true,
      smart: {
        enabled: true,
        recallLimit: 6
      }
    })

    expect(merged.enabled).toBe(true)
    expect(merged.mode).toBe('hybrid')
    expect(merged.smart.enabled).toBe(true)
    expect(merged.smart.recallLimit).toBe(6)
  })
})

describe('normalizeUiFontFamily', () => {
  it('always resolves to system-native (selector removed)', () => {
    expect(normalizeUiFontFamily(undefined)).toBe('system-native')
    expect(normalizeUiFontFamily('invalid')).toBe('system-native')
    expect(normalizeUiFontFamily('inter-noto')).toBe('system-native')
    expect(normalizeUiFontFamily('system-native')).toBe('system-native')
  })
})
