// Theme tokens can resolve to hex or rgba. Mix with transparent so Tailwind's
// /NN modifiers multiply either form instead of silently dropping the utility.
const themeColor = (token) => ({ opacityValue }) =>
  opacityValue === undefined || opacityValue === '1'
    ? `var(${token})`
    : `color-mix(in srgb, var(${token}) calc(${opacityValue} * 100%), transparent)`

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
          DEFAULT: themeColor('--ds-accent'),
          foreground: themeColor('--ds-accent-foreground'),
          soft: themeColor('--ds-accent-soft')
        },
        background: themeColor('--ds-bg-canvas'),
        foreground: themeColor('--ds-text'),
        border: themeColor('--ds-border'),
        muted: {
          DEFAULT: themeColor('--ds-surface-subtle'),
          foreground: themeColor('--ds-text-muted')
        },
        sidebar: themeColor('--ds-surface-subtle'),
        primary: {
          DEFAULT: themeColor('--ds-accent'),
          foreground: themeColor('--ds-accent-foreground')
        },
        ds: {
          main: themeColor('--ds-bg-main'),
          sidebar: themeColor('--ds-bg-sidebar'),
          canvas: themeColor('--ds-bg-canvas'),
          card: themeColor('--ds-surface-card'),
          elevated: themeColor('--ds-surface-elevated'),
          subtle: themeColor('--ds-surface-subtle'),
          hover: themeColor('--ds-surface-hover'),
          border: themeColor('--ds-border'),
          'border-muted': themeColor('--ds-border-muted'),
          ink: themeColor('--ds-text'),
          muted: themeColor('--ds-text-muted'),
          faint: themeColor('--ds-text-faint'),
          success: themeColor('--ds-success'),
          'success-soft': themeColor('--ds-success-soft'),
          danger: themeColor('--ds-danger'),
          'danger-soft': themeColor('--ds-danger-soft'),
          'diff-added': themeColor('--ds-diff-added'),
          'diff-added-soft': themeColor('--ds-diff-added-soft'),
          'diff-removed': themeColor('--ds-diff-removed'),
          'diff-removed-soft': themeColor('--ds-diff-removed-soft'),
          skill: themeColor('--ds-skill'),
          'skill-soft': themeColor('--ds-skill-soft'),
          userbubble: themeColor('--ds-bubble-user'),
          userbubbleFg: themeColor('--ds-bubble-user-fg')
        }
      },
      // Unqualified borders and dividers also use the current soft hairline.
      borderColor: {
        DEFAULT: themeColor('--ds-border')
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
