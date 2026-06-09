import { type ReactElement, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { AppSettingsV1 } from '@shared/app-settings'
import { applyTheme } from '../lib/apply-theme'
import { useChatStore } from '../store/chat-store'
import { Eye, EyeOff, ExternalLink, Sparkles, Sun, Moon, Monitor, X } from 'lucide-react'

type ThemePref = AppSettingsV1['theme']
type SetupFormPatch = Partial<Omit<AppSettingsV1, 'deepseek'>> & {
  deepseek?: Partial<AppSettingsV1['deepseek']>
}

const themeOptions: { value: ThemePref; icon: typeof Sun; labelKey: string }[] = [
  { value: 'system', icon: Monitor, labelKey: 'themeSystem' },
  { value: 'light', icon: Sun, labelKey: 'themeLight' },
  { value: 'dark', icon: Moon, labelKey: 'themeDark' }
]
const DEEPSEEK_USAGE_URL = 'https://platform.deepseek.com/usage'

export function InitialSetupDialog(): ReactElement {
  const { t } = useTranslation('settings')
  const initialSetupMode = useChatStore((s) => s.initialSetupMode)
  const closeInitialSetup = useChatStore((s) => s.closeInitialSetup)
  const applyI18n = useChatStore((s) => s.applyI18nFromSettings)
  const reloadUiSettings = useChatStore((s) => s.reloadUiSettings)
  const probeRuntime = useChatStore((s) => s.probeRuntime)

  const [form, setForm] = useState<AppSettingsV1 | null>(null)
  const [showApiKey, setShowApiKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isPreview = initialSetupMode === 'preview'

  useEffect(() => {
    let cancelled = false
    if (typeof window.dsGui === 'undefined') return
    void window.dsGui.getSettings().then((s) => {
      if (!cancelled) setForm(s)
    })
    return () => { cancelled = true }
  }, [])

  const updateForm = (patch: SetupFormPatch) => {
    if (!form) return
    const next: AppSettingsV1 = {
      ...form,
      ...patch,
      deepseek: { ...form.deepseek, ...(patch.deepseek ?? {}) }
    }
    setForm(next)
  }

  const handleThemeChange = (theme: ThemePref) => {
    if (!form) return
    updateForm({ theme })
    applyTheme(theme)
  }

  const handleClose = () => {
    setError(null)
    closeInitialSetup()
    void reloadUiSettings()
  }

  const handleOpenOfficialApiPage = () => {
    if (typeof window.dsGui?.openExternal !== 'function') return
    void window.dsGui.openExternal(DEEPSEEK_USAGE_URL)
  }

  const handleSave = async () => {
    if (!form) return
    if (!form.deepseek.apiKey.trim()) {
      setError(t('firstRunApiKeyValidation'))
      return
    }
    setSaving(true)
    setError(null)
    try {
      if (typeof window.dsGui === 'undefined') throw new Error('Preload bridge missing')
      const next = await window.dsGui.setSettings(form)
      setForm(next)
      await applyI18n(next.locale)
      void reloadUiSettings()
      void probeRuntime('background')
      closeInitialSetup()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (!form) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4 backdrop-blur-sm">
        <div className="ds-glass rounded-2xl px-5 py-4 text-sm text-ds-muted">
          {t('loading')}
        </div>
      </div>
    )
  }

  const selectedTheme = form.theme
  const choiceButtonClass = (active: boolean): string =>
    [
      'flex h-12 items-center justify-center gap-2 rounded-[16px] border px-4 text-[15px] font-medium transition-all duration-200',
      active
        ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/15'
        : 'border-ds-border bg-ds-card text-ds-muted hover:border-ds-border-strong hover:text-ds-ink'
    ].join(' ')
  const fieldClass =
    'w-full rounded-[18px] border border-ds-border bg-ds-card px-4 py-3 text-[15px] text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60 focus:ring-2 focus:ring-accent/15'
  const labelClass = 'text-[15px] font-medium text-ds-ink'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4 backdrop-blur-sm">
      <div className="ds-glass ds-glass-strong w-full max-w-[592px] overflow-hidden rounded-[28px] text-ds-ink">
        <div className="bg-[radial-gradient(circle_at_top_right,var(--ds-accent-soft),transparent_42%)] px-8 pb-7 pt-8">
          <div className="flex items-center justify-between gap-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-accent/25 bg-accent/10 px-3.5 py-1.5 text-[13px] font-semibold text-accent">
              <Sparkles className="h-3.5 w-3.5" strokeWidth={1.9} />
              {t(isPreview ? 'firstRunPreviewBadge' : 'firstRunBadge')}
            </div>
            <button
              type="button"
              onClick={handleClose}
              aria-label={t('firstRunClose')}
              title={t('firstRunClose')}
              className="flex h-10 w-10 items-center justify-center rounded-full text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            >
              <X className="h-[18px] w-[18px]" strokeWidth={1.8} />
            </button>
          </div>
          <h1 className="mt-5 text-[22px] font-semibold tracking-[-0.02em] text-ds-ink">
            {t('firstRunTitle')}
          </h1>
          <p className="mt-3 text-[15px] leading-7 text-ds-muted">
            {t('firstRunSubtitle')}
          </p>
        </div>

        <div className="space-y-6 px-8 py-7">
          <div className="border-t border-ds-border-muted" />

          <div className="space-y-3">
            <label className={labelClass}>
              {t('theme')}
            </label>
            <div className="grid grid-cols-3 gap-3">
              {themeOptions.map(({ value, icon: Icon, labelKey }) => {
                const isActive = selectedTheme === value
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => handleThemeChange(value)}
                    className={choiceButtonClass(isActive)}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span>{t(labelKey)}</span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="space-y-3">
            <label className={labelClass}>
              {t('language')}
            </label>
            <div className="grid grid-cols-2 gap-3">
              {(['en', 'zh'] as const).map((lang) => {
                const isActive = form.locale === lang
                return (
                  <button
                    key={lang}
                    type="button"
                    onClick={() => {
                      updateForm({ locale: lang })
                      void applyI18n(lang)
                    }}
                    className={choiceButtonClass(isActive)}
                  >
                    {lang === 'en' ? 'English' : '简体中文'}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="space-y-3">
            <label className={labelClass}>
              {t('apiKey')}
            </label>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={form.deepseek.apiKey}
                onChange={(e) => updateForm({ deepseek: { apiKey: e.target.value } })}
                placeholder="sk-..."
                className={`${fieldClass} pr-12 font-mono tracking-[0.02em] placeholder:font-sans`}
              />
              <button
                type="button"
                onClick={() => setShowApiKey((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-ds-faint transition-colors hover:text-ds-muted"
              >
                {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <div className="flex flex-col gap-2 rounded-[18px] border border-ds-border-muted bg-ds-subtle/50 px-4 py-3 text-[13px] text-ds-muted sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <p className="leading-6">
                {t('firstRunBuyApiHint')}
              </p>
              <button
                type="button"
                onClick={handleOpenOfficialApiPage}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-accent/25 bg-accent/10 px-3 py-1.5 text-[12.5px] font-semibold text-accent transition hover:bg-accent/15"
              >
                <span>{t('firstRunBuyApiAction')}</span>
                <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.9} />
              </button>
            </div>
          </div>

          <div className="space-y-3">
            <label className={labelClass}>
              {t('baseUrl')}
            </label>
            <input
              type="text"
              value={form.deepseek.baseUrl}
              onChange={(e) => updateForm({ deepseek: { baseUrl: e.target.value } })}
              placeholder="https://api.deepseek.com/beta"
              className={fieldClass}
            />
          </div>
        </div>

        <div className="space-y-4 px-8 pb-8 pt-1">
          {error && (
            <div className="rounded-[18px] border border-[var(--ds-danger)]/20 bg-[var(--ds-danger-soft)] px-4 py-3 text-[13px] text-[var(--ds-danger)]">
              {error}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <button
              type="button"
              onClick={handleClose}
              className="h-11 rounded-[16px] border border-ds-border bg-ds-card px-4 text-[15px] font-semibold text-ds-ink transition hover:border-ds-border-strong hover:bg-ds-hover"
            >
              {t('firstRunClose')}
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={handleSave}
              className="h-11 rounded-[16px] bg-accent px-4 text-[15px] font-semibold text-white shadow-[0_16px_34px_var(--ds-accent-soft)] transition hover:brightness-110 disabled:opacity-50"
            >
              {saving ? t('firstRunSaving') : t('firstRunSave')}
            </button>
          </div>

          <p className="text-center text-[12.5px] leading-6 text-ds-faint">
            {t(isPreview ? 'firstRunPreviewHint' : 'firstRunChangeLater')}
          </p>
        </div>
      </div>
    </div>
  )
}
