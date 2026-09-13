import type { ReactElement } from 'react'
import type { Notice } from '../extensions/marketplace-shared'
import { NoticeView } from '../extensions/marketplace-ui'

export function ComposerNoticeToast({ notice, onDismiss }: { notice: Notice; onDismiss: () => void }): ReactElement {
  return <div className="max-w-[min(100%,560px)]"><NoticeView notice={notice} onDismiss={onDismiss} /></div>
}
