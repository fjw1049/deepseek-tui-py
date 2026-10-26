import { existsSync, mkdirSync } from 'node:fs'
import { basename, extname, isAbsolute, join } from 'node:path'
import type { DownloadItem } from 'electron'
import type { AppSettingsV1 } from '../../shared/app-settings'

const pendingPaths = new Set<string>()

/** Called synchronously in will-download, before Electron chooses its destination. */
export function configureBrowserDownload(item: DownloadItem, settings: AppSettingsV1, defaultDirectory: string): void {
  const requested = settings.browserDownloadDirectory
  const directory = requested && isAbsolute(requested) ? requested : defaultDirectory
  const name = basename(item.getFilename()) || 'download'
  if (settings.browserAskDownloadLocation !== false) {
    item.setSaveDialogOptions({ defaultPath: join(directory, name) })
    return
  }
  mkdirSync(directory, { recursive: true })
  const extension = extname(name)
  const stem = name.slice(0, name.length - extension.length)
  let path = join(directory, name)
  for (let index = 1; existsSync(path) || pendingPaths.has(path); index++) path = join(directory, `${stem} (${index})${extension}`)
  pendingPaths.add(path)
  item.once('done', () => pendingPaths.delete(path))
  item.setSavePath(path)
}
