import type { ReactElement, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  applyThemePreset,
  chromeThemeEquals,
  createThemeShareString,
  defaultAppearanceSettings,
  getThemePresetSeed,
  isDefaultChromeTheme,
  listThemePresetsForVariant,
  normalizeHexColor,
  parseThemeShareString,
  pickReadableTextColor,
  type ChromeThemeV1,
  type EmptyHomeLayout,
  type ThemeVariant,
  type UiDensity
} from '@shared/appearance'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
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

// -webkit-font-smoothing only has an effect on macOS; hide the toggle elsewhere.
const IS_MAC = window.dsGui?.platform === 'darwin'

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
  const defaults = useMemo(() => defaultAppearanceSettings(), [])
  const resolvedVariant = useResolvedVariant(form.theme)
  // Fixed order: sorting the active variant first made the two cards swap
  // positions under the cursor when the OS theme flipped in system mode.
  const variantOrder: readonly ThemeVariant[] = ['light', 'dark']
  const onAppearancePatch = (patch: AppearancePatchV1): void => onPatch({ appearance: patch })
  const [restoreArmed, setRestoreArmed] = useState(false)
  const restoreTimer = useRef<number | null>(null)
  const isAtDefaults =
    form.theme === 'dark' &&
    form.uiFontScale === 'medium' &&
    form.uiFontFamily === 'system-native' &&
    isDefaultChromeTheme(appearance.themes.light, 'light') &&
    isDefaultChromeTheme(appearance.themes.dark, 'dark') &&
    appearance.uiDensity === defaults.uiDensity &&
    appearance.emptyHomeLayout === defaults.emptyHomeLayout &&
    appearance.chatFontSizePx === defaults.chatFontSizePx &&
    appearance.terminalFontSizePx === defaults.terminalFontSizePx &&
    appearance.terminalFontFamily === defaults.terminalFontFamily &&
    appearance.fontSmoothing === defaults.fontSmoothing &&
    appearance.timestampFormat === defaults.timestampFormat

  useEffect(() => {
    return () => {
      if (restoreTimer.current) window.clearTimeout(restoreTimer.current)
    }
  }, [])

  const restoreDefaults = (): void => {
    onPatch({
      theme: 'dark',
      uiFontScale: 'medium',
      uiFontFamily: 'system-native',
      appearance: defaultAppearanceSettings()
    })
    setRestoreArmed(false)
  }

  const requestRestoreDefaults = (): void => {
    if (restoreArmed) {
      if (restoreTimer.current) window.clearTimeout(restoreTimer.current)
      restoreTimer.current = null
      restoreDefaults()
      return
    }
    setRestoreArmed(true)
    if (restoreTimer.current) window.clearTimeout(restoreTimer.current)
    restoreTimer.current = window.setTimeout(() => {
      setRestoreArmed(false)
      restoreTimer.current = null
    }, 4000)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-3">
        <SectionLabel>{t('appearanceSectionTheme')}</SectionLabel>
        <button
          type="button"
          onClick={requestRestoreDefaults}
          disabled={isAtDefaults}
          className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12.5px] font-medium transition disabled:cursor-default disabled:opacity-40 ${
            restoreArmed
              ? 'bg-red-500/10 text-red-700 hover:bg-red-500/15 dark:text-red-300'
              : 'text-ds-faint hover:bg-ds-hover hover:text-ds-ink'
          }`}
        >
          <RotateCcw className="h-3 w-3" strokeWidth={1.75} />
          <span aria-live="polite">
            {restoreArmed ? t('appearanceRestoreConfirm') : t('appearanceRestoreDefaults')}
          </span>
        </button>
      </div>

      <Card>
        <Row
          title={t('theme')}
          description={t('themeDesc')}
          control={
            <GlassSegmentedControl
              className="w-full"
              ariaLabel={t('theme')}
              value={form.theme}
              items={[
                { value: 'system', label: t('themeSystem') },
                { value: 'light', label: t('themeLight') },
                { value: 'dark', label: t('themeDark') }
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
              aria-label={t('fontScale')}
              wrapperClassName="h-10 rounded-xl"
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
              className="w-full"
              ariaLabel={t('uiDensity')}
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
          title={t('emptyHomeLayout')}
          description={t('emptyHomeLayoutDesc')}
          control={
            <GlassSegmentedControl<EmptyHomeLayout>
              className="w-full"
              ariaLabel={t('emptyHomeLayout')}
              value={appearance.emptyHomeLayout ?? 'normal'}
              items={[
                { value: 'normal', label: t('emptyHomeLayoutNormal') },
                { value: 'simple', label: t('emptyHomeLayoutSimple') }
              ]}
              onChange={(value) => onAppearancePatch({ emptyHomeLayout: value })}
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
              ariaLabel={t('chatFontSize')}
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
              ariaLabel={t('terminalFontSize')}
              onCommit={(value) => onAppearancePatch({ terminalFontSizePx: value })}
            />
          }
        />
        <Row
          title={t('terminalFont')}
          description={t('terminalFontDesc')}
          control={
            <FontInput
              options={TERMINAL_FONT_SUGGESTIONS}
              value={appearance.terminalFontFamily}
              onChange={(value) => onAppearancePatch({ terminalFontFamily: value })}
              placeholder={t('terminalFontPlaceholder')}
              ariaLabel={t('terminalFont')}
              className="text-center"
            />
          }
        />
        {IS_MAC ? (
          <Row
            title={t('fontSmoothing')}
            description={t('fontSmoothingDesc')}
            control={
              <Toggle
                checked={appearance.fontSmoothing}
                ariaLabel={t('fontSmoothing')}
                onChange={(value) => onAppearancePatch({ fontSmoothing: value })}
              />
            }
          />
        ) : null}
      </Card>

      <SectionLabel>{t('appearanceSectionTime')}</SectionLabel>

      <Card>
        <Row
          title={t('timeFormat')}
          description={t('timeFormatDesc')}
          control={
            <SettingsSelect
              aria-label={t('timeFormat')}
              wrapperClassName="h-10 rounded-xl"
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
  const isPristine = isDefaultChromeTheme(theme, variant)
  const presetSeed = getThemePresetSeed(theme.presetId, variant)
  const isCustomized = !isPristine && (!presetSeed || !chromeThemeEquals(theme, presetSeed))
  const preset = presets.find((entry) => entry.id === theme.presetId)
  const presetLabel =
    preset?.id === 'default' ? t('themePresetDefault') : (preset?.label ?? t('themePresetCustom'))
  const titleLabel = variant === 'light' ? t('themePackLightTitle') : t('themePackDarkTitle')
  const controlLabel = (label: string): string => `${titleLabel} · ${label}`
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
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
    const next = applyThemePreset(theme, presetId, variant)
    if (next) onThemeReplace(next)
  }

  const copyShareString = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(createThemeShareString(variant, theme))
      setCopyStatus('copied')
      if (copyTimer.current) window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopyStatus('idle'), 1500)
    } catch {
      setCopyStatus('failed')
      if (copyTimer.current) window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopyStatus('idle'), 2500)
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
          <h2 className="text-[16px] font-semibold text-ds-ink">{titleLabel}</h2>
          {!isPristine ? (
            <button
              type="button"
              title={t('themePackReset')}
              aria-label={controlLabel(t('themePackReset'))}
              onClick={() => onThemeReplace({ ...DEFAULT_CHROME_THEMES[variant] })}
              className="inline-flex h-6 w-6 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            >
              <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.75} />
            </button>
          ) : null}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            aria-expanded={importOpen}
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
            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition hover:bg-ds-hover ${
              copyStatus === 'failed' ? 'text-red-700 dark:text-red-300' : 'text-ds-muted hover:text-ds-ink'
            }`}
          >
            {copyStatus === 'copied' ? (
              <Check className="h-3.5 w-3.5 text-emerald-500" strokeWidth={2} />
            ) : (
              <Copy className="h-3.5 w-3.5" strokeWidth={1.75} />
            )}
            <span aria-live="polite">
              {copyStatus === 'copied'
                ? t('themePackCopied')
                : copyStatus === 'failed'
                  ? t('themePackCopyFailed')
                  : t('themePackCopy')}
            </span>
          </button>
          <div className="w-40">
            <SettingsSelect
              aria-label={controlLabel(t('themePackPreset'))}
              allowReselect
              wrapperClassName="h-10 rounded-xl"
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

      <div className="px-5 pt-2 text-[12.5px] text-ds-faint">
        {statusText}
        {isCustomized ? ` ${t('themePackCustomized', { preset: presetLabel })}` : null}
      </div>

      {importOpen ? (
        <div className="mx-5 mt-2 rounded-xl border border-ds-border-muted bg-ds-main/45 p-3">
          <textarea
            value={importText}
            onChange={(e) => {
              setImportText(e.target.value)
              setImportError(null)
            }}
            placeholder="codex-theme-v1:{…}"
            rows={3}
            aria-label={controlLabel(t('themePackShareString'))}
            className="w-full rounded-lg border border-ds-border bg-ds-card px-2.5 py-1.5 font-mono text-[12px] text-ds-ink placeholder:text-ds-faint focus:border-accent/40 focus:outline-none"
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <span
              role={importError ? 'alert' : undefined}
              className="min-w-0 truncate text-[12px] text-red-700 dark:text-red-300"
            >
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
            <ColorPill
              value={theme.accent}
              ariaLabel={controlLabel(t('themeAccent'))}
              onCommit={(value) => onThemePatch({ accent: value })}
            />
          }
        />
        <Row
          title={t('themeBackground')}
          control={
            <ColorPill
              value={theme.surface}
              ariaLabel={controlLabel(t('themeBackground'))}
              onCommit={(value) => onThemePatch({ surface: value })}
            />
          }
        />
        <Row
          title={t('themeForeground')}
          control={
            <ColorPill
              value={theme.ink}
              ariaLabel={controlLabel(t('themeForeground'))}
              onCommit={(value) => onThemePatch({ ink: value })}
            />
          }
        />
        <Row
          title={t('themeUiFont')}
          control={
            <FontInput
              value={theme.uiFont}
              onChange={(value) => onThemePatch({ uiFont: value })}
              placeholder={t('themeUiFontPlaceholder')}
              ariaLabel={controlLabel(t('themeUiFont'))}
            />
          }
        />
        <Row
          title={t('themeCodeFont')}
          control={
            <FontInput
              value={theme.codeFont}
              onChange={(value) => onThemePatch({ codeFont: value })}
              placeholder={t('themeCodeFontPlaceholder')}
              ariaLabel={controlLabel(t('themeCodeFont'))}
              mono
            />
          }
        />
        <Row
          title={t('themeTranslucent')}
          description={t(IS_MAC ? 'themeTranslucentDesc' : 'themeTranslucentUnsupported')}
          control={
            <Toggle
              checked={theme.translucent}
              ariaLabel={controlLabel(t('themeTranslucent'))}
              onChange={(value) => onThemePatch({ translucent: value })}
              disabled={!IS_MAC}
            />
          }
        />
        <Row
          title={t('themeContrast')}
          control={
            <div className="flex h-10 w-full items-center gap-3">
              <input
                type="range"
                min={0}
                max={100}
                value={theme.contrast}
                onChange={(e) => onThemePatch({ contrast: Number(e.target.value) })}
                aria-label={controlLabel(t('themeContrast'))}
                className="ds-no-drag h-1.5 w-full cursor-pointer appearance-none rounded-full bg-ds-border accent-[var(--ds-accent)]"
              />
              <span className="w-8 shrink-0 text-center font-mono text-[13px] leading-none text-ds-muted">
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
  ariaLabel,
  onCommit
}: {
  value: string
  ariaLabel: string
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
      className="relative flex h-10 w-full items-center overflow-hidden rounded-full border px-2 shadow-sm focus-within:ring-2 focus-within:ring-accent/45"
      style={{
        backgroundColor: value,
        borderColor: 'var(--ds-border)',
        color: pickReadableTextColor(value)
      }}
    >
      <span className="absolute left-2 top-1/2 z-[1] inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center">
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
          aria-label={ariaLabel}
        />
      </span>
      <input
        value={draft}
        maxLength={7}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commitDraft}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commitDraft()
        }}
        spellCheck={false}
        aria-label={`${ariaLabel} · HEX`}
        className="h-full w-full min-w-0 bg-transparent px-9 text-center font-mono text-[13px] font-medium uppercase leading-10 focus:outline-none"
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

const CONTROL_FIELD_CLASS =
  'box-border h-10 w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 text-center text-[14px] leading-10 text-ds-ink shadow-sm placeholder:text-ds-faint focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30'

function FontInput({
  value,
  placeholder,
  ariaLabel,
  onChange,
  options,
  mono = false,
  className = ''
}: {
  value: string
  placeholder: string
  ariaLabel: string
  onChange: (value: string) => void
  /** When provided, renders a custom aligned dropdown instead of native datalist. */
  options?: readonly string[]
  mono?: boolean
  className?: string
}): ReactElement {
  const [draft, setDraft] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useLightDismiss({ open, onDismiss: () => setOpen(false), refs: [containerRef] })

  const selectOption = useCallback(
    (opt: string) => {
      setDraft(opt)
      onChange(opt)
      setOpen(false)
      inputRef.current?.focus()
    },
    [onChange]
  )

  const displayValue = draft ?? value
  const fieldClass = `${CONTROL_FIELD_CLASS} ${mono ? 'font-mono' : ''} ${className}`.trim()

  if (!options) {
    return (
      <input
        ref={inputRef}
        value={displayValue}
        onChange={(event) => {
          const next = event.target.value
          setDraft(next)
          onChange(next)
        }}
        onBlur={() => setDraft(null)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        spellCheck={false}
        autoComplete="off"
        maxLength={256}
        className={fieldClass}
      />
    )
  }

  const filtered = displayValue
    ? options.filter((o) => o.toLowerCase().includes(displayValue.toLowerCase()))
    : options

  return (
    <div ref={containerRef} className="relative w-full min-w-0">
      <input
        ref={inputRef}
        value={displayValue}
        onChange={(event) => {
          const next = event.target.value
          setDraft(next)
          onChange(next)
          if (!open) setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setDraft(null)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        spellCheck={false}
        autoComplete="off"
        maxLength={256}
        className={fieldClass}
      />
      {open && filtered.length > 0 && (
        <ul className="absolute left-0 right-0 top-full z-50 mt-1 max-h-48 overflow-auto rounded-xl border border-ds-border bg-ds-card py-1 shadow-lg">
          {filtered.map((opt) => (
            <li key={opt}>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); selectOption(opt) }}
                className={`block w-full px-3 py-1.5 text-left text-[13px] transition hover:bg-ds-hover ${
                  opt === value ? 'font-semibold text-ds-ink' : 'text-ds-muted'
                }`}
              >
                {opt}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function PxInput({
  value,
  min,
  max,
  ariaLabel,
  onCommit
}: {
  value: number
  min: number
  max: number
  ariaLabel: string
  onCommit: (value: number) => void
}): ReactElement {
  const [draft, setDraft] = useState<string | null>(null)
  // Commit on blur/Enter only: committing per keystroke clamped a half-typed
  // value (typing "18" committed "1" -> min) and the whole UI jumped mid-edit.
  const commit = (): void => {
    if (draft === null) return
    const parsed = Number(draft.trim())
    setDraft(null)
    if (Number.isFinite(parsed)) {
      onCommit(Math.min(max, Math.max(min, Math.round(parsed))))
    }
  }
  return (
    <div className="flex h-10 w-full items-center gap-2">
      <input
        type="number"
        min={min}
        max={max}
        step={1}
        value={draft ?? String(value)}
        aria-label={ariaLabel}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
        }}
        className={`${CONTROL_FIELD_CLASS} text-center tabular-nums`}
      />
      <span className="shrink-0 text-[13px] leading-none text-ds-faint">px</span>
    </div>
  )
}

function SectionLabel({ children }: { children: ReactNode }): ReactElement {
  return (
    <h2 className="px-1 text-[12.5px] font-medium uppercase tracking-wide text-ds-faint">
      {children}
    </h2>
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
  control,
  controlMaxWidth = 'sm:max-w-[280px]'
}: {
  title: string
  description?: ReactNode
  control: ReactNode
  controlMaxWidth?: string
}): ReactElement {
  return (
    <div className="ds-density-row flex flex-col gap-3 px-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold leading-none text-ds-ink">{title}</div>
        {description ? (
          <p className="mt-1.5 max-w-md text-pretty text-[13px] leading-relaxed text-ds-muted">
            {description}
          </p>
        ) : null}
      </div>
      <div className={`flex w-full min-w-0 items-center justify-end sm:ml-auto ${controlMaxWidth} sm:shrink-0`}>
        {control}
      </div>
    </div>
  )
}

function Toggle({
  checked,
  ariaLabel,
  onChange,
  disabled = false
}: {
  checked: boolean
  ariaLabel: string
  onChange: (v: boolean) => void
  disabled?: boolean
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 self-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-45 ${
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
