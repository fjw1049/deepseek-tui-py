import { flushSync } from 'react-dom'
import { applyTheme, type ThemePreference } from './apply-theme'

let transitioning = false

/** Reveal the new theme from the trigger, with a feathered circular edge. */
export async function transitionTheme(pref: ThemePreference, origin: { x: number; y: number }): Promise<void> {
  if (transitioning) return
  if (!document.startViewTransition || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    applyTheme(pref)
    return
  }

  const x = Math.min(Math.max(origin.x, 0), window.innerWidth)
  const y = Math.min(Math.max(origin.y, 0), window.innerHeight)
  const diameter = 2.5 * Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y))
  const mask = `url("data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2"/></filter></defs><circle cx="50" cy="50" r="42" fill="white" filter="url(#blur)"/></svg>')}")`
  const style = document.createElement('style')
  style.textContent = `
    html.ds-theme-transition::view-transition-group(root) { animation: none; }
    html.ds-theme-transition::view-transition-old(root),
    html.ds-theme-transition::view-transition-new(root) { animation: none; mix-blend-mode: normal; }
    html.ds-theme-transition::view-transition-old(root) { z-index: 1; }
    html.ds-theme-transition::view-transition-new(root) {
      z-index: 2;
      mask-image: ${mask};
      mask-repeat: no-repeat;
      animation: ds-theme-reveal 820ms cubic-bezier(0.16, 1, 0.3, 1) both;
    }
    @keyframes ds-theme-reveal {
      from { mask-position: ${x}px ${y}px; mask-size: 0px 0px; }
      to { mask-position: ${x - diameter / 2}px ${y - diameter / 2}px; mask-size: ${diameter}px ${diameter}px; }
    }
  `
  transitioning = true
  document.head.appendChild(style)
  document.documentElement.classList.add('ds-theme-transition')
  let applied = false
  const apply = (): void => {
    flushSync(() => applyTheme(pref))
    applied = true
  }
  try {
    const transition = document.startViewTransition(apply)
    // A skipped capture rejects ready, while the update can still succeed.
    void transition.ready.catch(() => {})
    await transition.finished
  } catch {
    if (!applied) apply()
  } finally {
    style.remove()
    document.documentElement.classList.remove('ds-theme-transition')
    transitioning = false
  }
}
