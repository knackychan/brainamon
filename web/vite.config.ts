import { svelte } from '@sveltejs/vite-plugin-svelte'
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'
import { defineConfig, searchForWorkspaceRoot } from 'vite'

// Dev mode (dev.bat): Vite serves the UI on 127.0.0.1:5173 and proxies the API to the backend.
// changeOrigin rewrites the Host header to 127.0.0.1:18765 so server/guard.py accepts it.
const backend = { target: 'http://127.0.0.1:18765', changeOrigin: true }
// Compile only the issuer's public verifier; never import runtime settings or private material.
const trust = readFileSync(fileURLToPath(new URL('../core/license.py', import.meta.url)), 'utf8').match(/PUBLIC_KEYS:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(([\s\S]*?)\)/)
if (!trust) throw new Error('License public verifier configuration is missing')
const issuerKeys = [...trust[1].matchAll(/['"]([a-fA-F0-9]{64})['"]/g)].map(m => m[1])

export default defineConfig({
  define: { __LICENSE_PUBLIC_KEYS__: JSON.stringify(issuerKeys) },
  plugins: [svelte()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': backend, '/thumb': backend, '/cards': backend, '/files': backend, '/wiskit': backend },
    // the phone imports the shared prompt files (knowledge/prompts, src/mobile/ai/prompts.ts)
    fs: { allow: [
      searchForWorkspaceRoot(process.cwd()),
      fileURLToPath(new URL('../knowledge/prompts', import.meta.url)),
      fileURLToPath(new URL('../LICENSE', import.meta.url)),
      fileURLToPath(new URL('../THIRD_PARTY_NOTICES.md', import.meta.url)),
      fileURLToPath(new URL('../mobile-shell/store/privacy-policy.md', import.meta.url)),
    ] },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // Three pages: the app, Wiskit's drop panel (projects/desktop-app plan 07), which stays small, and
    // the phone (projects/mobile-app/PLAN.md Phase 2), served by the same backend at /mobile.html.
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('index.html', import.meta.url)),
        panel: fileURLToPath(new URL('panel.html', import.meta.url)),
        mobile: fileURLToPath(new URL('mobile.html', import.meta.url)),
      },
    },
  },
})
