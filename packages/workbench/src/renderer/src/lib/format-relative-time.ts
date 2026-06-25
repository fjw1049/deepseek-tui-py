function formatDurationCompact(totalSeconds: number): string {
  const sec = Math.max(0, Math.floor(totalSeconds))
  if (sec < 60) return `${sec}s`

  const minutes = Math.floor(sec / 60)
  const seconds = sec % 60
  if (minutes < 60) {
    return seconds > 0 ? `${minutes}m${seconds}s` : `${minutes}m`
  }

  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  if (hours < 24) {
    let out = `${hours}h`
    if (mins > 0) out += `${mins}m`
    if (seconds > 0) out += `${seconds}s`
    return out
  }

  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d`

  const weeks = Math.floor(days / 7)
  if (weeks < 5) return `${weeks}w`

  return `${Math.floor(days / 30)}mo`
}

function formatDurationLargestUnit(totalSeconds: number): string {
  const sec = Math.max(0, Math.floor(totalSeconds))
  if (sec < 60) return `${sec}s`

  const minutes = Math.floor(sec / 60)
  if (minutes < 60) return `${minutes}m`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`

  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d`

  const weeks = Math.floor(days / 7)
  if (weeks < 5) return `${weeks}w`

  return `${Math.floor(days / 30)}mo`
}

/** Compact elapsed-time label for narrow sidebars, e.g. `11s`, `3m`, `1h22m3s`. */
export function formatRelativeTimeCompact(input: string): string {
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) {
    return input
  }

  const elapsedSec = Math.floor((Date.now() - date.getTime()) / 1000)
  if (elapsedSec < 0) return '0s'
  return formatDurationCompact(elapsedSec)
}

/** Sidebar-friendly elapsed-time label using only the largest unit, e.g. `6m`, `1h`, `2d`. */
export function formatRelativeTimeLargestUnit(input: string): string {
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) {
    return input
  }

  const elapsedSec = Math.floor((Date.now() - date.getTime()) / 1000)
  if (elapsedSec < 0) return '0s'
  return formatDurationLargestUnit(elapsedSec)
}

export function formatRelativeTime(input: string, locale: string): string {
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) {
    return input
  }

  const now = new Date()
  const diffMs = date.getTime() - now.getTime()
  const absSeconds = Math.abs(diffMs) / 1000
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })

  if (absSeconds < 60) {
    return formatter.format(Math.round(diffMs / 1000), 'second')
  }

  const absMinutes = absSeconds / 60
  if (absMinutes < 60) {
    return formatter.format(Math.round(diffMs / (60 * 1000)), 'minute')
  }

  const absHours = absMinutes / 60
  if (absHours < 24) {
    return formatter.format(Math.round(diffMs / (60 * 60 * 1000)), 'hour')
  }

  const absDays = absHours / 24
  if (absDays < 7) {
    return formatter.format(Math.round(diffMs / (24 * 60 * 60 * 1000)), 'day')
  }

  if (absDays < 30) {
    return formatter.format(Math.round(diffMs / (7 * 24 * 60 * 60 * 1000)), 'week')
  }

  const sameYear = date.getFullYear() === now.getFullYear()
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' })
  }).format(date)
}
