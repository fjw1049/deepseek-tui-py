import i18n from 'i18next'
import { reportActionError } from '../store/feedback-store'

export async function copyText(text: string): Promise<boolean> {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    reportActionError(i18n.t('common:copyFailed'))
    return false
  }
}
