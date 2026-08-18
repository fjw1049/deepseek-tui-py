import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactElement
} from 'react'
import { PawPrint } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { usePetController } from '../../hooks/use-pet-controller'
import { filterPetSlashMenu, PET_SLASH_MENU } from '../../lib/pet/pet-slash-commands'
import { useNoticeAutoDismiss, type Notice } from '../extensions/marketplace-shared'
import { PetMascotDock } from '../pet/PetMascotDock'
import { ComposerNoticeToast } from './composer-notice'
import { FloatingComposer } from './FloatingComposer'
import { GoalStrip } from './GoalStrip'

type Props = ComponentProps<typeof FloatingComposer> & {
  /** One-shot notice from parent (e.g. preview pick limit); keyed by nonce. */
  flashNotice?: Notice | null
  flashNoticeNonce?: number
}

const COMPOSER_CLEARANCE_VAR = '--ds-composer-clearance'

export function ComposerStage(props: Props): ReactElement {
  const { t } = useTranslation('common')
  const pet = usePetController()
  const rootRef = useRef<HTMLDivElement>(null)
  const [composerNotice, setComposerNotice] = useState<Notice | null>(null)
  useNoticeAutoDismiss(composerNotice, setComposerNotice)

  const { flashNotice = null, flashNoticeNonce = 0, ...composerProps } = props

  useEffect(() => {
    if (flashNoticeNonce > 0 && flashNotice) {
      setComposerNotice(flashNotice)
    }
  }, [flashNotice, flashNoticeNonce])

  const petSlashCommands = useMemo(
    () =>
      PET_SLASH_MENU.map((item) => ({
        command: item.command,
        token: item.token,
        title: t(item.titleKey),
        description: t(item.descriptionKey),
        icon: <PawPrint className="h-4 w-4" strokeWidth={1.8} />
      })),
    [t]
  )

  const handleSend = (text: string): void => {
    if (pet.handlePetSlash(text)) return
    composerProps.onSend(text)
  }

  // Timeline spacer follows real composer height (approvals /
  // queued messages) so overlapping chrome doesn't cover the last answer or
  // make the dialogue appear to jump when the tray mounts.
  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root || typeof ResizeObserver === 'undefined') return
    const publish = (): void => {
      const height = Math.ceil(root.getBoundingClientRect().height)
      document.documentElement.style.setProperty(
        COMPOSER_CLEARANCE_VAR,
        `${Math.max(height, 0)}px`
      )
    }
    publish()
    const ro = new ResizeObserver(publish)
    ro.observe(root)
    return () => {
      ro.disconnect()
      document.documentElement.style.removeProperty(COMPOSER_CLEARANCE_VAR)
    }
  }, [])

  return (
    <div ref={rootRef} className="relative flex w-full flex-col items-stretch">
      {composerNotice ? (
        <div className="ds-chat-stage mb-1.5 flex w-full justify-center px-3 sm:px-4">
          <ComposerNoticeToast notice={composerNotice} />
        </div>
      ) : null}
      <div className="relative">
        <GoalStrip />
        {/* Decorative only: rest just above the input (bottom-full) and ignore
            hits so the model picker popover above the composer stays clickable
            on the right. */}
        <div className="pointer-events-none absolute bottom-full right-0 z-0">
          <PetMascotDock
            visible
            status={pet.status}
            stateId={pet.stateId}
            spritesheetSrc={pet.spritesheetSrc}
            roamOffset={pet.roamOffset}
            motionPaused={pet.motionPaused}
          />
        </div>
        <FloatingComposer
          {...composerProps}
          onNoticeChange={setComposerNotice}
          onSend={handleSend}
          petSlashCommands={petSlashCommands}
          onApplyPetSlashCommand={pet.handlePetSlash}
          filterPetSlashCommands={filterPetSlashMenu}
        />
      </div>
    </div>
  )
}
