"""Exercise the actual phone navigation callbacks with non-parent browser history."""
import json
import unittest

from tests.test_phone_js import node, TS_RESOLVE


class BackupNavigation(unittest.TestCase):
    def test_header_back_uses_the_backup_screen_parents(self):
        result = json.loads(node(TS_RESOLVE + r"""
            import fs from 'node:fs'
            const { parentHash } = await import('./web/src/mobile/back.ts')
            const src = fs.readFileSync('web/src/mobile/Mobile.svelte', 'utf8').replace(/\r\n/g, '\n')
            const callback = src.match(/onclick=\{(\(\) => [^\n]+?)\} aria-label="Back"/)[1]
            const results = []
            for (const r of [{ tab: 'more', backup: true }, { tab: 'more', recover: true }]) {
              const location = { hash: '#/lib' }, calls = []
              new Function('r', 'parentHash', 'location', 'history', 'return (' + callback + ')')(
                r, parentHash, location, { back: () => calls.push('wrong history entry') })()
              results.push({ hash: location.hash, calls })
            }
            console.log(JSON.stringify(results))
        """))
        self.assertEqual(result, [{'hash': '#/more', 'calls': []}, {'hash': '#/backup', 'calls': []}])

    def test_pairing_link_in_the_open_tab_restarts_the_startup_parser(self):
        result = json.loads(node(TS_RESOLVE + r"""
            import fs from 'node:fs'
            const src = fs.readFileSync('web/src/mobile/state.svelte.ts', 'utf8').replace(/\r\n/g, '\n')
            const callback = src.match(/window.addEventListener\('hashchange', (\(\) => \{[\s\S]*?\})\)/)[1]
            const calls = [], phone = { route: { tab: 'more', backup: true } }
            const location = { hash: '#pair=synthetic-code', reload: () => calls.push('reload') }
            new Function('phone', 'location', 'parseRoute', 'return (' + callback + ')')(
              phone, location, () => { calls.push('ignored pairing'); return { tab: 'lib' } })()
            console.log(JSON.stringify(calls))
        """))
        self.assertEqual(result, ['reload'])
