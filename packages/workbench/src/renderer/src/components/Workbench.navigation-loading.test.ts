// @vitest-environment happy-dom
import { expect, it, vi } from 'vitest'

const navigation = vi.hoisted(() => {
  let ready!: () => void
  const pending = new Promise<void>(resolve => { ready = resolve })
  return { ready, pending, requested: new Set<string>() }
})
vi.mock('./SettingsView', async () => {
  navigation.requested.add('settings'); await navigation.pending
  return { SettingsView: () => null }
})
vi.mock('./extensions/MarketplaceView', async () => {
  navigation.requested.add('marketplace'); await navigation.pending
  return { MarketplaceView: () => null }
})
vi.mock('./automation/AutomationCenter', async () => {
  navigation.requested.add('automation'); await navigation.pending
  return { AutomationCenter: () => null }
})
vi.mock('./channels/ChannelCenter', async () => {
  navigation.requested.add('channels'); await navigation.pending
  return { ChannelCenter: () => null }
})
vi.mock('./kanban/KanbanView', async () => {
  navigation.requested.add('kanban'); await navigation.pending
  return { KanbanView: () => null }
})

it('does not mark Workbench loaded before its navigation pages are ready', async () => {
  let loaded = false
  const workbench = import('./Workbench').then(() => { loaded = true })
  try {
    await vi.waitFor(() => expect(navigation.requested.size).toBeGreaterThan(0), { timeout: 5000 })
    expect(loaded).toBe(false)
  } finally {
    navigation.ready()
    await workbench
  }
  expect(navigation.requested).toEqual(new Set(['settings', 'marketplace', 'automation', 'channels', 'kanban']))
  expect(loaded).toBe(true)
})
