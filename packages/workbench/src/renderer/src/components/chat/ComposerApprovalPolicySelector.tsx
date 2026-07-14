import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactElement
} from 'react'
import { Check, Hand, Shield, Zap } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ApprovalPolicy } from '@shared/app-settings'
import { useChatStore } from '../../store/chat-store'

/**
 * Composer shortcut for the three most-used approval policies that already
 * exist in Settings → Permissions. Values are the real `ApprovalPolicy`
 * enum members — never invent labels that belong to sandbox mode.
 */
export type ComposerApprovalTier = Extract<ApprovalPolicy, 'on-request' | 'untrusted' | 'auto'>

type Props = {
  disabled?: boolean
  onOpenChange?: (open: boolean) => void
}

export function ComposerApprovalPolicySelector({
  disabled = false,
  onOpenChange
}: Props): ReactElement {
  const { t } = useTranslation(['common', 'settings'])
  const openSettings = useChatStore((s) => s.openSettings)
  const probeRuntime = useChatStore((s) => s.probeRuntime)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [open, setOpen] = useState(false)
  const [policy, setPolicy] = useState<ApprovalPolicy>('on-request')
  const [saving, setSaving] = useState(false)

  const setMenuOpen = useCallback(
    (next: boolean) => {
      setOpen(next)
      onOpenChange?.(next)
    },
    [onOpenChange]
  )

  const refreshPolicy = useCallback(async (): Promise<void> => {
    if (typeof window.dsGui?.getSettings !== 'function') return
    const settings = await window.dsGui.getSettings()
    setPolicy(settings.deepseek.approvalPolicy)
  }, [])

  useEffect(() => {
    void refreshPolicy()
  }, [refreshPolicy])

  useEffect(() => {
    if (!open) return
    void refreshPolicy()
  }, [open, refreshPolicy])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent): void => {
      const target = event.target
      if (!(target instanceof Node) || !wrapRef.current?.contains(target)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open, setMenuOpen])

  const triggerLabel =
    policy === 'auto'
      ? t('settings:approvalAuto')
      : policy === 'untrusted'
        ? t('settings:approvalUntrusted')
        : policy === 'never'
          ? t('settings:approvalNever')
          : policy === 'suggest'
            ? t('settings:approvalSuggest')
            : t('settings:approvalOnRequest')

  const TriggerIcon =
    policy === 'auto' ? Zap : policy === 'untrusted' ? Shield : Hand

  // auto = soft amber; untrusted = pale gold; on-request = pale green
  const tierAccent: Record<ComposerApprovalTier, string> = {
    auto: '#e0a04a',
    untrusted: '#c9b06a',
    'on-request': '#7eab8a'
  }
  const triggerAccent =
    policy === 'auto' || policy === 'untrusted' || policy === 'on-request'
      ? tierAccent[policy]
      : undefined

  const options: Array<{
    id: ComposerApprovalTier
    title: string
    description: string
    Icon: typeof Hand
    accent: string
  }> = [
    {
      id: 'on-request',
      title: t('settings:approvalOnRequest'),
      description: t('common:composerApprovalOnRequestDesc'),
      Icon: Hand,
      accent: tierAccent['on-request']
    },
    {
      id: 'untrusted',
      title: t('settings:approvalUntrusted'),
      description: t('common:composerApprovalUntrustedDesc'),
      Icon: Shield,
      accent: tierAccent.untrusted
    },
    {
      id: 'auto',
      title: t('settings:approvalAuto'),
      description: t('common:composerApprovalAutoDesc'),
      Icon: Zap,
      accent: tierAccent.auto
    }
  ]

  const selectPolicy = async (next: ComposerApprovalTier): Promise<void> => {
    if (saving || next === policy) {
      setMenuOpen(false)
      return
    }
    if (typeof window.dsGui?.setSettings !== 'function') return
    setSaving(true)
    try {
      const updated = await window.dsGui.setSettings({
        deepseek: { approvalPolicy: next }
      })
      setPolicy(updated.deepseek.approvalPolicy)
      setMenuOpen(false)
      void probeRuntime('background')
    } catch {
      /* keep previous selection */
    } finally {
      setSaving(false)
    }
  }

  return (
    <div ref={wrapRef} className="relative mr-1.5 shrink-0">
      <button
        type="button"
        disabled={disabled || saving}
        onClick={() => setMenuOpen(!open)}
        className="ds-no-drag inline-flex h-8 shrink-0 select-none items-center gap-1.5 text-[13px] font-semibold transition hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-50"
        style={triggerAccent ? { color: triggerAccent } : undefined}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('settings:approvalPolicy')}
        title={t('settings:approvalPolicy')}
      >
        <TriggerIcon className="h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
        <span className={triggerAccent ? undefined : 'text-ds-ink'}>{triggerLabel}</span>
      </button>

      {open ? (
        <div className="absolute bottom-full left-0 z-40 mb-2 w-[min(100vw-2rem,320px)]">
          <div className="ds-glass overflow-hidden rounded-2xl p-2 shadow-[0_18px_48px_rgba(15,23,42,0.18)]">
            <div className="flex items-start justify-between gap-3 px-2 pb-2 pt-1.5">
              <p className="text-[13px] font-semibold leading-5 text-ds-ink">
                {t('settings:approvalPolicy')}
              </p>
              <button
                type="button"
                className="shrink-0 text-[12px] font-medium text-accent transition hover:opacity-80"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  setMenuOpen(false)
                  openSettings('permissions')
                }}
              >
                {t('common:composerApprovalLearnMore')}
              </button>
            </div>
            <div className="space-y-0.5">
              {options.map((option) => {
                const selected = policy === option.id
                const OptionIcon = option.Icon
                return (
                  <button
                    key={option.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={selected}
                    disabled={saving}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => void selectPolicy(option.id)}
                    className={`flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2.5 text-left transition ${
                      selected ? 'bg-ds-hover' : 'hover:bg-ds-hover/70'
                    }`}
                  >
                    <OptionIcon
                      className="mt-0.5 h-4 w-4 shrink-0"
                      strokeWidth={1.9}
                      style={{ color: option.accent }}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <span
                        className="block text-[13px] font-semibold leading-5"
                        style={{ color: option.accent }}
                      >
                        {option.title}
                      </span>
                      <span className="mt-0.5 block text-[12px] leading-5 text-ds-muted">
                        {option.description}
                      </span>
                    </span>
                    {selected ? (
                      <Check
                        className="mt-0.5 h-4 w-4 shrink-0 text-ds-ink"
                        strokeWidth={2.2}
                        aria-hidden
                      />
                    ) : (
                      <span className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
