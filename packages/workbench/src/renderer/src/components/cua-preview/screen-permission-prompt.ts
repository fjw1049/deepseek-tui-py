export type ScreenPermission = { status: string; appName: string; appId?: string }

const remembered = new Set<string>()
const prefix = 'cua-screen-permission-notice:v1:'

/** Remember only that a missing-permission notice was shown, never authorization. */
export function claimScreenPermissionPrompt(permission: ScreenPermission): boolean {
  const key = prefix + (permission.appId ?? permission.appName)
  if (permission.status === 'granted') {
    remembered.delete(key)
    try { window.localStorage.removeItem(key) } catch { /* Memory still works. */ }
    return false
  }
  if (!['denied', 'not-determined', 'restricted'].includes(permission.status)) return false
  let seen = remembered.has(key)
  try { seen ||= window.localStorage.getItem(key) === 'shown' } catch { /* Memory fallback. */ }
  remembered.add(key)
  try { window.localStorage.setItem(key, 'shown') } catch { /* Do not block computer use. */ }
  return !seen
}
