/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['selector', '[data-theme="dark"]'],
  content: [
    './src/renderer/index.html',
    './src/renderer/src/**/*.{ts,tsx}',
    './node_modules/streamdown/dist/**/*.js'
  ],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: 'var(--ds-accent)',
          foreground: '#ffffff',
          soft: 'var(--ds-accent-soft)'
        },
        background: 'var(--ds-bg-canvas)',
        foreground: 'var(--ds-text)',
        border: 'var(--ds-border)',
        muted: {
          DEFAULT: 'var(--ds-surface-subtle)',
          foreground: 'var(--ds-text-muted)'
        },
        sidebar: 'var(--ds-surface-subtle)',
        primary: {
          DEFAULT: 'var(--ds-accent)',
          foreground: '#ffffff'
        },
        ds: {
          main: 'var(--ds-bg-main)',
          sidebar: 'var(--ds-bg-sidebar)',
          canvas: 'var(--ds-bg-canvas)',
          card: 'var(--ds-surface-card)',
          elevated: 'var(--ds-surface-elevated)',
          subtle: 'var(--ds-surface-subtle)',
          hover: 'var(--ds-surface-hover)',
          border: 'var(--ds-border)',
          'border-muted': 'var(--ds-border-muted)',
          ink: 'var(--ds-text)',
          muted: 'var(--ds-text-muted)',
          faint: 'var(--ds-text-faint)',
          success: 'var(--ds-success)',
          'success-soft': 'var(--ds-success-soft)',
          danger: 'var(--ds-danger)',
          'danger-soft': 'var(--ds-danger-soft)',
          'diff-added': 'var(--ds-diff-added)',
          'diff-added-soft': 'var(--ds-diff-added-soft)',
          'diff-removed': 'var(--ds-diff-removed)',
          'diff-removed-soft': 'var(--ds-diff-removed-soft)',
          skill: 'var(--ds-skill)',
          'skill-soft': 'var(--ds-skill-soft)',
          userbubble: 'var(--ds-bubble-user)',
          userbubbleFg: 'var(--ds-bubble-user-fg)'
        }
      },
      /* Colors above are full rgba() var() strings, so Tailwind v3 cannot apply
         `/NN` alpha modifiers to them — classes like `border-ds-border/60` are
         silently NOT generated and the border falls back to preflight's default
         border-color. Point that default at the theme token so every such
         border renders as the soft hairline instead of opaque gray-200
         (#e5e7eb), which glared on dark surfaces. divideColor follows this. */
      borderColor: {
        DEFAULT: 'var(--ds-border)'
      },
      boxShadow: {
        composer: 'var(--ds-shadow-composer)',
        shell: 'var(--ds-shadow-shell)',
        panel: 'var(--ds-shadow-panel)'
      },
      borderRadius: {
        xl: '10px',
        '2xl': '14px',
        '3xl': '16px'
      },
      fontFamily: {
        sans: ['var(--font-ui)'],
        display: ['var(--font-display)'],
        mono: ['var(--font-mono)'],
        ui: ['var(--font-ui)']
      }
    }
  },
  plugins: []
}
