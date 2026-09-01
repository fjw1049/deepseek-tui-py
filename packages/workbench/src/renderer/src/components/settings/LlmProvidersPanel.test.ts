// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  defaultLlmProviders,
  type AppSettingsV1
} from '@shared/app-settings'
import { LlmProvidersPanel } from './LlmProvidersPanel'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: { model?: string }) =>
      values?.model ? `${key}:${values.model}` : key
  })
}))

vi.mock('../chat/provider-icons.js', () => ({
  resolveProviderIcon: () => ({ key: 'test', colored: false, color: '', svg: '<svg />' }),
  uniquifySvgIds: (svg: string) => svg
}))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.stubGlobal('dsGui', {
    setSettings: vi.fn().mockResolvedValue(undefined),
    fetchProviderModels: vi.fn().mockResolvedValue({
      ok: true,
      modelIds: ['glm-5.1']
    })
  })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('LlmProvidersPanel', () => {
  it('offers deletion for every model and persists a deleted discovered model', async () => {
    const onUpdate = vi.fn()
    const llmProviders = defaultLlmProviders()
    llmProviders['volcengine-ark'] = {
      apiKey: 'secret',
      lastFetchedModels: ['glm-5.1'],
      models: [
        { id: 'glm-5.1', enabled: true, contextWindow: 500_000 },
        { id: 'gl5-5.3-flash', enabled: true, contextWindow: 500_000 }
      ]
    }
    const form = {
      llmProviders,
      customEndpoints: [],
      asrProviders: [],
      defaultLlmProviderId: 'volcengine-ark'
    } as unknown as AppSettingsV1

    await act(async () => {
      root.render(createElement(LlmProvidersPanel, { form, onUpdate }))
    })

    const providerButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('llmProviderVolcengine')
    )!
    await act(async () => providerButton.click())

    const removeButtons = document.body.querySelectorAll<HTMLButtonElement>(
      '.ds-llm-inset__pick-remove'
    )
    expect(removeButtons).toHaveLength(2)

    const removeButton = document.body.querySelector<HTMLButtonElement>(
      '[aria-label="llmDeleteModel:glm-5.1"]'
    )
    expect(removeButton).not.toBeNull()

    await act(async () => removeButton!.click())
    expect(document.body.textContent).not.toContain('glm-5.1')

    const saveButton = Array.from(document.body.querySelectorAll('button')).find(
      (button) => button.textContent === 'saveEndpointBtn'
    )!
    await act(async () => saveButton.click())

    expect(onUpdate).toHaveBeenCalledWith({
      llmProviders: {
        'volcengine-ark': {
          apiKey: 'secret',
          lastFetchedModels: ['glm-5.1'],
          hiddenModels: ['glm-5.1'],
          models: [{ id: 'gl5-5.3-flash', enabled: true, contextWindow: 500_000 }]
        }
      }
    })
  })

  it('keeps a deleted discovered model hidden when the provider refreshes', async () => {
    const llmProviders = defaultLlmProviders()
    llmProviders['volcengine-ark'] = {
      apiKey: 'secret',
      lastFetchedModels: ['glm-5.1'],
      hiddenModels: ['glm-5.1'],
      models: []
    }
    const form = {
      llmProviders,
      customEndpoints: [],
      asrProviders: [],
      defaultLlmProviderId: 'volcengine-ark'
    } as unknown as AppSettingsV1

    await act(async () => {
      root.render(createElement(LlmProvidersPanel, { form, onUpdate: vi.fn() }))
    })

    const providerButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('llmProviderVolcengine')
    )!
    await act(async () => providerButton.click())

    expect(document.body.textContent).not.toContain('glm-5.1')
    expect(window.dsGui.fetchProviderModels).toHaveBeenCalledWith('volcengine-ark')
  })
})
