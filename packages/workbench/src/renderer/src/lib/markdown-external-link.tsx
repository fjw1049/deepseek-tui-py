import type { ComponentProps, MouseEvent, ReactElement } from 'react'

/**
 * Anchor for untrusted markdown (model reasoning, marketplace READMEs). A bare
 * `<a>` would navigate the privileged app window, so http(s)/mailto links are
 * handed to the OS browser and everything else is rendered inert.
 */
export function MarkdownExternalLink({
  href,
  children,
  className,
  title
}: ComponentProps<'a'> & { node?: unknown }): ReactElement {
  const external = href ? /^(https?:|mailto:)/i.test(href) : false
  if (!external) return <span className={className}>{children}</span>
  const onClick = (event: MouseEvent<HTMLAnchorElement>): void => {
    event.preventDefault()
    if (href && typeof window.dsGui?.openExternal === 'function') void window.dsGui.openExternal(href)
  }
  return (
    <a href={href} title={title} className={className} onClick={onClick} rel="noreferrer noopener">
      {children}
    </a>
  )
}

export const markdownExternalLinkComponents = { a: MarkdownExternalLink }
