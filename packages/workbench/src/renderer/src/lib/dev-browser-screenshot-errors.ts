import type { TFunction } from 'i18next'

const SCREENSHOT_ERROR_I18N_KEYS: Record<string, string> = {
  'Main window unavailable.': 'browserScreenshotFailed',
  'Screenshot request came from an unexpected window.': 'browserScreenshotFailed',
  'Browser tab is not ready.': 'browserScreenshotNotReady',
  'Invalid browser target.': 'browserScreenshotFailed',
  'Browser tab belongs to another window.': 'browserScreenshotFailed',
  'Browser tab is not attached.': 'browserScreenshotNotReady',
  'Screenshot timed out.': 'browserScreenshotTimeout',
  'Screenshot is empty.': 'browserScreenshotEmpty',
  'Screenshot capture returned no image data.': 'browserScreenshotEmpty',
  'Screenshot image is empty.': 'browserScreenshotEmpty'
}

export function localizeDevBrowserScreenshotError(
  message: string | undefined,
  t: TFunction<'common'>
): string {
  const trimmed = message?.trim()
  if (!trimmed) return t('browserScreenshotFailed')
  const key = SCREENSHOT_ERROR_I18N_KEYS[trimmed]
  if (key) return t(key)
  return trimmed
}
