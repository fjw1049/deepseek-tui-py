import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Anchor,
  Archive,
  Box,
  ChevronLeft,
  Globe,
  HardDrive,
  Keyboard,
  Palette,
  Settings,
  Shield
} from 'lucide-react'
import { useChatStore, type SettingsRouteSection } from '../../store/chat-store'
import { requestLeaveSettings } from '../../lib/settings-leave'

type SettingsCategory = SettingsRouteSection

export function SettingsSidebarNav(): ReactElement {
  const { t } = useTranslation('settings')
  const category = useChatStore((s) => s.settingsSection)
  const openSettings = useChatStore((s) => s.openSettings)

  const catCls = (c: SettingsCategory): string =>
    `flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[13.5px] font-medium transition ${
      category === c
        ? 'bg-ds-hover text-ds-ink'
        : 'text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
    }`

  return (
    <div className="ds-no-drag flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-1 pb-2">
        <button
          type="button"
          onClick={() => requestLeaveSettings()}
          className="flex w-full items-center gap-2 rounded-xl px-2 py-2 text-[14px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink"
        >
          <ChevronLeft className="h-4 w-4" strokeWidth={1.75} />
          {t('back')}
        </button>
      </div>
      <nav className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-1">
        <button type="button" className={catCls('general')} onClick={() => openSettings('general')}>
          <Globe className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
          {t('general')}
        </button>
        <button
          type="button"
          className={catCls('appearance')}
          onClick={() => openSettings('appearance')}
        >
          <Palette className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
          {t('appearance')}
        </button>
        <button
          type="button"
          className={catCls('shortcuts')}
          onClick={() => openSettings('shortcuts')}
        >
          <Keyboard className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
          {t('shortcuts')}
        </button>
        <button type="button" className={catCls('models')} onClick={() => openSettings('models')}>
          <Box className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
          {t('models')}
        </button>
        <button type="button" className={catCls('hooks')} onClick={() => openSettings('hooks')}>
          <Anchor className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
          {t('hooks')}
        </button>
        <button
          type="button"
          className={catCls('permissions')}
          onClick={() => openSettings('permissions')}
        >
          <Shield className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
          {t('permissions')}
        </button>
        <button type="button" className={catCls('data')} onClick={() => openSettings('data')}>
          <HardDrive className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
          {t('data')}
        </button>
        <button type="button" className={catCls('archive')} onClick={() => openSettings('archive')}>
          <Archive className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
          {t('archive')}
        </button>
      </nav>
      <div className="mt-auto shrink-0 border-t border-ds-border px-1 pt-2">
        <div className="flex items-center gap-2 rounded-xl px-2 py-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ds-subtle text-ds-muted">
            <Settings className="h-4 w-4" strokeWidth={1.75} />
          </div>
          <div className="min-w-0 truncate text-[13px] font-medium text-ds-ink">
            {t('settingsFooter')}
          </div>
        </div>
      </div>
    </div>
  )
}
