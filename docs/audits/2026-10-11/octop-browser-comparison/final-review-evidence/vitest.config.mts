import { defineConfig } from '/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/node_modules/vitest/dist/config.js'
export default defineConfig({
  root: '/private/tmp/browser-final-audit-20261012/ui',
  resolve: { alias: {
    '@shared': '/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared',
    'virtual:material-icons': '/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/test/material-icons-stub.ts',
    'react': '/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/node_modules/react',
    'react-dom': '/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/node_modules/react-dom'
  } },
  test: { environment: 'happy-dom', globals: true, include: ['*.test.ts'] }
})
