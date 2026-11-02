"""The shared UI components (web/src/components/ui, web/src/mobile/ui) render exactly the markup they
replace: projects/ui-building-blocks plan 01. Fixture.svelte uses every component; expected.html is the
hand-written markup the windows and phone screens had before."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'ui_blocks'

# compiles .svelte files for the server on import, then prints the fixture's HTML without Svelte's comments
RENDER = r"""
import { registerHooks } from 'node:module'
import fs from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
const compiler = (await import(pathToFileURL(process.cwd() + '/web/node_modules/svelte/compiler/index.js').href)).default
const web = pathToFileURL(process.cwd() + '/web/package.json').href
registerHooks({
  resolve: (spec, ctx, next) => next(spec, spec === 'svelte' || spec.startsWith('svelte/') ? { ...ctx, parentURL: web } : ctx),
  load(url, ctx, next) {
    if (!url.endsWith('.svelte')) return next(url, ctx)
    const file = fileURLToPath(url)
    const { js } = compiler.compile(fs.readFileSync(file, 'utf8'), { filename: file, generate: 'server' })
    return { format: 'module', source: js.code, shortCircuit: true }
  },
})
const { render } = await import('svelte/server')
const { default: Fixture } = await import(pathToFileURL(process.cwd() + '/tests/fixtures/ui_blocks/Fixture.svelte').href)
console.log(render(Fixture).body.replace(/<!--[\s\S]*?-->/g, '').replace(/ svelte-[a-z0-9]+(?=[" ])/g, ''))
"""


@unittest.skipUnless(shutil.which('node') and (ROOT / 'web/node_modules/svelte').exists(),
                     'needs Node and installed web dependencies')
class UiBlocksTest(unittest.TestCase):
    def test_components_render_the_markup_they_replace(self):
        r = subprocess.run(['node', '--input-type=module', '-e', RENDER], cwd=ROOT, capture_output=True, text=True,
                           encoding='utf-8', timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertEqual(r.stdout.strip(), (FIXTURES / 'expected.html').read_text(encoding='utf-8').strip())


if __name__ == '__main__':
    unittest.main()
