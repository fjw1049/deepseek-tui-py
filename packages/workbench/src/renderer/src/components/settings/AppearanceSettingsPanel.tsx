import type { ReactElement, ReactNode } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ClipboardPaste, Copy, RotateCcw } from 'lucide-react'
import type { AppSettingsV1, AppearancePatchV1 } from '@shared/app-settings'
import {
  CUSTOM_THEME_PRESET_ID,
  DEFAULT_CHROME_THEMES,
  MAX_CHAT_FONT_SIZE_PX,
  MAX_TERMINAL_FONT_SIZE_PX,
  MIN_CHAT_FONT_SIZE_PX,
  MIN_TERMINAL_FONT_SIZE_PX,
  createThemeShareString,
  defaultAppearanceSettings,
  getThemePresetSeed,
  listThemePresetsForVariant,
  normalizeHexColor,
  parseThemeShareString,
  type ChromeThemeV1,
  type ThemeVariant,
  type UiDensity
} from '@shared/appearance'
import { GlassSegmentedControl } from './GlassSegmentedControl'
import { SettingsSelect } from './SettingsSelect'

type AppearanceViewPatch = {
  theme?: AppSettingsV1['theme']
  uiFontScale?: AppSettingsV1['uiFontScale']
  uiFontFamily?: AppSettingsV1['uiFontFamily']
  appearance?: AppearancePatchV1
}

type Props = {
  form: AppSettingsV1
  /** Single patch callback so combined updates (e.g. restore defaults) stay atomic. */
  onPatch: (patch: AppearanceViewPatch) => void
}

const TERMINAL_FONT_SUGGESTIONS = [
  'JetBrains Mono',
  'Fira Code',
  'SF Mono',
  'Menlo',
  'Monaco',
  'Consolas',
  'Cascadia Code',
  'IBM Plex Mono',
  'Source Code Pro'
]

function useResolvedVariant(theme: AppSettingsV1['theme']): ThemeVariant {
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (): void => setSystemDark(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  if (theme === 'light' || theme === 'dark') return theme
  return systemDark ? 'dark' : 'light'
}

export function AppearanceSettingsPanel({ form, onPatch }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const appearance = form.appearance
  const resolvedVariant = useResolvedVariant(form.theme)
  const variantOrder: readonly ThemeVariant[] =
    resolvedVariant === 'dark' ? (['dark', 'light'] as const) : (['light', 'dark'] as const)
  const onAppearancePatch = (patch: AppearancePatchV1): void => onPatch({ appearance: patch })

  const restoreDefaults = (): void => {
    onPatch({
      theme: 'system',
      uiFontScale: 'small',
      uiFontFamily: 'system-native',
      appearance: defaultAppearanceSettings()
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-3">
        <SectionLabel>{t('appearanceSectionTheme')}</SectionLabel>
        <button
          type="button"
          onClick={restoreDefaults}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12.5px] font-medium text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
        >
          <RotateCcw className="h-3 w-3" strokeWidth={1.75} />
          {t('appearanceRestoreDefaults')}
        </button>
      </div>

      <Card>
        <Row
          title={t('theme')}
          description={t('themeDesc')}
          control={
            <GlassSegmentedControl
              value={form.theme}
              items={[
                { value: 'light', label: t('themeLight') },
                { value: 'dark', label: t('themeDark') },
                { value: 'system', label: t('themeSystem') }
              ]}
              onChange={(value) => onPatch({ theme: value })}
            />
          }
        />
        <Row
          title={t('fontScale')}
          description={t('fontScaleDesc')}
          control={
            <SettingsSelect
              value={form.uiFontScale}
              onChange={(e) =>
                onPatch({ uiFontScale: e.target.value as AppSettingsV1['uiFontScale'] })
              }
            >
              <option value="small">{t('fontScaleSmall')}</option>
              <option value="medium">{t('fontScaleMedium')}</option>
              <option value="large">{t('fontScaleLarge')}</option>
            </SettingsSelect>
          }
        />
      </Card>

      {variantOrder.map((variant) => (
        <ThemePackCard
          key={variant}
          variant={variant}
          theme={appearance.themes[variant]}
          isActive={resolvedVariant === variant}
          mode={form.theme}
          onThemePatch={(patch) => onAppearancePatch({ themes: { [variant]: patch } })}
          onThemeReplace={(theme) => onAppearancePatch({ themes: { [variant]: theme } })}
        />
      ))}

      <Card>
        <Row
          title={t('uiDensity')}
          description={t('uiDensityDesc')}
          control={
            <GlassSegmentedControl<UiDensity>
              value={appearance.uiDensity}
              items={[
                { value: 'compact', label: t('uiDensityCompact') },
                { value: 'comfortable', label: t('uiDensityComfortable') },
                { value: 'spacious', label: t('uiDensitySpacious') }
              ]}
              onChange={(value) => onAppearancePatch({ uiDensity: value })}
            />
          }
        />
        <Row
          title={t('chatFontSize')}
          description={t('chatFontSizeDesc')}
          control={
            <PxInput
              value={appearance.chatFontSizePx}
              min={MIN_CHAT_FONT_SIZE_PX}
              max={MAX_CHAT_FONT_SIZE_PX}
              onCommit={(value) => onAppearancePatch({ chatFontSizePx: value })}
            />
          }
        />
        <Row
          title={t('terminalFontSize')}
          description={t('terminalFontSizeDesc')}
          control={
            <PxInput
              value={appearance.terminalFontSizePx}
              min={MIN_TERMINAL_FONT_SIZE_PX}
              max={MAX_TERMINAL_FONT_SIZE_PX}
              onCommit={(value) => onAppearancePatch({ terminalFontSizePx: value })}
            />
          }
        />
        <Row
          title={t('terminalFont')}
          description={t('terminalFontDesc')}
          control={
            <>
              <input
                list="ds-terminal-font-suggestions"
                value={appearance.terminalFontFamily}
                onChange={(e) => onAppearancePatch({ terminalFontFamily: e.target.value })}
                placeholder={t('terminalFontPlaceholder')}
                className="w-full rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm placeholder:text-ds-faint focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
              />
              <datalist id="ds-terminal-font-suggestions">
                {TERMINAL_FONT_SUGGESTIONS.map((family) => (
                  <option key={family} value={family} />
                ))}
              </datalist>
            </>
          }
        />
        <Row
          title={t('fontSmoothing')}
          description={t('fontSmoothingDesc')}
          control={
            <Toggle
              checked={appearance.fontSmoothing}
              onChange={(value) => onAppearancePatch({ fontSmoothing: value })}
            />
          }
        />
      </Card>

      <SectionLabel>{t('appearanceSectionTime')}</SectionLabel>

      <Card>
        <Row
          title={t('timeFormat')}
          description={t('timeFormatDesc')}
          control={
            <SettingsSelect
              value={appearance.timestampFormat}
              onChange={(e) =>
                onAppearancePatch({
                  timestampFormat: e.target.value as AppSettingsV1['appearance']['timestampFormat']
                })
              }
            >
              <option value="locale">{t('timeFormatLocale')}</option>
              <option value="12-hour">{t('timeFormat12h')}</option>
              <option value="24-hour">{t('timeFormat24h')}</option>
            </SettingsSelect>
          }
        />
      </Card>
    </div>
  )
}

function ThemePackCard({
  variant,
  theme,
  isActive,
  mode,
  onThemePatch,
  onThemeReplace
}: {
  variant: ThemeVariant
  theme: ChromeThemeV1
  isActive: boolean
  mode: AppSettingsV1['theme']
  onThemePatch: (patch: Partial<ChromeThemeV1>) => void
  onThemeReplace: (theme: ChromeThemeV1) => void
}): ReactElement {
  const { t } = useTranslation('settings')
  const presets = useMemo(() => listThemePresetsForVariant(variant), [variant])
  const presetKnown = presets.some((preset) => preset.id === theme.presetId)
  const [copied, setCopied] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importError, setImportError] = useState<string | null>(null)
  const copyTimer = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (copyTimer.current) window.clearTimeout(copyTimer.current)
    }
  }, [])

  const selectPreset = (presetId: string): void => {
    const seed = getThemePresetSeed(presetId, variant)
    if (seed) onThemeReplace(seed)
  }

  const copyShareString = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(createThemeShareString(variant, theme))
      setCopied(true)
      if (copyTimer.current) window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable; ignore */
    }
  }

  const importShareString = (): void => {
    const result = parseThemeShareString(importText, variant)
    if (!result.ok) {
      setImportError(
        result.error === 'variant-mismatch' ? t('themeImportVariantMismatch') : t('themeImportInvalid')
      )
      return
    }
    onThemeReplace(result.theme)
    setImportOpen(false)
    setImportText('')
    setImportError(null)
  }

  const statusText = isActive
    ? t('themePackActive')
    : mode === 'system'
      ? t('themePackInactiveSystem')
      : t('themePackInactiveLocked', {
          mode: mode === 'light' ? t('themeLight') : t('themeDark')
        })

  return (
    <section className="ds-content-card rounded-2xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ds-border-muted px-5 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-[16px] font-semibold text-ds-ink">
            {variant === 'light' ? t('themePackLightTitle') : t('themePackDarkTitle')}
          </h2>
          <button
            type="button"
            title={t('themePackReset')}
            aria-label={t('themePackReset')}
            onClick={() => onThemeReplace({ ...DEFAULT_CHROME_THEMES[variant] })}
            className="inline-flex h-6 w-6 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
          >
            <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.75} />
          </button>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              setImportOpen((open) => !open)
              setImportError(null)
            }}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
          >
            <ClipboardPaste className="h-3.5 w-3.5" strokeWidth={1.75} />
            {t('themePackImport')}
          </button>
          <button
            type="button"
            onClick={() => void copyShareString()}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-emerald-500" strokeWidth={2} />
            ) : (
              <Copy className="h-3.5 w-3.5" strokeWidth={1.75} />
            )}
            {copied ? t('themePackCopied') : t('themePackCopy')}
          </button>
          <div className="w-40">
            <SettingsSelect
              value={presetKnown ? theme.presetId : CUSTOM_THEME_PRESET_ID}
              onChange={(e) => selectPreset(e.target.value)}
            >
              {presets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.id === 'default' ? t('themePresetDefault') : preset.label}
                </option>
              ))}
              {!presetKnown ? (
                <option value={CUSTOM_THEME_PRESET_ID} disabled>
                  {t('themePresetCustom')}
                </option>
              ) : null}
            </SettingsSelect>
          </div>
        </div>
      </div>

      <div className="px-5 pt-2 text-[12.5px] text-ds-faint">{statusText}</div>

      {importOpen ? (
        <div className="mx-5 mt-2 rounded-xl border border-ds-border-muted bg-ds-main/45 p-3">
          <textarea
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            placeholder="codex-theme-v1:{…}"
            rows={3}
            className="w-full rounded-lg border border-ds-border bg-ds-card px-2.5 py-1.5 font-mono text-[12px] text-ds-ink placeholder:text-ds-faint focus:border-accent/40 focus:outline-none"
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <span className="min-w-0 truncate text-[12px] text-red-700 dark:text-red-300">
              {importError}
            </span>
            <button
              type="button"
              onClick={importShareString}
              disabled={!importText.trim()}
              className="shrink-0 rounded-lg border border-ds-border bg-ds-card px-3 py-1.5 text-[12.5px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('themePackImportApply')}
            </button>
          </div>
        </div>
      ) : null}

      <div className="divide-y divide-ds-border-muted px-2 py-1">
        <Row
          title={t('themeAccent')}
          control={
            <ColorPill value={theme.accent} onCommit={(value) => onThemePatch({ accent: value })} />
          }
        />
        <Row
          title={t('themeBackground')}
          control={
            <ColorPill value={theme.surface} onCommit={(value) => onThemePatch({ surface: value })} />
          }
        />
        <Row
          title={t('themeForeground')}
          control={<ColorPill value={theme.ink} onCommit={(value) => onThemePatch({ ink: value })} />}
        />
        <Row
          title={t('themeUiFont')}
          control={
            <input
              value={theme.uiFont}
              onChange={(e) => onThemePatch({ uiFont: e.target.value })}
              placeholder={t('themeUiFontPlaceholder')}
              className="w-full rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm placeholder:text-ds-faint focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
            />
          }
        />
        <Row
          title={t('themeCodeFont')}
          control={
            <input
              value={theme.codeFont}
              onChange={(e) => onThemePatch({ codeFont: e.target.value })}
              placeholder={t('themeCodeFontPlaceholder')}
              className="w-full rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm placeholder:text-ds-faint focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
            />
          }
        />
        <Row
          title={t('themeTranslucent')}
          control={
            <Toggle
              checked={theme.translucent}
              onChange={(value) => onThemePatch({ translucent: value })}
            />
          }
        />
        <Row
          title={t('themeContrast')}
          control={
            <div className="flex w-full items-center gap-3">
              <input
                type="range"
                min={0}
                max={100}
                value={theme.contrast}
                onChange={(e) => onThemePatch({ contrast: Number(e.target.value) })}
                className="ds-no-drag h-1.5 w-full cursor-pointer appearance-none rounded-full bg-ds-border accent-[var(--ds-accent)]"
              />
              <span className="w-8 shrink-0 text-right font-mono text-[13px] text-ds-muted">
                {theme.contrast}
              </span>
            </div>
          }
        />
      </div>
    </section>
  )
}

function ColorPill({
  value,
  onCommit
}: {
  value: string
  onCommit: (hex: string) => void
}): ReactElement {
  const [draft, setDraft] = useState(value.toUpperCase())
  useEffect(() => {
    setDraft(value.toUpperCase())
  }, [value])

  const commitDraft = (): void => {
    const normalized = normalizeHexColor(draft, '')
    if (normalized && normalized !== value) {
      onCommit(normalized)
    } else {
      setDraft(value.toUpperCase())
    }
  }

  return (
    <div
      className="flex h-10 w-full items-center gap-2 overflow-hidden rounded-full border px-2 shadow-sm"
      style={{
        backgroundColor: value,
        borderColor: 'var(--ds-border)',
        color: pickReadableTextColor(value)
      }}
    >
      <span className="relative inline-flex h-6 w-6 shrink-0 items-center justify-center">
        <span
          aria-hidden
          className="block h-6 w-6 rounded-full border"
          style={{ borderColor: 'currentColor', opacity: 0.85 }}
        />
        <input
          type="color"
          value={normalizeHexColor(value, '#000000')}
          onChange={(e) => onCommit(e.target.value)}
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          aria-label={value}
        />
      </span>
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commitDraft}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commitDraft()
        }}
        spellCheck={false}
        className="w-full min-w-0 bg-transparent font-mono text-[13px] font-medium uppercase focus:outline-none"
        // Override the global .ds-settings-page input glass material (bg + blur +
        // inset shadow) so the hex text stays on the solid color pill behind it.
        style={{
          color: 'inherit',
          backgroundColor: 'transparent',
          backdropFilter: 'none',
          WebkitBackdropFilter: 'none',
          boxShadow: 'none'
        }}
      />
    </div>
  )
}

function pickReadableTextColor(hexColor: string): string {
  const normalized = normalizeHexColor(hexColor, '#000000')
  const r = Number.parseInt(normalized.slice(1, 3), 16)
  const g = Number.parseInt(normalized.slice(3, 5), 16)
  const b = Number.parseInt(normalized.slice(5, 7), 16)
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return luminance > 0.6 ? '#1a1a1a' : '#ffffff'
}

function PxInput({
  value,
  min,
  max,
  onCommit
}: {
  value: number
  min: number
  max: number
  onCommit: (value: number) => void
}): ReactElement {
  return (
    <div className="flex items-center gap-2">
      <input
        type="number"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(e) => {
          const parsed = Number(e.target.value)
          if (Number.isFinite(parsed)) {
            onCommit(Math.min(max, Math.max(min, Math.round(parsed))))
          }
        }}
        className="w-24 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
      />
      <span className="text-[13px] text-ds-faint">px</span>
    </div>
  )
}

function SectionLabel({ children }: { children: ReactNode }): ReactElement {
  return (
    <div className="px-1 text-[12.5px] font-medium uppercase tracking-wide text-ds-faint">
      {children}
    </div>
  )
}

function Card({ children }: { children: ReactNode }): ReactElement {
  return (
    <section className="ds-content-card rounded-2xl">
      <div className="divide-y divide-ds-border-muted px-2 py-1">{children}</div>
    </section>
  )
}

function Row({
  title,
  description,
  control
}: {
  title: string
  description?: ReactNode
  control: ReactNode
}): ReactElement {
  return (
    <div className="ds-density-row flex flex-col gap-3 px-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold text-ds-ink">{title}</div>
        {description ? (
          <p className="mt-0.5 max-w-md text-pretty text-[13px] leading-relaxed text-ds-muted">
            {description}
          </p>
        ) : null}
      </div>
      <div className="w-full min-w-0 sm:ml-auto sm:max-w-[280px] sm:shrink-0">
        <div className="flex w-full justify-end">{control}</div>
      </div>
    </div>
  )
}

function Toggle({
  checked,
  onChange
}: {
  checked: boolean
  onChange: (v: boolean) => void
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${
        checked ? 'bg-accent' : 'bg-ds-faint'
      }`}
    >
      <span
        className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition ${
          checked ? 'left-6' : 'left-0.5'
        }`}
      />
    </button>
  )
}
