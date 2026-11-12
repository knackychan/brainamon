// One shared vault/access implementation in the page and the Android worker.
import { build } from 'vite'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const trust = readFileSync(new URL('../../core/license.py', import.meta.url), 'utf8').match(/PUBLIC_KEYS:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(([\s\S]*?)\)/)
if (!trust) throw Error('Missing public verifiers')
await build({
  configFile: false,
  root: fileURLToPath(new URL('../', import.meta.url)),
  define: { __LICENSE_PUBLIC_KEYS__: JSON.stringify([...trust[1].matchAll(/['"]([a-fA-F0-9]{64})['"]/g)].map(m => m[1])) },
  build: {
    outDir: '../mobile-shell/android/app/src/main/assets/sync', emptyOutDir: true,
    lib: { entry: 'src/mobile/sync/worker.ts', name: 'BrainamonSync', formats: ['iife'], fileName: () => 'worker.js' },
    target: 'es2022', minify: false,
  },
})
