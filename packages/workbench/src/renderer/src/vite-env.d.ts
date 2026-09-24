/// <reference types="vite/client" />

declare module '*.webp' {
  const src: string
  export default src
}

declare module '*.svg' {
  const src: string
  export default src
}

declare module '*.svg?raw' {
  const src: string
  export default src
}

declare module '*.png' {
  const src: string
  export default src
}

import type { DetailedHTMLProps, HTMLAttributes } from 'react'

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      webview: DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        // React 19 ships its own webview JSX typing (allowpopups?: boolean),
        // but React refuses to WRITE boolean attributes on non-standard
        // elements — the string form is required for the attribute to reach
        // the DOM and enable window.open in Electron guests.
        allowpopups?: boolean | string
        partition?: string
        src?: string
        webpreferences?: string
      }
      'reasoning-effort-selector': DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>
    }
  }
}
