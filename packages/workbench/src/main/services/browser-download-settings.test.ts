import { EventEmitter } from 'node:events'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, it, vi } from 'vitest'
import type { DownloadItem } from 'electron'
import type { AppSettingsV1 } from '../../shared/app-settings'
import { configureBrowserDownload } from './browser-download-settings'
const directory = mkdtempSync(join(tmpdir(), 'browser-download-'))
afterEach(() => rmSync(join(directory, 'report.txt'), { force: true }))
const item = () => Object.assign(new EventEmitter(), { getFilename: () => 'report.txt', setSavePath: vi.fn(), setSaveDialogOptions: vi.fn() })
it('uses the requested folder in the native save dialog', () => {
  const download = item()
  configureBrowserDownload(download as unknown as DownloadItem, { browserDownloadDirectory: directory } as AppSettingsV1, '/fallback')
  expect(download.setSaveDialogOptions).toHaveBeenCalledWith({ defaultPath: join(directory, 'report.txt') })
  expect(download.setSavePath).not.toHaveBeenCalled()
})
it('auto-saves without replacing an existing file', () => {
  writeFileSync(join(directory, 'report.txt'), 'keep')
  const download = item()
  configureBrowserDownload(download as unknown as DownloadItem, { browserAskDownloadLocation: false } as AppSettingsV1, directory)
  expect(download.setSavePath).toHaveBeenCalledWith(join(directory, 'report (1).txt'))
  expect(readFileSync(join(directory, 'report.txt'), 'utf8')).toBe('keep')
  download.emit('done')
})
it('reserves different paths for simultaneous same-name downloads', () => {
  const first = item(), second = item()
  const settings = { browserAskDownloadLocation: false } as AppSettingsV1
  configureBrowserDownload(first as unknown as DownloadItem, settings, directory)
  configureBrowserDownload(second as unknown as DownloadItem, settings, directory)
  expect(first.setSavePath.mock.calls[0][0]).not.toBe(second.setSavePath.mock.calls[0][0])
  first.emit('done'); second.emit('done')
})
