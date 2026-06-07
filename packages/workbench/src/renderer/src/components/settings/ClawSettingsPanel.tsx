import type { ReactElement } from 'react'
import { CalendarClock, ChevronRight, MessageCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { AppSettingsV1, ClawSettingsPatchV1 } from '@shared/app-settings'
import { useChatStore } from '../../store/chat-store'

type Props = {
  form: AppSettingsV1
  onClawPatch: (patch: ClawSettingsPatchV1) => void
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${checked ? 'bg-emerald-500' : 'bg-ds-faint'}`}
    >
      <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition ${checked ? 'left-[22px]' : 'left-0.5'}`} />
    </button>
  )
}

export function ClawSettingsPanel({ form, onClawPatch }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const setRoute = useChatStore((state) => state.setRoute)

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-2xl border border-ds-border bg-ds-card/95 shadow-sm">
        <div className="border-b border-ds-border-muted px-5 py-3">
          <h2 className="text-[16px] font-semibold text-ds-ink">{t('clawRuntime')}</h2>
          <p className="mt-1 text-[13px] leading-6 text-ds-muted">{t('clawEnabledDesc')}</p>
        </div>
        <div className="flex items-center justify-between gap-4 px-5 py-4">
          <div>
            <div className="text-[14px] font-medium text-ds-ink">{t('clawEnabled')}</div>
            <div className="mt-0.5 text-[12px] text-ds-faint">{t('clawMasterSwitchDesc')}</div>
          </div>
          <Toggle checked={form.claw.enabled} onChange={(enabled) => onClawPatch({ enabled })} />
        </div>
      </div>

      <div className="rounded-2xl border border-ds-border bg-ds-card/95 shadow-sm">
        <div className="border-b border-ds-border-muted px-5 py-3">
          <h2 className="text-[16px] font-semibold text-ds-ink">{t('clawOpsTitle')}</h2>
          <p className="mt-1 text-[13px] leading-6 text-ds-muted">{t('clawOpsDesc')}</p>
        </div>
        <button
          type="button"
          onClick={() => setRoute('automation')}
          className="flex w-full items-center gap-3 border-b border-ds-border-muted px-5 py-4 text-left hover:bg-ds-hover"
        >
          <CalendarClock className="h-5 w-5 text-ds-muted" />
          <span className="flex-1">
            <span className="block text-[14px] font-medium text-ds-ink">
              {t('clawOpsAutomationTitle')}
            </span>
            <span className="mt-0.5 block text-[12px] text-ds-faint">
              {t('clawOpsAutomationDesc')}
            </span>
          </span>
          <ChevronRight className="h-4 w-4 text-ds-faint" />
        </button>
        <button
          type="button"
          onClick={() => setRoute('channels')}
          className="flex w-full items-center gap-3 px-5 py-4 text-left hover:bg-ds-hover"
        >
          <MessageCircle className="h-5 w-5 text-ds-muted" />
          <span className="flex-1">
            <span className="block text-[14px] font-medium text-ds-ink">
              {t('clawOpsChannelsTitle')}
            </span>
            <span className="mt-0.5 block text-[12px] text-ds-faint">
              {t('clawOpsChannelsDesc')}
            </span>
          </span>
          <ChevronRight className="h-4 w-4 text-ds-faint" />
        </button>
      </div>
    </div>
  )
}
