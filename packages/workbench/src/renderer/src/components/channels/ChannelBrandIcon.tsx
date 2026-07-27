import type { ReactElement } from 'react'
import feishuSvg from '../../assets/channel-icons/feishu.svg?raw'
import emailSvg from '../../assets/channel-icons/email.svg?raw'
import wecomSvg from '../../assets/channel-icons/wecom.svg?raw'

export type ChannelBrand = 'feishu' | 'email' | 'wecom'

type BrandMeta = {
  svg: string
  /** Soft wash behind the full-color brand mark. */
  washClass: string
  label: string
}

const BRANDS: Record<ChannelBrand, BrandMeta> = {
  feishu: {
    svg: feishuSvg,
    washClass:
      'bg-[linear-gradient(145deg,#E8F7FF_0%,#EAF3FF_55%,#F0F7FF_100%)] dark:bg-[linear-gradient(145deg,rgba(51,112,255,0.22),rgba(0,214,185,0.14))]',
    label: 'Feishu'
  },
  email: {
    svg: emailSvg,
    washClass:
      'bg-[linear-gradient(145deg,#EAF6FF_0%,#E3F2FC_100%)] dark:bg-[linear-gradient(145deg,rgba(75,163,227,0.22),rgba(47,143,214,0.12))]',
    label: 'Email'
  },
  wecom: {
    svg: wecomSvg,
    washClass:
      'bg-[linear-gradient(145deg,#E9F9EF_0%,#E6F6EB_100%)] dark:bg-[linear-gradient(145deg,rgba(7,193,96,0.22),rgba(7,193,96,0.10))]',
    label: 'WeCom'
  }
}

type Props = {
  brand: ChannelBrand
  className?: string
}

/**
 * Channel list app mark — full-color brand glyph in a larger soft tile so it
 * reads as the real app icon without overwhelming the card typography.
 */
export function ChannelBrandIcon({ brand, className = '' }: Props): ReactElement {
  const meta = BRANDS[brand]

  return (
    <div
      className={`ds-channel-brand-icon flex h-[58px] w-[58px] shrink-0 items-center justify-center rounded-[15px] shadow-[inset_0_0_0_1px_rgba(15,23,42,0.04)] ${meta.washClass} ${className}`}
      aria-hidden
      title={meta.label}
    >
      <span
        className="ds-channel-brand-glyph block h-9 w-9 [&_svg]:block [&_svg]:h-full [&_svg]:w-full"
        dangerouslySetInnerHTML={{ __html: meta.svg }}
      />
    </div>
  )
}
