import { expect, it, vi } from 'vitest'
vi.mock('electron', () => ({ ipcMain: { handle: vi.fn() } }))
import { chromeSetupUrl } from './cua-setup'

it('opens only the extension store page and the extension settings', () => {
  expect(chromeSetupUrl('store')).toBe('https://chromewebstore.google.com/detail/chatgpt/hehggadaopoacecdllhhajmbjkdcmajg')
  expect(chromeSetupUrl('extension')).toBe('chrome://extensions/?id=hehggadaopoacecdllhhajmbjkdcmajg')
  for (const page of ['https://example.com', 'chrome://settings', 'toString', '__proto__', null, 1]) {
    expect(chromeSetupUrl(page)).toBeNull()
  }
})
