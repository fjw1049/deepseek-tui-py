import { getSettingsSnapshot, loadSettingsSnapshot } from './settings-snapshot'
import { openPreviewUrl } from './open-preview-url'

/** Applies only to explicit link clicks; agent navigation and explicit previews keep their target. */
export async function openBrowserLink(href: string): Promise<void> {
  let url: URL
  try { url = new URL(href) } catch { return }
  if (!['http:', 'https:', 'mailto:'].includes(url.protocol)) return
  if (url.protocol !== 'mailto:') {
    const settings = getSettingsSnapshot() ?? await loadSettingsSnapshot().catch(() => null)
    const host = url.hostname
    const local = host === 'localhost' || host.endsWith('.localhost') || host === '[::1]' || /^127\./.test(host)
    const target = local ? settings?.browserLocalLinkTarget : settings?.browserLinkTarget
    if (target === 'internal') { openPreviewUrl(href); return }
  }
  await window.dsGui.openExternal(href)
}
