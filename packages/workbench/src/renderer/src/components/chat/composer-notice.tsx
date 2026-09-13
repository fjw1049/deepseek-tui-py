import type { ReactElement } from 'react'
import type { Notice } from '../extensions/marketplace-shared'
import { FeedbackNotice } from '../FeedbackNotice'

export function ComposerNoticeToast({ notice, onDismiss }: { notice: Notice; onDismiss: () => void }): ReactElement {
  return <div className="max-w-[min(100%,560px)]"><FeedbackNotice {...notice} onDismiss={onDismiss} /></div>
}
