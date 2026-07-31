import type { ReactElement, ReactNode } from 'react'
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
  Search,
  Settings,
  Shield
} from 'lucide-react'
import { useChatStore, type SettingsRouteSection } from '../../store/chat-store'
import { requestLeaveSettings } from '../../lib/settings-leave'

type SettingsCategory = SettingsRouteSection

type NavItem = {
  id: SettingsCategory
  labelKey: string
  icon: ReactNode
}

const NAV_ITEMS: NavItem[] = [
  { id: 'general', labelKey: 'general', icon: <Globe className="h-4 w-4" strokeWidth={1.75} /> },
  { id: 'appearance', labelKey: 'appearance', icon: <Palette className="h-4 w-4" strokeWidth={1.75} /> },
  { id: 'shortcuts', labelKey: 'shortcuts', icon: <Keyboard className="h-4 w-4" strokeWidth={1.75} /> },
  { id: 'models', labelKey: 'models', icon: <Box className="h-4 w-4" strokeWidth={1.75} /> },
  { id: 'search', labelKey: 'search', icon: <Search className="h-4 w-4" strokeWidth={1.75} /> },
  { id: 'hooks', labelKey: 'hooks', icon: <Anchor className="h-4 w-4" strokeWidth={1.75} /> },
  { id: 'permissions', labelKey: 'permissions', icon: <Shield className="h-4 w-4" strokeWidth={1.75} /> },
  { id: 'data', labelKey: 'data', icon: <HardDrive className="h-4 w-4" strokeWidth={1.75} /> },
  { id: 'archive', labelKey: 'archive', icon: <Archive className="h-4 w-4" strokeWidth={1.75} /> }
]

export function SettingsSidebarNav(): ReactElement {
  const { t } = useTranslation('settings')
  const category = useChatStore((s) => s.settingsSection)
  const openSettings = useChatStore((s) => s.openSettings)

  return (
    <div className="ds-no-drag flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-1 pb-2">
        <button
          type="button"
          onClick={() => requestLeaveSettings()}
          className="ds-sidebar-link ds-sidebar-link--plain flex w-full"
        >
          <span className="ds-sidebar-link__icon text-ds-muted">
            <ChevronLeft className="h-4 w-4" strokeWidth={1.75} />
          </span>
          <span className="min-w-0 flex-1 truncate text-left">{t('back')}</span>
        </button>
      </div>
      <nav className="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto px-1" aria-label={t('title')}>
        {NAV_ITEMS.map((item) => {
          const active = category === item.id
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => openSettings(item.id)}
              aria-current={active ? 'page' : undefined}
              className={`ds-sidebar-link ds-sidebar-link--plain ${
                active ? 'ds-sidebar-link--active' : ''
              }`}
            >
              <span
                className={`ds-sidebar-link__icon ${active ? 'text-accent' : 'text-ds-muted'}`}
              >
                {item.icon}
              </span>
              <span className="min-w-0 flex-1 truncate text-left">{t(item.labelKey)}</span>
            </button>
          )
        })}
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
