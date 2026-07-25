import { useMemo, useState, type ComponentProps, type ReactElement } from 'react'
import { PawPrint } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { usePetController } from '../../hooks/use-pet-controller'
import { filterPetSlashMenu, PET_SLASH_MENU } from '../../lib/pet/pet-slash-commands'
import { useNoticeAutoDismiss, type Notice } from '../extensions/marketplace-shared'
import { PetMascotDock } from '../pet/PetMascotDock'
import { ComposerNoticeToast } from './composer-notice'
import { FloatingComposer } from './FloatingComposer'
import { ProcessTray } from './ProcessTray'

type Props = ComponentProps<typeof FloatingComposer>

export function ComposerStage(props: Props): ReactElement {
  const { t } = useTranslation('common')
  const pet = usePetController()
  const [composerNotice, setComposerNotice] = useState<Notice | null>(null)
  useNoticeAutoDismiss(composerNotice, setComposerNotice)

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
    props.onSend(text)
  }

  return (
    <div className="flex w-full flex-col items-stretch">
      <div className="relative">
        <div className="ds-chat-stage flex w-full px-3 sm:px-4">
          <div className="ds-no-drag min-w-0 flex-1">
            <ProcessTray />
          </div>
        </div>
        {/* Decorative only: sit behind the composer (z-0) and ignore hits so the
            model picker popover above the input stays clickable on the right. */}
        <div className="pointer-events-none absolute bottom-0 right-0 z-0">
          <PetMascotDock
            visible
            status={pet.status}
            stateId={pet.stateId}
            spritesheetSrc={pet.spritesheetSrc}
            roamOffset={pet.roamOffset}
            motionPaused={pet.motionPaused}
          />
        </div>
      </div>
      {composerNotice ? (
        <div className="ds-chat-stage mb-1.5 flex w-full justify-center px-3 sm:px-4">
          <ComposerNoticeToast notice={composerNotice} />
        </div>
      ) : null}
      <FloatingComposer
        {...props}
        onNoticeChange={setComposerNotice}
        onSend={handleSend}
        petSlashCommands={petSlashCommands}
        onApplyPetSlashCommand={pet.handlePetSlash}
        filterPetSlashCommands={filterPetSlashMenu}
      />
    </div>
  )
}
