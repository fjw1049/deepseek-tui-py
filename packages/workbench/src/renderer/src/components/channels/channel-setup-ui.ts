/** Shared field / action chrome for channel setup panels (Feishu / Email / WeCom). */

export const channelNoticeClass = (tone: 'success' | 'error' | 'info'): string =>
  `rounded-lg px-3 py-2 text-[13px] ${
    tone === 'error'
      ? 'bg-red-500/10 text-red-700 dark:text-red-200'
      : tone === 'success'
        ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-200'
        : 'bg-ds-subtle text-ds-muted'
  }`

export const CHANNEL_FIELD = 'grid gap-1'
export const CHANNEL_LABEL = 'text-[13px] font-medium text-ds-ink'
export const CHANNEL_HINT = 'text-[13px] leading-6 text-ds-muted'
export const CHANNEL_CONTROL =
  'rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-accent/60'
export const CHANNEL_ACTIONS = 'flex flex-wrap gap-2'
export const CHANNEL_PRIMARY_BTN =
  'inline-flex items-center gap-1.5 rounded-lg bg-accent/10 px-3 py-2 text-[13px] font-medium text-accent hover:bg-accent/20 disabled:opacity-50'
export const CHANNEL_SECONDARY_BTN =
  'inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink hover:bg-ds-hover disabled:opacity-50'
export const CHANNEL_BTN_ICON = 'h-3.5 w-3.5'
